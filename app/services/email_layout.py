"""One place that owns what a JAOT email looks like.

Every outgoing email is built here, so the brand cannot drift between them
again. Before this there were three tiers: the onboarding sequence had a
wrapper of its own in a palette nobody else used (Tailwind blue on cool grey),
and the two emails a new account sees FIRST -- verify your address, reset your
password -- were raw ``<h2>``/``<p>``/``<a>`` with no wrapper at all, so they
rendered as Times New Roman on white with a default blue underline.

The palette is the platform's own, read off ``frontend/src/app/globals.css``:
warm cream and brown with a sage accent, not the cool blue the emails used.

**Fonts.** Headings ask for Fraunces first because a few clients (Apple Mail,
iOS) do load it, and fall back to Georgia -- the closest old-style serif every
client already has. Web fonts are not reliable in email, so the fallback is
what most readers actually see, and it is chosen to be right on its own.

**Inline styles only.** Gmail strips ``<style>`` blocks, so there is no
stylesheet here by design, and the layout is a table because Outlook still
does not do flexbox.
"""

from __future__ import annotations

from html import escape as _html_escape

from app.services.email_translations import get_email_string

# -- The platform's palette (frontend/src/app/globals.css, light theme) -------
#: Page behind the card.
BG = "#F6F0EA"
#: The card itself.
SURFACE = "#FFFFFF"
#: Body text.
TEXT = "#3A3230"
#: Secondary text -- the footer, captions.
MUTED = "#6B5F59"
#: Brand: headings, buttons, links.
PRIMARY = "#5D4E47"
#: Sage accent -- the callout rule.
ACCENT = "#8AA499"
#: Hairlines. A flat hex, because ``rgba()`` is unreliable in Outlook.
BORDER = "#E4DBD3"
#: Panel behind a callout or a story card.
PANEL = "#F1E6D8"
#: Code blocks. Dark, like the studio's editor.
CODE_BG = "#3A3230"
CODE_TEXT = "#E8D9C5"

SERIF = "Fraunces, Georgia, 'Times New Roman', Times, serif"
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

#: Where a reader replies or asks for help. The rest of the platform uses this
#: address (the footer of every email, the privacy and terms pages, the help
#: menu); ``founders@jaot.io`` appeared in one email only and nowhere else.
SUPPORT_EMAIL = "support@jaot.io"

#: Public site root. Kept here so no email builds a URL by hand.
SITE = "https://jaot.io"

#: Every in-app destination an email links to, checked against the router.
#: ``/settings/notifications`` and ``/feedback`` never existed -- the first was
#: the unsubscribe link in EVERY footer, the second was the whole day-14 call
#: to action, and both answered 404.
DOCS_QUICK_START = SITE + "/docs/getting-started/quick-start"
DOCS_API_SOLVE = SITE + "/docs/api/solve"
DOCS_ROOT = SITE + "/docs"
API_KEYS = SITE + "/workspace/api-keys"
MARKETPLACE = SITE + "/marketplace"
#: The page that actually holds the notification preferences.
NOTIFICATION_SETTINGS = SITE + "/workspace/settings"


def safe(text: str, fallback: str = "there") -> str:
    """HTML-escape a user-controlled value before inlining it into markup."""
    if not text:
        return fallback
    return _html_escape(text, quote=True)


def heading(text: str, level: int = 1) -> str:
    """A brand heading. Serif, brown, no bright blue anywhere."""
    size = {1: "28px", 2: "20px"}.get(level, "20px")
    return (
        '<h{lvl} style="margin:0 0 16px;font-family:{serif};font-weight:600;'
        'font-size:{size};line-height:1.25;color:{primary};">{text}</h{lvl}>'
    ).format(lvl=level, serif=SERIF, size=size, primary=PRIMARY, text=text)


def paragraph(text: str, muted: bool = False) -> str:
    colour = MUTED if muted else TEXT
    return (
        '<p style="margin:0 0 16px;font-family:{sans};font-size:15px;'
        'line-height:1.6;color:{colour};">{text}</p>'
    ).format(sans=SANS, colour=colour, text=text)


def link(href: str, label: str) -> str:
    """An inline link, in the brand brown rather than the browser blue."""
    return '<a href="{href}" style="color:{primary};text-decoration:underline;">{label}</a>'.format(
        href=href, primary=PRIMARY, label=label
    )


def button(href: str, label: str) -> str:
    """The one call to action. Solid brand brown, generous tap target."""
    return (
        '<a href="{href}" style="display:inline-block;background:{primary};'
        "color:#FFFFFF;font-family:{sans};font-size:15px;font-weight:600;"
        "padding:13px 26px;border-radius:8px;text-decoration:none;"
        'margin:8px 0 4px;">{label}</a>'
    ).format(href=href, primary=PRIMARY, sans=SANS, label=label)


