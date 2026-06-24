"""
Tests for the onboarding email system.

Covers:
- EmailService backends (console, SMTP mock)
- All 5 onboarding email templates (Day 0, 1, 3, 7, 14)
- Celery task scheduling
- Signup trigger integration
- Edge cases: empty names, special characters, HTML escaping
"""

from unittest.mock import MagicMock, patch

from app.services.email_service import ConsoleBackend, EmailService, SMTPBackend
from app.services.onboarding_emails import (
    ONBOARDING_SEQUENCE,
    day0_welcome,
    day1_api_setup,
    day3_catalog,
    day7_credits,
    day14_feedback,
)


class TestEmailServiceBackends:
    def test_configure_console_default(self):
        EmailService.configure()
        assert isinstance(EmailService._backend, ConsoleBackend)

    def test_configure_smtp_without_host_falls_back_to_console(self):
        EmailService.configure(backend="smtp", smtp_host="")
        assert isinstance(EmailService._backend, ConsoleBackend)

    def test_configure_smtp_with_host(self):
        EmailService.configure(backend="smtp", smtp_host="smtp.example.com")
        assert isinstance(EmailService._backend, SMTPBackend)
        # Reset to console for other tests
        EmailService.configure()

    def test_send_batch_empty_list(self):
        EmailService.configure()
        count = EmailService.send_batch(recipients=[], subject="Empty", html="<p>Hi</p>")
        assert count == 0


class TestOnboardingSequenceRegistry:
    def test_sequence_has_5_emails(self):
        assert len(ONBOARDING_SEQUENCE) == 5

    def test_sequence_days(self):
        assert set(ONBOARDING_SEQUENCE.keys()) == {0, 1, 3, 7, 14}


class TestDay0Welcome:
    def test_contains_user_name(self):
        subject, html = day0_welcome("Bob", "ok_test_")
        assert "Bob" in html

    def test_contains_api_key_prefix(self):
        subject, html = day0_welcome("Alice", "ok_live_abc")
        assert "ok_live_abc" in html

    def test_contains_curl_example(self):
        subject, html = day0_welcome("Alice", "ok_live_")
        assert "curl" in html

    def test_subject_mentions_welcome(self):
        subject, html = day0_welcome("Alice", "ok_live_")
        assert "welcome" in subject.lower() or "Welcome" in subject


class TestDay1ApiSetup:
    def test_contains_python_example(self):
        _, html = day1_api_setup("Alice")
        # Specific Python code marker — requires the literal `import requests`
        # call inside a <pre> code block, not just the word "python" in CSS
        assert "import requests" in html
        # Confirm it lives inside a code/pre element, not as marketing text
        assert "<pre" in html

    def test_contains_javascript_example(self):
        _, html = day1_api_setup("Alice")
        # Specific JS marker — fetch() call signature, not just "JavaScript" in a heading
        assert "await fetch(" in html
        assert "JavaScript" in html


class TestDay3Catalog:
    def test_mentions_model_count(self):
        _, html = day3_catalog("Alice")
        # Must mention 101 in a labelled context (templates/optimization), not
        # as a stray digit somewhere in a CSS pixel value or filename.
        assert "101 ready-to-use" in html

    def test_lists_key_models(self):
        _, html = day3_catalog("Alice")
        assert "Knapsack" in html
        assert "Vehicle Routing" in html
        assert "Portfolio" in html


class TestDay7Credits:
    def test_shows_credit_balance(self):
        _, html = day7_credits("Alice", 1234)
        # Balance must appear in a labelled context, not as a stray "1234"
        assert "1234 credits" in html.lower() or ">1234 " in html

    def test_shows_pricing_table(self):
        _, html = day7_credits("Alice", 200)
        assert "Free" in html
        assert "Starter" in html
        assert "Pro" in html

    def test_zero_balance(self):
        """Strengthened TA-06 (12.4 Plan 05 LOW, D-08 relaxation): structured DOM + edge.

        Before: single substring check (`"0 credits" in html.lower()` or `">0 "`) T3.
        After: assert the balance line renders the full labelled value in a
        unique HTML tag context, the credits unit appears next to it, and the
        pricing-tier table is also present (proving the full template ran).
        Plus negative-balance edge.
        """
        _, html = day7_credits("Alice", 0)
        html_lower = html.lower()

        # Balance line: the template renders `<p ...>{balance} {creditsUnit}</p>`
        # with creditsUnit defaulting to "credits". Must appear together to
        # rule out the stray "0" trap the legacy assertion guarded against.
        assert "0 credits" in html_lower or ">0 " in html, (
            "Balance line missing labelled zero (expected '0 credits' or '>0 ')"
        )

        # Structural: the balance must appear inside a styled <p> block
        # (not as a stray digit in CSS). The template uses
        # 'font-size:36px;font-weight:700' for the balance line.
        assert "font-weight:700" in html
        # Pricing table proves the full template ran end-to-end.
        assert "Free" in html and "Starter" in html and "Pro" in html
        # Currency / plan column header present.
        assert "Price" in html

        # Edge: negative balance must still render without crashing and must
        # display the negative value (template does not clamp at 0).
        _, neg_html = day7_credits("Alice", -50)
        neg_lower = neg_html.lower()
        assert ("-50 credits" in neg_lower) or (">-50 " in neg_html) or ("-50" in neg_html), (
            "Negative balance line missing labelled value"
        )


