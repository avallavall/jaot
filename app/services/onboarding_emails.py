"""
Onboarding email sequence for new users.

Sequence:
    Day 0  — Welcome + first solve guide
    Day 1  — API key setup + code examples
    Day 3  — Model catalog tour + templates
    Day 7  — Credit system + upgrade prompt
    Day 14 — Success stories + feedback request

Each function returns (subject, html_body) for the email service.
All functions accept an optional `locale` parameter for translated content.
"""

from collections.abc import Callable
from html import escape as _html_escape
from urllib.parse import quote as _url_quote

from app.services.email_translations import get_email_string

BRAND_COLOR = "#2563eb"


def _safe_name(name: str) -> str:
    """HTML-escape a user-controlled name before inlining into email markup.

    Falls back to a generic 'there' label so the salutation stays grammatical
    when the user supplied an empty name.
    """
    if not name:
        return "there"
    return _html_escape(name, quote=True)


def _wrap(content: str, locale: str | None = None) -> str:
    """Wrap content in a responsive email template with translated footer."""

    def t(key: str) -> str:
        return get_email_string("footer", key, locale)

    footer = f"""
<div style="margin-top:32px;padding-top:16px;border-top:1px solid #e5e7eb;color:#6b7280;font-size:12px;">
    <p>{t("brand")}</p>
    <p><a href="https://jaot.io" style="color:#2563eb;">jaot.io</a> ·
       <a href="https://jaot.io/docs" style="color:#2563eb;">{t("docsLink")}</a> ·
       <a href="mailto:support@jaot.io" style="color:#2563eb;">{t("supportLink")}</a></p>
    <p style="margin-top:8px;">{t("unsubscribe")}
       <a href="https://jaot.io/settings/notifications" style="color:#6b7280;">{t("unsubscribeLink")}</a></p>
</div>
"""

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:32px 24px;background:#ffffff;">
{content}
{footer}
</div>
</body>
</html>
"""


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
    <p style="font-size:16px;color:#374151;">
        {t("bodyIntro")}
    </p>

    <div style="background:#f0f9ff;border-left:4px solid {BRAND_COLOR};padding:16px;margin:24px 0;border-radius:4px;">
        <h3 style="margin:0 0 8px 0;color:#1e40af;">{t("apiKeyHeading")}</h3>
        <code style="background:#e0f2fe;padding:4px 8px;border-radius:4px;font-size:14px;">{safe_api_key_prefix}••••••••</code>
        <p style="margin:8px 0 0;font-size:13px;color:#6b7280;">
            {t("apiKeyHint")} <a href="https://jaot.io/workspace/api-keys" style="color:{BRAND_COLOR};">{t("apiKeyLink")}</a>
        </p>
    </div>

    <h2 style="color:#111827;">{t("firstSolveHeading")}</h2>
    <pre style="background:#1e293b;color:#e2e8f0;padding:16px;border-radius:8px;overflow-x:auto;font-size:13px;">
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

    <p style="color:#374151;">{t("bodyOutro")}</p>

    <a href="https://jaot.io/docs/getting-started"
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

    safe_name = _safe_name(user_name)
    subject = t("subject")
    html = _wrap(
        f"""
    <h1 style="color:{BRAND_COLOR};">{t("heading").format(user_name=safe_name)}</h1>
    <p style="font-size:16px;color:#374151;">
        {t("bodyIntro")}
    </p>

    <h2 style="color:#111827;">Python</h2>
    <pre style="background:#1e293b;color:#e2e8f0;padding:16px;border-radius:8px;overflow-x:auto;font-size:13px;">
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

    <h2 style="color:#111827;">JavaScript / Node.js</h2>
    <pre style="background:#1e293b;color:#e2e8f0;padding:16px;border-radius:8px;overflow-x:auto;font-size:13px;">
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

    <h2 style="color:#111827;">{t("bestPracticesHeading")}</h2>
    <ul style="color:#374151;">
        <li>{t("tip1")}</li>
        <li>{t("tip2")}</li>
        <li>{t("tip3")} <a href="https://jaot.io/workspace/api-keys" style="color:{BRAND_COLOR};">Settings</a></li>
    </ul>

    <a href="https://jaot.io/docs/api/reference"
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
    <p style="font-size:16px;color:#374151;">
        {t("bodyIntro")}
    </p>

    <table style="width:100%;border-collapse:collapse;margin:24px 0;">
        <tr style="background:#f0f9ff;">
            <th style="text-align:left;padding:8px 12px;border-bottom:2px solid #e5e7eb;">{t("tableModel")}</th>
            <th style="text-align:left;padding:8px 12px;border-bottom:2px solid #e5e7eb;">{t("tableUseCase")}</th>
        </tr>
        <tr><td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;">📦 {t("row1name")}</td><td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;">{t("row1desc")}</td></tr>
        <tr><td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;">👥 {t("row2name")}</td><td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;">{t("row2desc")}</td></tr>
        <tr><td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;">🚛 {t("row3name")}</td><td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;">{t("row3desc")}</td></tr>
        <tr><td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;">📊 {t("row4name")}</td><td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;">{t("row4desc")}</td></tr>
        <tr><td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;">🏭 {t("row5name")}</td><td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;">{t("row5desc")}</td></tr>
        <tr><td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;">💰 {t("row6name")}</td><td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;">{t("row6desc")}</td></tr>
        <tr><td style="padding:8px 12px;">🔧 {t("moreTemplates")}</td><td style="padding:8px 12px;"></td></tr>
    </table>

    <p style="color:#374151;">
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


