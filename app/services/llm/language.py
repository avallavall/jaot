"""The language the assistant answers in.

The platform ships in five languages, but everything the LLM generates used to
come back in English regardless of what the user was reading. The fix is one
directive appended to whichever system prompt is in play, built here so the
wording — and the parts that must NOT be translated — are stated once.
"""

# Only the locales the product actually ships. An unknown value falls back to
# English rather than asking a model to write in a language we do not serve.
SUPPORTED_LOCALES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "ca": "Catalan",
    "fr": "French",
    "de": "German",
}

DEFAULT_LOCALE = "en"

_DIRECTIVE = """

## Response language
Write your entire answer in {language}, whatever language the model, the data or \
the user's message happen to be in. This applies to prose, headings, bullet lists \
and any commentary.

NEVER translate: variable, constraint, set or parameter names; expressions, code, \
JSON keys and values; JModel source; file names; or identifiers of any kind. They \
are the model's vocabulary — translating them breaks the link between your answer \
and what the user sees on screen. Quote them exactly as given."""


def normalize_locale(locale: str | None) -> str:
    """Map an incoming locale to one we serve ("es-ES" → "es"), else the default."""
    if not locale:
        return DEFAULT_LOCALE
    base = locale.strip().lower().replace("_", "-").split("-")[0]
    return base if base in SUPPORTED_LOCALES else DEFAULT_LOCALE


def language_directive(locale: str | None) -> str:
    """The block to append to a system prompt so the answer comes back in ``locale``.

    Returned for English too: the model is not reliably English-by-default once
    the conversation, the model names or the data are in another language — being
    explicit costs a few tokens and removes the guesswork.
    """
    return _DIRECTIVE.format(language=SUPPORTED_LOCALES[normalize_locale(locale)])


__all__ = ["DEFAULT_LOCALE", "SUPPORTED_LOCALES", "language_directive", "normalize_locale"]
