# Operations runbook

Every command below is run from `backend/` with the environment of the tier you
are operating on. Destructive commands default to a dry run; `--apply` is
always opt-in.

```bash
python manage.py doctor     # start here for anything you don't understand yet
```

---

## Stuck processing job

**Symptom:** a video sits in `processing`, `normalizing`, `queued` or
`validating` and never resolves.

```bash
python manage.py stuck --minutes 60
```

Read `run_status` and `lease_expires_at` in the output:

| What you see | What it means | Action |
|---|---|---|
| `lease_expires_at` in the past, status `running` | The worker died. | `python manage.py stuck --requeue` |
| `lease_expires_at` in the future | A worker is genuinely still working. | Wait. A 40-minute 4K match takes minutes. |
| `run_status: pending`, queue depth > 0 | No worker is consuming. | Check worker containers are up; `python manage.py queue`. |
| `run_status: pending`, queue depth 0 | The message was lost after the run row was written. | `python manage.py stuck --requeue` re-enqueues it. |
| `attempt` at `max_attempts` | Already given up. | The video should be `failed`; if not, investigate the run's `error_detail`. |

The stale-lease sweep also runs automatically inside every worker every 120
seconds, so this is usually a way to *confirm* recovery rather than to cause it.

---

## Failed normalization

**Symptom:** videos fail with `transcode_failed`, `probe_failed`,
`corrupt_media` or `ffmpeg_unavailable`.

```sql
SELECT error_code, failed_stage, count(*)
FROM analysis_runs
WHERE status = 'failed' AND created_at > now() - interval '24 hours'
GROUP BY 1, 2 ORDER BY 3 DESC;
```

- **`ffmpeg_unavailable`** — the container is missing ffmpeg. Verify the image:
  `docker run --rm shuttlesense-worker:latest ffmpeg -version`. This should be
  impossible with the shipped Dockerfile, which apt-installs it and asserts the
  version at build time.
- **`corrupt_media` / `no_video_stream`** — the user's file. Permanent and
  non-retryable by design; the user sees a clear message. Nothing to do.
- **`transcode_failed` clustered on one source format** — a real gap. Get the
  detail (server-side only, never sent to the client):

  ```sql
  SELECT error_detail FROM analysis_runs WHERE id = '<run_id>';
  ```

- **`transcode_timeout`** — raise `FFMPEG_TIMEOUT_S`, or the input is beyond
  `MAX_VIDEO_DURATION_S`.

To retry after fixing the cause, use the API (`POST /videos/{id}/reprocess`),
which creates a **new** analysis run and preserves the failed one.

---

## Orphaned storage object

**Symptom:** storage bytes exceed what `video_assets` accounts for.

```bash
python manage.py reconcile --user <user_id>     # dry run, always start here
python manage.py reconcile                      # whole project (slow)
```

The report classifies every disagreement:

- **`missing_objects`** — a row claims an object that is not in the bucket.
  Serious: a user has a match whose file is gone. Check whether retention or a
  purge ran; the derived ones are reproducible via `reprocess`.
- **`orphaned_objects`** — an object with no live asset row. Usually a crash
  between "uploaded" and "row written". Safe to remove once you have looked at
  it:

  ```bash
  python manage.py reconcile --user <id> --apply --delete-orphans
  ```

- **`size_mismatches`** — recorded size differs from actual. `--apply` corrects
  the row.

Reconciliation never deletes without both `--apply` and `--delete-orphans`.

---

## Worker unavailable

**Symptom:** queue depth climbing, nothing progressing.

```bash
python manage.py queue          # depth, backend, health
python manage.py doctor         # database / storage / queue / ffmpeg
```

1. Are worker containers running? They serve no HTTP, so there is no health
   endpoint to poll — check the orchestrator and the logs.
2. `queue.healthy: false` → the worker cannot reach pgmq. Check `DATABASE_URL`
   and that the extension exists: `SELECT * FROM pgmq.metrics('shuttlesense_analysis');`
3. Work is safe while workers are down. Messages stay queued; in-flight runs
   have leases that expire and are reclaimed. **No user action is lost.**
4. Scale out, not up: `docker compose up --scale worker=4`. Raising
   `WORKER_CONCURRENCY` makes concurrent pipelines contend for the same cores
   and the same frame-buffer budget, so they finish later than in sequence.

---

## Supabase unavailable

1. `/api/v1/ready` reports which dependency is down.
2. **Uploads in progress keep working** — the browser is talking to Storage
   directly, not through the API, and TUS resumes after an interruption.
3. Queued jobs stay queued. The worker's transient failures back off
   exponentially (15s → 300s) rather than spinning.
