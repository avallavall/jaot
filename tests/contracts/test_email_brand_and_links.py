"""What every outgoing email must be true of.

Two things went wrong here and neither had a test. Four links answered 404 —
one of them the unsubscribe in EVERY footer, another the whole day-14 call to
action — and the two emails a new account sees first had no template at all,
so they rendered as Times New Roman on white.
"""

from __future__ import annotations

import re

import pytest

from app.services import email_layout
from app.services.onboarding_emails import ONBOARDING_SEQUENCE

pytestmark = pytest.mark.contract

#: Every in-app path an email is allowed to link to. Each was checked against
#: the frontend router. Adding one here without adding the page is the mistake
#: this list exists to stop.
_KNOWN_PATHS = frozenset(
    {
        "",
        "/",
        "/docs",
        "/docs/getting-started/quick-start",
        "/docs/api/solve",
        "/workspace/api-keys",
        "/workspace/models",
        "/workspace/settings",
        "/marketplace",
        # The destinations the transactional pair exists to deliver.
        "/verify-email",
        "/reset-password",
        # Not a page: the example request in the day-0 email.
        "/api/v2/solve",
    }
)

_LOCALES = ("en", "es", "ca", "fr", "de")


def _all_emails(locale: str) -> list[tuple[str, str]]:
    """(name, html) for every email the platform sends to a person."""
    out: list[tuple[str, str]] = []
    for day, build in sorted(ONBOARDING_SEQUENCE.items()):
        kwargs: dict = {"user_name": "Ada", "locale": locale}
        if day == 0:
            kwargs["api_key_prefix"] = "ok_live_"
        out.append((f"day{day}", build(**kwargs)[1]))
    out.append(("verify", email_layout.verify_email("https://jaot.io/verify-email?t=x", locale)[1]))
    out.append(
        ("reset", email_layout.reset_password("https://jaot.io/reset-password?t=x", locale)[1])
    )
    return out


def _jaot_paths(html: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r"https://jaot\.io([^\"'\s<)]*)", html)}


# CONTRACT-TEST: no email links to a page that does not exist.
@pytest.mark.parametrize("locale", _LOCALES)
def test_every_link_points_at_a_real_page(locale: str) -> None:
    for name, html in _all_emails(locale):
        for path in _jaot_paths(html):
            bare = path.split("?")[0].rstrip("/") or "/"
            assert bare in _KNOWN_PATHS or path in _KNOWN_PATHS, (
                f"{name} ({locale}) links to https://jaot.io{path}, which is not a known page"
            )


# CONTRACT-TEST: the routes that were 404 stay dead.
@pytest.mark.parametrize("locale", _LOCALES)
def test_the_routes_that_never_existed_are_not_linked_again(locale: str) -> None:
    gone = ("/settings/notifications", "/feedback", '/docs/getting-started"', "/docs/api/reference")
    for name, html in _all_emails(locale):
        for path in gone:
            assert f"https://jaot.io{path}" not in html, f"{name} ({locale}) links {path} again"


# CONTRACT-TEST: every email carries the platform's brand, not a palette of its own.
@pytest.mark.parametrize("locale", _LOCALES)
def test_every_email_wears_the_platform_brand(locale: str) -> None:
    for name, html in _all_emails(locale):
        assert email_layout.BG in html, f"{name} ({locale}) is missing the brand background"
        assert email_layout.PRIMARY in html, f"{name} ({locale}) is missing the brand colour"
        assert ">JAOT</span>" in html, f"{name} ({locale}) has no masthead"
        # The blue the emails used to be built in.
        assert "#2563eb" not in html.lower(), f"{name} ({locale}) still carries the old blue"


# CONTRACT-TEST: the transactional pair is wrapped, and offers no unsubscribe.
#
# They used to be raw `<h2>`/`<p>`/`<a>`. They are also not marketing: offering
# to unsubscribe from "confirm your address" would be a lie.
@pytest.mark.parametrize("locale", _LOCALES)
def test_the_transactional_pair_is_wrapped_and_never_offers_unsubscribe(locale: str) -> None:
    for build, url in (
        (email_layout.verify_email, "https://jaot.io/verify-email?t=x"),
        (email_layout.reset_password, "https://jaot.io/reset-password?t=x"),
    ):
        subject, html = build(url, locale)
        assert subject, "no subject"
        assert html.startswith("<!DOCTYPE html>")
        assert url in html, "the link it exists to deliver is missing"
        assert email_layout.NOTIFICATION_SETTINGS not in html, "offered to unsubscribe"


# CONTRACT-TEST: no English leaks into a translated email.
#
# The day-1 tip linked to the API keys page under the literal word "Settings",
# in every language.
def test_no_english_label_leaks_into_a_translated_email() -> None:
    _, html = ONBOARDING_SEQUENCE[1](user_name="Ada", locale="es")
    assert ">Settings</a>" not in html, "the API keys link is labelled in English"
    assert "Claves API" in html


# CONTRACT-TEST: a reader replies to the address the platform actually uses.
def test_feedback_goes_to_the_support_address() -> None:
    _, html = ONBOARDING_SEQUENCE[14](user_name="Ada", locale="en")
    assert "founders@jaot.io" not in html
    assert f"mailto:{email_layout.SUPPORT_EMAIL}" in html


# CONTRACT-TEST: a name somebody chose cannot become markup in somebody's inbox.
#
# A notification about an execution names the model, and a model is named by
# whoever made it. The helpers took that straight into the HTML.
def test_the_layout_escapes_what_it_is_given() -> None:
    nasty = '<img src=x onerror="alert(1)">'
    for built in (email_layout.heading(nasty), email_layout.paragraph(nasty)):
        assert "<img" not in built, "markup survived into the email"
        assert "&lt;img" in built

    labelled = email_layout.button("https://jaot.io/workspace/models", nasty)
    assert "<img" not in labelled
    assert "&lt;img" in labelled


# CONTRACT-TEST: a button never points at a scheme a reader should not click.
def test_a_button_refuses_anything_but_http_https_and_mailto() -> None:
    for href in ("javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "//evil.test"):
        assert email_layout.button(href, "Open") == "", f"{href} rendered a button"
        assert "<a" not in email_layout.link(href, "Open"), f"{href} rendered a link"

    # A path is resolved against the site; the real schemes go through.
    assert email_layout.SITE + "/workspace/models" in email_layout.button("/workspace/models", "Go")
    assert "mailto:support@jaot.io" in email_layout.button("mailto:support@jaot.io", "Write")
