"""Tests for email delivery system (Task 5.9).

Covers:
- Email task enqueueing via Celery
- Template rendering with all required variables
- Locale-specific rendering
- SMTP error handling
- Batch sending edge cases
- SMTP configuration validation
"""

import smtplib
from unittest.mock import MagicMock, patch

import pytest

import app.services.email_service as email_service_mod
from app.services.email_service import (
    ConsoleBackend,
    EmailService,
    SMTPBackend,
)
from app.services.onboarding_emails import (
    ONBOARDING_SEQUENCE,
    day0_welcome,
    day7_credits,
    day14_feedback,
)
from app.services.platform_settings_service import PlatformSettingsService as PSS


class TestCeleryTaskEnqueueing:
    """Verify email tasks are properly enqueued through Celery."""

    def test_schedule_enqueues_all_five_days(self):
        """schedule_onboarding_sequence should call apply_async 5 times."""
        with patch("app.tasks.email_tasks.send_onboarding_email") as mock_task:
            mock_task.apply_async = MagicMock()
            from app.tasks.email_tasks import schedule_onboarding_sequence

            result = schedule_onboarding_sequence(
                user_email="new@test.com",
                user_name="Test",
                api_key_prefix="ok_live_",
            )
            assert result["status"] == "scheduled"
            assert mock_task.apply_async.call_count == 5

    def test_schedule_passes_correct_kwargs_per_day(self):
        """Each apply_async call should include user_email, user_name, day, and api_key_prefix."""
        with patch("app.tasks.email_tasks.send_onboarding_email") as mock_task:
            mock_task.apply_async = MagicMock()
            from app.tasks.email_tasks import schedule_onboarding_sequence

            schedule_onboarding_sequence(
                user_email="alice@test.com",
                user_name="Alice",
                api_key_prefix="ok_live_abc",
            )

            expected_days = sorted(ONBOARDING_SEQUENCE.keys())
            actual_days = []
            for call_args in mock_task.apply_async.call_args_list:
                kwargs_dict = call_args[1].get("kwargs", {})
                actual_days.append(kwargs_dict["day"])
                assert kwargs_dict["user_email"] == "alice@test.com"
                assert kwargs_dict["user_name"] == "Alice"

            assert sorted(actual_days) == expected_days

    def test_schedule_day0_has_short_countdown(self):
        """Day 0 should have a countdown of 5 seconds, not days."""
        with patch("app.tasks.email_tasks.send_onboarding_email") as mock_task:
            mock_task.apply_async = MagicMock()
            from app.tasks.email_tasks import schedule_onboarding_sequence

            schedule_onboarding_sequence(
                user_email="bob@test.com",
                user_name="Bob",
                api_key_prefix="ok_live_",
            )

            # Find the day 0 call
            for call_args in mock_task.apply_async.call_args_list:
                kwargs_dict = call_args[1].get("kwargs", {})
                if kwargs_dict["day"] == 0:
                    countdown = call_args[1].get("countdown")
                    assert countdown == 5
                    break

    def test_send_task_retries_on_failure(self):
        """send_onboarding_email should propagate EmailDeliveryError when SMTP fails.

        Outside Celery's eager mode, ``self.retry(exc=...)`` re-raises the
        underlying cause directly so callers see the typed delivery error.
        """
        from app.tasks.email_tasks import EmailDeliveryError, send_onboarding_email

        with patch.object(EmailService, "send", return_value=False) as mock_send:
            with pytest.raises(EmailDeliveryError) as exc_info:
                send_onboarding_email(
                    user_email="fail@test.com",
                    user_name="Fail",
                    day=1,
                )
        # send must have been invoked exactly once (no retry inside the task body)
        assert mock_send.call_count == 1
        assert "fail@test.com" in str(exc_info.value)
        # Exception is the typed delivery error and carries no inner cause chain
        # (retry path re-raises it directly outside eager mode)
        assert exc_info.value.__cause__ is None or isinstance(
            exc_info.value.__cause__, EmailDeliveryError
        )


