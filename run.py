"""Entry point for running the JAOT application."""

import logging
import subprocess
import sys

import uvicorn
from dotenv import load_dotenv

from app.config import settings

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


def run_migrations() -> None:
    """Run pending Alembic migrations before starting the server."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "infra/alembic.ini", "upgrade", "head"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            logger.info("✅ Database migrations applied successfully")
            if "Running upgrade" in result.stderr:
                for line in result.stderr.strip().split("\n"):
                    if "Running upgrade" in line:
                        logger.info(f"  {line.strip()}")
        else:
            logger.error(f"❌ Migration failed: {result.stderr}")
            sys.exit(1)
    except subprocess.TimeoutExpired:
        logger.error("❌ Migration timed out after 60s")
        sys.exit(1)
    except FileNotFoundError:
        logger.warning("⚠️ Alembic not found, skipping migrations")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if settings.DEBUG:
        run_migrations()
    else:
        logger.info("Skipping auto-migrations (DEBUG=False). Use the migrate container instead.")
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        workers=settings.WORKERS,
        log_level="info",
        reload=settings.RELOAD,
        # Trust X-Forwarded-* from the reverse proxy (Caddy) so request.url.scheme
        # is "https" in production. Without this, FastAPI builds redirect Location
        # headers (e.g. trailing-slash 307s) with http://, which browsers block as
        # mixed content on the https site. Safe: uvicorn (:8001) is only reachable
        # via Caddy on the internal Docker network — the port is never published.
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
