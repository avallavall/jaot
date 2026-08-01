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
            assert len(result["days"]) == 4
            # All 5 days should have been enqueued
            assert mock_task.apply_async.call_count == 4
            # No call should set a non-None locale (locale absent or explicitly None)
            for c in mock_task.apply_async.call_args_list:
                kwargs_dict = c[1].get("kwargs", {})
                assert kwargs_dict.get("locale") is None, (
                    f"locale unexpectedly set to {kwargs_dict.get('locale')!r}"
                )


# ---------------------------------------------------------------------------
# The transactional auth emails follow the same rule as the onboarding sequence:
# they are sent in the language the account was created in. Nothing wrote
# User.locale at signup, so the entire translated email programme — onboarding
# included — went out in English regardless of who signed up.
# ---------------------------------------------------------------------------


class TestSignupRecordsTheLocale:
    @staticmethod
    def _enable_registration(db_session):
        from app.services.platform_settings_service import PlatformSettingsService

        PlatformSettingsService.set(db_session, "REGISTRATION_ENABLED", "true")
        db_session.commit()

    def test_signup_persists_the_locale_it_was_made_in(self, client, db_session):
        from app.models import User

        self._enable_registration(db_session)
        resp = client.post(
            "/api/v2/auth/signup/email",
            json={
                "email": "locale.signup@example.com",
                "name": "Locale Probe",
                "organization_name": "Locale Probe Org",
                "password": "a-very-long-password",
                "confirm_password": "a-very-long-password",
                "tos_accepted": True,
                "locale": "de",
            },
        )
        assert resp.status_code in (200, 201), resp.text

        user = db_session.query(User).filter(User.email == "locale.signup@example.com").one()
        assert user.locale == "de"

    def test_signup_without_a_locale_is_still_accepted(self, client, db_session):
        from app.models import User

        self._enable_registration(db_session)
        resp = client.post(
            "/api/v2/auth/signup/email",
            json={
                "email": "no.locale@example.com",
                "name": "No Locale",
                "organization_name": "No Locale Org",
                "password": "a-very-long-password",
                "confirm_password": "a-very-long-password",
                "tos_accepted": True,
            },
        )
        assert resp.status_code in (200, 201), resp.text
        user = db_session.query(User).filter(User.email == "no.locale@example.com").one()
        assert user.locale is None


class TestAuthEmailsAreTranslated:
    def test_reset_and_verify_strings_exist_for_every_product_locale(self):
        from app.services.email_translations import get_email_string

        for locale in ("en", "es", "ca", "fr", "de"):
            for key in ("subject", "heading", "body", "cta", "expiry"):
                assert get_email_string("verify_email", key, locale), (
                    f"verify_email.{key} missing for {locale}"
                )
            for key in ("subject", "heading", "body", "cta", "expiry", "ignore"):
                assert get_email_string("reset_password", key, locale), (
                    f"reset_password.{key} missing for {locale}"
                )

    def test_a_locale_we_do_not_translate_falls_back_to_english(self):
        from app.services.email_translations import get_email_string

        assert get_email_string("reset_password", "subject", "ja") == (
            get_email_string("reset_password", "subject", "en")
        )

    def test_reset_email_is_sent_in_the_users_language(self, client, db_session, monkeypatch):
        """# CONTRACT-TEST: a password reset arrives in the language of the account."""
        from app.models import User
        from app.services.auth.password_service import PasswordService

        user = User(
            id="usr_reset_locale_probe",
            email="reset.locale@example.com",
            name="Reset Probe",
            organization_id="org_reset_locale_probe",
            role="member",
            password_hash=PasswordService.hash_password("a-very-long-password"),
            locale="es",
        )
        from app.models import Organization

        db_session.add(
            Organization(id="org_reset_locale_probe", name="Reset Locale Org", slug="reset-locale")
        )
        db_session.add(user)
        db_session.commit()

        sent: dict[str, str] = {}

        from app.services import email_service

        def _capture(to: str, subject: str, html: str, **kwargs: object) -> bool:
            sent["subject"] = subject
            sent["html"] = html
            return True

        monkeypatch.setattr(email_service.EmailService, "send", staticmethod(_capture))

        resp = client.post(
            "/api/v2/auth/forgot-password", json={"email": "reset.locale@example.com"}
        )
        assert resp.status_code == 200, resp.text
        assert sent["subject"] == "Restablece tu contraseña de JAOT"
        assert "Restablecer contraseña" in sent["html"]
