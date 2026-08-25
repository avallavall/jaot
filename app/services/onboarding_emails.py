"""
Onboarding email sequence for new users.

Sequence:
    Day 0  — Welcome + first solve guide
    Day 1  — API key setup + code examples
    Day 3  — Model catalog tour + templates
    Day 14 — Success stories + feedback request

Each function returns (subject, html_body) for the email service.
All functions accept an optional `locale` parameter for translated content.
"""

from collections.abc import Callable
from html import escape as _html_escape
from urllib.parse import quote as _url_quote

from app.services import email_layout
from app.services.email_translations import get_email_string

#: Kept as a name so the four builders below read the same. The value is
#: the platform's, not a colour picked for email.
BRAND_COLOR = email_layout.PRIMARY


def _safe_name(name: str) -> str:
    """HTML-escape a user-controlled name before inlining into email markup.

    Falls back to a generic 'there' label so the salutation stays grammatical
    when the user supplied an empty name.
    """
    if not name:
        return "there"
    return _html_escape(name, quote=True)


def _wrap(content: str, locale: str | None = None) -> str:
    """Put an onboarding email on the shared JAOT page.

    The look lives in :mod:`app.services.email_layout`, which every email now
    shares. This wrapper had a palette of its own — Tailwind blue on cool grey —
    that matched nothing on the site.
    """
    return email_layout.wrap(content, locale)


def day0_welcome(user_name: str, api_key_prefix: str, locale: str | None = None) -> tuple[str, str]:
    """Day 0: Welcome email with first solve guide."""

    def t(key: str) -> str:
        return get_email_string("day0", key, locale)

    safe_name = _safe_name(user_name)
    safe_api_key_prefix = _html_escape(api_key_prefix, quote=True)

    subject = t("subject")
    html = _wrap(
        f"""
    <h1 style="color:{BRAND_COLOR};margin-bottom:8px;">{t("heading").format(user_name=safe_name)} 🎉</h1>
    <p style="font-size:16px;color:#3A3230;">
        {t("bodyIntro")}
    </p>

    <div style="background:#F1E6D8;border-left:4px solid {BRAND_COLOR};padding:16px;margin:24px 0;border-radius:4px;">
        <h3 style="margin:0 0 8px 0;color:#5D4E47;">{t("apiKeyHeading")}</h3>
        <code style="background:#F1E6D8;padding:4px 8px;border-radius:4px;font-size:14px;">{safe_api_key_prefix}••••••••</code>
        <p style="margin:8px 0 0;font-size:13px;color:#6B5F59;">
            {t("apiKeyHint")} <a href="https://jaot.io/workspace/api-keys" style="color:{BRAND_COLOR};">{t("apiKeyLink")}</a>
        </p>
    </div>

    <h2 style="color:#5D4E47;">{t("firstSolveHeading")}</h2>
    <pre style="background:#3A3230;color:#E4DBD3;padding:16px;border-radius:8px;overflow-x:auto;font-size:13px;">
curl -X POST https://jaot.io/api/v2/solve \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{{
    "template": "knapsack",
    "input": {{
      "items": [
        {{"name": "laptop", "value": 1000, "weight": 3}},
        {{"name": "phone", "value": 800, "weight": 1}},
        {{"name": "tablet", "value": 500, "weight": 2}}
      ],
      "capacity": 4
    }}
  }}'</pre>

    <p style="color:#3A3230;">{t("bodyOutro")}</p>

    <a href="https://jaot.io/docs/getting-started/quick-start"
       style="display:inline-block;background:{BRAND_COLOR};color:white;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600;margin-top:16px;">
        {t("ctaText")}
    </a>
    """,
        locale=locale,
    )
    return subject, html


