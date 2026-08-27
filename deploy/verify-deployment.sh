#!/usr/bin/env bash
# Check a deployed ShuttleSense API before wiring the frontend to it.
#
#   ./deploy/verify-deployment.sh https://shuttlesense-api.onrender.com \
#                                 https://badminton-coach-asa24.vercel.app
#
# The second argument is the browser origin the API must accept. Getting CORS
# wrong is the single most common reason a correctly-deployed API still leaves
# the frontend showing "can't reach the API", and it is invisible from curl
# unless you ask for it specifically.
set -uo pipefail

API="${1:-}"
ORIGIN="${2:-}"
if [[ -z "$API" ]]; then
  echo "usage: $0 <api-base-url> [browser-origin]" >&2
  exit 64
fi
API="${API%/}"

pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=$((fail+1)); }
note() { printf '        %s\n' "$1"; }

echo "Checking $API"
echo

# --- liveness ------------------------------------------------------------
echo "Liveness"
body=$(curl -fsS --max-time 90 "$API/api/v1/health" 2>/dev/null)
if [[ "$body" == *'"status":"ok"'* ]]; then
  ok "/api/v1/health"
else
  bad "/api/v1/health did not return ok"
  note "On Render's free tier the first request after a sleep can take ~50s."
  note "Run this again before concluding anything is wrong."
fi

# --- readiness: the one that actually proves the wiring -------------------
echo
echo "Readiness (database, storage, queue)"
ready=$(curl -sS --max-time 90 "$API/api/v1/ready" 2>/dev/null)
if [[ -z "$ready" ]]; then
  bad "/api/v1/ready returned nothing"
else
  for dep in database storage queue; do
    if [[ "$ready" == *"\"$dep\":true"* ]]; then
      ok "$dep reachable"
    else
      bad "$dep NOT reachable"
      # /ready explains its own failures; prefer the server's reason to a guess.
      reason=$(python3 -c "
import json,sys
try:
    d = json.loads(sys.argv[1])
    print((d.get('reasons') or {}).get(sys.argv[2], ''))
except Exception:
    pass" "$ready" "$dep" 2>/dev/null)
      if [[ -n "$reason" ]]; then
        note "$reason"
      else
        case "$dep" in
          database) note "Check DATABASE_URL. Needs scheme postgresql+psycopg:// and the right password.";;
          storage)  note "Check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.";;
          queue)    note "Check pgmq exists: SELECT * FROM pgmq.metrics('shuttlesense_analysis');";;
        esac
      fi
    fi
  done
  for setting in '"storage_backend":"supabase"' '"job_backend":"pgmq"' '"auth_mode":"supabase"'; do
    if [[ "$ready" == *"$setting"* ]]; then
      ok "${setting//\"/}"
    else
      bad "expected $setting"
      note "A production deploy on a local backend loses data on restart."
    fi
  done
fi

# --- authorization --------------------------------------------------------
echo
echo "Authorization"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$API/api/v1/videos")
[[ "$code" == "401" ]] && ok "unauthenticated /videos -> 401" \
                       || bad "unauthenticated /videos -> $code (expected 401)"

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$API/docs")
[[ "$code" == "404" ]] && ok "/docs disabled in production -> 404" \
                       || bad "/docs -> $code (expected 404; is APP_ENV=production?)"

# --- CORS -----------------------------------------------------------------
if [[ -n "$ORIGIN" ]]; then
  echo
  echo "CORS for $ORIGIN"
  hdrs=$(curl -s -i -X OPTIONS --max-time 60 \
    -H "Origin: $ORIGIN" \
    -H "Access-Control-Request-Method: GET" \
    -H "Access-Control-Request-Headers: authorization" \
    "$API/api/v1/videos" 2>/dev/null)
  if grep -qi "access-control-allow-origin: *${ORIGIN}" <<<"$hdrs"; then
    ok "origin allowed"
  else
    bad "origin NOT allowed"
    note "CORS_ORIGINS must contain exactly: $ORIGIN"
    note "Exact match — scheme, host, no trailing slash."
  fi
  grep -qi "access-control-allow-headers:.*authorization" <<<"$hdrs" \
    && ok "Authorization header permitted" \
    || bad "Authorization header not permitted; every API call will fail"
fi

# --- security headers -----------------------------------------------------
echo
echo "Security headers"
h=$(curl -sI --max-time 60 "$API/api/v1/health")
for header in x-content-type-options x-frame-options referrer-policy; do
  grep -qi "^$header:" <<<"$h" && ok "$header" || bad "$header missing"
done

echo
echo "────────────────────────────────────────"
if (( fail == 0 )); then
  echo "All $pass checks passed. Safe to point the frontend at this API."
else
  echo "$pass passed, $fail failed. Fix the failures before wiring the frontend."
fi
exit $(( fail > 0 ))
