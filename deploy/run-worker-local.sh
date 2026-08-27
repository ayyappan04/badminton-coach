#!/usr/bin/env bash
# Run the analysis worker on THIS machine against your real Supabase project.
#
# Why you might want this: the worker is the expensive half to host (it decodes
# video and runs pose estimation, so it wants CPU and memory), while the API is
# a control plane that needs almost nothing. Running the worker locally costs
# nothing and still exercises the entire production path — TUS uploads landing
# in Supabase Storage, pgmq handing out jobs, signed playback URLs.
#
# It is not a permanent answer: close the laptop and queued matches wait. But
# it is the right first step, because it proves the cloud wiring before you pay
# anyone to host it.
#
#   cp deploy/worker.env.example deploy/worker.env   # then fill it in
#   ./deploy/run-worker-local.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE="${1:-deploy/worker.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE — copy deploy/worker.env.example and fill it in." >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

for var in SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY DATABASE_URL; do
  if [[ -z "${!var:-}" ]]; then
    echo "$var is not set in $ENV_FILE" >&2
    exit 1
  fi
done

echo "Building the worker image..."
docker build -q -t shuttlesense-api:latest -f backend/Dockerfile backend >/dev/null

# Docker Desktop's default memory allocation is often below what a 4K match
# needs. MAX_ANALYSIS_FRAME_MB is the pipeline's own frame-buffer budget and
# must sit comfortably under the container limit, or the worker is OOM-killed
# mid-analysis rather than degrading to a sparser sample rate.
MEM="${WORKER_MEMORY:-4g}"
FRAME_MB="${MAX_ANALYSIS_FRAME_MB:-1200}"

echo "Starting worker (memory=$MEM, frame budget=${FRAME_MB}MB)"
echo "Ctrl-C stops it; in-flight work is finished first, and anything unclaimed"
echo "stays queued in pgmq for the next worker."
echo

exec docker run --rm -it \
  --name shuttlesense-worker \
  --memory "$MEM" \
  -e APP_ENV=production \
  -e LOG_FORMAT=text \
  -e STORAGE_BACKEND=supabase \
  -e JOB_BACKEND=pgmq \
  -e AUTH_MODE=supabase \
  -e STORAGE_DIR=/tmp/shuttlesense \
  -e WORKER_CONCURRENCY="${WORKER_CONCURRENCY:-1}" \
  -e MAX_ANALYSIS_FRAME_MB="$FRAME_MB" \
  -e SUPABASE_URL="$SUPABASE_URL" \
  -e SUPABASE_SERVICE_ROLE_KEY="$SUPABASE_SERVICE_ROLE_KEY" \
  -e DATABASE_URL="$DATABASE_URL" \
  -e JWT_SECRET="${JWT_SECRET:-unused-in-supabase-auth-mode}" \
  shuttlesense-api:latest \
  python -m app.jobs.runner
