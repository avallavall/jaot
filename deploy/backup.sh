#!/usr/bin/env bash
set -eo pipefail

# JAOT Database Backup — automated daily pg_dump with tiered retention + offsite sync.
# Runs as a cron job on the production host.
#
# Usage:
#   ./backup.sh              # Full backup (daily cron)
#   ./backup.sh --dry-run    # Validate without executing
#   ./backup.sh --notify-test # Send a test notification email
#   ./backup.sh --install-cron # Install the cron entry
#
# Env from /opt/jaot/.env.production: POSTGRES_USER (default jaot),
# POSTGRES_DB (default jaot), NOTIFY_EMAIL, STORAGEBOX_USER.

BACKUP_DIR="/opt/jaot/backups"
COMPOSE_FILE="/opt/jaot/deploy/docker-compose.prod.yml"
DATE=$(date +%Y-%m-%d_%H%M)
DAY_OF_WEEK=$(date +%u)    # 1=Monday, 7=Sunday
DAY_OF_MONTH=$(date +%d)   # 01-31
FILENAME="jaot_${DATE}.dump"
LOG_FILE="${BACKUP_DIR}/backup.log"
START_EPOCH=$(date +%s)

# Targeted grep avoids `source` (no code execution risk on hostile .env).
# `|| true` guards set -o pipefail: a missing key must yield "" (defaults apply), not kill the script.
load_env_var() {
    grep "^${1}=" /opt/jaot/.env.production 2>/dev/null | head -1 | cut -d'=' -f2- || true
}
pg_user=$(load_env_var POSTGRES_USER)
pg_user="${pg_user:-jaot}"
pg_db=$(load_env_var POSTGRES_DB)
pg_db="${pg_db:-jaot}"
NOTIFY_EMAIL=$(load_env_var NOTIFY_EMAIL)
STORAGEBOX_USER=$(load_env_var STORAGEBOX_USER)
EMAIL_FROM=$(load_env_var EMAIL_FROM)
EMAIL_FROM="${EMAIL_FROM:-noreply@jaot.io}"

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg"
    mkdir -p "${BACKUP_DIR}"
    echo "$msg" >> "${LOG_FILE}"
}

send_failure_notification() {
    local error_msg="${1:-Unknown error}"

    if [ -z "${NOTIFY_EMAIL:-}" ]; then
        log "NOTIFY_EMAIL not set, skipping failure notification"
        return 0
    fi
    if ! command -v msmtp &>/dev/null; then
        log "msmtp not installed, skipping failure notification"
        return 0
    fi

    local subject="[JAOT Backup] FAILED - ${DATE}"
    local body
    body="JAOT database backup FAILED at $(date '+%Y-%m-%d %H:%M:%S UTC')

Error: ${error_msg}

Backup directory listing:
$(ls -lh "${BACKUP_DIR}/daily/" 2>/dev/null || echo '  (directory not accessible)')

Weekly backups:
$(ls -lh "${BACKUP_DIR}/weekly/" 2>/dev/null || echo '  (directory not accessible)')

Monthly backups:
$(ls -lh "${BACKUP_DIR}/monthly/" 2>/dev/null || echo '  (directory not accessible)')

Please investigate immediately.
--
JAOT Backup System"

    # Resend rejects mail without an explicit To: header (550 Missing `to` field).
    echo -e "To: ${NOTIFY_EMAIL}\nSubject: ${subject}\nFrom: ${EMAIL_FROM:-noreply@jaot.io}\n\n${body}" \
        | msmtp "${NOTIFY_EMAIL}" 2>/dev/null || log "WARNING: Failed to send failure notification email"
}

