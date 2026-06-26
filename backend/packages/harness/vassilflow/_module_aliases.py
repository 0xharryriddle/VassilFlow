"""Lazy import aliases for VassilFlow facade module paths."""

from __future__ import annotations

import sys
from importlib import import_module
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
from importlib.util import find_spec, spec_from_loader

_PACKAGE_ALIAS_ROOTS = {
    "community",
    "guardrails",
    "mcp",
    "models",
    "persistence",
    "reflection",
    "sandbox",
    "skills",
    "subagents",
    "tools",
    "tracing",
    "uploads",
    "utils",
}

_REAL_FACADE_ROOTS_WITH_DEEP_ALIASES = {"agents", "config"}


def _target_module_name(fullname: str) -> str | None:
    prefix = "vassilflow."
    if not fullname.startswith(prefix):
        return None

    suffix = fullname[len(prefix) :]
    root, separator, _rest = suffix.partition(".")
    if root in _PACKAGE_ALIAS_ROOTS:
        return f"deerflow.{suffix}"
    if root in _REAL_FACADE_ROOTS_WITH_DEEP_ALIASES and separator:
        return f"deerflow.{suffix}"
    return None


class _VassilFlowAliasImporter(MetaPathFinder, Loader):
    """Resolve implementation-deep ``vassilflow.*`` imports to ``deerflow.*``."""

    def find_spec(
        self,
        fullname: str,
        path: object | None = None,
        target: object | None = None,
    ) -> ModuleSpec | None:
        target_name = _target_module_name(fullname)
        if target_name is None:
            return None

        target_spec = find_spec(target_name)
        if target_spec is None:
            return None

        is_package = target_spec.submodule_search_locations is not None
        spec = spec_from_loader(fullname, self, is_package=is_package)
        if spec is None:
            return None
        spec.loader_state = {"target_name": target_name}
        spec.origin = target_spec.origin
        if is_package:
            spec.submodule_search_locations = list(target_spec.submodule_search_locations or [])
        return spec

    def create_module(self, spec: ModuleSpec) -> object:
        target_name = spec.loader_state["target_name"]
        module = import_module(target_name)
        sys.modules[spec.name] = module
        return module

    def exec_module(self, module: object) -> None:
        return None


def install_vassilflow_module_aliases() -> None:
    """Install the VassilFlow facade import aliaser once per process."""

    if any(isinstance(finder, _VassilFlowAliasImporter) for finder in sys.meta_path):
        return
    sys.meta_path.insert(0, _VassilFlowAliasImporter())
