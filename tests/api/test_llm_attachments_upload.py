"""HTTP-level tests for LLM conversation document attachments.

These go through the full ASGI stack on purpose: the global BodyLimitMiddleware
(operator-configured via MAX_REQUEST_BODY_MB, unlimited by default) must NOT
swallow uploads that the attachment endpoint itself is designed to accept (50 MB
cap enforced in app/api/v2/llm.py from document_extraction.MAX_FILE_SIZE — an LLM
cost ceiling, which is why it stays). The attachments route is exempt from the
global body limit so real-world PDFs reach the endpoint instead of being rejected
with a generic 413.
"""

from __future__ import annotations


def _create_conversation(authenticated_client) -> str:
    response = authenticated_client.post("/api/v2/llm/conversations", json={})
    assert response.status_code == 201
    conv_id: str = response.json()["id"]
    return conv_id


class TestAttachmentUploadSizeContract:
    # CONTRACT-TEST: uploads up to the attachment cap (50 MB) must reach the
    # endpoint and succeed — the body-limit middleware exempts the attachments
    # route (the global body limit is also 50 MB).
    def test_upload_passes_global_body_limit(self, authenticated_client) -> None:
        conv_id = _create_conversation(authenticated_client)

        # 2 MB of plain text — comfortably under the 50 MB attachment cap; the
        # attachments route is exempt from the global body limit either way.
        content = (b"optimization model context line\n" * 65_536)[: 2 * 1024 * 1024]
        response = authenticated_client.post(
            f"/api/v2/llm/conversations/{conv_id}/attachments",
            files={"file": ("context.txt", content, "text/plain")},
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["filename"] == "context.txt"
        # Extraction truncates at 100K chars — what matters here is that the
        # request was not rejected by the middleware with a generic 413.
        assert data["char_count"] > 0

    def test_upload_over_50mb_rejected_by_endpoint_cap(self, authenticated_client) -> None:
        conv_id = _create_conversation(authenticated_client)

        content = b"x" * (50 * 1024 * 1024 + 1024)  # just over the 50 MB cap
        response = authenticated_client.post(
            f"/api/v2/llm/conversations/{conv_id}/attachments",
            files={"file": ("huge.txt", content, "text/plain")},
        )

        assert response.status_code == 413
        # The endpoint's own message, not the middleware's generic body
        assert "Maximum size" in response.json()["detail"]

    def test_upload_exemption_is_surgical(self) -> None:
        """The exemption must skip ONLY the upload routes.

        The global body limit is now operator-configured and off by default
        (MAX_REQUEST_BODY_MB), so this exercises the middleware with a limit set —
        which is the state in which the exemption means anything at all.
        """
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        from app.shared.core.body_limit import BodyLimitMiddleware

        async def ok(request):
            return JSONResponse({"received": len(await request.body())})

        app = Starlette(
            routes=[
                Route("/api/v2/llm/conversations", ok, methods=["POST"]),
                Route("/api/v2/llm/conversations/{cid}/attachments", ok, methods=["POST"]),
                Route("/api/v2/solve/import", ok, methods=["POST"]),
            ]
        )
        app.add_middleware(BodyLimitMiddleware, max_bytes=1024)
        client = TestClient(app, raise_server_exceptions=False)
        oversized = b"x" * 4096

        # Normal route: the configured limit applies.
        assert client.post("/api/v2/llm/conversations", content=oversized).status_code == 413

        # Upload routes enforce their own caps, so the middleware steps aside.
        assert client.post("/api/v2/solve/import", content=oversized).status_code == 200
        assert (
            client.post(
                "/api/v2/llm/conversations/cnv_1/attachments", content=oversized
            ).status_code
            == 200
        )
