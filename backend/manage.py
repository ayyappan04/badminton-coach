#!/usr/bin/env python
"""Operational CLI.

Every destructive command defaults to a dry run and prints what it WOULD do.
An automated deleter that is wrong once destroys a user's match footage; a
reporter that is wrong once prints a wrong line. The asymmetry is the reason
`--apply` is always opt-in.

    python manage.py doctor
    python manage.py reconcile [--user ID] [--apply] [--delete-orphans]
    python manage.py stuck [--minutes 60] [--requeue]
    python manage.py retention [--apply]
    python manage.py stale-assets
    python manage.py queue [--depth] [--ensure]
    python manage.py capacity [--limit 200]
    python manage.py usage --user ID [--recalculate]
    python manage.py purge-video --video ID --apply
    python manage.py delete-account --user ID --apply
"""
import argparse
import json
import sys

from app.core.observability import configure_logging


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def cmd_doctor(args) -> int:
    """One-shot check of every dependency this deployment needs."""
    from sqlalchemy import text
    from app.core import config
    from app.db.session import engine
    from app.jobs import get_dispatcher
    from app.media import ffmpeg
    from app.storage import get_storage

    report = {
        "app_env": config.APP_ENV,
        "storage_backend": config.STORAGE_BACKEND,
        "job_backend": config.JOB_BACKEND,
        "auth_mode": config.AUTH_MODE,
        "checks": {},
    }

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        report["checks"]["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        report["checks"]["database"] = f"FAIL: {exc}"

    try:
        report["checks"]["storage"] = "ok" if get_storage().health() else "FAIL: unhealthy"
    except Exception as exc:  # noqa: BLE001
        report["checks"]["storage"] = f"FAIL: {exc}"

    try:
        dispatcher = get_dispatcher()
        report["checks"]["queue"] = "ok" if dispatcher.health() else "FAIL: unhealthy"
        report["checks"]["queue_durable"] = getattr(dispatcher, "durable", False)
    except Exception as exc:  # noqa: BLE001
        report["checks"]["queue"] = f"FAIL: {exc}"

    try:
        report["checks"]["ffmpeg"] = ffmpeg.ffmpeg_bin()
        report["checks"]["ffprobe"] = ffmpeg.ffprobe_bin()
    except Exception as exc:  # noqa: BLE001
        report["checks"]["ffmpeg"] = f"FAIL: {exc}"

    # A production deployment on the local backends is almost certainly a
    # misconfiguration: neither survives a container restart.
    warnings = []
    if config.IS_PRODUCTION and config.STORAGE_BACKEND == "local":
        warnings.append("STORAGE_BACKEND=local in production: worker disks are ephemeral.")
    if config.IS_PRODUCTION and config.JOB_BACKEND == "local":
        warnings.append("JOB_BACKEND=local in production: jobs are lost on restart.")
    if config.IS_PRODUCTION and config.AUTH_MODE == "legacy":
        warnings.append("AUTH_MODE=legacy in production: Supabase Auth is the intended source.")
    report["warnings"] = warnings

    _print(report)
    failed = any(str(v).startswith("FAIL") for v in report["checks"].values())
    return 1 if failed or warnings else 0


def cmd_reconcile(args) -> int:
    """Compare video_assets against what the buckets actually hold."""
    from app.db.session import SessionLocal
    from app.services import reconcile_service

    with SessionLocal() as db:
        report = reconcile_service.reconcile(
            db, user_id=args.user, dry_run=not args.apply,
            delete_orphans=args.delete_orphans,
        )
    _print(report.as_dict())
    if not args.apply:
        print("\n(dry run — pass --apply to write corrections)", file=sys.stderr)
    return 0 if report.as_dict()["healthy"] else 2


def cmd_stuck(args) -> int:
    """Videos parked in an in-flight state with no live lease behind them."""
    from app.db.session import SessionLocal
    from app.jobs.handlers import requeue_stalled
    from app.services import reconcile_service

    with SessionLocal() as db:
        rows = reconcile_service.find_stuck_videos(db, older_than_minutes=args.minutes)
        _print({"stuck_videos": rows, "count": len(rows)})
        if args.requeue and rows:
            print(f"\nrequeued {requeue_stalled(db)} stalled run(s)", file=sys.stderr)
    return 0 if not rows else 2


def cmd_retention(args) -> int:
    """Originals past their retention window whose derived assets are verified."""
    from app.db.session import SessionLocal
    from app.services import deletion_service

    with SessionLocal() as db:
        actions = deletion_service.apply_retention(db, dry_run=not args.apply)
    _print({"candidates": actions, "count": len(actions), "applied": bool(args.apply)})
    if not args.apply:
        print("\n(dry run — pass --apply to delete)", file=sys.stderr)
    return 0


def cmd_stale_assets(args) -> int:
    """Derived assets whose transform version no longer matches configuration.
    They are reproducible, so they can be deleted and regenerated."""
    from app.db.session import SessionLocal
    from app.services import reconcile_service

    with SessionLocal() as db:
        rows = reconcile_service.find_stale_derived(db)
    _print({"stale_assets": rows, "count": len(rows)})
    return 0


def cmd_capacity(args) -> int:
    """Measured throughput, for sizing the worker fleet.

    Answers "how many workers do we need" from recorded runs rather than from
    a guess, and shows whether a pipeline release changed the cost per minute
    of footage.
    """
    from sqlalchemy import func
    from app.db.session import SessionLocal
    from app.models.runs import AnalysisRun, SUCCEEDED

    with SessionLocal() as db:
        runs = (
            db.query(AnalysisRun)
            .filter(AnalysisRun.status == SUCCEEDED, AnalysisRun.metrics.isnot(None))
            .order_by(AnalysisRun.completed_at.desc())
            .limit(args.limit).all()
        )
        factors, by_version = [], {}
        for run in runs:
            rf = (run.metrics or {}).get("realtime_factor")
            if rf:
                factors.append(rf)
                by_version.setdefault(run.pipeline_version, []).append(rf)

        pending = db.query(func.count(AnalysisRun.id)).filter(
            AnalysisRun.status.in_(("pending", "claimed", "running"))).scalar()

    if not factors:
        _print({"note": "no completed runs with metrics yet", "pending_runs": pending})
        return 0

    ordered = sorted(factors)
    p50 = ordered[len(ordered) // 2]
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    _print({
        "samples": len(ordered),
        "realtime_factor": {"p50": round(p50, 3), "p95": round(p95, 3),
                            "max": round(ordered[-1], 3)},
        "by_pipeline_version": {
            v: round(sum(f) / len(f), 3) for v, f in by_version.items()
        },
        "pending_runs": pending,
        "note": (
            "realtime_factor is compute-seconds per second of footage. "
            "One worker sustains roughly 3600/(p95 * avg_match_seconds) matches per hour."
        ),
    })
    return 0


def cmd_queue(args) -> int:
    from app.jobs import get_dispatcher

    dispatcher = get_dispatcher()
    if args.ensure and hasattr(dispatcher, "ensure_queues"):
        dispatcher.ensure_queues()
        print("queues ensured", file=sys.stderr)
    _print({
        "backend": getattr(dispatcher, "backend", "?"),
        "durable": getattr(dispatcher, "durable", False),
        "depth": dispatcher.depth(),
        "healthy": dispatcher.health(),
    })
    return 0


def cmd_usage(args) -> int:
    from app.db.session import SessionLocal
    from app.services import usage_service

    with SessionLocal() as db:
        if args.recalculate:
            usage_service.recalculate(db, args.user)
            db.commit()
        _print(usage_service.snapshot(db, args.user))
    return 0


def cmd_purge_video(args) -> int:
    from app.db.session import SessionLocal
    from app.models.video import Video
    from app.services import deletion_service

    with SessionLocal() as db:
        video = db.get(Video, args.video)
        if video is None:
            print(f"video {args.video} not found", file=sys.stderr)
            return 1
        if video.deleted_at is None:
            print("video is not tombstoned; purge refuses to touch a live video.",
                  file=sys.stderr)
            print("Delete it through the API first, or pass --force-tombstone.",
                  file=sys.stderr)
            if not args.force_tombstone:
                return 1
            deletion_service.soft_delete_video(db, video, enqueue_cleanup=False)
        if not args.apply:
            _print({"would_purge": args.video, "dry_run": True})
            return 0
        removed = deletion_service.purge_video_objects(db, args.video)
    _print({"purged": args.video, "objects_removed": removed})
    return 0


def cmd_delete_account(args) -> int:
    from app.db.session import SessionLocal
    from app.models.video import Video
    from app.services import deletion_service

    if not args.apply:
        with SessionLocal() as db:
            count = db.query(Video).filter_by(owner_user_id=args.user).count()
        _print({"user_id": args.user, "videos_that_would_be_deleted": count, "dry_run": True})
        print("\n(dry run — pass --apply to erase)", file=sys.stderr)
        return 0

    with SessionLocal() as db:
        summary = deletion_service.delete_account(db, args.user)
    _print({"user_id": args.user, **summary, "applied": True})
    return 0


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="manage.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check database, storage, queue and ffmpeg").set_defaults(fn=cmd_doctor)

    p = sub.add_parser("reconcile", help="compare asset rows against object storage")
    p.add_argument("--user", help="limit to one user (much cheaper)")
    p.add_argument("--apply", action="store_true", help="write corrections")
    p.add_argument("--delete-orphans", action="store_true",
                   help="also delete objects with no asset row (requires --apply)")
    p.set_defaults(fn=cmd_reconcile)

    p = sub.add_parser("stuck", help="find videos stuck in an in-flight state")
    p.add_argument("--minutes", type=int, default=60)
    p.add_argument("--requeue", action="store_true", help="return stalled runs to the queue")
    p.set_defaults(fn=cmd_stuck)

    p = sub.add_parser("retention", help="originals past their retention window")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_retention)

    sub.add_parser("stale-assets", help="derived assets from an outdated transform").set_defaults(fn=cmd_stale_assets)

    p = sub.add_parser("capacity", help="measured throughput, for sizing the worker fleet")
    p.add_argument("--limit", type=int, default=200, help="how many recent runs to sample")
    p.set_defaults(fn=cmd_capacity)

    p = sub.add_parser("queue", help="queue depth and health")
    p.add_argument("--ensure", action="store_true", help="create the queues if absent")
    p.set_defaults(fn=cmd_queue)

    p = sub.add_parser("usage", help="per-user storage accounting")
    p.add_argument("--user", required=True)
    p.add_argument("--recalculate", action="store_true", help="recount from video_assets")
    p.set_defaults(fn=cmd_usage)

    p = sub.add_parser("purge-video", help="delete a tombstoned video's objects and rows")
    p.add_argument("--video", required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--force-tombstone", action="store_true",
                   help="tombstone first if it is still live (use with care)")
    p.set_defaults(fn=cmd_purge_video)

    p = sub.add_parser("delete-account", help="erase an account and all its data")
    p.add_argument("--user", required=True)
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_delete_account)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