def day1_api_setup(user_name: str, locale: str | None = None) -> tuple[str, str]:
    """Day 1: API key management + Python/JS code examples."""

    def t(key: str) -> str:
        return get_email_string("day1", key, locale)

    # The label used to be the literal word "Settings", in English, inside an
    # email translated into five languages.
    keys_link = email_layout.link(email_layout.API_KEYS, t("apiKeysLinkLabel"))

    safe_name = _safe_name(user_name)
    subject = t("subject")
    html = _wrap(
        f"""
    <h1 style="color:{BRAND_COLOR};">{t("heading").format(user_name=safe_name)}</h1>
    <p style="font-size:16px;color:#3A3230;">
        {t("bodyIntro")}
    </p>

    <h2 style="color:#5D4E47;">Python</h2>
    <pre style="background:#3A3230;color:#E4DBD3;padding:16px;border-radius:8px;overflow-x:auto;font-size:13px;">
import requests

result = requests.post(
    "https://jaot.io/api/v2/solve",
    headers={{"Authorization": "Bearer YOUR_API_KEY"}},
    json={{
        "template": "budget_allocation",
        "input": {{
            "total_budget": 100000,
            "departments": [
                {{"name": "Marketing", "expected_roi": 1.8}},
                {{"name": "R&D", "expected_roi": 2.5}},
                {{"name": "Sales", "expected_roi": 1.5}},
            ]
        }}
    }}
).json()

print(result["solution"]["variables"])</pre>

    <h2 style="color:#5D4E47;">JavaScript / Node.js</h2>
    <pre style="background:#3A3230;color:#E4DBD3;padding:16px;border-radius:8px;overflow-x:auto;font-size:13px;">
const res = await fetch("https://jaot.io/api/v2/solve", {{
  method: "POST",
  headers: {{
    "Authorization": "Bearer YOUR_API_KEY",
    "Content-Type": "application/json",
  }},
  body: JSON.stringify({{
    template: "knapsack",
    input: {{ items: [...], capacity: 100 }}
  }})
}});
const data = await res.json();</pre>

    <h2 style="color:#5D4E47;">{t("bestPracticesHeading")}</h2>
    <ul style="color:#3A3230;">
        <li>{t("tip1")}</li>
        <li>{t("tip2")}</li>
        <li>{t("tip3")} {keys_link}</li>
    </ul>

    <a href="https://jaot.io/docs/api/solve"
       style="display:inline-block;background:{BRAND_COLOR};color:white;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600;margin-top:16px;">
        {t("ctaText")}
    </a>
    """,
        locale=locale,
    )
    return subject, html


def day3_catalog(user_name: str, locale: str | None = None) -> tuple[str, str]:
    """Day 3: Template catalog tour — 101 ready-to-use templates."""

    def t(key: str) -> str:
        return get_email_string("day3", key, locale)

    safe_name = _safe_name(user_name)
    subject = t("subject")
    html = _wrap(
        f"""
    <h1 style="color:{BRAND_COLOR};">{t("heading").format(user_name=safe_name)}</h1>
    <p style="font-size:16px;color:#3A3230;">
        {t("bodyIntro")}
    </p>

    <table style="width:100%;border-collapse:collapse;margin:24px 0;">
        <tr style="background:#F1E6D8;">
            <th style="text-align:left;padding:8px 12px;border-bottom:2px solid #E4DBD3;">{t("tableModel")}</th>
            <th style="text-align:left;padding:8px 12px;border-bottom:2px solid #E4DBD3;">{t("tableUseCase")}</th>
        </tr>
        <tr><td style="padding:8px 12px;border-bottom:1px solid #F1E6D8;">📦 {t("row1name")}</td><td style="padding:8px 12px;border-bottom:1px solid #F1E6D8;">{t("row1desc")}</td></tr>
        <tr><td style="padding:8px 12px;border-bottom:1px solid #F1E6D8;">👥 {t("row2name")}</td><td style="padding:8px 12px;border-bottom:1px solid #F1E6D8;">{t("row2desc")}</td></tr>
        <tr><td style="padding:8px 12px;border-bottom:1px solid #F1E6D8;">🚛 {t("row3name")}</td><td style="padding:8px 12px;border-bottom:1px solid #F1E6D8;">{t("row3desc")}</td></tr>
        <tr><td style="padding:8px 12px;border-bottom:1px solid #F1E6D8;">📊 {t("row4name")}</td><td style="padding:8px 12px;border-bottom:1px solid #F1E6D8;">{t("row4desc")}</td></tr>
        <tr><td style="padding:8px 12px;border-bottom:1px solid #F1E6D8;">🏭 {t("row5name")}</td><td style="padding:8px 12px;border-bottom:1px solid #F1E6D8;">{t("row5desc")}</td></tr>
        <tr><td style="padding:8px 12px;border-bottom:1px solid #F1E6D8;">💰 {t("row6name")}</td><td style="padding:8px 12px;border-bottom:1px solid #F1E6D8;">{t("row6desc")}</td></tr>
        <tr><td style="padding:8px 12px;">🔧 {t("moreTemplates")}</td><td style="padding:8px 12px;"></td></tr>
    </table>

    <p style="color:#3A3230;">
        {t("bodyOutro")}
    </p>

    <a href="https://jaot.io/workspace/models"
       style="display:inline-block;background:{BRAND_COLOR};color:white;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600;margin-top:16px;">
        {t("ctaText")}
    </a>
    """,
        locale=locale,
    )
    return subject, html


