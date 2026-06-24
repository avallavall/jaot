#!/usr/bin/env bash
set -euo pipefail

# JAOT Post-Deploy Health Check
#
# Verifies all services are healthy after deployment.
#
# Usage:
#   bash deploy/health-check.sh                # Run on the server (default)
#   bash deploy/health-check.sh --remote       # Run from local machine via SSH
#   DOMAIN=jaot.io bash deploy/health-check.sh # Override domain
#
# Exit 0 on all pass, 1 on any failure.

DOMAIN="${DOMAIN:-jaot.io}"
TIMEOUT="${HEALTH_CHECK_TIMEOUT:-60}"
API_HEALTH_URL="https://${DOMAIN}/api/v2/health/status"
FRONTEND_URL="https://${DOMAIN}/en"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASSED=0
FAILED=0
WARNINGS=0

log_pass()  { echo -e "  ${GREEN}[PASS]${NC}  $*"; PASSED=$((PASSED + 1)); }
log_fail()  { echo -e "  ${RED}[FAIL]${NC}  $*" >&2; FAILED=$((FAILED + 1)); }
log_warn()  { echo -e "  ${YELLOW}[WARN]${NC}  $*"; WARNINGS=$((WARNINGS + 1)); }
log_info()  { echo -e "  ${BLUE}[INFO]${NC}  $*"; }

echo "============================================"
echo " JAOT Post-Deploy Health Check"
echo " Domain: ${DOMAIN}"
echo " Timeout: ${TIMEOUT}s"
echo "============================================"
echo ""

echo "--- Docker Container Health ---"

CONTAINERS=(
    "jaot_prod_postgres:PostgreSQL"
    "jaot_prod_redis:Redis"
    "jaot_prod_rabbitmq:RabbitMQ"
    "jaot_prod_api:API (FastAPI)"
    "jaot_prod_celery:Celery Worker"
    "jaot_prod_beat:Celery Beat"
    "jaot_prod_frontend:Frontend (Next.js)"
    "jaot_prod_caddy:Caddy (Reverse Proxy)"
)

for entry in "${CONTAINERS[@]}"; do
    container="${entry%%:*}"
    label="${entry##*:}"

    status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "not found")

    case "$status" in
        healthy)
            log_pass "$label ($container): healthy"
            ;;
        starting)
            log_warn "$label ($container): starting (may need more time)"
            ;;
        unhealthy)
            log_fail "$label ($container): unhealthy"
            last_log=$(docker inspect --format='{{range .State.Health.Log}}{{.Output}}{{end}}' "$container" 2>/dev/null | tail -3 || true)
            if [[ -n "$last_log" ]]; then
                echo "         Last health check output: $last_log"
            fi
            ;;
        "not found")
            log_fail "$label ($container): container not found"
            ;;
        *)
            log_fail "$label ($container): unknown status '$status'"
            ;;
    esac
done

echo ""

echo "--- HTTPS Connectivity ---"

if command -v curl &>/dev/null; then
    elapsed=0
    https_ok=false

    while [[ $elapsed -lt $TIMEOUT ]]; do
        http_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://${DOMAIN}/" 2>/dev/null || echo "000")

        if [[ "$http_code" == "200" || "$http_code" == "301" || "$http_code" == "302" || "$http_code" == "307" ]]; then
            log_pass "HTTPS https://${DOMAIN}/ responds (HTTP $http_code) [${elapsed}s]"
            https_ok=true
            break
        fi

        sleep 2
        elapsed=$((elapsed + 2))
    done

    if [[ "$https_ok" == "false" ]]; then
        log_fail "HTTPS https://${DOMAIN}/ did not respond within ${TIMEOUT}s (last HTTP code: $http_code)"
    fi
else
    log_warn "curl not available, skipping HTTPS connectivity check"
fi

echo ""

echo "--- API Health Endpoint ---"

if command -v curl &>/dev/null; then
    elapsed=0
    api_ok=false

    while [[ $elapsed -lt $TIMEOUT ]]; do
        response=$(curl -s --max-time 10 "$API_HEALTH_URL" 2>/dev/null || echo "")
        http_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$API_HEALTH_URL" 2>/dev/null || echo "000")

        if [[ "$http_code" == "200" ]]; then
            log_pass "API ${API_HEALTH_URL} responds (HTTP 200) [${elapsed}s]"
            if [[ -n "$response" ]]; then
                echo "         Response: $(echo "$response" | head -c 200)"
            fi
            api_ok=true
            break
        fi

        sleep 2
        elapsed=$((elapsed + 2))
    done

    if [[ "$api_ok" == "false" ]]; then
        log_fail "API ${API_HEALTH_URL} did not respond with 200 within ${TIMEOUT}s (last HTTP code: $http_code)"
    fi
else
    log_warn "curl not available, skipping API health check"
fi

echo ""

echo "--- Frontend Page Load ---"

if command -v curl &>/dev/null; then
    elapsed=0
    frontend_ok=false

    while [[ $elapsed -lt $TIMEOUT ]]; do
        http_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$FRONTEND_URL" 2>/dev/null || echo "000")

        if [[ "$http_code" == "200" ]]; then
            log_pass "Frontend ${FRONTEND_URL} responds (HTTP 200) [${elapsed}s]"
            frontend_ok=true
            break
        fi

        sleep 2
        elapsed=$((elapsed + 2))
    done

    if [[ "$frontend_ok" == "false" ]]; then
        log_fail "Frontend ${FRONTEND_URL} did not respond with 200 within ${TIMEOUT}s (last HTTP code: $http_code)"
    fi
else
    log_warn "curl not available, skipping frontend page load check"
fi

echo ""

echo "--- Monitoring Services (non-critical) ---"

MONITORING_CONTAINERS=(
    "jaot_prod_prometheus:Prometheus"
    "jaot_prod_node_exporter:Node Exporter"
    "jaot_prod_cadvisor:cAdvisor"
    "jaot_prod_grafana:Grafana"
    "jaot_prod_alertmanager:Alertmanager"
    "jaot_prod_postgres_exporter:PostgreSQL Exporter"
    "jaot_prod_redis_exporter:Redis Exporter"
    "jaot_prod_blackbox:Blackbox Exporter"
)

for entry in "${MONITORING_CONTAINERS[@]}"; do
    container="${entry%%:*}"
    label="${entry##*:}"

    status=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null || echo "not found")

    if [[ "$status" == "running" ]]; then
        log_pass "$label ($container): running"
    elif [[ "$status" == "not found" ]]; then
        log_warn "$label ($container): not found (monitoring may not be deployed)"
    else
        log_warn "$label ($container): $status"
    fi
done

echo ""

echo "============================================"
TOTAL=$((PASSED + FAILED))
echo " Results: ${PASSED}/${TOTAL} passed, ${FAILED} failed, ${WARNINGS} warnings"

if [[ $FAILED -eq 0 ]]; then
    echo -e " ${GREEN}ALL CHECKS PASSED${NC}"
    echo "============================================"
    exit 0
else
    echo -e " ${RED}${FAILED} CHECK(S) FAILED${NC}"
    echo "============================================"
    exit 1
fi
