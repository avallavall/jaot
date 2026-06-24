#!/bin/sh
# Alertmanager entrypoint: renders alertmanager.yml from template, then starts alertmanager.
# Requires ALERT_EMAIL_RECIPIENT to be set in the environment.
set -e

TEMPLATE="/etc/alertmanager/alertmanager.yml.tmpl"
CONFIG="/etc/alertmanager/alertmanager.yml"

if [ -z "$ALERT_EMAIL_RECIPIENT" ]; then
  echo "ERROR: ALERT_EMAIL_RECIPIENT is not set. Cannot start Alertmanager." >&2
  exit 1
fi

# Substitute environment variable in template and write the final config.
# Uses sed instead of envsubst because prom/alertmanager Alpine image lacks gettext.
sed "s|\${ALERT_EMAIL_RECIPIENT}|${ALERT_EMAIL_RECIPIENT}|g" "$TEMPLATE" > "$CONFIG"

echo "Alertmanager config rendered successfully"

# Exec into the real alertmanager binary with all original arguments.
exec /bin/alertmanager "$@"
