"""Validity of the Vercel deployment config.

Vercel validates `vercel.json` against a strict schema BEFORE the build runs.
An unknown property fails the deployment with no build logs at all, which is a
genuinely confusing failure — it looks like an infrastructure outage rather
than a typo. Both mistakes below have already caused a red deployment on this
project, so they are pinned here where they cost seconds instead of a push.
"""
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
VERCEL_JSON = REPO / "vercel.json"

# Per Vercel's published schema.
ALLOWED_TOP_LEVEL = {
    "$schema", "buildCommand", "cleanUrls", "crons", "devCommand", "env",
    "framework", "functions", "git", "github", "headers", "ignoreCommand",
    "images", "installCommand", "outputDirectory", "public", "redirects",
    "regions", "rewrites", "trailingSlash",
}
ALLOWED_REWRITE_KEYS = {"source", "destination", "has", "missing"}
ALLOWED_HEADER_KEYS = {"source", "headers", "has", "missing"}


@pytest.fixture(scope="module")
def config():
    if not VERCEL_JSON.exists():
        pytest.skip("vercel.json not present")
    return json.loads(VERCEL_JSON.read_text())


def test_is_valid_json(config):
    assert isinstance(config, dict)


def test_no_comment_keys_anywhere(config):
    """JSON has no comments. A `"//"` key fails schema validation, and the
    deployment then dies before producing a single build log line."""
    offenders = []

    def walk(node, path="root"):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "//":
                    offenders.append(path)
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    walk(config)
    assert not offenders, (
        "vercel.json contains pseudo-comment keys, which fail schema "
        f"validation before the build starts: {offenders}"
    )


def test_only_known_top_level_properties(config):
    unknown = set(config) - ALLOWED_TOP_LEVEL
    assert not unknown, f"unknown top-level vercel.json properties: {unknown}"


def test_rewrite_and_header_entries_use_known_keys(config):
    for i, rule in enumerate(config.get("rewrites", [])):
        unknown = set(rule) - ALLOWED_REWRITE_KEYS
        assert not unknown, f"rewrites[{i}] has unknown keys: {unknown}"
    for i, rule in enumerate(config.get("headers", [])):
        unknown = set(rule) - ALLOWED_HEADER_KEYS
        assert not unknown, f"headers[{i}] has unknown keys: {unknown}"


def test_spa_rewrite_does_not_swallow_api_calls(config):
    """A true catch-all answers /api/v1/* with index.html and a 200.

    A missing backend then looks like a working one returning HTML, and every
    API call fails as a JSON parse error at a call site that appears to have
    succeeded. This is the single most confusing way to misconfigure this app.
    """
    rewrites = config.get("rewrites", [])
    fallbacks = [r for r in rewrites if r.get("destination") == "/index.html"]
    assert fallbacks, "no SPA history fallback: deep links would 404"

    for rule in fallbacks:
        source = rule["source"]
        assert "api/" in source and "?!" in source, (
            f"SPA fallback {source!r} does not exclude api/ — it will answer "
            "API calls with index.html and a 200"
        )


def test_build_output_points_at_the_vite_build(config):
    """The project uses Vite. A stale create-react-app preset in Vercel's
    dashboard once made this deploy run `react-scripts build`, which exists
    nowhere in this repository."""
    assert config.get("framework") is None, (
        "framework must be null so it overrides any dashboard preset"
    )
    assert config.get("outputDirectory") == "frontend/dist"
    assert "npm run build" in config.get("buildCommand", "")


def test_assets_are_cached_immutably_and_index_is_not(config):
    rules = {r["source"]: r for r in config.get("headers", [])}
    assets = rules.get("/assets/(.*)")
    index = rules.get("/index.html")
    assert assets and index, "expected cache rules for /assets and /index.html"

    def cache_value(rule):
        return next(h["value"] for h in rule["headers"] if h["key"] == "Cache-Control")

    assert "immutable" in cache_value(assets), "content-hashed assets should cache hard"
    assert "max-age=0" in cache_value(index), (
        "index.html must not be cached: it names the current asset hashes"
    )