class TestTemplateRendering:
    """Verify all templates render without errors and produce valid HTML."""

    @pytest.mark.parametrize("day", sorted(ONBOARDING_SEQUENCE.keys()))
    def test_template_renders_without_error(self, day):
        from html.parser import HTMLParser

        gen = ONBOARDING_SEQUENCE[day]
        # Use a name with HTML special chars to verify escaping
        attack_name = "<script>alert(1)</script>"
        if day == 0:
            subject, html = gen(attack_name, "ok_test_prefix")
        elif day == 7:
            subject, html = gen(attack_name, 999)
        else:
            subject, html = gen(attack_name)

        assert isinstance(subject, str) and len(subject) > 0
        assert isinstance(html, str) and len(html) > 50

        # Parse HTML — must not raise
        class _Parser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tags: list[str] = []

            def handle_starttag(self, tag, attrs):
                self.tags.append(tag)

        parser = _Parser()
        parser.feed(html)
        # HTML should have at least html and body-like structure
        assert "html" in parser.tags, f"day {day}: missing <html> tag"

        # User-controlled name field must be HTML-escaped:
        # the literal "<script>" should NOT survive in the rendered output
        assert "<script>alert(1)</script>" not in html, f"day {day}: XSS — script tag not escaped"

    def test_day0_contains_api_key_and_curl(self):
        _, html = day0_welcome("Alice", "ok_live_xyz123")
        assert "ok_live_xyz123" in html
        assert "curl" in html

    def test_day7_contains_credit_balance(self):
        _, html = day7_credits("Bob", 42)
        # Balance must appear in a labelled context, not as a stray "42" in
        # CSS, IDs, or pixel values. Look for "42" adjacent to "credit" or
        # inside an HTML element close-tag boundary.
        assert ("42 credit" in html.lower()) or (">42<" in html) or (">42 " in html), (
            "balance 42 not found in a labelled context"
        )

    def test_day14_contains_feedback_request(self):
        _, html = day14_feedback("Carol")
        assert "feedback" in html.lower()

    @pytest.mark.parametrize("day", sorted(ONBOARDING_SEQUENCE.keys()))
    def test_all_templates_include_unsubscribe(self, day):
        gen = ONBOARDING_SEQUENCE[day]
        if day == 0:
            _, html = gen("Test", "ok_live_")
        elif day == 7:
            _, html = gen("Test", 200)
        else:
            _, html = gen("Test")
        assert "unsubscribe" in html.lower()


