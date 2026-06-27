# Upstream Provenance

VassilFlow began from an upstream open-source agent runtime and now maintains its
own product identity, package namespace, runtime paths, and harness direction.

The active VassilFlow codebase uses `vassilflow.*` as the canonical Python
package namespace. Legacy names such as `DEER_FLOW_*`, `.deer-flow`,
`deerflow.db`, and `X-DeerFlow-*` remain only as migration fallbacks for
existing checkouts, persisted data, and deployment environments.

Historical planning notes, migration documents, and compatibility comments may
still mention the upstream project when they explain provenance, bug history, or
why a legacy alias exists. New product documentation and runtime examples should
prefer VassilFlow-owned names.
