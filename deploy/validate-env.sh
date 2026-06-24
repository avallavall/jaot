#!/usr/bin/env bash
set -euo pipefail

# JAOT Environment Validation — validates infrastructure env vars before deploy.
#
# Two-tier config: tier 1 (env vars: DB, Redis, Celery, JWT, CORS) is loaded
# before the database; tier 2 (platform_settings DB table) holds business
# config. This script only validates tier 1.
#
# Docker Compose resolves ${VAR} from .env.production (env_file), .env in CWD
# (YAML interpolation), and host env. All three are checked.
#
# Usage: bash deploy/validate-env.sh .env.production
# Exit 0 on pass, 1 on failure.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

log_pass()  { echo -e "${GREEN}[PASS]${NC}  $*"; }
log_fail()  { echo -e "${RED}[FAIL]${NC}  $*" >&2; ERRORS=$((ERRORS + 1)); }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; WARNINGS=$((WARNINGS + 1)); }
log_info()  { echo -e "       $*"; }

ENV_FILE="${1:-.env.production}"
COMPOSE_ENV_FILE=".env"

if [[ ! -f "$ENV_FILE" ]]; then
    log_fail "Environment file not found: $ENV_FILE"
    echo "Usage: bash deploy/validate-env.sh <path-to-env-file>"
    exit 1
fi

echo "============================================"
echo " JAOT Environment Validation"
echo " Primary:  $ENV_FILE"
if [[ -f "$COMPOSE_ENV_FILE" ]]; then
    echo " Compose:  $COMPOSE_ENV_FILE"
fi
echo "============================================"
echo ""

_read_from_file() {
    local var_name="$1" file="$2"
    local value
    value=$(grep -E "^${var_name}=" "$file" 2>/dev/null | head -1 | cut -d= -f2- || true)
    value=$(echo "$value" | sed 's/[[:space:]]*#[^"]*$//' | xargs 2>/dev/null || echo "$value")
    echo "$value"
}

get_env_value() {
    local var_name="$1"
    local value

    value=$(_read_from_file "$var_name" "$ENV_FILE")

    if [[ -z "$value" && -f "$COMPOSE_ENV_FILE" ]]; then
        value=$(_read_from_file "$var_name" "$COMPOSE_ENV_FILE")
    fi

    if [[ -z "$value" ]]; then
        value="${!var_name:-}"
    fi

    echo "$value"
}

echo "--- Infrastructure Secrets ---"

# Required by Python Settings in app/config.py.
APP_REQUIRED=("JWT_SECRET" "DATABASE_URL" "REDIS_URL" "CELERY_BROKER_URL")

for var in "${APP_REQUIRED[@]}"; do
    value=$(get_env_value "$var")
    if [[ -z "$value" ]]; then
        # docker-compose may compose these URLs from individual creds.
        if [[ "$var" == "DATABASE_URL" ]]; then
            PG_USER=$(get_env_value "POSTGRES_USER")
            PG_PASS=$(get_env_value "POSTGRES_PASSWORD")
            PG_DB=$(get_env_value "POSTGRES_DB")
            if [[ -n "$PG_USER" && -n "$PG_PASS" && -n "$PG_DB" ]]; then
                log_pass "DATABASE_URL composed from POSTGRES_USER/PASSWORD/DB"
                continue
            fi
        fi
        if [[ "$var" == "REDIS_URL" ]]; then
            REDIS_PASS=$(get_env_value "REDIS_PASSWORD")
            if [[ -n "$REDIS_PASS" ]]; then
                log_pass "REDIS_URL composed from REDIS_PASSWORD"
                continue
            fi
        fi
        if [[ "$var" == "CELERY_BROKER_URL" ]]; then
            RMQ_PASS=$(get_env_value "RABBITMQ_PASS")
            if [[ -n "$RMQ_PASS" ]]; then
                log_pass "CELERY_BROKER_URL composed from RABBITMQ_PASS"
                continue
            fi
        fi
        log_fail "$var is empty or not set"
    else
        log_pass "$var is set"
    fi
