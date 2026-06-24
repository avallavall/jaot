#!/usr/bin/env bash
set -euo pipefail

# Plausible self-hosted — post-deploy smoke test.
#
# Asserts the public endpoint surface of plausible.jaot.io:
#   GET  /js/script.js     -> 200 + Content-Type: application/javascript
#   POST /api/event        -> 202 (event ingestion)
#   GET  /login            -> 404 (dashboard never publicly exposed)
#   GET  /register         -> 404
#   GET  /api/v2/query     -> 404
#   GET  /                 -> 404
#
# Usage:
#   bash deploy/scripts/smoke-plausible.sh
#   DOMAIN=staging.plausible.jaot.io TIMEOUT=60 bash deploy/scripts/smoke-plausible.sh
#
# Exit 0 on all-pass, 1 on any failure.

DOMAIN="${DOMAIN:-plausible.jaot.io}"
TIMEOUT="${TIMEOUT:-30}"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log_pass() { echo -e "  ${GREEN}[PASS]${NC}  $*"; }
log_fail() { echo -e "  ${RED}[FAIL]${NC}  $*" >&2; }
log_info() { echo -e "  ${BLUE}[INFO]${NC}  $*"; }

if ! command -v curl &>/dev/null; then
    log_fail "curl not available on this host — smoke test cannot run"
    exit 1
fi

echo "============================================"
echo " Plausible Smoke — ${DOMAIN}"
echo " Timeout per probe: ${TIMEOUT}s"
echo "============================================"

# Git Bash on Windows occasionally concatenates curl's exit code onto the
# HTTP status code; trim to 3 chars.
http_code_clean() {
    local code="${1:-000}"
    [[ "${#code}" -gt 3 ]] && code="${code:0:3}"
    echo "$code"
}

# Probe HTTP endpoint with bounded retry.
# Args: method url expected_status label [content_type_grep_pattern]
# Writes "PASS|FAIL <label> [details]" to $PROBE_OUT (per-invocation, parallel-safe).
probe_http() {
    local method="$1" url="$2" expected="$3" label="$4" ct_pattern="${5:-}"
    local elapsed=0 code="000" ct=""
    local curl_args=(-s -o /dev/null -w '%{http_code}' --max-time 10 -X "$method")
    [[ "$method" == "POST" ]] && curl_args+=(
        -H 'Content-Type: application/json'
        -H 'User-Agent: smoke-test-curl'
        -d '{"name":"pageview","url":"https://jaot.io/","domain":"jaot.io"}'
    )

    while (( elapsed < TIMEOUT )); do
        code=$(curl "${curl_args[@]}" "$url" 2>/dev/null || true)
        code=$(http_code_clean "$code")
        if [[ "$code" == "$expected" ]]; then
            if [[ -n "$ct_pattern" ]]; then
                ct=$(curl -sI --max-time 10 "$url" 2>/dev/null \
                    | grep -i '^content-type:' | head -1 | awk -F': *' '{print $2}' | tr -d '\r\n')
                if ! echo "$ct" | grep -qi "$ct_pattern"; then
                    sleep 2; elapsed=$((elapsed + 2)); continue
                fi
                echo "PASS|${label}: HTTP ${code}, Content-Type=${ct} [${elapsed}s]" >"$PROBE_OUT"
            else
                echo "PASS|${label}: HTTP ${code} [${elapsed}s]" >"$PROBE_OUT"
            fi
            return 0
        fi
        sleep 2; elapsed=$((elapsed + 2))
    done
    echo "FAIL|${label} — expected HTTP ${expected} within ${TIMEOUT}s (last: ${code:-none}${ct:+, Content-Type: $ct})" >"$PROBE_OUT"
    return 1
}

# Probes 1 + 6 run sequentially (happy paths); 2-5 (404 lockdown) run in
# parallel — cuts worst case from 4×TIMEOUT to ~TIMEOUT on misconfiguration.
TMPDIR_PROBES=$(mktemp -d)
trap 'rm -rf "$TMPDIR_PROBES"' EXIT

run_probe() {
    local idx="$1" method="$2" url="$3" expected="$4" label="$5" ct="${6:-}"
    PROBE_OUT="$TMPDIR_PROBES/probe_${idx}.out" \
        probe_http "$method" "$url" "$expected" "$label" "$ct"
}

log_info "Probe 1: GET /js/script.js (D-01/D-02)"
run_probe 1 GET  "https://${DOMAIN}/js/script.js" 200 "GET /js/script.js" "application/javascript" || true

log_info "Probe 2-5: lockdown checks in parallel (D-03/D-08)"
run_probe 2 GET "https://${DOMAIN}/login"        404 "GET /login"        & p2=$!
run_probe 3 GET "https://${DOMAIN}/register"     404 "GET /register"     & p3=$!
run_probe 4 GET "https://${DOMAIN}/api/v2/query" 404 "GET /api/v2/query" & p4=$!
run_probe 5 GET "https://${DOMAIN}/"             404 "GET /"             & p5=$!
wait "$p2" "$p3" "$p4" "$p5" || true

log_info "Probe 6: POST /api/event (D-02)"
run_probe 6 POST "https://${DOMAIN}/api/event" 202 "POST /api/event" || true

passed=0
failed=0
for idx in 1 2 3 4 5 6; do
    out=$(cat "$TMPDIR_PROBES/probe_${idx}.out" 2>/dev/null || echo "FAIL|probe ${idx} produced no output")
    verdict="${out%%|*}"
    msg="${out#*|}"
    case "$verdict" in
        PASS) log_pass "$msg"; passed=$((passed + 1));;
        *)    log_fail "$msg"; failed=$((failed + 1));;
    esac
done

echo ""
echo "============================================"
total=$((passed + failed))
echo " Results: ${passed}/${total} passed, ${failed} failed"
if (( failed == 0 )); then
    echo -e " ${GREEN}ALL CHECKS PASSED${NC}"
    echo "============================================"
    exit 0
else
    echo -e " ${RED}${failed} CHECK(S) FAILED${NC}"
    echo "============================================"
    exit 1
fi
