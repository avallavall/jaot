#!/usr/bin/env bash
set -euo pipefail

# Manual replay helper for the idempotent daily Celery tasks.
#
# Fires ONE fresh execution by sending the task to the broker via the
# `celery_app` Python entrypoint, then prints the resulting task id. Must run
# INSIDE the production API container (`jaot_prod_api`).
#
# Usage (typical, from operator workstation):
#   ssh jaot@<VPS_IP> \
#     'docker exec jaot_prod_api bash /opt/jaot/deploy/scripts/replay-daily-task.sh process_scheduled_withdrawals'
#
# Sanctioned tasks:
#   - process_scheduled_withdrawals
#   - run_balance_reconciliation
#   - hexaly_platform_license_expiry_sweep
#
# Exits non-zero if no task name or broker send fails. Prints the new task id
# on stdout on success (single UUID-like line).

if [ "$#" -lt 1 ] || [ -z "${1:-}" ]; then
  echo "usage: $0 <celery-task-name>" >&2
  echo "       e.g. $0 process_scheduled_withdrawals" >&2
  exit 2
fi

TASK_NAME="$1"

python - "$TASK_NAME" <<'PY'
import sys

from app.shared.core.celery_app import celery_app

task_name = sys.argv[1]
result = celery_app.send_task(task_name)
print(result.id)
PY
