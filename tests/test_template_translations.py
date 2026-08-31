"""Does every template card have text, in every language the platform ships?

The studio and the marketplace read card text from
``frontend/messages/<locale>.json``, not from the YAML. ``useTemplateTranslation``
falls back to the English the API served whenever a key is missing, so a card
with no entry shows English in all five locales and nothing reports it.

``frontend/src/__tests__/template-translations.test.ts`` was supposed to catch
that, and could not: it counted the JSON against a hardcoded 101 and never
looked at the YAML at all. There were 102 templates, so ``assignment`` had no
entry in any of the five locales, and the vitest suite stayed green.

The YAML is the source of truth. These tests compare the locale files to it.
"""

import json
import pathlib
import re

import pytest

from app.data.templates import load_all_templates

ALL_TEMPLATES = load_all_templates()
MESSAGES = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "messages"
LOCALES = ("en", "es", "ca", "fr", "de")

#: YAML field -> the camelCase key the frontend reads.
FIELDS = {
    "display_name": "displayName",
    "short_description": "shortDescription",
    "description": "description",
    "scenario_description": "scenarioDescription",
}


def _load(locale: str) -> dict:
    return json.loads((MESSAGES / f"{locale}.json").read_text(encoding="utf-8"))["templates"]


def _norm(text: str | None) -> str:
    """YAML folded blocks carry newlines the JSON does not."""
    return re.sub(r"\s+", " ", (text or "").strip())


@pytest.mark.parametrize("locale", LOCALES)
def test_every_template_has_an_entry(locale: str) -> None:
    """A card with no entry shows English, whatever language the reader chose."""
    entries = {k for k, v in _load(locale).items() if isinstance(v, dict) and "displayName" in v}
    ids = {t.id for t in ALL_TEMPLATES}
    assert not ids - entries, f"{locale}.json has no entry for: {sorted(ids - entries)}"
    assert not entries - ids, (
        f"{locale}.json has entries for templates that no longer exist: {sorted(entries - ids)}"
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_every_entry_is_filled(locale: str) -> None:
    """An empty string renders as an empty card, which is worse than a fallback."""
    entries = _load(locale)
    blank = [
        f"{t.id}.{key}"
        for t in ALL_TEMPLATES
        for key in (*FIELDS.values(), "categoryDisplayName")
        if not (entries.get(t.id) or {}).get(key)
    ]
    assert not blank, f"{locale}.json has empty text for: {blank[:10]}"


def test_english_matches_the_yaml_word_for_word() -> None:
    """The API serves the YAML and the studio renders en.json. They must agree."""
    entries = _load("en")
    drift = [
        f"{t.id}.{key}"
        for t in ALL_TEMPLATES
        for yaml_field, key in FIELDS.items()
        if _norm(getattr(t, yaml_field, "")) != _norm(entries[t.id].get(key))
    ]
    assert not drift, (
        f"en.json has drifted from the template YAML on: {drift[:10]}"
        f"{f' (+{len(drift) - 10} more)' if len(drift) > 10 else ''}"
    )


@pytest.mark.parametrize("locale", [loc for loc in LOCALES if loc != "en"])
def test_long_prose_is_actually_translated(locale: str) -> None:
    """A paragraph identical to the English one was never translated.

    Only prose over 80 characters is checked. A short display name can honestly
    be the same word in two languages; a four-line scenario cannot.
    """
    english, entries = _load("en"), _load(locale)
    untranslated = [
        f"{t.id}.{key}"
        for t in ALL_TEMPLATES
        for key in ("description", "scenarioDescription")
        if len(english[t.id].get(key, "")) > 80 and english[t.id].get(key) == entries[t.id].get(key)
    ]
    assert not untranslated, (
        f"{locale}.json repeats the English text verbatim for: {untranslated[:10]}"
        f"{f' (+{len(untranslated) - 10} more)' if len(untranslated) > 10 else ''}"
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_every_category_has_a_name(locale: str) -> None:
    """The marketplace groups by category and labels each group from here."""
    entries = _load(locale)
    categories = entries.get("_categories", {})
    used = {t.category for t in ALL_TEMPLATES}
    assert not used - set(categories), (
        f"{locale}.json _categories has no name for: {sorted(used - set(categories))}"
    )
    assert not set(categories) - used, (
        f"{locale}.json _categories names categories no template uses: "
        f"{sorted(set(categories) - used)}"
    )
