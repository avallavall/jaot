"""The FastAPI session dependency, in a module with no other job.

``DBSession`` is what endpoints annotate their session parameter with, and
``app.api.deps`` re-exports it — that is where route modules should import it
from, per the project rule.

It lives here rather than in either of the two obvious places, for one reason
each:

* not in ``app.api.deps``, because that module builds ``CurrentUser`` on top of
  ``app.api.v2.auth``, and ``auth`` needs a session annotation of its own. Owning
  the alias there makes a cycle: deps -> auth -> deps.
* not in ``app.shared.db.base`` next to ``get_db``, because that module defines
  ``Base`` and Alembic imports it (``infra/alembic/env.py``). It is kept free of
  anything but SQLAlchemy on purpose — its own ``get_db`` docstring calls that
  out — and ``Depends`` is a web-layer concern with no business being on the
  migration tool's import path.

So: a leaf that imports ``get_db`` and nothing else. Both consumers import it
without either importing the other.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.shared.db.base import get_db

DBSession = Annotated[Session, Depends(get_db)]

__all__ = ["DBSession"]
