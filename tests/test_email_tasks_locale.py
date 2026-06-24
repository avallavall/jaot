"""
Tests for locale threading through Celery email tasks.

Covers:
- send_onboarding_email passes locale to email generator
- send_onboarding_email without locale defaults to None
- schedule_onboarding_sequence accepts locale and passes to apply_async
- schedule_onboarding_sequence with locale=None works without error
"""

from unittest.mock import MagicMock, patch

from app.services.email_service import EmailService


class TestSendOnboardingEmailLocale:
    def test_passes_locale_to_day0_generator(self):
        """Day 0 generator should receive locale kwarg exactly once."""
        with patch.object(EmailService, "send", return_value=True):
            with patch("app.tasks.email_tasks.ONBOARDING_SEQUENCE") as mock_seq:
                mock_gen = MagicMock(return_value=("Subject", "<p>HTML</p>"))
                mock_seq.get.return_value = mock_gen
                mock_seq.keys.return_value = [0]

                from app.tasks.email_tasks import send_onboarding_email

                result = send_onboarding_email(
                    user_email="test@test.com",
                    user_name="Alice",
                    day=0,
                    api_key_prefix="ok_live_",
                    locale="es",
                )
                assert result["status"] == "sent"
                # Single deterministic kwarg assertion (no hedged 'or')
                mock_gen.assert_called_once()
                kwargs = mock_gen.call_args.kwargs
                assert kwargs["locale"] == "es"

    def test_passes_locale_to_day7_generator(self):
        """Day 7 generator should receive locale kwarg exactly once."""
        with patch.object(EmailService, "send", return_value=True):
            with patch("app.tasks.email_tasks.ONBOARDING_SEQUENCE") as mock_seq:
                mock_gen = MagicMock(return_value=("Subject", "<p>HTML</p>"))
                mock_seq.get.return_value = mock_gen
                mock_seq.keys.return_value = [7]

                from app.tasks.email_tasks import send_onboarding_email

                result = send_onboarding_email(
                    user_email="test@test.com",
                    user_name="Bob",
                    day=7,
                    credits_balance=500,
                    locale="fr",
                )
                assert result["status"] == "sent"
                mock_gen.assert_called_once()
                kwargs = mock_gen.call_args.kwargs
                assert kwargs["locale"] == "fr"

    def test_passes_locale_to_default_generator(self):
        """Day 1/3/14 generators should receive locale kwarg exactly once."""
        with patch.object(EmailService, "send", return_value=True):
            with patch("app.tasks.email_tasks.ONBOARDING_SEQUENCE") as mock_seq:
                mock_gen = MagicMock(return_value=("Subject", "<p>HTML</p>"))
                mock_seq.get.return_value = mock_gen
                mock_seq.keys.return_value = [1]

                from app.tasks.email_tasks import send_onboarding_email

                result = send_onboarding_email(
                    user_email="test@test.com",
                    user_name="Carol",
                    day=1,
                    locale="de",
                )
                assert result["status"] == "sent"
                mock_gen.assert_called_once()
                kwargs = mock_gen.call_args.kwargs
                assert kwargs["locale"] == "de"

    def test_no_locale_defaults_to_none(self):
        """Calling without locale should pass None to generator (or omit the kwarg)."""
        with patch.object(EmailService, "send", return_value=True):
            with patch("app.tasks.email_tasks.ONBOARDING_SEQUENCE") as mock_seq:
                mock_gen = MagicMock(return_value=("Subject", "<p>HTML</p>"))
                mock_seq.get.return_value = mock_gen
                mock_seq.keys.return_value = [1]

                from app.tasks.email_tasks import send_onboarding_email

                result = send_onboarding_email(
                    user_email="test@test.com",
                    user_name="Dave",
                    day=1,
                )
                assert result["status"] == "sent"
                # When called without locale, the generator must receive None
                # (or have the kwarg absent — both indicate no override).
                mock_gen.assert_called_once()
                kwargs = mock_gen.call_args.kwargs
                assert kwargs.get("locale") is None


class TestScheduleOnboardingSequenceLocale:
    def test_accepts_locale_parameter(self):
        """schedule_onboarding_sequence should accept locale."""
        with patch("app.tasks.email_tasks.send_onboarding_email") as mock_task:
            mock_task.apply_async = MagicMock()
            from app.tasks.email_tasks import schedule_onboarding_sequence

            result = schedule_onboarding_sequence(
                user_email="new@user.com",
                user_name="New User",
                api_key_prefix="ok_live_",
                locale="es",
            )
            assert result["status"] == "scheduled"
            # Verify locale in kwargs of each apply_async call
            for c in mock_task.apply_async.call_args_list:
                kwargs_dict = c[1].get("kwargs", c[0][0] if c[0] else {})
                assert kwargs_dict.get("locale") == "es", f"locale not passed in {kwargs_dict}"

    def test_locale_none_works(self):
        """schedule_onboarding_sequence without locale should enqueue 5 with locale=None."""
        with patch("app.tasks.email_tasks.send_onboarding_email") as mock_task:
            mock_task.apply_async = MagicMock()
            from app.tasks.email_tasks import schedule_onboarding_sequence

            result = schedule_onboarding_sequence(
                user_email="new@user.com",
                user_name="New User",
            )
            assert result["status"] == "scheduled"
            assert len(result["days"]) == 5
            # All 5 days should have been enqueued
            assert mock_task.apply_async.call_count == 5
            # No call should set a non-None locale (locale absent or explicitly None)
            for c in mock_task.apply_async.call_args_list:
                kwargs_dict = c[1].get("kwargs", {})
                assert kwargs_dict.get("locale") is None, (
                    f"locale unexpectedly set to {kwargs_dict.get('locale')!r}"
                )