4. Do **not** restart workers to "clear" anything. A restart abandons the
   message currently in hand; the lease mechanism recovers it, but a restart
   loop only makes recovery slower.

---

## Queue backlog

```bash
python manage.py queue
```

```sql
-- how long jobs are waiting
SELECT status, count(*), min(created_at) AS oldest
FROM analysis_runs WHERE status IN ('pending','claimed','running') GROUP BY 1;
```

- Add worker containers. Throughput is linear in worker count.
- Check for a poison message cycling: `SELECT * FROM pgmq.metrics('shuttlesense_analysis_dlq');`
- If one user is flooding the queue, `MAX_ANALYSIS_JOBS_PER_DAY` and
  `MAX_ACTIVE_UPLOADS_PER_USER` are the levers.

---

## Sizing the worker fleet

```bash
python manage.py capacity
```

`realtime_factor` is compute-seconds per second of footage — the number that
turns "we have N minutes of backlog" into "we need M workers". It is recorded
per run, so `by_pipeline_version` also shows whether a release changed the cost
of analysis.

One worker sustains roughly `3600 / (p95 × average_match_seconds)` matches per
hour. Scale out by adding worker containers; raising `WORKER_CONCURRENCY` makes
concurrent pipelines contend for the same cores and the same frame-buffer
budget, so they finish later than they would in sequence.

---

## Reprocess a video

Use the API so a new run is created and history is preserved:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  https://api.shuttlesense.com/api/v1/videos/<video_id>/reprocess
```

The previous run stays in `analysis_runs` with `is_current = false`. Exactly
one run per video may be current — enforced by a partial unique index, not by
convention.

Bulk reprocessing after a pipeline upgrade: find stale derived assets first.

```bash
python manage.py stale-assets
```

---

## Purge a deleted video

Deletion is two-phase. Phase 1 (tombstone, revoke shares, cancel jobs) is
synchronous. Phase 2 (objects and analysis rows) is an idempotent job.

```bash
python manage.py purge-video --video <id>            # dry run
python manage.py purge-video --video <id> --apply
```

`purge-video` **refuses to touch a video that is not tombstoned**, so a stale
cleanup message cannot delete something a user can still see.

---

## Delete an account

```bash
python manage.py delete-account --user <id>          # dry run: counts only
python manage.py delete-account --user <id> --apply
```

Idempotent, so a partially-failed run can simply be repeated. Reviews the user
performed **for other people** are those people's data: the link is revoked,
the note is not destroyed.

The Supabase Auth identity is separate — delete it in the Supabase dashboard or
via the Admin API once the application data is gone.

---

## Inspect storage usage

```bash
python manage.py usage --user <id>
python manage.py usage --user <id> --recalculate     # recount from video_assets
```

```sql
-- biggest consumers
SELECT user_id, pg_size_pretty(original_bytes + derived_bytes) AS total
FROM storage_usage ORDER BY original_bytes + derived_bytes DESC LIMIT 20;
```

Usage is a maintained counter, not a bucket scan. If it drifts,
`--recalculate` is authoritative and `reconcile` explains why it drifted.

---

## Retention

Originals are **never** deleted as part of processing.

```bash
python manage.py retention                # candidates only
python manage.py retention --apply
```

Retention refuses to delete an original when the video is not `analyzed`, when
the analysis proxy row is missing, or when the proxy object cannot be
confirmed present in the bucket. `RETAIN_ORIGINAL_ALWAYS=true` (the default)
disables it entirely — turn it off only once a deliberate product policy
exists.

---

## Reading the logs

Logs are JSON in production. One video id reconstructs the whole story:

```bash
# everything about one match, across API and worker containers
<log query tool> | jq 'select(.video_id == "<id>")'

# failures by stage in the last hour
<log query tool> | jq 'select(.level=="ERROR") | .stage' | sort | uniq -c
```

Tokens, service keys and signed URLs are redacted structurally, including when
nested inside a dict. If you see one in a log, that is a bug worth fixing at
the redaction list in `app/core/observability.py`, not a reason to be careful
by hand.

---

## Metrics

```bash
curl -H "x-metrics-token: $METRICS_TOKEN" https://api.shuttlesense.com/api/v1/metrics
```

Worth alerting on:

| Metric | Suggests |
|---|---|
| `queue_wait_seconds` p95 rising | Add workers |
| `processing_failures_by_stage` spike on one stage | A regression, or a new source format |
| `analysis_jobs_dead_lettered` > 0 | A poison message needs a human |
| `stale_leases_reclaimed` rising | Workers dying — OOM? Check memory limits |
| `uploads_failed{reason=size_mismatch}` rising | Network problems, or a client bug |
| `storage_bytes_original` growth vs. revenue | Time to revisit retention |
