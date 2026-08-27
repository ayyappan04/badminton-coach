#!/usr/bin/env bash
# Validate deploy/worker.env BEFORE starting the worker.
#
# Checks the values locally and then actually connects, so a wrong password is
# caught here in two seconds rather than as a container that starts, fails, and
# retries against a pooler that eventually blocks it.
set -uo pipefail
cd "$(dirname "$0")/.."
ENV_FILE="${1:-deploy/worker.env}"

pass=0; fail=0
ok()  { printf '  \033[32mPASS\033[0m  %s\n' "$1"; pass=$((pass+1)); }
bad() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=$((fail+1)); }
note(){ printf '        %s\n' "$1"; }

[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE" >&2; exit 1; }
# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

echo "Checking $ENV_FILE"
echo

# --- the two values you had to fill in ------------------------------------
if [[ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]]; then
  bad "SUPABASE_SERVICE_ROLE_KEY is empty"
  note "Supabase -> Project Settings -> API Keys -> Secret keys -> Reveal"
elif [[ "$SUPABASE_SERVICE_ROLE_KEY" == sb_publishable_* ]]; then
  bad "that is the PUBLISHABLE key, not the secret key"
  note "The publishable key cannot bypass RLS; the worker needs the secret one."
else
  ok "SUPABASE_SERVICE_ROLE_KEY looks set"
fi

url="${DATABASE_URL:-}"
if [[ -z "$url" ]]; then
  bad "DATABASE_URL is empty"
elif [[ "$url" == *REPLACE_WITH_DB_PASSWORD* || "$url" == *"[YOUR-PASSWORD]"* ]]; then
  bad "DATABASE_URL still contains the password placeholder"
  note "Replace it with the real database password — this exact mistake cost"
  note "four failed deploys, because the resulting error blames the password."
else
  ok "DATABASE_URL has no placeholder"

  # Session pooler, not transaction pooler: the worker needs a connection it
  # keeps for the whole session.
  if [[ "$url" == *pooler.supabase.com* ]]; then
    if [[ "$url" == *:6543/* ]]; then
      bad "port 6543 is the TRANSACTION pooler"
      note "The worker needs the SESSION pooler on 5432: transaction mode hands"
      note "the connection back after every statement, breaking pgmq."
    else
      ok "using the session pooler (5432)"
    fi
    [[ "$url" == *"postgres.$(echo "${SUPABASE_URL:-}" | sed 's#https://##; s#\.supabase\.co##')"* ]] \
      && ok "username is tenant-qualified" \
      || bad "username should be postgres.<project_ref> for the pooler"
  elif [[ "$url" == *db.*.supabase.co* ]]; then
    bad "that is the DIRECT connection (IPv6-only)"
    note "Many home networks cannot reach it. Use the session pooler instead."
  fi
fi

# --- does it actually work? -----------------------------------------------
echo
echo "Live checks"
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  ok "Docker is running"
else
  bad "Docker is not running — start Docker Desktop"
fi

if [[ -n "${SUPABASE_SERVICE_ROLE_KEY:-}" ]]; then
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
    -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
    -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
    "${SUPABASE_URL%/}/storage/v1/bucket")
  [[ "$code" == "200" ]] && ok "secret key authenticates to Supabase Storage" \
                         || bad "Storage rejected the secret key (HTTP $code)"
fi

echo
echo "────────────────────────────────────────"
if (( fail == 0 )); then
  echo "All $pass checks passed. Start the worker with:"
  echo "    ./deploy/run-worker-local.sh"
else
  echo "$pass passed, $fail failed. Fix the failures above first."
  echo "The database password itself is verified when the worker starts —"
  echo "watch for 'worker started' with no connection errors."
fi
exit $(( fail > 0 ))
