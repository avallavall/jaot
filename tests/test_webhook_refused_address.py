"""An address the server will not call is refused once, not retried four times.

`deliver_webhook` already dropped a payload aimed at a private, loopback or
link-local address — that is the SSRF guard, and it belongs at the egress
point. What it returned was the same `False` a timeout returns, so the task
treated a settled answer as a bad moment: four attempts over seven minutes, and
then a notification telling the owner their endpoint had not answered after
four tries. Nothing had ever been sent to it.

The task now asks `blocked_url_target` — the same function the create form uses
to reject such a URL — for its own decision: whether trying again could change
anything. A hostname that does not resolve is deliberately still retried, since
it may resolve by the next attempt.
"""

from unittest.mock import patch

import pytest

from app.tasks.webhook_tasks import deliver_webhook_task

TASK = "app.tasks.webhook_tasks"


def test_a_private_address_is_refused_without_delivering() -> None:
    with (
        patch(f"{TASK}.blocked_url_target", return_value="192.168.1.20"),
        patch(f"{TASK}.deliver_webhook") as deliver,
        patch(f"{TASK}._record_attempt") as record,
        patch(f"{TASK}._notify_delivery_failed") as notify,
    ):
        result = deliver_webhook_task(
            url="http://intranet.example.com/hook",
            payload={"event": "trigger.execution.completed"},
            run_id="trun_abc",
        )

    assert result["status"] == "refused"
    assert result["address"] == "192.168.1.20"
    assert deliver.call_count == 0, "it tried to deliver to an address it had already refused"
    # The attempt is recorded, and settled: no verdict is left open for retries
    # that will never come.
    record.assert_called_once_with("trun_abc", delivered=False)
    assert notify.call_count == 1


def test_the_owner_is_told_the_address_is_the_problem() -> None:
    with (
        patch(f"{TASK}.blocked_url_target", return_value="127.0.0.1"),
        patch(f"{TASK}.deliver_webhook"),
        patch(f"{TASK}._record_attempt"),
        patch(f"{TASK}._notify_delivery_failed") as notify,
    ):
        deliver_webhook_task(url="http://localhost/hook", payload={}, run_id="trun_abc")

    reason = notify.call_args.kwargs["reason"]
    assert "127.0.0.1" in reason
    assert "attempts" not in reason, "it still counted attempts that were never made"
    assert "public address" in reason, "it does not say what to do about it"


def test_a_public_address_is_delivered_as_before() -> None:
    with (
        patch(f"{TASK}.blocked_url_target", return_value=None),
        patch(f"{TASK}.deliver_webhook", return_value=True) as deliver,
        patch(f"{TASK}._record_attempt") as record,
    ):
        result = deliver_webhook_task(
            url="https://example.com/hook", payload={"event": "x"}, run_id="trun_abc"
        )

    assert result["status"] == "delivered"
    assert deliver.call_count == 1
    record.assert_called_once_with("trun_abc", delivered=True)


def test_a_hostname_that_does_not_resolve_is_still_retried() -> None:
    """Not settled: it may resolve by the next attempt, which is what retries are for."""
    with (
        # `blocked_url_target` answers None for an unresolvable name on purpose.
        patch(f"{TASK}.blocked_url_target", return_value=None),
        patch(f"{TASK}.deliver_webhook", return_value=False),
        patch(f"{TASK}._record_attempt"),
        patch(f"{TASK}._notify_delivery_failed"),
        pytest.raises(Exception),  # noqa: B017 — Celery's retry signal, whatever it is
    ):
        deliver_webhook_task(url="https://nope.invalid/hook", payload={}, run_id="trun_abc")