def day14_feedback(user_name: str, locale: str | None = None) -> tuple[str, str]:
    """Day 14: Success stories + feedback request."""

    def t(key: str) -> str:
        return get_email_string("day14", key, locale)

    safe_name = _safe_name(user_name)
    url_safe_name = _url_quote(user_name) if user_name else "anonymous"

    # The four faces linked to /feedback?rating=..., a route that never existed:
    # every one of them answered 404, so the whole ask did nothing. A mailto
    # carries the rating for real and needs no new page. The address is the one
    # the rest of the platform uses; this email pointed at founders@jaot.io,
    # which appears nowhere else.
    def _face(emoji: str, rating: str, spaced: bool = True) -> str:
        gap = "margin-right:8px;" if spaced else ""
        href = (
            f"mailto:{email_layout.SUPPORT_EMAIL}"
            f"?subject={_url_quote(t('subject'))}"
            f"&body={_url_quote(f'[{rating}] ')}{url_safe_name}"
        )
        return f'<a href="{href}" style="text-decoration:none;font-size:24px;{gap}">{emoji}</a>'

    rating_row = (
        _face("😍", "great")
        + _face("😊", "good")
        + _face("😐", "ok")
        + _face("😞", "bad", spaced=False)
    )
    feedback_cta = email_layout.button(
        f"mailto:{email_layout.SUPPORT_EMAIL}?subject={_url_quote(t('subject'))}",
        t("ctaText"),
    )
    subject = t("subject")
    html = _wrap(
        f"""
    <h1 style="color:{BRAND_COLOR};">{t("heading").format(user_name=safe_name)}</h1>
    <p style="font-size:16px;color:#3A3230;">
        {t("bodyIntro")}
    </p>

    <h2 style="color:#5D4E47;">{t("storiesHeading")}</h2>
    <div style="margin:16px 0;">
        <div style="background:#F1E6D8;padding:16px;border-radius:8px;margin-bottom:12px;">
            <p style="font-weight:600;color:#5D4E47;margin:0 0 4px;">🏭 {t("story1title")}</p>
            <p style="color:#6B5F59;margin:0;">{t("story1desc")}</p>
        </div>
        <div style="background:#F1E6D8;padding:16px;border-radius:8px;margin-bottom:12px;">
            <p style="font-weight:600;color:#5D4E47;margin:0 0 4px;">🚚 {t("story2title")}</p>
            <p style="color:#6B5F59;margin:0;">{t("story2desc")}</p>
        </div>
        <div style="background:#F1E6D8;padding:16px;border-radius:8px;">
            <p style="font-weight:600;color:#5D4E47;margin:0 0 4px;">📊 {t("story3title")}</p>
            <p style="color:#6B5F59;margin:0;">{t("story3desc")}</p>
        </div>
    </div>

    <h2 style="color:#5D4E47;">{t("feedbackHeading")}</h2>
    <p style="color:#3A3230;">{t("feedbackPrompt")}</p>
    <div style="margin:16px 0;">
        {rating_row}
    </div>

    <p style="color:#3A3230;">
        {t("replyPrompt")}
    </p>

    {feedback_cta}
    """,
        locale=locale,
    )
    return subject, html


# Registry of all onboarding emails by day offset
# ADR-008: the day-7 credit/pricing explainer left with the money layer.
ONBOARDING_SEQUENCE: dict[int, Callable[..., tuple[str, str]]] = {
    0: day0_welcome,
    1: day1_api_setup,
    3: day3_catalog,
    14: day14_feedback,
}