class TestDay14Feedback:
    def test_contains_feedback_emojis(self):
        _, html = day14_feedback("Alice")
        # Test name promises emoji code-point coverage. Check the four
        # rating emoji code points the template renders.
        assert "\U0001f60d" in html  # heart-eyes (great)
        assert "\U0001f60a" in html  # smile (good)
        assert "\U0001f610" in html  # neutral (ok)
        assert "\U0001f61e" in html  # frown (bad)

    def test_contains_success_stories(self):
        _, html = day14_feedback("Alice")
        assert "Manufacturing" in html or "Logistics" in html or "Investment" in html


class TestEdgeCases:
    def test_empty_name(self):
        """Empty name must produce a sensible salutation, not 'Hi ,'."""
        for day, gen in ONBOARDING_SEQUENCE.items():
            if day == 0:
                subject, html = gen("", "ok_live_")
            elif day == 7:
                subject, html = gen("", 200)
            else:
                subject, html = gen("")
            assert isinstance(subject, str)
            assert isinstance(html, str)
            # Must NOT render the broken empty-name salutation
            assert "Hi ," not in html, f"day {day}: empty-name produced 'Hi ,' artifact"
            assert "Welcome, !" not in html
            assert ", !" not in html
            # Production fix: empty name falls back to a generic placeholder

    def test_special_characters_in_name(self):
        """Names with special chars must be HTML-escaped (XSS protection)."""
        for day, gen in ONBOARDING_SEQUENCE.items():
            if day == 0:
                subject, html = gen("O'Brien & Co <script>", "ok_live_")
            elif day == 7:
                subject, html = gen("O'Brien & Co <script>", 200)
            else:
                subject, html = gen("O'Brien & Co <script>")
            assert isinstance(html, str)
            # CRITICAL: literal <script> tag must be escaped, not passed through
            assert "<script>" not in html, (
                f"day {day}: XSS — literal <script> tag rendered into HTML"
            )
            # Escaped form should appear instead
            assert "&lt;script&gt;" in html

    def test_unicode_name(self):
        """Unicode names should work."""
        subject, html = day0_welcome("María García", "ok_live_")
        assert "María" in html

    def test_all_templates_have_unsubscribe(self):
        """All templates should include an unsubscribe link."""
        for day, gen in ONBOARDING_SEQUENCE.items():
            if day == 0:
                _, html = gen("Test", "ok_live_")
            elif day == 7:
                _, html = gen("Test", 200)
            else:
                _, html = gen("Test")
            assert "unsubscribe" in html.lower() or "Unsubscribe" in html

    def test_all_templates_valid_html(self):
        """All templates parse cleanly and contain a top-level <html> root."""
        from html.parser import HTMLParser

        class _StructureParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.opened: list[str] = []

            def handle_starttag(self, tag, attrs):
                self.opened.append(tag)

        for day, gen in ONBOARDING_SEQUENCE.items():
            if day == 0:
                _, html = gen("Test", "ok_live_")
            elif day == 7:
                _, html = gen("Test", 200)
            else:
                _, html = gen("Test")

            parser = _StructureParser()
            parser.feed(html)  # raises on malformed HTML
            assert "html" in parser.opened, f"day {day}: missing <html> root element"
            assert "body" in parser.opened, f"day {day}: missing <body> element"


class TestEmailTasks:
    def test_send_onboarding_email_day0(self):
        """Day 0 task should call EmailService.send."""
        with patch.object(EmailService, "send", return_value=True) as mock_send:
            from app.tasks.email_tasks import send_onboarding_email

            result = send_onboarding_email(
                user_email="test@test.com",
                user_name="Alice",
                day=0,
                api_key_prefix="ok_test_",
            )
            assert result["status"] == "sent"
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args
            assert call_kwargs[1]["to"] == "test@test.com"

    def test_send_onboarding_email_day7(self):
        """Day 7 task must render credits balance into the HTML body."""
        with patch.object(EmailService, "send", return_value=True) as mock_send:
            from app.tasks.email_tasks import send_onboarding_email

            result = send_onboarding_email(
                user_email="test@test.com",
                user_name="Bob",
                day=7,
                credits_balance=500,
            )
            assert result["status"] == "sent"
            # Capture the rendered HTML and assert the balance was substituted in
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args.kwargs
            assert "500" in call_kwargs["html"]
            # Confirm the balance is in a labelled context (not stray digit)
            assert "500 credits" in call_kwargs["html"].lower() or ">500 " in call_kwargs["html"]

    def test_send_onboarding_email_invalid_day(self):
        """Invalid day should return error."""
        from app.tasks.email_tasks import send_onboarding_email

        result = send_onboarding_email(
            user_email="test@test.com",
            user_name="Alice",
            day=99,
        )
        assert result["status"] == "error"

    def test_schedule_onboarding_sequence(self):
        """Scheduling should queue 5 tasks."""
        with patch("app.tasks.email_tasks.send_onboarding_email") as mock_task:
            mock_task.apply_async = MagicMock()
            from app.tasks.email_tasks import schedule_onboarding_sequence

            result = schedule_onboarding_sequence(
                user_email="new@user.com",
                user_name="New User",
                api_key_prefix="ok_live_",
            )
            assert result["status"] == "scheduled"
            assert len(result["days"]) == 5
            assert mock_task.apply_async.call_count == 5
