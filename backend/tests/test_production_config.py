"""Configuration-dependent safety behaviour.

These run the app in a subprocess with different environment variables,
because `app.core.config` resolves its settings at import time and the rest
of the suite has already imported it.
"""
import os
import subprocess
import sys
import textwrap

import pytest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _run(script: str, env_overrides: dict):
    env = {**os.environ, **env_overrides}
    # Ensure the child does not inherit the suite's test secret unless asked.
    for key in ("JWT_SECRET", "DATABASE_URL", "STORAGE_DIR", "REQUIRE_EMAIL_VERIFICATION"):
        if key not in env_overrides:
            env.pop(key, None)
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=180,
    )


def test_production_refuses_to_start_without_jwt_secret(tmp_path):
    """The old hardcoded fallback secret made every token forgeable. In
    production the app must now refuse to boot rather than use it."""
    result = _run(
        "import app.core.config as c; print('STARTED', c.JWT_SECRET)",
        {
            "APP_ENV": "production",
            "DATABASE_URL": f"sqlite:///{tmp_path/'p.db'}",
            "STORAGE_DIR": str(tmp_path / "storage"),
        },
    )
    assert result.returncode != 0, f"production started without a JWT secret: {result.stdout}"
    assert "JWT_SECRET" in (result.stderr + result.stdout)
    assert "STARTED" not in result.stdout


def test_production_refuses_the_known_development_secret(tmp_path):
    result = _run(
        "import app.core.config as c; print('STARTED')",
        {
            "APP_ENV": "production",
            "JWT_SECRET": "dev-secret-change-in-production",
            "DATABASE_URL": f"sqlite:///{tmp_path/'p2.db'}",
            "STORAGE_DIR": str(tmp_path / "storage2"),
        },
    )
    assert result.returncode != 0, "the published development secret was accepted in production"


def test_production_starts_with_a_real_secret(tmp_path):
    result = _run(
        "import app.core.config as c; assert not c.__dict__.get('_x'); print('STARTED')",
        {
            "APP_ENV": "production",
            "JWT_SECRET": "b8f1c2d3e4a5968778695a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d",
            "DATABASE_URL": f"sqlite:///{tmp_path/'p3.db'}",
            "STORAGE_DIR": str(tmp_path / "storage3"),
        },
    )
    assert result.returncode == 0, f"failed to start with a valid secret: {result.stderr[-800:]}"
    assert "STARTED" in result.stdout


def test_unverified_login_blocked_when_verification_required(tmp_path):
    """With REQUIRE_EMAIL_VERIFICATION=true, signup must not hand out a
    session and login must be refused until the address is verified."""
    script = """
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core.mailer import outbox

        c = TestClient(app)
        reg = c.post("/api/v1/auth/register", json={
            "email": "gate@example.com", "password": "CorrectHorse9!battery", "display_name": "G"})
        assert reg.status_code == 200, reg.text
        assert reg.json()["token"] is None, "session token issued before verification"
        assert reg.json()["email_verification_required"] is True

        pre = c.post("/api/v1/auth/login", json={
            "email": "gate@example.com", "password": "CorrectHorse9!battery"})
        assert pre.status_code == 403, f"unverified login allowed: {pre.status_code}"

        tok = outbox[-1]["token"]
        v = c.post("/api/v1/auth/verify-email", json={"token": tok})
        assert v.status_code == 200, v.text

        post = c.post("/api/v1/auth/login", json={
            "email": "gate@example.com", "password": "CorrectHorse9!battery"})
        assert post.status_code == 200, f"verified login refused: {post.status_code}"
        print("GATE_OK")
    """
    result = _run(script, {
        "APP_ENV": "development",
        "REQUIRE_EMAIL_VERIFICATION": "true",
        "JWT_SECRET": "test-secret-for-verification-gate-subprocess",
        "DATABASE_URL": f"sqlite:///{tmp_path/'gate.db'}",
        "STORAGE_DIR": str(tmp_path / "gate-storage"),
    })
    assert "GATE_OK" in result.stdout, f"stdout={result.stdout[-1500:]}\nstderr={result.stderr[-1500:]}"


def test_no_secrets_committed_to_the_repo():
    """Guard against a real credential being pasted into tracked source."""
    import shutil

    repo = BACKEND_DIR.parent
    # The container image ships neither git nor a .git directory (both are in
    # .dockerignore, deliberately). A scan that cannot run must skip, not pass
    # silently — a green tick from a test that did nothing is worse than a skip.
    if shutil.which("git") is None or not (repo / ".git").exists():
        pytest.skip("no git work tree here (e.g. inside the container image)")

    tracked = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True, text=True).stdout.split()
    suspicious = []
    needles = ("sk-ant-", "sk-live-", "AKIA", "-----BEGIN RSA PRIVATE KEY-----",
               "-----BEGIN OPENSSH PRIVATE KEY-----")
    self_rel = str(Path(__file__).resolve().relative_to(repo))
    for rel in tracked:
        # Skip this file: it necessarily contains the patterns it searches for.
        if rel == self_rel:
            continue
        f = repo / rel
        if not f.is_file() or f.suffix in {".png", ".jpg", ".svg", ".ico", ".mp4"}:
            continue
        try:
            text = f.read_text(errors="ignore")
        except Exception:
            continue
        for needle in needles:
            if needle in text:
                suspicious.append(f"{rel}: {needle}")
    assert not suspicious, f"possible secrets committed: {suspicious}"


