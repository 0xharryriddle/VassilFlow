# Runtime Readiness Runbook

## Frontend

- Run `pnpm.cmd typecheck`.
- Run `pnpm.cmd lint`.
- Run `pnpm.cmd exec rstest run`.
- Smoke the homepage and workspace demo routes.

## Backend

- Run backend unit tests.
- Run the doctor/setup related tests.
- Verify runtime paths resolve under `.vassilflow`.

## Static Demo Integrity

- `frontend/public/demo/threads` contains only VassilFlow-native demos.
- `DEMO_THREAD_IDS` matches existing demo directories.
- Each artifact path resolves to a real file under `user-data/outputs`.

## Go Criteria

- No user-facing inherited identity in landing or static demos.
- Readiness checks pass.
- Remaining legacy references are explicitly classified as migration compatibility or tests.
