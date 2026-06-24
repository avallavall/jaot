"""
Email service abstraction for JAOT.

Provides a pluggable email backend system. Currently supports:
- ConsoleBackend (development — prints to stdout/logs)
- SMTPBackend (production — sends via SMTP)

Configuration:
    Set EMAIL_BACKEND, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD in .env
    Default: console backend (no emails sent, just logged)

Usage:
    service = EmailService()
    service.send(to="user@example.com", subject="Welcome", html=html_body)
"""

import logging
import smtplib
import time
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# F8: lazy reconfigure TTL. Email-related PlatformSettings (EMAIL_BACKEND,
# SMTP_HOST/PORT/USER/PASSWORD, SMTP_USE_TLS, EMAIL_FROM) are edited by operators
# at runtime via the admin panel. The api process and each Celery worker child
# cache the backend at class level, so without this they keep the OLD config
# until restart. On send() we re-read those keys at most once per TTL window and
# rebuild the backend ONLY when a value actually changed. 60s is chosen because
# email sends are infrequent (one cheap SELECT per minute of activity is
# negligible) while still bounding operator-visible staleness to ~1 minute —
# fast enough for credential rotation and backend switches without a restart.
_BACKEND_TTL_SECONDS = 60.0

# The 7 PlatformSettings keys that determine the SMTP backend. Single source of
# truth shared by configure_from_pss() and the lazy-refresh path.
_EMAIL_PSS_KEYS = [
    "EMAIL_BACKEND",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SMTP_USE_TLS",
    "EMAIL_FROM",
]


class EmailBackend(ABC):
    """Abstract email backend."""

    @abstractmethod
    def send(
        self,
        to: str,
        subject: str,
        html: str,
        from_email: str | None = None,
        reply_to: str | None = None,
    ) -> bool:
        """Send an email. Returns True on success."""
        ...


class ConsoleBackend(EmailBackend):
    """Development backend — logs emails instead of sending them."""

    def send(
        self,
        to: str,
        subject: str,
        html: str,
        from_email: str | None = None,
        reply_to: str | None = None,
    ) -> bool:
        logger.info(
            f"[EMAIL] To: {to} | Subject: {subject} | "
            f"From: {from_email or 'default'} | Length: {len(html)} chars"
        )
        return True


class SMTPBackend(EmailBackend):
    """Production backend — sends emails via SMTP.

    The SMTP password is stored as a private attribute and masked in
    ``__repr__`` to prevent accidental exposure in tracebacks and logs.
    """

    def __init__(
        self,
        host: str,
        port: int = 587,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        default_from: str = "JAOT <noreply@jaot.io>",
    ):
        self.host = host
        self.port = port
        self.username = username
        self._password = password  # private — never exposed in __dict__ directly
        self.use_tls = use_tls
        self.default_from = default_from

    def __repr__(self) -> str:
        return (
            f"SMTPBackend(host={self.host!r}, port={self.port}, "
            f"username={self.username!r}, password='***', use_tls={self.use_tls})"
        )

    def send(
        self,
        to: str,
        subject: str,
        html: str,
        from_email: str | None = None,
        reply_to: str | None = None,
    ) -> bool:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email or self.default_from
        msg["To"] = to
        if reply_to:
            msg["Reply-To"] = reply_to

        msg.attach(MIMEText(html, "html"))

        try:
            logger.debug(f"Connecting to SMTP {self.host}:{self.port}")
            if self.use_tls:
                server = smtplib.SMTP(self.host, self.port)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(self.host, self.port)

            if self.username:
                server.login(self.username, self._password)

            server.sendmail(msg["From"], [to], msg.as_string())
            server.quit()
            logger.info(f"Email sent to {to}: {subject}")
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error(f"SMTP authentication failed for {self.host} (credentials masked)")
            return False
        except (smtplib.SMTPException, OSError) as e:
            # Mask any credential details that might leak via exception message
            error_msg = str(e).replace(self._password, "***") if self._password else str(e)
            logger.error(f"Failed to send email to {to}: {error_msg}")
            return False