class TestSMTPErrorHandling:
    """Verify the email system handles SMTP failures gracefully."""

    def test_smtp_connection_refused(self):
        """SMTPBackend.send returns False on connection failure."""
        backend = SMTPBackend(
            host="nonexistent.invalid",
            port=587,
            username="user",
            password="pass",
        )
        result = backend.send(
            to="test@test.com",
            subject="Test",
            html="<p>Hello</p>",
        )
        assert result is False

    def test_smtp_authentication_failure(self):
        """SMTPBackend.send returns False on auth failure."""
        backend = SMTPBackend(
            host="smtp.example.com",
            port=587,
            username="wrong",
            password="wrong",
        )
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value = mock_server
            mock_server.starttls.return_value = None
            mock_server.login.side_effect = smtplib.SMTPAuthenticationError(
                535, b"Authentication failed"
            )

            result = backend.send(
                to="test@test.com",
                subject="Test",
                html="<p>Hi</p>",
            )
            assert result is False

    def test_smtp_sendmail_failure(self):
        """SMTPBackend.send returns False when sendmail raises."""
        backend = SMTPBackend(
            host="smtp.example.com",
            port=587,
            username="user",
            password="pass",
        )
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value = mock_server
            mock_server.starttls.return_value = None
            mock_server.login.return_value = None
            mock_server.sendmail.side_effect = smtplib.SMTPException("Relay denied")

            result = backend.send(
                to="test@test.com",
                subject="Test",
                html="<p>Hi</p>",
            )
            assert result is False

    def test_smtp_password_masked_in_repr(self):
        """SMTPBackend.__repr__ should not expose the password."""
        backend = SMTPBackend(
            host="smtp.example.com",
            port=587,
            username="user",
            password="supersecret",
        )
        repr_str = repr(backend)
        assert "supersecret" not in repr_str
        assert "***" in repr_str

    def test_smtp_password_masked_in_error_log(self):
        """Password in exception message is replaced with *** on failure.

        Patches the email_service logger.error directly to inspect the
        actual log message — avoids any handler-level interaction issues.
        """
        backend = SMTPBackend(
            host="smtp.example.com",
            port=587,
            username="user",
            password="mysecretpass",
        )

        with (
            patch("app.services.email_service.logger") as mock_logger,
            patch("smtplib.SMTP") as mock_smtp_cls,
        ):
            mock_server = MagicMock()
            mock_smtp_cls.return_value = mock_server
            mock_server.starttls.return_value = None
            mock_server.login.return_value = None
            mock_server.sendmail.side_effect = smtplib.SMTPException(
                "Error with mysecretpass in message"
            )

            result = backend.send(
                to="test@test.com",
                subject="Test",
                html="<p>Hi</p>",
            )
        assert result is False
        # Collect every message passed to logger.error during this run
        error_msgs = [str(call.args[0]) for call in mock_logger.error.call_args_list]
        all_text = "\n".join(error_msgs)
        # Password must NOT appear in any error log message
        assert "mysecretpass" not in all_text, f"password leaked: {all_text!r}"
        # Masked marker must appear in the error log message
        assert "***" in all_text, f"masking marker missing from {all_text!r}"

    def test_smtp_ssl_backend_on_non_tls(self):
        """SMTPBackend with use_tls=False should use SMTP_SSL."""
        backend = SMTPBackend(
            host="smtp.example.com",
            port=465,
            use_tls=False,
        )
        with patch("smtplib.SMTP_SSL") as mock_ssl_cls:
            mock_server = MagicMock()
            mock_ssl_cls.return_value = mock_server
            mock_server.sendmail.return_value = {}
            mock_server.quit.return_value = None

            result = backend.send(
                to="test@test.com",
                subject="Test",
                html="<p>Hi</p>",
            )
            assert result is True
            mock_ssl_cls.assert_called_once()


class TestVerifySmtpTlsHandshake:
    """Verify EmailService.verify_smtp_tls_handshake behavior."""

    def test_verify_returns_true_for_non_smtp_backend(self):
        """Console backend verification returns (True, ...) immediately."""
        EmailService.configure()  # console
        is_valid, msg = EmailService.verify_smtp_tls_handshake()
        assert is_valid is True
        assert "Not using SMTP" in msg

    def test_verify_rejects_empty_smtp_host(self):
        """SMTP backend with empty host is rejected by the TLS-handshake check.

        Constructs the SMTPBackend explicitly (instead of mutating private
        state on a real backend) so the test exercises a deterministic
        configuration via the SMTPBackend constructor.
        """
        # Save and restore backend so we don't poison other tests
        original_backend = EmailService._backend
        try:
            EmailService._backend = SMTPBackend(host="", port=587, username="u", password="p")
            is_valid, msg = EmailService.verify_smtp_tls_handshake()
            assert is_valid is False
            assert "empty" in msg.lower()
        finally:
            EmailService._backend = original_backend

    def test_verify_rejects_unreachable_smtp_host(self):
        """TLS handshake against an unreachable host returns (False, ...) with the host name."""
        EmailService.configure(backend="smtp", smtp_host="nonexistent.invalid", smtp_port=587)
        is_valid, msg = EmailService.verify_smtp_tls_handshake()
        assert is_valid is False
        # Diagnostic: the message should mention the offending host
        assert "nonexistent.invalid" in msg
        EmailService.configure()  # reset


