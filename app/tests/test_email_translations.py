"""Tests for email translation completeness and get_email_string behavior (I18N-12)."""

import os
import sys

import pytest

# Add app root to path so we can import services
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.email_translations import EMAIL_TRANSLATIONS, get_email_string

EXPECTED_EMAIL_KEYS = ["day0", "day1", "day3", "day7", "day14", "footer"]
EXPECTED_LOCALES = [
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


class TestEmailTranslationsStructure:
    """EMAIL_TRANSLATIONS has all 6 email types with all 17 locales."""

    def test_all_email_types_present(self):
        for key in EXPECTED_EMAIL_KEYS:
            assert key in EMAIL_TRANSLATIONS, f"Missing email type: {key}"

    def test_each_email_type_has_string_keys(self):
        for email_key in EXPECTED_EMAIL_KEYS:
            strings = EMAIL_TRANSLATIONS[email_key]
            assert len(strings) > 0, f"{email_key} has no string keys"

    @pytest.mark.parametrize("email_key", EXPECTED_EMAIL_KEYS)
    def test_all_locales_present_in_each_string(self, email_key):
        strings = EMAIL_TRANSLATIONS[email_key]
        for string_key, locale_map in strings.items():
            for locale in EXPECTED_LOCALES:
                assert locale in locale_map, f"{email_key}.{string_key} missing locale: {locale}"

    @pytest.mark.parametrize("email_key", EXPECTED_EMAIL_KEYS)
    def test_no_empty_translations(self, email_key):
        strings = EMAIL_TRANSLATIONS[email_key]
        for string_key, locale_map in strings.items():
            for locale, value in locale_map.items():
                assert isinstance(value, str) and len(value) > 0, (
                    f"{email_key}.{string_key}.{locale} is empty"
                )


class TestGetEmailString:
    """get_email_string returns correct translations with English fallback."""

    def test_returns_english_when_no_locale(self):
        result = get_email_string("day0", "subject")
        assert result == EMAIL_TRANSLATIONS["day0"]["subject"]["en"]

    def test_returns_english_when_locale_is_none(self):
        result = get_email_string("day0", "subject", locale=None)
        assert result == EMAIL_TRANSLATIONS["day0"]["subject"]["en"]

    def test_returns_translated_string_for_known_locale(self):
        result = get_email_string("day0", "subject", locale="es")
        assert result == EMAIL_TRANSLATIONS["day0"]["subject"]["es"]
        assert result != EMAIL_TRANSLATIONS["day0"]["subject"]["en"]

    def test_falls_back_to_english_for_unknown_locale(self):
        result = get_email_string("day0", "subject", locale="xx")
        assert result == EMAIL_TRANSLATIONS["day0"]["subject"]["en"]

    def test_returns_empty_string_for_unknown_email_key(self):
        result = get_email_string("nonexistent", "subject", locale="en")
        assert result == ""

    def test_returns_empty_string_for_unknown_string_key(self):
        result = get_email_string("day0", "nonexistent", locale="en")
        assert result == ""

    @pytest.mark.parametrize("locale", ["fr", "de", "it", "ca", "ru"])
    def test_non_english_locales_return_different_text(self, locale):
        en_result = get_email_string("day0", "subject", locale="en")
        locale_result = get_email_string("day0", "subject", locale=locale)
        assert locale_result != en_result, f"{locale} day0.subject is identical to English"