class EmailService:
    """High-level email service with pluggable backend."""

    _instance: "EmailService | None" = None
    _backend: EmailBackend = ConsoleBackend()
    # F8 lazy-reconfigure bookkeeping (class-level, shared by every caller in
    # the process — works in both the api process and each Celery worker child).
    # _backend_loaded_at: monotonic time of the last PSS-driven configure, or
    #   None when the backend was set directly (configure()/tests) — None means
    #   "don't auto-refresh", so manual/test configuration is never clobbered.
    # _backend_signature: tuple of the email PSS values that produced the
    #   current backend, used for a cheap "did anything change?" compare.
    _backend_loaded_at: "float | None" = None
    _backend_signature: "tuple[str, ...] | None" = None

    @classmethod
    def configure(
        cls,
        backend: str = "console",
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        smtp_use_tls: bool = True,
        default_from: str = "JAOT <noreply@jaot.io>",
    ) -> None:
        """Configure the email service. Call once at app startup.

        Sets the backend directly. Clears the F8 PSS-provenance markers so a
        backend set here (or in tests) is treated as "manually configured" and
        is never auto-refreshed by the lazy TTL path. ``configure_from_pss``
        re-stamps them after calling this.
        """
        cls._backend_loaded_at = None
        cls._backend_signature = None
        if backend == "smtp" and smtp_host:
            cls._backend = SMTPBackend(
                host=smtp_host,
                port=smtp_port,
                username=smtp_user,
                password=smtp_password,
                use_tls=smtp_use_tls,
                default_from=default_from,
            )
            logger.info(f"Email service configured: SMTP ({smtp_host}:{smtp_port})")
        else:
            cls._backend = ConsoleBackend()
            logger.info("Email service configured: console (development mode)")

    @staticmethod
    def _signature_from_vals(vals: dict[str, str]) -> tuple[str, ...]:
        """Build a stable signature tuple from the email PSS values.

        Used to detect whether the backend-determining config actually changed
        since the last configure, so the TTL refresh path only rebuilds the
        backend on a real change (avoids needless churn every TTL window).
        """
        return tuple(vals.get(k, "") or "" for k in _EMAIL_PSS_KEYS)

    @classmethod
    def configure_from_pss(cls, db: "Session") -> None:
        """Load email config from platform_settings in a single DB round-trip and configure.

        Reads the 7 email keys via ``PSS.get_many`` (one SELECT) instead of seven
        separate getter calls. Called from FastAPI lifespan and Celery worker init,
        and from the lazy-refresh path on ``send()``/``send_batch()``. Records the
        load time and config signature so subsequent sends can detect runtime
        changes (F8) without rebuilding the backend on every call.
        """
        from app.services.platform_settings_service import PlatformSettingsService as PSS

        vals = PSS.get_many(db, _EMAIL_PSS_KEYS)
        smtp_port_raw = vals.get("SMTP_PORT") or "0"
        try:
            smtp_port = int(smtp_port_raw)
        except (ValueError, TypeError):
            smtp_port = 0
        smtp_use_tls = (vals.get("SMTP_USE_TLS") or "").strip().lower() in ("true", "1", "yes")
        cls.configure(
            backend=vals.get("EMAIL_BACKEND", ""),
            smtp_host=vals.get("SMTP_HOST", ""),
            smtp_port=smtp_port,
            smtp_user=vals.get("SMTP_USER", ""),
            smtp_password=vals.get("SMTP_PASSWORD", ""),
            smtp_use_tls=smtp_use_tls,
            default_from=vals.get("EMAIL_FROM", ""),
        )
        cls._backend_signature = cls._signature_from_vals(vals)
        cls._backend_loaded_at = time.monotonic()

    @classmethod
    def _maybe_reconfigure(cls, db: "Session | None") -> None:
        """Lazily refresh the backend from PSS if the cache is stale (F8).

        No-ops unless the backend was last configured from PSS more than
        ``_BACKEND_TTL_SECONDS`` ago. When the TTL has elapsed it re-reads the
        email PSS keys (one SELECT) and rebuilds the backend ONLY if a value
        changed; otherwise it just bumps the load time so the next check is
        deferred another TTL window.

        Best-effort: any DB/PSS error is logged and swallowed so a transient
        DB hiccup never turns a send into a failure — the stale-but-working
        backend is kept. ``db`` may be None (callers without a session); in
        that case a short-lived ``SessionLocal`` is opened and closed here.
        """
        # Backend set directly (configure()/tests) — never auto-refresh it.
        if cls._backend_loaded_at is None:
            return
        if (time.monotonic() - cls._backend_loaded_at) < _BACKEND_TTL_SECONDS:
            return

        owns_session = False
        try:
            if db is None:
                from app.shared.db.session import SessionLocal

                db = SessionLocal()
                owns_session = True

            from app.services.platform_settings_service import PlatformSettingsService as PSS

            vals = PSS.get_many(db, _EMAIL_PSS_KEYS)
            new_signature = cls._signature_from_vals(vals)
            if new_signature == cls._backend_signature:
                # Unchanged — defer the next check, don't rebuild the backend.
                cls._backend_loaded_at = time.monotonic()
                return

            logger.info("Email config changed in PlatformSettings — reconfiguring backend (F8)")
            cls.configure_from_pss(db)
        except Exception:
            logger.exception("Email backend lazy-refresh failed — keeping existing backend (F8)")
            # Defer the next attempt so we don't hammer a failing DB every send.
            cls._backend_loaded_at = time.monotonic()
        finally:
            if owns_session and db is not None:
                try:
                    db.close()
                except Exception:
                    pass

    @classmethod
    def verify_smtp_tls_handshake(cls, timeout: int = 10) -> tuple[bool, str]:
        """Verify the SMTP TLS handshake (EHLO + STARTTLS + EHLO).

        NOTE: This method does NOT validate SMTP credentials (login). A wrong
        SMTP_PASSWORD passes this check and only fails on the first real
        ``.send()``. Renamed in Phase 12.4 (F7) for honesty — the prior name
        implied delivery-readiness, which is stronger than the actual
        TLS-handshake-only check performed here.

        Args:
            timeout: Connection timeout in seconds (default 10).

        Returns immediately with ``(True, "Not using SMTP backend")``
        if the active backend is not :class:`SMTPBackend`.

        Returns:
            A tuple ``(is_valid, message)`` -- never raises.
        """
        if not isinstance(cls._backend, SMTPBackend):
            return (True, "Not using SMTP backend")

        backend: SMTPBackend = cls._backend
        if not backend.host:
            return (False, "SMTP host is empty")

        try:
            if backend.use_tls:
                server = smtplib.SMTP(backend.host, backend.port, timeout=timeout)
                server.ehlo()
                server.starttls()
                server.ehlo()
            else:
                server = smtplib.SMTP_SSL(backend.host, backend.port, timeout=timeout)
                server.ehlo()
            server.quit()
            return (
                True,
                f"SMTP connection verified ({backend.host}:{backend.port})",
            )
        except (smtplib.SMTPException, OSError) as e:
            return (
                False,
                f"SMTP connection to {backend.host}:{backend.port} failed: {e}",
            )

    @classmethod
    def send(
        cls,
        to: str,
        subject: str,
        html: str,
        from_email: str | None = None,
        reply_to: str | None = None,
        db: "Session | None" = None,
    ) -> bool:
        """Send an email using the configured backend.

        F8: before sending, lazily refreshes the backend from PlatformSettings
        if the cached config is older than ``_BACKEND_TTL_SECONDS`` and has
        changed, so runtime admin edits take effect without a process restart.
        Pass ``db`` to reuse an open session (callers in a request/task already
        have one); when omitted a short-lived session is opened only if a
        refresh is actually due.
        """
        cls._maybe_reconfigure(db)
        return cls._backend.send(
            to=to,
            subject=subject,
            html=html,
            from_email=from_email,
            reply_to=reply_to,
        )

    @classmethod
    def send_batch(
        cls,
        recipients: list[str],
        subject: str,
        html: str,
        from_email: str | None = None,
        db: "Session | None" = None,
    ) -> int:
        """Send the same email to multiple recipients. Returns count of successful sends.

        The lazy backend refresh (F8) runs once up front; per-recipient
        ``send()`` calls then reuse the freshly-checked backend within the same
        TTL window (no repeated DB reads inside the loop).
        """
        cls._maybe_reconfigure(db)
        sent = 0
        for to in recipients:
            if cls.send(to=to, subject=subject, html=html, from_email=from_email, db=db):
                sent += 1
        return sent
