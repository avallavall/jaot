"""The assistant answers in the user's language (not always English)."""

import pytest

from app.services.llm.language import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    language_directive,
    normalize_locale,
)
from app.services.llm.prompt_templates import build_system_prompt

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("incoming", "expected"),
    [
        ("es", "es"),
        ("ca", "ca"),
        ("fr", "fr"),
        ("de", "de"),
        ("en", "en"),
        # Region variants and casing map onto the language we serve…
        ("es-ES", "es"),
        ("fr_CA", "fr"),
        ("DE", "de"),
        ("  ca  ", "ca"),
        # …and anything we do not ship falls back rather than asking a model to
        # write in a language the product has no UI for.
        ("pt", DEFAULT_LOCALE),
        ("zh-Hans", DEFAULT_LOCALE),
        ("", DEFAULT_LOCALE),
        (None, DEFAULT_LOCALE),
    ],
)
def test_locales_normalise_to_a_language_we_ship(incoming, expected):
    assert normalize_locale(incoming) == expected


def test_the_directive_names_the_language_in_the_prompt():
    assert "Spanish" in language_directive("es")
    assert "Catalan" in language_directive("ca")
    assert "German" in language_directive("de-AT")
    # Unknown -> English, never a language we do not serve.
    assert "English" in language_directive("pt-BR")


# CONTRACT-TEST: identifiers are the model's vocabulary. Translating them would
# break the link between the explanation and what the user sees on screen.
def test_the_directive_forbids_translating_identifiers():
    directive = language_directive("fr")
    assert "NEVER translate" in directive
    for protected in ("variable", "JModel source", "JSON keys"):
        assert protected in directive


def test_every_shipped_locale_has_a_language_name():
    # The 5 locales the frontend routes on.
    assert set(SUPPORTED_LOCALES) == {"en", "es", "ca", "fr", "de"}
    assert all(name and name[0].isupper() for name in SUPPORTED_LOCALES.values())


def test_the_chat_system_prompt_carries_the_language_last():
    prompt = build_system_prompt(locale="ca")
    assert "Catalan" in prompt
    # Last block: the closest instruction to the user's turn wins ties.
    assert prompt.rstrip().endswith("Quote them exactly as given.")


def test_a_prompt_without_a_locale_still_states_a_language():
    # No locale is not "no instruction": an unstated language is exactly how the
    # assistant ended up answering in English regardless of the reader.
    assert "English" in build_system_prompt()
