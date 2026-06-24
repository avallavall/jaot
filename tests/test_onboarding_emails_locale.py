"""
Tests for localized onboarding emails.

Covers:
- get_email_string fallback to English for unknown locale
- get_email_string returns correct translation for known locale
- All 5 email functions accept locale parameter (None, "es", "xx")
- Day 3 email says "101" not "11"
- _wrap with locale produces translated footer
- All 17 locales work without error for all 5 functions
"""

import pytest

from app.services.email_translations import EMAIL_TRANSLATIONS, get_email_string
from app.services.onboarding_emails import (
    _wrap,
    day0_welcome,
    day1_api_setup,
    day3_catalog,
    day7_credits,
    day14_feedback,
)

ALL_LOCALES = [
    "en",
    "es",
    "ca",
    "fr",
    "de",
    "it",
    "pt",
    "nl",
    "pl",
    "ro",
    "el",
    "cs",
    "sv",
    "da",
    "fi",
    "hu",
    "ru",
]


# get_email_string


class TestGetEmailString:
    def test_returns_english_for_unknown_locale(self):
        result = get_email_string("day0", "subject", "xx")
        en_result = get_email_string("day0", "subject", "en")
        assert result == en_result
        assert len(result) > 0

    def test_returns_english_for_none_locale(self):
        result = get_email_string("day0", "subject", None)
        en_result = get_email_string("day0", "subject", "en")
        assert result == en_result

    def test_returns_correct_translation_for_known_locale(self):
        en = get_email_string("day0", "subject", "en")
        es = get_email_string("day0", "subject", "es")
        # Spanish should be different from English
        assert es != en
        assert len(es) > 0

    def test_all_email_keys_exist(self):
        for key in ["day0", "day1", "day3", "day7", "day14", "footer"]:
            assert key in EMAIL_TRANSLATIONS, f"Missing email key: {key}"

    def test_all_locales_present_for_subjects(self):
        for email_key in ["day0", "day1", "day3", "day7", "day14"]:
            for locale in ALL_LOCALES:
                result = get_email_string(email_key, "subject", locale)
                assert len(result) > 0, f"Empty subject for {email_key}/{locale}"


# day0_welcome locale support


class TestDay0WelcomeLocale:
    def test_locale_none_returns_english(self):
        subj_none, html_none = day0_welcome("Alice", "ok_live_", locale=None)
        subj_en, html_en = day0_welcome("Alice", "ok_live_", locale="en")
        assert subj_none == subj_en

    def test_locale_es_returns_spanish(self):
        subject, html = day0_welcome("Alice", "ok_live_", locale="es")
        # Subject should be in Spanish (different from English)
        en_subject, _ = day0_welcome("Alice", "ok_live_", locale="en")
        assert subject != en_subject

    def test_locale_unknown_falls_back_to_english(self):
        subj_xx, _ = day0_welcome("Alice", "ok_live_", locale="xx")
        subj_en, _ = day0_welcome("Alice", "ok_live_", locale="en")
        assert subj_xx == subj_en


# day1_api_setup locale support


class TestDay1ApiSetupLocale:
    def test_locale_es(self):
        subject_es, _ = day1_api_setup("Alice", locale="es")
        subject_en, _ = day1_api_setup("Alice", locale="en")
        assert subject_es != subject_en

    def test_locale_unknown_fallback(self):
        subj_xx, _ = day1_api_setup("Alice", locale="xx")
        subj_en, _ = day1_api_setup("Alice", locale="en")
        assert subj_xx == subj_en


# day3_catalog locale support + 101 templates update


class TestDay3CatalogLocale:
    def test_subject_says_101_not_11_in_english(self):
        subject, html = day3_catalog("Alice", locale="en")
        assert "101" in subject or "101" in html
        assert "11 pre-built" not in html
        assert "11 ready" not in subject

    def test_locale_es(self):
        subject_es, _ = day3_catalog("Alice", locale="es")
        subject_en, _ = day3_catalog("Alice", locale="en")
        assert subject_es != subject_en

    def test_locale_unknown_fallback(self):
        subj_xx, _ = day3_catalog("Alice", locale="xx")
        subj_en, _ = day3_catalog("Alice", locale="en")
        assert subj_xx == subj_en


# day7_credits locale support


class TestDay7CreditsLocale:
    def test_locale_none(self):
        subject, html = day7_credits("Alice", 500, locale=None)
        # Balance must appear in a labelled context, not as stray "500"
        assert "500 credits" in html.lower() or ">500 " in html

    def test_locale_es(self):
        subject_es, _ = day7_credits("Alice", 500, locale="es")
        subject_en, _ = day7_credits("Alice", 500, locale="en")
        assert subject_es != subject_en

    def test_locale_unknown_fallback(self):
        subj_xx, _ = day7_credits("Alice", 500, locale="xx")
        subj_en, _ = day7_credits("Alice", 500, locale="en")
        assert subj_xx == subj_en


# day14_feedback locale support


class TestDay14FeedbackLocale:
    def test_locale_es(self):
        subject_es, _ = day14_feedback("Alice", locale="es")
        subject_en, _ = day14_feedback("Alice", locale="en")
        assert subject_es != subject_en

    def test_locale_unknown_fallback(self):
        subj_xx, _ = day14_feedback("Alice", locale="xx")
        subj_en, _ = day14_feedback("Alice", locale="en")
        assert subj_xx == subj_en


# _wrap with locale (translated footer)


class TestWrapLocale:
    def test_wrap_with_french_locale_has_translated_footer(self):
        html = _wrap("<p>Hello</p>", locale="fr")
        # Should contain French footer text (different from English unsubscribe text)
        fr_unsub = get_email_string("footer", "unsubscribe", "fr")
        assert fr_unsub in html

    def test_wrap_with_none_locale_has_english_footer(self):
        html = _wrap("<p>Hello</p>", locale=None)
        en_unsub = get_email_string("footer", "unsubscribe", "en")
        assert en_unsub in html


class TestAll17Locales:
    @pytest.mark.parametrize("locale", ALL_LOCALES)
    def test_all_emails_work_for_locale(self, locale):
        """All 5 email functions produce valid output for every locale.

        For non-English locales, also assert each subject DIFFERS from the
        English subject — catches silent fall-through to the en bundle when
        a translation key is missing.
        """
        s0, _ = day0_welcome("Test", "ok_live_", locale=locale)
        s1, _ = day1_api_setup("Test", locale=locale)
        s3, _ = day3_catalog("Test", locale=locale)
        s7, _ = day7_credits("Test", 200, locale=locale)
        s14, _ = day14_feedback("Test", locale=locale)

        for subj in (s0, s1, s3, s7, s14):
            assert isinstance(subj, str) and len(subj) > 0

        if locale != "en":
            en_s0, _ = day0_welcome("Test", "ok_live_", locale="en")
            en_s1, _ = day1_api_setup("Test", locale="en")
            en_s3, _ = day3_catalog("Test", locale="en")
            en_s7, _ = day7_credits("Test", 200, locale="en")
            en_s14, _ = day14_feedback("Test", locale="en")

            assert s0 != en_s0, f"day0 subject for {locale} matches en (silent fallthrough)"
            assert s1 != en_s1, f"day1 subject for {locale} matches en (silent fallthrough)"
            assert s3 != en_s3, f"day3 subject for {locale} matches en (silent fallthrough)"
            assert s7 != en_s7, f"day7 subject for {locale} matches en (silent fallthrough)"
            assert s14 != en_s14, f"day14 subject for {locale} matches en (silent fallthrough)"