def _run_module(code: str, env: dict):
    """Run a snippet in a fresh interpreter with a controlled environment.

    A subprocess is essential here: `app.core.config` reads the environment at
    import time, so the guard cannot be exercised in-process.
    """
    import os
    import subprocess
    import sys

    child = {**os.environ, **env, "PYTHONPATH": str(BACKEND_DIR)}
    # conftest sets JWT_SECRET for the whole test session, and it would be
    # inherited here — silently satisfying the very guard under test. Anything
    # the caller did not ask for explicitly is removed.
    for key in ("JWT_SECRET", "AUTH_MODE", "STORAGE_BACKEND", "JOB_BACKEND"):
        if key not in env:
            child.pop(key, None)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR, capture_output=True, text=True, env=child,
    )


def test_jwt_secret_required_only_when_legacy_tokens_are_accepted(tmp_path):
    """The production guard must protect the thing it is guarding.

    JWT_SECRET signs THIS application's own tokens. Under AUTH_MODE=supabase
    there are none — Supabase issues them and they are verified against its
    JWKS. Demanding the secret there fails a deployment over a value with no
    effect, which is exactly what happened on the first production deploy.
    """
    base = {
        "APP_ENV": "production",
        "DATABASE_URL": f"sqlite:///{tmp_path/'g.db'}",
        "STORAGE_DIR": str(tmp_path / "gs"),
    }
    probe = "from app.core import config; print('STARTED', bool(config.JWT_SECRET))"

    # legacy and dual both accept tokens we signed -> the secret is required.
    for mode in ("legacy", "dual"):
        result = _run_module(probe, {**base, "AUTH_MODE": mode})
        assert "STARTED" not in result.stdout, f"AUTH_MODE={mode} started without JWT_SECRET"
        assert "FATAL" in (result.stdout + result.stderr)

    # supabase-only -> no local tokens exist, so it must start.
    result = _run_module(probe, {**base, "AUTH_MODE": "supabase"})
    assert "STARTED True" in result.stdout, (
        f"supabase mode refused to start over an unused secret:\n{result.stderr[-800:]}"
    )

    # And a supplied secret is still honoured in every mode.
    result = _run_module(probe, {**base, "AUTH_MODE": "supabase",
                                 "JWT_SECRET": "a-real-secret-value-for-this-test"})
    assert "STARTED True" in result.stdout


def test_api_starts_even_when_the_database_is_unreachable(tmp_path):
    """A web service must boot and report degraded, not crash-loop.

    Import-time seeding used to connect to Postgres, so any database
    misconfiguration killed the process before it could serve /api/v1/ready —
    the endpoint whose entire purpose is explaining that class of failure.
    Diagnostics unavailable precisely when needed are not diagnostics.
    """
    probe = (
        "from fastapi.testclient import TestClient; from app.main import app; "
        "c = TestClient(app); "
        "h = c.get('/api/v1/health'); r = c.get('/api/v1/ready'); "
        "print('HEALTH', h.status_code); print('READY', r.status_code); "
        "print('DBREASON', (r.json().get('reasons') or {}).get('database', ''))"
    )
    result = _run_module(probe, {
        "APP_ENV": "production",
        "AUTH_MODE": "supabase",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_placeholder",
        # Points nowhere reachable.
        "DATABASE_URL": "postgresql://postgres:pw@127.0.0.1:1/postgres",
        "STORAGE_DIR": str(tmp_path / "s"),
        "CORS_ORIGINS": "https://example.com",
    })
    assert "HEALTH 200" in result.stdout, (
        "the process did not survive an unreachable database:\n"
        f"{result.stdout[-600:]}\n{result.stderr[-1200:]}"
    )
    assert "READY 503" in result.stdout, "readiness should report degraded"
    assert "DBREASON" in result.stdout and "check DATABASE_URL" in result.stdout


def test_ready_names_missing_configuration(tmp_path):
    """A blueprint prompts for several values and it is easy to leave one
    blank. The resulting failure otherwise appears somewhere unrelated."""
    probe = (
        "from fastapi.testclient import TestClient; from app.main import app; "
        "c = TestClient(app); r = c.get('/api/v1/ready'); "
        "print('CONFIG', (r.json().get('reasons') or {}).get('configuration', ''))"
    )
    result = _run_module(probe, {
        "APP_ENV": "production",
        "AUTH_MODE": "supabase",
        "STORAGE_BACKEND": "supabase",
        "SUPABASE_URL": "",
        "SUPABASE_SERVICE_ROLE_KEY": "",
        "DATABASE_URL": f"sqlite:///{tmp_path/'c.db'}",
        "STORAGE_DIR": str(tmp_path / "s"),
    })
    assert "SUPABASE_URL is empty" in result.stdout, result.stdout[-500:]
    assert "AUTH_MODE=supabase" in result.stdout
