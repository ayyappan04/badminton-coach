# CI workflow

`ci.yml` here is the exact intended contents of `.github/workflows/ci.yml`.

It lives under `docs/ci/` because the credential used to push this branch did
not carry GitHub's `workflow` OAuth scope, so it could not create a file under
`.github/workflows/`. Nothing about the workflow itself is unusual — this is
purely a token-permission constraint.

## To activate it

Either grant the pushing token the `workflow` scope, or add the file directly
on GitHub, or run locally with a suitably scoped credential:

```bash
mkdir -p .github/workflows
cp docs/ci/ci.yml .github/workflows/ci.yml
git add .github/workflows/ci.yml && git commit -m "Add CI workflow" && git push
```

## What it runs

| Job | Steps |
|---|---|
| `backend` | install → pytest (98 tests) → pip-audit (advisory) → bandit (fails on medium+) |
| `frontend` | npm ci → tsc typecheck → oxlint → npm audit (fails on high) → build |
| `secrets` | gitleaks over full history |