def callout(body: str) -> str:
    """A panel with the sage rule down its left edge."""
    return (
        '<div style="background:{panel};border-left:3px solid {accent};'
        'padding:16px 18px;border-radius:0 8px 8px 0;margin:0 0 20px;">{body}</div>'
    ).format(panel=PANEL, accent=ACCENT, body=body)


def panel(body: str) -> str:
    """A quiet panel with no rule -- used for the story cards."""
    return (
        '<div style="background:{panel};padding:16px 18px;border-radius:8px;'
        'margin:0 0 12px;">{body}</div>'
    ).format(panel=PANEL, body=body)


def code_block(code: str) -> str:
    return (
        '<pre style="background:{bg};color:{fg};padding:18px;border-radius:8px;'
        "overflow-x:auto;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
        'font-size:13px;line-height:1.5;margin:0 0 20px;white-space:pre-wrap;">{code}</pre>'
    ).format(bg=CODE_BG, fg=CODE_TEXT, code=code)


def _masthead() -> str:
    """The wordmark, in the same serif the site puts in its top-left corner."""
    return (
        '<div style="padding:0 0 24px;border-bottom:1px solid {border};margin-bottom:28px;">'
        '<span style="font-family:{serif};font-size:22px;letter-spacing:0.01em;'
        'color:{primary};">JAOT</span></div>'
    ).format(border=BORDER, serif=SERIF, primary=PRIMARY)


def _footer(locale: str | None, show_unsubscribe: bool) -> str:
    def t(key: str) -> str:
        return get_email_string("footer", key, locale)

    style = "color:{muted};text-decoration:underline;".format(muted=MUTED)
    unsubscribe = ""
    if show_unsubscribe:
        unsubscribe = (
            '<p style="margin:10px 0 0;">{label} <a href="{href}" style="{style}">{cta}</a></p>'
        ).format(
            label=t("unsubscribe"),
            href=NOTIFICATION_SETTINGS,
            style=style,
            cta=t("unsubscribeLink"),
        )
    return """
<div style="margin-top:36px;padding-top:18px;border-top:1px solid {border};
            font-family:{sans};font-size:12px;line-height:1.6;color:{muted};">
    <p style="margin:0;">{brand}</p>
    <p style="margin:6px 0 0;">
        <a href="{site}" style="{style}">jaot.io</a> &middot;
        <a href="{docs}" style="{style}">{docs_label}</a> &middot;
        <a href="mailto:{support}" style="{style}">{support_label}</a>
    </p>
    {unsubscribe}
</div>
""".format(
        border=BORDER,
        sans=SANS,
        muted=MUTED,
        brand=t("brand"),
        site=SITE,
        docs=DOCS_ROOT,
        docs_label=t("docsLink"),
        support=SUPPORT_EMAIL,
        support_label=t("supportLink"),
        style=style,
        unsubscribe=unsubscribe,
    )


def wrap(content: str, locale: str | None = None, *, unsubscribe: bool = True) -> str:
    """Put ``content`` on a JAOT-looking page.

    ``unsubscribe`` is False for the transactional pair: verifying an address
    and resetting a password are not marketing, and offering to unsubscribe
    from them would be a lie.
    """
    return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light">
</head>
<body style="margin:0;padding:0;background:{bg};font-family:{sans};color:{text};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:{bg};padding:32px 12px;">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0"
           style="max-width:600px;width:100%;background:{surface};
                  border:1px solid {border};border-radius:12px;">
      <tr><td style="padding:32px 32px 28px;font-family:{sans};font-size:15px;
                     line-height:1.6;color:{text};">
        {masthead}
        {content}
        {footer}
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>
""".format(
        bg=BG,
        surface=SURFACE,
        border=BORDER,
        sans=SANS,
        text=TEXT,
        masthead=_masthead(),
        content=content,
        footer=_footer(locale, unsubscribe),
    )


# -- The transactional pair, which used to have no template at all -----------


def _transactional(
    group: str, url: str, locale: str | None, *, extra_keys: tuple[str, ...] = ()
) -> tuple[str, str]:
    def t(key: str) -> str:
        return get_email_string(group, key, locale)

    body = (
        heading(t("heading"))
        + paragraph(t("body"))
        + button(url, t("cta"))
        + paragraph(t("expiry"), muted=True)
    )
    for key in extra_keys:
        body += paragraph(t(key), muted=True)
    return t("subject"), wrap(body, locale, unsubscribe=False)


def verify_email(verify_url: str, locale: str | None = None) -> tuple[str, str]:
    """(subject, html) for "confirm your address" -- the first email an account gets."""
    return _transactional("verify_email", verify_url, locale)


def reset_password(reset_url: str, locale: str | None = None) -> tuple[str, str]:
    """(subject, html) for "reset your password".

    Carries the extra "ignore this if it was not you" line the verify email has
    no equivalent of.
    """
    return _transactional("reset_password", reset_url, locale, extra_keys=("ignore",))
