#!/usr/bin/env bash
set -euo pipefail

# JAOT Database Restore — restores a backup created by backup.sh via pg_restore.
#
# Usage:
#   ./restore.sh <backup-file>                  # Restore from a local .dump file
#   ./restore.sh --from-offsite <date>          # Fetch from offsite storage, then restore
#   ./restore.sh --dry-run <backup-file>        # Validate without restoring
#   ./restore.sh --list                         # List available backups
#   ./restore.sh help                           # Show this help
#
# Stops app services, restores with pg_restore --clean --if-exists, verifies,
# then restarts services.
#
# Env from /opt/jaot/.env.production: POSTGRES_USER (default jaot),
# POSTGRES_DB (default jaot), STORAGEBOX_USER (for --from-offsite).

COMPOSE_FILE="/opt/jaot/deploy/docker-compose.prod.yml"
BACKUP_DIR="/opt/jaot/backups"
LOG_FILE="${BACKUP_DIR}/restore.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { local msg="[$(date '+%Y-%m-%d %H:%M:%S')] [INFO]  $*"; echo -e "${BLUE}${msg}${NC}"; echo "$msg" >> "${LOG_FILE}" 2>/dev/null || true; }
log_warn()    { local msg="[$(date '+%Y-%m-%d %H:%M:%S')] [WARN]  $*"; echo -e "${YELLOW}${msg}${NC}"; echo "$msg" >> "${LOG_FILE}" 2>/dev/null || true; }
log_error()   { local msg="[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*"; echo -e "${RED}${msg}${NC}" >&2; echo "$msg" >> "${LOG_FILE}" 2>/dev/null || true; }
log_success() { local msg="[$(date '+%Y-%m-%d %H:%M:%S')] [OK]    $*"; echo -e "${GREEN}${msg}${NC}"; echo "$msg" >> "${LOG_FILE}" 2>/dev/null || true; }

# Targeted grep avoids `source` (no code execution risk).
load_env_var() {
    grep "^${1}=" /opt/jaot/.env.production 2>/dev/null | head -1 | cut -d'=' -f2-
}

pg_user=$(load_env_var POSTGRES_USER)
pg_user="${pg_user:-jaot}"
pg_db=$(load_env_var POSTGRES_DB)
pg_db="${pg_db:-jaot}"
STORAGEBOX_USER=$(load_env_var STORAGEBOX_USER)

# App services that hold DB connections, in stop/start order. The monolithic
# celery_worker was split (Phase 6 INF-01/02) into per-queue workers; the old
# name is no longer a service in docker-compose.prod.yml, so `up -d
# celery_worker` would fail with "no such service". celery_worker_hexaly is
# intentionally excluded: it is profile-gated (`profiles: ["hexaly"]`),
# deployed out-of-band via `--profile hexaly`, and its image is gated off in CI.
APP_SERVICES="api celery_worker_default celery_worker_scip celery_worker_highs celery_beat frontend"

stop_app_services() {
    log_info "Stopping application services..."
    docker compose -f "${COMPOSE_FILE}" stop ${APP_SERVICES} 2>/dev/null || true
    log_success "Application services stopped"
}

start_app_services() {
    log_info "Starting application services..."
    docker compose -f "${COMPOSE_FILE}" up -d ${APP_SERVICES}
    log_success "Application services started"
}

decrypt_if_needed() {
    local file="$1"
    if [[ "$file" == *.gpg ]]; then
        local decrypted="${file%.gpg}"
        if [ ! -f /opt/jaot/.backup-key.gpg ]; then
            log_error "Backup is encrypted but no key found at /opt/jaot/.backup-key.gpg"
            exit 1
        fi
        log_info "Decrypting backup..."
        gpg --batch --yes --passphrase-file /opt/jaot/.backup-key.gpg \
            --decrypt -o "$decrypted" "$file"
        log_success "Backup decrypted: $(basename "$decrypted")"
        echo "$decrypted"
    else
        echo "$file"
    fi
}

restore_backup() {
    local backup_file="$1"

    if [ ! -f "$backup_file" ]; then
        log_error "Backup file not found: $backup_file"
        exit 1
    fi

    backup_file=$(decrypt_if_needed "$backup_file")

    local file_size
    file_size=$(du -h "$backup_file" | cut -f1)
    log_info "Restoring from: $(basename "$backup_file") (${file_size})"

    log_info "Validating backup file (pg_restore --list)..."
    if ! docker exec -i jaot_prod_postgres pg_restore --list < "$backup_file" > /dev/null 2>&1; then
        log_error "Backup file is not a valid pg_restore archive: $backup_file"
        exit 1
    fi
    log_success "Backup file is valid"

    stop_app_services

    log_info "Running pg_restore --clean --if-exists..."
    if docker exec -i jaot_prod_postgres pg_restore \
        -U "${pg_user}" -d "${pg_db}" \
        --clean --if-exists \
        < "$backup_file"; then
        log_success "pg_restore completed"
    else
        # pg_restore may return non-zero for non-fatal warnings (e.g., "relation does not exist" on --clean).
        log_warn "pg_restore returned non-zero exit code (may include non-fatal warnings)"
    fi

    verify_restore

    start_app_services

    log_success "Restore complete!"
}