done

echo ""

# Used in docker-compose.prod.yml ${VAR} interpolation.
echo "--- Compose Secrets ---"

COMPOSE_REQUIRED=("POSTGRES_PASSWORD" "REDIS_PASSWORD" "RABBITMQ_PASS" "GRAFANA_ADMIN_PASSWORD" "QDRANT_API_KEY" "PLAUSIBLE_SECRET_KEY_BASE" "PLAUSIBLE_POSTGRES_PASSWORD")

for var in "${COMPOSE_REQUIRED[@]}"; do
    value=$(get_env_value "$var")
    if [[ -z "$value" ]]; then
        log_fail "$var is empty or not set"
    else
        log_pass "$var is set"
    fi
done

echo ""

echo "--- JWT Validation ---"

JWT_SECRET=$(get_env_value "JWT_SECRET")
if [[ -n "$JWT_SECRET" ]]; then
    if [[ "$JWT_SECRET" == "change-me" || "$JWT_SECRET" == "secret" || "$JWT_SECRET" == "your-secret-here" ]]; then
        log_fail "JWT_SECRET is a known default value"
    elif [[ ${#JWT_SECRET} -lt 32 ]]; then
        log_fail "JWT_SECRET is too short (${#JWT_SECRET} chars, min 32)"
        log_info "Generate: openssl rand -hex 32"
    else
        log_pass "JWT_SECRET length OK (${#JWT_SECRET} chars)"
    fi
fi

echo ""

echo "--- Production Safety ---"

DEBUG=$(get_env_value "DEBUG")
if [[ "$DEBUG" == "True" || "$DEBUG" == "true" || "$DEBUG" == "1" ]]; then
    log_fail "DEBUG is enabled (set DEBUG=False)"
else
    log_pass "DEBUG is disabled"
fi

RELOAD=$(get_env_value "RELOAD")
if [[ "$RELOAD" == "True" || "$RELOAD" == "true" || "$RELOAD" == "1" ]]; then
    log_fail "RELOAD is enabled (set RELOAD=False)"
else
    log_pass "RELOAD is disabled"
fi

ALLOWED_ORIGINS=$(get_env_value "ALLOWED_ORIGINS")
if [[ -n "$ALLOWED_ORIGINS" && "$ALLOWED_ORIGINS" == *"*"* ]]; then
    log_fail "ALLOWED_ORIGINS contains wildcard (*)"
elif [[ -n "$ALLOWED_ORIGINS" && "$ALLOWED_ORIGINS" == *"localhost"* ]]; then
    log_warn "ALLOWED_ORIGINS contains localhost"
else
    log_pass "ALLOWED_ORIGINS OK"
fi

echo ""

echo "--- Password Strength ---"

check_password_strength() {
    local var_name="$1" min_length="${2:-12}"
    local value
    value=$(get_env_value "$var_name")
    if [[ -z "$value" ]]; then
        return
    fi
    if [[ ${#value} -lt $min_length ]]; then
        log_warn "$var_name is short (${#value} chars, recommended >= $min_length)"
    else
        log_pass "$var_name length OK (${#value} chars)"
    fi
}

check_password_strength "POSTGRES_PASSWORD" 16
check_password_strength "REDIS_PASSWORD" 16
check_password_strength "RABBITMQ_PASS" 16
check_password_strength "GRAFANA_ADMIN_PASSWORD" 12

echo ""

echo "============================================"
if [[ $ERRORS -eq 0 ]]; then
    echo -e "${GREEN} PASSED${NC} - $ERRORS errors, $WARNINGS warnings"
    echo "============================================"
    exit 0
else
    echo -e "${RED} FAILED${NC} - $ERRORS error(s), $WARNINGS warning(s)"
    echo "============================================"
    echo ""
    echo "Fix the errors above before deploying."
    exit 1
fi
