# Upstream Provenance

VassilFlow began from an upstream open-source agent runtime and now maintains its
own product identity, package namespace, runtime paths, and harness direction.

The active VassilFlow codebase uses `vassilflow.*` as the canonical Python
package namespace. Runtime configuration, local state, database files, HTTP
headers, Docker names, and public documentation should use VassilFlow-owned
names exclusively.

Historical planning notes may still explain provenance when that context is
useful, but runtime examples and user-facing documentation should not depend on
upstream names.
