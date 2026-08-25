"""Queue background work only once the transaction that justifies it commits.

A service flushes and leaves the commit to its caller. A Celery job queued at
the call site therefore races that commit: the worker owns a different
connection, so it can look for a row that is not visible yet, find nothing, and
drop the work silently. The same call is wrong in the other direction too — a
caller that rolls back has queued a job for something that never happened.

``queue_after_commit`` moves the ``delay()`` onto SQLAlchemy's ``after_commit``
event, and cancels it on ``after_rollback``. It was written once because the
hand-rolled version had already been copied to a second place, which is how
D-29 started.
"""

import logging
from typing import Any, Protocol

from sqlalchemy import event
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class Queueable(Protocol):
    """Anything with Celery's ``delay`` signature. Keeps Celery out of this layer."""

    name: str

    def delay(self, *args: Any, **kwargs: Any) -> Any: ...


def queue_after_commit(db: Session, task: Queueable, *args: Any, **kwargs: Any) -> None:
    """Call ``task.delay(*args, **kwargs)`` when ``db`` commits, never before.

    Nothing is queued if the transaction rolls back instead. A broker that is
    down or absent is logged and swallowed: the committed row is the record of
    what happened, and losing the follow-up job must not undo it.

    Both listeners are registered with ``once=True`` so SQLAlchemy detaches them
    itself. Whichever fires second finds the work already settled and does
    nothing, which is what makes this safe on the long-lived session a Celery
    task holds for its whole run.
    """
    settled = False

    def _queue(_session: object) -> None:
        nonlocal settled
        if settled:
            return
        settled = True
        try:
            task.delay(*args, **kwargs)
        except Exception:
            logger.warning("Could not queue %s after the commit", task.name, exc_info=True)

    def _cancel(_session: object) -> None:
        nonlocal settled
        if settled:
            return
        settled = True
        logger.debug("Rolled back before committing — %s was not queued", task.name)

    event.listen(db, "after_commit", _queue, once=True)
    event.listen(db, "after_rollback", _cancel, once=True)