send_success_notification() {
    local backup_size="${1:-unknown}"
    local duration="${2:-unknown}"
    local offsite="${3:-skipped}"

    if [ -z "${NOTIFY_EMAIL:-}" ]; then
        return 0
    fi
    if ! command -v msmtp &>/dev/null; then
        return 0
    fi

    local daily_count weekly_count monthly_count
    daily_count=$(find "${BACKUP_DIR}/daily" -name "*.dump*" 2>/dev/null | wc -l)
    weekly_count=$(find "${BACKUP_DIR}/weekly" -name "*.dump*" 2>/dev/null | wc -l)
    monthly_count=$(find "${BACKUP_DIR}/monthly" -name "*.dump*" 2>/dev/null | wc -l)

    local subject="[JAOT Backup] OK - ${DATE}"
    local body
    body="JAOT database backup completed successfully.

Backup: ${FILENAME}
Size: ${backup_size}
Duration: ${duration}s
Offsite sync: ${offsite}

Retention:
  Daily backups:   ${daily_count} (keep 7)
  Weekly backups:  ${weekly_count} (keep 4)
  Monthly backups: ${monthly_count} (keep 3)

--
JAOT Backup System"

    echo -e "To: ${NOTIFY_EMAIL}\nSubject: ${subject}\nFrom: ${EMAIL_FROM}\n\n${body}" \
        | msmtp "${NOTIFY_EMAIL}" 2>/dev/null || log "WARNING: Failed to send success notification email"
}

create_backup() {
    log "Starting database backup: ${FILENAME}"

    mkdir -p "${BACKUP_DIR}/daily" "${BACKUP_DIR}/weekly" "${BACKUP_DIR}/monthly"

    # pg_dump -Fc: compressed custom format, supports parallel restore.
    log "Running pg_dump (user=${pg_user}, db=${pg_db}, format=custom)..."
    docker exec jaot_prod_postgres pg_dump -U "${pg_user}" -Fc "${pg_db}" \
        > "${BACKUP_DIR}/daily/${FILENAME}"

    local backup_size
    backup_size=$(stat -c%s "${BACKUP_DIR}/daily/${FILENAME}" 2>/dev/null || echo "0")
    if [ "${backup_size}" -eq 0 ]; then
        log "ERROR: Backup file is empty (0 bytes)"
        exit 1
    fi

    # pg_restore --list reads TOC without restoring.
    log "Verifying backup integrity..."
    if docker exec jaot_prod_postgres pg_restore --list "/tmp/${FILENAME}" > /dev/null 2>&1; then
        log "Backup integrity verified (TOC readable)"
    else
        # Fall back to host-side verification since file is on host.
        if command -v pg_restore &>/dev/null; then
            pg_restore --list "${BACKUP_DIR}/daily/${FILENAME}" > /dev/null 2>&1 || {
                log "ERROR: Backup integrity check FAILED -- dump may be corrupt"
                send_failure_notification "Backup integrity verification failed for ${FILENAME}"
                exit 1
            }
            log "Backup integrity verified (TOC readable)"
        else
            log "WARNING: pg_restore not available on host, skipping integrity check"
        fi
    fi

    if [ -f /opt/jaot/.backup-key.gpg ]; then
        log "Encrypting backup..."
        gpg --batch --yes --passphrase-file /opt/jaot/.backup-key.gpg \
            --symmetric --cipher-algo AES256 \
            -o "${BACKUP_DIR}/daily/${FILENAME}.gpg" \
            "${BACKUP_DIR}/daily/${FILENAME}"
        rm -f "${BACKUP_DIR}/daily/${FILENAME}"
        FILENAME="${FILENAME}.gpg"
        log "Backup encrypted with AES-256"
    else
        log "WARNING: No encryption key found at /opt/jaot/.backup-key.gpg -- backup stored unencrypted"
    fi

    local human_size
    human_size=$(du -h "${BACKUP_DIR}/daily/${FILENAME}" | cut -f1)
    log "Backup created: ${FILENAME} (${human_size})"
}

