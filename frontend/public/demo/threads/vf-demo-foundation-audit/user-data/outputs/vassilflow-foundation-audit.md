# VassilFlow Foundation Audit

## Goal

Make VassilFlow read as a standalone superagent harness, with no user-facing reliance on inherited project identity.

## Residue Classes

- User-facing residue: landing copy, static demos, public assets, workspace examples.
- Runtime residue: compatibility aliases, migration scripts, old state-directory handling.
- Test residue: assertions that prove legacy names do not leak into new behavior.

## Cleanup Rules

- VassilFlow names are canonical in UI, config, scripts, and docs.
- Legacy compatibility is acceptable only when it is explicit migration behavior.
- Static demos must show VassilFlow harness workflows rather than inherited showcase tasks.

## Readiness Gates

- Frontend typecheck, lint, unit tests, and homepage smoke.
- Backend unit tests and formatting checks.
- Search audit for inherited identity, legacy demo text, and old static assets.