def day7_credits(
    user_name: str, credits_balance: int, locale: str | None = None
) -> tuple[str, str]:
    """Day 7: Credit system explanation + upgrade prompt."""

    def t(key: str) -> str:
        return get_email_string("day7", key, locale)

    safe_name = _safe_name(user_name)
    subject = t("subject")
    html = _wrap(
        f"""
    <h1 style="color:{BRAND_COLOR};">{t("heading").format(user_name=safe_name)}</h1>
    <p style="font-size:16px;color:#374151;">
        {t("bodyIntro")}
    </p>

    <div style="background:#f0fdf4;border:1px solid #bbf7d0;padding:16px;border-radius:8px;margin:24px 0;text-align:center;">
        <p style="font-size:14px;color:#166534;margin:0;">{t("balanceLabel")}</p>
        <p style="font-size:36px;font-weight:700;color:#15803d;margin:8px 0;">{credits_balance} {t("creditsUnit")}</p>
    </div>

    <h2 style="color:#111827;">{t("howCreditsWork")}</h2>
    <ul style="color:#374151;line-height:1.8;">
        <li>{t("creditTip1")}</li>
        <li>{t("creditTip2")}</li>
        <li>{t("creditTip3")}</li>
        <li>{t("creditTip4")}</li>
    </ul>

    <h2 style="color:#111827;">{t("plansHeading")}</h2>
    <table style="width:100%;border-collapse:collapse;margin:16px 0;">
        <tr style="background:#f0f9ff;">
            <th style="padding:8px;border-bottom:2px solid #e5e7eb;">Plan</th>
            <th style="padding:8px;border-bottom:2px solid #e5e7eb;">Credits</th>
            <th style="padding:8px;border-bottom:2px solid #e5e7eb;">Price</th>
        </tr>
        <tr><td style="padding:8px;border-bottom:1px solid #f3f4f6;">Free</td><td style="padding:8px;border-bottom:1px solid #f3f4f6;">50/mo</td><td style="padding:8px;border-bottom:1px solid #f3f4f6;">€0</td></tr>
        <tr><td style="padding:8px;border-bottom:1px solid #f3f4f6;">Starter</td><td style="padding:8px;border-bottom:1px solid #f3f4f6;">600/mo</td><td style="padding:8px;border-bottom:1px solid #f3f4f6;">€19/mo</td></tr>
        <tr><td style="padding:8px;border-bottom:1px solid #f3f4f6;">Pro</td><td style="padding:8px;border-bottom:1px solid #f3f4f6;">2,500/mo</td><td style="padding:8px;border-bottom:1px solid #f3f4f6;">€49/mo</td></tr>
        <tr><td style="padding:8px;">Business</td><td style="padding:8px;">10,000/mo</td><td style="padding:8px;">€149/mo</td></tr>
    </table>

    <a href="https://jaot.io/workspace/credits"
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
    subject = t("subject")
    html = _wrap(
        f"""
    <h1 style="color:{BRAND_COLOR};">{t("heading").format(user_name=safe_name)}</h1>
    <p style="font-size:16px;color:#374151;">
        {t("bodyIntro")}
    </p>

    <h2 style="color:#111827;">{t("storiesHeading")}</h2>
    <div style="margin:16px 0;">
        <div style="background:#f9fafb;padding:16px;border-radius:8px;margin-bottom:12px;">
            <p style="font-weight:600;color:#111827;margin:0 0 4px;">🏭 {t("story1title")}</p>
            <p style="color:#6b7280;margin:0;">{t("story1desc")}</p>
        </div>
        <div style="background:#f9fafb;padding:16px;border-radius:8px;margin-bottom:12px;">
            <p style="font-weight:600;color:#111827;margin:0 0 4px;">🚚 {t("story2title")}</p>
            <p style="color:#6b7280;margin:0;">{t("story2desc")}</p>
        </div>
        <div style="background:#f9fafb;padding:16px;border-radius:8px;">
            <p style="font-weight:600;color:#111827;margin:0 0 4px;">📊 {t("story3title")}</p>
            <p style="color:#6b7280;margin:0;">{t("story3desc")}</p>
        </div>
    </div>

    <h2 style="color:#111827;">{t("feedbackHeading")}</h2>
    <p style="color:#374151;">{t("feedbackPrompt")}</p>
    <div style="margin:16px 0;">
        <a href="https://jaot.io/feedback?rating=great" style="text-decoration:none;font-size:24px;margin-right:8px;">😍</a>
        <a href="https://jaot.io/feedback?rating=good" style="text-decoration:none;font-size:24px;margin-right:8px;">😊</a>
        <a href="https://jaot.io/feedback?rating=ok" style="text-decoration:none;font-size:24px;margin-right:8px;">😐</a>
        <a href="https://jaot.io/feedback?rating=bad" style="text-decoration:none;font-size:24px;">😞</a>
    </div>

    <p style="color:#374151;">
        {t("replyPrompt")}
    </p>

    <a href="mailto:founders@jaot.io?subject=Feedback%20from%20{url_safe_name}"
       style="display:inline-block;background:{BRAND_COLOR};color:white;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600;margin-top:16px;">
        {t("ctaText")}
    </a>
    """,
        locale=locale,
    )
    return subject, html


# Registry of all onboarding emails by day offset
ONBOARDING_SEQUENCE: dict[int, Callable[..., tuple[str, str]]] = {
    0: day0_welcome,
    1: day1_api_setup,
    3: day3_catalog,
    7: day7_credits,
    14: day14_feedback,
}
