"""Single source of truth for the platform version.

Bump here at release time — health endpoints, the FastAPI app metadata, the
Prometheus app-info gauge and the settings-registry default all read this.
"""

APP_VERSION = "3.4.0"
