"""ADR-009: an endpoint that does not await anything must not be `async def`.

The rule exists because the database session is synchronous. FastAPI runs a plain
`def` handler in a threadpool, but an `async def` one runs ON the event loop — so a
query inside it stalls every other request that worker is serving. 113 handlers were
`async def` with no `await` anywhere in them (backend audit D-12); this test is what
stops that from creeping back one copy-pasted endpoint at a time.

The check is on the source, not on imports: an `async def` decorated with
`@router.<method>` whose body contains no `await`, `async with` or `async for` is a
defect by ADR-009 rule 1.

The one legitimate exception is a handler that returns a streaming response
(`StreamingResponse` / `EventSourceResponse`): the awaiting happens inside the
generator it hands back, which the event loop iterates afterwards, so the handler
itself has nothing to await. Those must stay `async def`.
"""

import ast
import pathlib

import pytest

pytestmark = pytest.mark.contract

ROUTE_DIRS = ("app/api", "app/domains")
STREAMING_MARKERS = ("StreamingResponse", "EventSourceResponse")


def _is_route(decorators: list[ast.expr]) -> bool:
    """True when a decorator looks like @router.get/post/put/patch/delete(...)."""
    for dec in decorators:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if (
            isinstance(target, ast.Attribute)
            and target.attr in {"get", "post", "put", "patch", "delete"}
            and isinstance(target.value, ast.Name)
            and target.value.id == "router"
        ):
            return True
    return False


def _awaits_something(node: ast.AsyncFunctionDef) -> bool:
    return any(isinstance(n, (ast.Await, ast.AsyncWith, ast.AsyncFor)) for n in ast.walk(node))


def _returns_a_stream(node: ast.AsyncFunctionDef, source: str) -> bool:
    segment = ast.get_source_segment(source, node) or ""
    return any(marker in segment for marker in STREAMING_MARKERS)


def _offenders() -> list[str]:
    found: list[str] = []
    for root in ROUTE_DIRS:
        for path in sorted(pathlib.Path(root).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source)
            except SyntaxError:  # pragma: no cover - a broken file fails elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.AsyncFunctionDef):
                    continue
                if not _is_route(node.decorator_list):
                    continue
                if _awaits_something(node) or _returns_a_stream(node, source):
                    continue
                found.append(f"{path}:{node.lineno} {node.name}")
    return found


# CONTRACT-TEST: ADR-009 rule 1 — no `async def` endpoint without an await.
def test_no_async_endpoint_without_an_await():
    offenders = _offenders()
    assert not offenders, (
        "these endpoints are `async def` but await nothing, so their synchronous work "
        "(a DB query, a parse, an upload) runs on the event loop and stalls every "
        "concurrent request — declare them `def` and FastAPI will use the threadpool "
        "(ADR-009):\n  " + "\n  ".join(offenders)
    )


def test_the_check_can_actually_fail():
    """A guard that cannot fail is decoration — prove the detector fires."""
    source = (
        "@router.get('/x')\n"
        "async def offending_handler(db: Session = Depends(get_db)):\n"
        "    return db.query(Thing).all()\n"
    )
    tree = ast.parse(source)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef))

    assert _is_route(node.decorator_list)
    assert not _awaits_something(node)
    assert not _returns_a_stream(node, source)


def test_streaming_handlers_are_recognised_as_legitimate():
    """The SSE exception is real, not a blanket escape hatch."""
    source = (
        "@router.post('/x')\n"
        "async def streaming_handler(db: Session = Depends(get_db)):\n"
        "    db.commit()\n"
        "    return EventSourceResponse(_stream(db=db))\n"
    )
    tree = ast.parse(source)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef))

    assert not _awaits_something(node)
    assert _returns_a_stream(node, source)