class TestBatchSending:
    """Verify batch email sending behavior."""

    def test_batch_partial_failure(self):
        """Batch sending counts only successful sends."""
        call_count = 0

        def flaky_send(**kwargs):
            nonlocal call_count
            call_count += 1
            return call_count % 2 == 0  # Fail odd, succeed even

        EmailService.configure()  # console
        with patch.object(EmailService._backend, "send", side_effect=flaky_send):
            count = EmailService.send_batch(
                recipients=["a@t.com", "b@t.com", "c@t.com", "d@t.com"],
                subject="Test",
                html="<p>Hi</p>",
            )
            # Calls 1(fail), 2(ok), 3(fail), 4(ok) -> 2 successes
            assert count == 2

    def test_batch_all_fail(self):
        """Batch with all failures returns 0."""
        EmailService.configure()
        with patch.object(EmailService._backend, "send", return_value=False):
            count = EmailService.send_batch(
                recipients=["a@t.com", "b@t.com"],
                subject="Test",
                html="<p>Hi</p>",
            )
            assert count == 0

    def test_batch_preserves_from_email(self):
        """Batch passes from_email to each send call."""
        EmailService.configure()
        with patch.object(EmailService._backend, "send", return_value=True) as mock_send:
            EmailService.send_batch(
                recipients=["a@t.com"],
                subject="Test",
                html="<p>Hi</p>",
                from_email="custom@jaot.io",
            )
            call_kwargs = mock_send.call_args[1]
            assert call_kwargs["from_email"] == "custom@jaot.io"


@pytest.fixture
def _restore_email_backend():
    """Save and restore EmailService class-level backend state around a test.

    F8 reconfigure tests mutate process-global class attributes; this guarantees
    no leakage into other tests in the suite.
    """
    saved = (
        EmailService._backend,
        EmailService._backend_loaded_at,
        EmailService._backend_signature,
    )
    yield
    (
        EmailService._backend,
        EmailService._backend_loaded_at,
        EmailService._backend_signature,
    ) = saved