promote_backup() {
    if [ "${DAY_OF_WEEK}" = "7" ]; then
        cp "${BACKUP_DIR}/daily/${FILENAME}" "${BACKUP_DIR}/weekly/${FILENAME}"
        log "Promoted to weekly backup (Sunday)"
    fi

    if [ "${DAY_OF_MONTH}" = "01" ]; then
        cp "${BACKUP_DIR}/daily/${FILENAME}" "${BACKUP_DIR}/monthly/${FILENAME}"
        log "Promoted to monthly backup (1st of month)"
    fi
}

prune_old_backups() {
    log "Pruning old backups..."

    # Count-based floor: never delete below min_keep. Then delete oldest beyond
    # the floor that are also older than max_days.
    prune_tier() {
        local dir="$1" min_keep="$2" max_days="$3" tier_name="$4"
        local count
        count=$(ls -1 "${dir}"/*.dump* 2>/dev/null | wc -l)
        if [ "$count" -le "$min_keep" ]; then
            log "${tier_name}: $count (keeping all -- below minimum $min_keep)"
            return 0
        fi
        ls -1t "${dir}"/*.dump* 2>/dev/null | tail -n +$((min_keep + 1)) | while read -r f; do
            if [ "$(find "$f" -mtime +${max_days} 2>/dev/null)" ]; then
                rm -f "$f"
                log "Deleted old ${tier_name} backup: $(basename "$f")"
            fi
        done
    }

    prune_tier "${BACKUP_DIR}/daily" 7 7 "daily"
    prune_tier "${BACKUP_DIR}/weekly" 4 28 "weekly"
    prune_tier "${BACKUP_DIR}/monthly" 3 90 "monthly"

    local daily_count weekly_count monthly_count
    daily_count=$(ls -1 "${BACKUP_DIR}/daily"/*.dump* 2>/dev/null | wc -l)
    weekly_count=$(ls -1 "${BACKUP_DIR}/weekly"/*.dump* 2>/dev/null | wc -l)
    monthly_count=$(ls -1 "${BACKUP_DIR}/monthly"/*.dump* 2>/dev/null | wc -l)

    log "Retention: ${daily_count} daily, ${weekly_count} weekly, ${monthly_count} monthly"
}

sync_offsite() {
    offsite_status="skipped"

    if [ -z "${STORAGEBOX_USER:-}" ]; then
        log "WARNING: STORAGEBOX_USER not set, skipping offsite sync"
        return 0
    fi

    log "Syncing backups to offsite storage..."

    local rc=0
    rsync -avz \
        -e 'ssh -p 23 -o StrictHostKeyChecking=accept-new -o BatchMode=yes' \
        "${BACKUP_DIR}/" \
        "${STORAGEBOX_USER}@${STORAGEBOX_USER}.your-storagebox.de:jaot-backups/" || rc=$?

    if [ "$rc" -eq 0 ]; then
        offsite_status="success"
        log "Offsite sync completed"
    else
        offsite_status="FAILED (exit code: ${rc})"
        log "WARNING: Offsite sync failed with exit code ${rc}"
    fi
}

dry_run() {
    echo "=== JAOT Backup Dry Run ==="
    echo ""

    if command -v docker &>/dev/null; then
        echo "[OK] Docker is installed: $(docker --version)"
    else
        echo "[FAIL] Docker is not installed"
    fi

    if docker inspect jaot_prod_postgres &>/dev/null; then
        echo "[OK] Container jaot_prod_postgres exists"
    else
        echo "[FAIL] Container jaot_prod_postgres not found"
    fi

    if [ -d "${BACKUP_DIR}" ] || mkdir -p "${BACKUP_DIR}" 2>/dev/null; then
        echo "[OK] Backup directory ${BACKUP_DIR} exists or can be created"
    else
        echo "[FAIL] Cannot create backup directory ${BACKUP_DIR}"
    fi

    if command -v msmtp &>/dev/null; then
        echo "[OK] msmtp is installed"
    else
        echo "[WARN] msmtp not installed (notifications will be skipped)"
    fi

    if [ -n "${STORAGEBOX_USER:-}" ]; then
        echo "[OK] STORAGEBOX_USER is set: ${STORAGEBOX_USER}"
    else
        echo "[WARN] STORAGEBOX_USER not set (offsite sync will be skipped)"
    fi

    echo ""
    echo "Retention policy:"
    echo "  Daily:   keep 7 days   (prune with -mtime +7)"
    echo "  Weekly:  keep 4 weeks  (prune with -mtime +28)"
    echo "  Monthly: keep 3 months (prune with -mtime +90)"
    echo ""
    echo "Cron schedule: 0 3 * * * (daily at 03:00 UTC)"
    echo ""

    exit 0
}

install_cron() {
    local cron_line="0 3 * * * /opt/jaot/deploy/backup.sh >> /opt/jaot/backups/backup.log 2>&1"

    # Remove any existing backup.sh entry before adding the new one.
    # `|| true`: on a host with no crontab yet, crontab -l/grep exit non-zero under pipefail.
    (crontab -l 2>/dev/null | grep -v 'backup.sh' || true; echo "${cron_line}") | crontab -

    echo "Cron entry installed:"
    echo "  ${cron_line}"
    echo ""
    echo "Verify with: crontab -l"
}

main() {
    case "${1:-}" in
        --dry-run)
            dry_run
            ;;
        --notify-test)
            log "Sending test notification..."
            send_success_notification "0B (test)" "0"
            log "Test notification sent (check ${NOTIFY_EMAIL:-'NOTIFY_EMAIL not set'})"
            exit 0
            ;;
        --install-cron)
            install_cron
            exit 0
            ;;
        "")
            ;;
        *)
            echo "Usage: $0 [--dry-run | --notify-test | --install-cron]"
            exit 1
            ;;
    esac

    # Rotate log over 10000 lines.
    if [ -f "${LOG_FILE}" ] && [ "$(wc -l < "${LOG_FILE}")" -gt 10000 ]; then
        tail -5000 "${LOG_FILE}" > "${LOG_FILE}.tmp"
        mv "${LOG_FILE}.tmp" "${LOG_FILE}"
        log "Log rotated (kept last 5000 lines)"
    fi

    # Prevent concurrent backup runs.
    LOCKFILE="/opt/jaot/backups/.backup.lock"
    mkdir -p "$(dirname "${LOCKFILE}")"
    exec 200>"${LOCKFILE}"
    flock -n 200 || { log "ERROR: Another backup is already running"; exit 1; }

    trap 'send_failure_notification "Script failed at line $LINENO"' ERR

    log "=========================================="
    log "JAOT Backup starting"
    log "=========================================="

    create_backup
    promote_backup
    prune_old_backups
    sync_offsite

    # Age-based WAL archive retention. pg_archivecleanup expects a WAL segment name and is
    # meaningless against pg_dump filenames (logical dumps carry no WAL position), so the
    # previous invocation failed silently on every run and the archive grew unbounded.
    # Without a base backup the archive is only a short forensic window — keep N days.
    if docker exec jaot_prod_postgres test -d /var/lib/postgresql/wal_archive 2>/dev/null; then
        local wal_retention_days
        wal_retention_days=$(load_env_var WAL_ARCHIVE_RETENTION_DAYS)
        wal_retention_days="${wal_retention_days:-14}"
        docker exec jaot_prod_postgres find /var/lib/postgresql/wal_archive -type f -name '0*' \
            -mtime "+${wal_retention_days}" -delete 2>/dev/null || true
        log "WAL archive pruned (retention: ${wal_retention_days} days)"
    fi

    local end_epoch
    end_epoch=$(date +%s)
    local duration=$((end_epoch - START_EPOCH))

    local backup_size
    backup_size=$(du -h "${BACKUP_DIR}/daily/${FILENAME}" | cut -f1)

    send_success_notification "${backup_size}" "${duration}" "${offsite_status:-skipped}"

    log "Backup completed in ${duration}s"
    log "=========================================="
}

main "$@"
