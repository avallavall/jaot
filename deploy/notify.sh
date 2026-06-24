#!/usr/bin/env bash
set -euo pipefail

# JAOT Deploy Notification — sends deploy status to Discord or Slack webhook.
#
# Usage:
#   bash deploy/notify.sh <success|failure|rollback>
#
# Env: DEPLOY_WEBHOOK_URL (required), plus optional COMMIT_SHA, COMMIT_AUTHOR,
# COMMIT_MESSAGE, CHANGED_SERVICES, DEPLOY_DURATION, DEPLOY_DIR (default /opt/jaot).
# Exit 0 on send/skip, 1 on send failure.

WEBHOOK_URL="${DEPLOY_WEBHOOK_URL:-}"
DEPLOY_DIR="${DEPLOY_DIR:-/opt/jaot}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "[INFO]  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }

STATUS="${1:-}"

if [[ -z "$STATUS" ]]; then
    echo "Usage: bash deploy/notify.sh <success|failure|rollback>"
    exit 1
fi

if [[ "$STATUS" != "success" && "$STATUS" != "failure" && "$STATUS" != "rollback" ]]; then
    log_error "Invalid status: $STATUS (expected: success, failure, rollback)"
    exit 1
fi

if [[ -z "$WEBHOOK_URL" ]]; then
    log_info "DEPLOY_WEBHOOK_URL not set, skipping notification."
    exit 0
fi

if ! command -v curl &>/dev/null; then
    log_error "curl is required but not found"
    exit 1
fi

# Auto-detect git info from repo if not provided.
if [[ -d "${DEPLOY_DIR}/.git" ]]; then
    COMMIT_SHA="${COMMIT_SHA:-$(git -C "$DEPLOY_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")}"
    COMMIT_AUTHOR="${COMMIT_AUTHOR:-$(git -C "$DEPLOY_DIR" log -1 --format='%an' 2>/dev/null || echo "unknown")}"
    COMMIT_MESSAGE="${COMMIT_MESSAGE:-$(git -C "$DEPLOY_DIR" log -1 --format='%s' 2>/dev/null || echo "unknown")}"
else
    COMMIT_SHA="${COMMIT_SHA:-unknown}"
    COMMIT_AUTHOR="${COMMIT_AUTHOR:-unknown}"
    COMMIT_MESSAGE="${COMMIT_MESSAGE:-unknown}"
fi

CHANGED_SERVICES="${CHANGED_SERVICES:-none}"
DEPLOY_DURATION="${DEPLOY_DURATION:-unknown}"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
HOSTNAME_VAL=$(hostname 2>/dev/null || echo "unknown")

case "$STATUS" in
    success)
        TITLE="Deploy Successful"
        COLOR_DISCORD=3066993
        COLOR_SLACK="good"
        EMOJI=":white_check_mark:"
        ;;
    failure)
        TITLE="Deploy FAILED"
        COLOR_DISCORD=15158332
        COLOR_SLACK="danger"
        EMOJI=":x:"
        ;;
    rollback)
        TITLE="Deploy ROLLED BACK"
        COLOR_DISCORD=16776960
        COLOR_SLACK="warning"
        EMOJI=":warning:"
        ;;
esac

DURATION_TEXT="$DEPLOY_DURATION"
if [[ "$DEPLOY_DURATION" =~ ^[0-9]+$ ]]; then
    minutes=$((DEPLOY_DURATION / 60))
    seconds=$((DEPLOY_DURATION % 60))
    if [[ $minutes -gt 0 ]]; then
        DURATION_TEXT="${minutes}m ${seconds}s"
    else
        DURATION_TEXT="${seconds}s"
    fi
fi

# Truncate to 100 chars for webhook display.
COMMIT_MSG_SHORT="${COMMIT_MESSAGE:0:100}"

log_info "Sending $STATUS notification..."

if echo "$WEBHOOK_URL" | grep -q "discord"; then
    PAYLOAD=$(cat <<DISCORD_EOF
{
  "embeds": [{
    "title": "${TITLE}",
    "color": ${COLOR_DISCORD},
    "fields": [
      {"name": "Commit", "value": "\`${COMMIT_SHA}\`", "inline": true},
      {"name": "Author", "value": "${COMMIT_AUTHOR}", "inline": true},
      {"name": "Duration", "value": "${DURATION_TEXT}", "inline": true},
      {"name": "Services", "value": "${CHANGED_SERVICES}"},
      {"name": "Message", "value": "${COMMIT_MSG_SHORT}"},
      {"name": "Host", "value": "${HOSTNAME_VAL}", "inline": true}
    ],
    "timestamp": "${TIMESTAMP}"
  }]
}
DISCORD_EOF
    )

    HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD" \
        "$WEBHOOK_URL" 2>/dev/null || echo "000")

    if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "204" ]]; then
        log_ok "Discord notification sent (HTTP $HTTP_CODE)"
    else
        log_error "Discord notification failed (HTTP $HTTP_CODE)"
        exit 1
    fi

else
    # Slack webhook (default)
    PAYLOAD=$(cat <<SLACK_EOF
{
  "blocks": [
    {
      "type": "header",
      "text": {"type": "plain_text", "text": "${EMOJI} ${TITLE}"}
    },
    {
      "type": "section",
      "fields": [
        {"type": "mrkdwn", "text": "*Commit:* \`${COMMIT_SHA}\`"},
        {"type": "mrkdwn", "text": "*Author:* ${COMMIT_AUTHOR}"},
        {"type": "mrkdwn", "text": "*Duration:* ${DURATION_TEXT}"},
        {"type": "mrkdwn", "text": "*Services:* ${CHANGED_SERVICES}"}
      ]
    },
    {
      "type": "section",
      "text": {"type": "mrkdwn", "text": "*Message:* ${COMMIT_MSG_SHORT}"}
    },
    {
      "type": "context",
      "elements": [
        {"type": "mrkdwn", "text": "Host: ${HOSTNAME_VAL} | ${TIMESTAMP}"}
      ]
    }
  ]
}
SLACK_EOF
    )

    HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD" \
        "$WEBHOOK_URL" 2>/dev/null || echo "000")

    if [[ "$HTTP_CODE" == "200" ]]; then
        log_ok "Slack notification sent (HTTP $HTTP_CODE)"
    else
        log_error "Slack notification failed (HTTP $HTTP_CODE)"
        exit 1
    fi
fi