def _set_email_pss(db, **overrides):
    """Write email-related PlatformSettings values for a test (real DB, flush only)."""
    defaults = {
        "EMAIL_BACKEND": "console",
        "SMTP_HOST": "",
        "SMTP_PORT": "587",
        "SMTP_USER": "",
        "SMTP_PASSWORD": "",
        "SMTP_USE_TLS": "true",
        "EMAIL_FROM": "JAOT <noreply@jaot.io>",
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        PSS.set(db, key, value)


class TestLazyReconfigureOnPssChange:
    """F8: EmailService picks up runtime PlatformSettings changes without restart.

    Option B — lazy reconfigure with a short TTL. On send()/send_batch() the
    service re-reads the email PSS keys at most once per TTL window and rebuilds
    the backend only when a value actually changed.
    """

    def test_send_after_ttl_rebuilds_backend_on_change(self, db_session, _restore_email_backend):
        """Changing EMAIL_BACKEND console→smtp + SMTP_HOST and calling send()
        AFTER the TTL window rebuilds the backend with the NEW config — no restart."""
        # Start configured from PSS as console.
        _set_email_pss(db_session, EMAIL_BACKEND="console")
        EmailService.configure_from_pss(db_session)
        assert isinstance(EmailService._backend, ConsoleBackend)
        loaded_at_before = EmailService._backend_loaded_at
        assert loaded_at_before is not None

        # Operator flips backend and sets a host at runtime.
        _set_email_pss(
            db_session, EMAIL_BACKEND="smtp", SMTP_HOST="smtp.newhost.test", SMTP_PORT="2525"
        )

        # Simulate the TTL window elapsing: jump monotonic clock forward.
        future = loaded_at_before + email_service_mod._BACKEND_TTL_SECONDS + 1.0
        with patch.object(email_service_mod.time, "monotonic", return_value=future):
            EmailService.send(to="x@t.com", subject="s", html="<p>h</p>", db=db_session)

        # Backend was rebuilt to the NEW SMTP config without any process restart.
        assert isinstance(EmailService._backend, SMTPBackend)
        assert EmailService._backend.host == "smtp.newhost.test"
        assert EmailService._backend.port == 2525

    def test_send_within_ttl_does_not_rebuild(self, db_session, _restore_email_backend):
        """Within the TTL window, a PSS change is NOT picked up yet and the
        backend instance is left untouched (no per-send DB churn)."""
        _set_email_pss(db_session, EMAIL_BACKEND="console")
        EmailService.configure_from_pss(db_session)
        backend_before = EmailService._backend
        assert isinstance(backend_before, ConsoleBackend)

        # Change PSS but stay within the TTL window (clock not advanced).
        _set_email_pss(db_session, EMAIL_BACKEND="smtp", SMTP_HOST="smtp.newhost.test")

        EmailService.send(to="x@t.com", subject="s", html="<p>h</p>", db=db_session)

        # Same backend instance — no rebuild, change not yet visible.
        assert EmailService._backend is backend_before

    def test_send_after_ttl_no_change_does_not_rebuild(self, db_session, _restore_email_backend):
        """After the TTL window with NO PSS change, the backend is NOT rebuilt
        (signature compare avoids needless churn); only the timer is deferred."""
        _set_email_pss(db_session, EMAIL_BACKEND="smtp", SMTP_HOST="smtp.stable.test")
        EmailService.configure_from_pss(db_session)
        backend_before = EmailService._backend
        assert isinstance(backend_before, SMTPBackend)
        loaded_at_before = EmailService._backend_loaded_at

        future = loaded_at_before + email_service_mod._BACKEND_TTL_SECONDS + 1.0
        with patch.object(email_service_mod.time, "monotonic", return_value=future):
            EmailService.send(to="x@t.com", subject="s", html="<p>h</p>", db=db_session)

        # Identity preserved: the unchanged backend was kept, not rebuilt.
        assert EmailService._backend is backend_before
        # The timer was bumped forward so the next check is deferred.
        assert EmailService._backend_loaded_at == future

    def test_send_opens_own_session_when_no_db_passed(self, db_session, _restore_email_backend):
        """send() with no db arg still refreshes after the TTL by opening a
        short-lived SessionLocal (covers call sites like onboarding tasks)."""
        _set_email_pss(db_session, EMAIL_BACKEND="console")
        EmailService.configure_from_pss(db_session)
        loaded_at_before = EmailService._backend_loaded_at
        assert isinstance(EmailService._backend, ConsoleBackend)

        # Operator change must be committed so a *separate* session sees it.
        _set_email_pss(db_session, EMAIL_BACKEND="smtp", SMTP_HOST="smtp.viaownsession.test")
        db_session.commit()

        future = loaded_at_before + email_service_mod._BACKEND_TTL_SECONDS + 1.0
        try:
            with patch.object(email_service_mod.time, "monotonic", return_value=future):
                # No db= passed → _maybe_reconfigure opens its own SessionLocal.
                EmailService.send(to="x@t.com", subject="s", html="<p>h</p>")
            assert isinstance(EmailService._backend, SMTPBackend)
            assert EmailService._backend.host == "smtp.viaownsession.test"
        finally:
            # Undo the committed change so the row doesn't leak past this test.
            _set_email_pss(db_session, EMAIL_BACKEND="console", SMTP_HOST="")
            db_session.commit()

    def test_directly_configured_backend_never_auto_refreshes(
        self, db_session, _restore_email_backend
    ):
        """Backends set via configure() (not PSS) have _backend_loaded_at=None and
        are never clobbered by the lazy refresh — preserves existing call sites
        and tests that call configure() then send()."""
        EmailService.configure()  # console, no PSS provenance
        assert EmailService._backend_loaded_at is None
        backend_before = EmailService._backend

        # Even with a divergent PSS value and a far-future clock, no refresh.
        _set_email_pss(db_session, EMAIL_BACKEND="smtp", SMTP_HOST="smtp.should-not-load.test")
        with patch.object(email_service_mod.time, "monotonic", return_value=10**9):
            result = EmailService.send(to="x@t.com", subject="s", html="<p>h</p>", db=db_session)

        assert result is True
        assert EmailService._backend is backend_before
        assert EmailService._backend_loaded_at is None
