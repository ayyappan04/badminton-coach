"""Configuration-dependent safety behaviour.

These run the app in a subprocess with different environment variables,
because `app.core.config` resolves its settings at import time and the rest
of the suite has already imported it.
"""
import os
import subprocess
import sys
import textwrap
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
    repo = BACKEND_DIR.parent
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
