"""Versioned trusted capability inputs carried in runtime context."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

CAPABILITY_INPUT_SCHEMA = "vassilflow.capability_input.v1"
CAPABILITY_INPUTS_CONTEXT_KEY = "capability_inputs"
MAX_CAPABILITY_INPUTS = 8

_KEY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_ENVELOPE_FIELDS = frozenset({"schema", "capability", "kind", "payload"})


class CapabilityContextError(ValueError):
    """Server-owned capability context is malformed or ambiguous."""


def trusted_capability_payload(
    context: Any,
    *,
    capability: str,
    kind: str,
) -> dict[str, Any] | None:
    """Return one validated trusted payload from runtime context."""

    if not isinstance(context, Mapping):
        return None
    raw_inputs = context.get(CAPABILITY_INPUTS_CONTEXT_KEY)
    if raw_inputs is None:
        return None
    if not isinstance(raw_inputs, list) or len(raw_inputs) > MAX_CAPABILITY_INPUTS:
        raise CapabilityContextError("Trusted capability inputs are invalid")

    match: dict[str, Any] | None = None
    seen: set[tuple[str, str]] = set()
    for raw in raw_inputs:
        if (
            not isinstance(raw, Mapping)
            or set(raw) != _ENVELOPE_FIELDS
            or raw.get("schema") != CAPABILITY_INPUT_SCHEMA
            or not isinstance(raw.get("capability"), str)
            or _KEY_RE.fullmatch(raw["capability"]) is None
            or not isinstance(raw.get("kind"), str)
            or _KEY_RE.fullmatch(raw["kind"]) is None
            or not isinstance(raw.get("payload"), Mapping)
        ):
            raise CapabilityContextError("Trusted capability input envelope is invalid")
        identity = (raw["capability"], raw["kind"])
        if identity in seen:
            raise CapabilityContextError("Trusted capability input envelope is duplicated")
        seen.add(identity)
        if identity == (capability, kind):
            match = dict(raw["payload"])
    return match