verify_restore() {
    log_info "Verifying restore..."

    local table_count
    table_count=$(docker exec jaot_prod_postgres psql -U "${pg_user}" -d "${pg_db}" -t -c \
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';" \
        2>/dev/null | tr -d '[:space:]')

    if [ -z "$table_count" ] || [ "$table_count" -eq 0 ]; then
        log_error "VERIFICATION FAILED: No tables found after restore"
        exit 1
    fi
    log_success "Tables found: ${table_count}"

    log_info "Row count sanity check:"
    for table in users organizations; do
        local count
        count=$(docker exec jaot_prod_postgres psql -U "${pg_user}" -d "${pg_db}" -t -c \
            "SELECT count(*) FROM ${table};" 2>/dev/null | tr -d '[:space:]' || echo "0")
        echo "  ${table}: ${count} rows"
    done

    log_success "Restore verification passed"
}

restore_from_offsite() {
    local date_pattern="${1:-}"

    if [ -z "${STORAGEBOX_USER}" ]; then
        log_error "STORAGEBOX_USER not set in .env.production -- cannot fetch from offsite"
        exit 1
    fi

    log_info "Fetching backup from offsite storage..."

    local tmp_dir="/tmp/jaot-restore-$$"
    mkdir -p "$tmp_dir"

    rsync -avz \
        -e 'ssh -p 23 -o StrictHostKeyChecking=accept-new -o BatchMode=yes' \
        "${STORAGEBOX_USER}@${STORAGEBOX_USER}.your-storagebox.de:jaot-backups/daily/" \
        "$tmp_dir/"

    # Find the most recent backup matching date pattern.
    local backup_file=""
    if [ -n "$date_pattern" ]; then
        backup_file=$(ls -1t "$tmp_dir"/jaot_${date_pattern}*.dump* 2>/dev/null | head -1)
    else
        backup_file=$(ls -1t "$tmp_dir"/*.dump* 2>/dev/null | head -1)
    fi

    if [ -z "$backup_file" ]; then
        log_error "No backup found matching pattern: ${date_pattern:-'latest'}"
        rm -rf "$tmp_dir"
        exit 1
    fi

    log_info "Found offsite backup: $(basename "$backup_file")"
    restore_backup "$backup_file"

    rm -rf "$tmp_dir"
}

dry_run() {
    local backup_file="$1"

    if [ ! -f "$backup_file" ]; then
        log_error "Backup file not found: $backup_file"
        exit 1
    fi

    local check_file
    check_file=$(decrypt_if_needed "$backup_file")

    local file_size
    file_size=$(du -h "$check_file" | cut -f1)

    echo "=== JAOT Restore Dry Run ==="
    echo ""
    echo "Backup file: $(basename "$backup_file")"
    echo "Size: ${file_size}"
    echo "Target database: ${pg_db} (user: ${pg_user})"
    echo ""

    log_info "Validating backup with pg_restore --list..."
    if docker exec -i jaot_prod_postgres pg_restore --list < "$check_file" > /dev/null 2>&1; then
        log_success "Backup is valid and restorable"
        echo ""
        echo "Table of contents:"
        docker exec -i jaot_prod_postgres pg_restore --list < "$check_file" 2>/dev/null | head -30
        echo "  ... (truncated)"
    else
        log_error "Backup file is NOT a valid pg_restore archive"
        exit 1
    fi

    echo ""
    echo "To restore, run: ./restore.sh $backup_file"
}

list_backups() {
    echo "=== Available JAOT Backups ==="
    echo ""

    for tier in daily weekly monthly; do
        echo "${tier^} backups:"
        if ls -lh "${BACKUP_DIR}/${tier}/"*.dump* 2>/dev/null | head -20; then
            true
        else
            echo "  (none)"
        fi
        echo ""
    done
}

show_help() {
    echo "JAOT Database Restore Script"
    echo ""
    echo "Usage: restore.sh <command> [options]"
    echo ""
    echo "Commands:"
    echo "  <backup-file>                  Restore from a local .dump file"
    echo "  --from-offsite [date]          Fetch from offsite storage, then restore"
    echo "                                 Date format: YYYY-MM-DD (optional, defaults to latest)"
    echo "  --dry-run <backup-file>        Validate backup without restoring"
    echo "  --list                         List available local backups"
    echo "  help                           Show this help"
    echo ""
    echo "Examples:"
    echo "  restore.sh /opt/jaot/backups/daily/jaot_2026-03-21_0300.dump"
    echo "  restore.sh --from-offsite 2026-03-20"
    echo "  restore.sh --dry-run /opt/jaot/backups/daily/jaot_2026-03-21_0300.dump"
    echo "  restore.sh --list"
    echo ""
    echo "The restore process:"
    echo "  1. Validates the backup file (pg_restore --list)"
    echo "  2. Stops application services (api, celery_worker_{default,scip,highs}, celery_beat, frontend)"
    echo "  3. Restores with: pg_restore -U \$POSTGRES_USER -d \$POSTGRES_DB --clean --if-exists"
    echo "  4. Verifies the restore (table count, row count sanity check)"
    echo "  5. Restarts application services"
}

mkdir -p "${BACKUP_DIR}" 2>/dev/null || true

case "${1:-help}" in
    --dry-run)
        if [ -z "${2:-}" ]; then
            log_error "Usage: restore.sh --dry-run <backup-file>"
            exit 1
        fi
        dry_run "$2"
        ;;
    --from-offsite)
        restore_from_offsite "${2:-}"
        ;;
    --list)
        list_backups
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        restore_backup "$1"
        ;;
esac
