# Deployment Checklist

## Runtime

- `VASSILFLOW_HOME` is configured.
- Gateway internal auth token is present in production.
- Sandbox provider is selected explicitly.

## Frontend

- Landing page renders VassilFlow-native copy.
- Workspace static demos load without inherited showcase data.
- Artifact panel can open generated files.

## Backend

- Config upgrade scripts prefer VassilFlow names.
- Runtime directories are scoped by user and thread.
- Readiness checks pass before deployment.
