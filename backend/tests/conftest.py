"""Test configuration for the backend test suite.

Sets up import paths and fixtures shared by the backend tests.
"""

from __future__ import annotations

import errno
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Make 'app' and 'vassilflow' importable from any working directory
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))


@pytest.fixture()
def symlink_or_skip():
    """Create a symlink or skip when the host does not grant that capability."""

    def create(
        link: Path,
        target: Path,
        *,
        target_is_directory: bool = False,
    ) -> None:
        try:
            link.symlink_to(target, target_is_directory=target_is_directory)
        except NotImplementedError as exc:
            pytest.skip(f"symlinks are not available on this platform: {exc}")
        except OSError as exc:
            unavailable = (
                exc.errno
                in {
                    errno.EACCES,
                    errno.EPERM,
                    errno.ENOTSUP,
                }
                or getattr(exc, "winerror", None) == 1314
            )
            if unavailable:
                pytest.skip(f"symlink creation requires host support or elevated privileges: {exc}")
            raise

    return create


@pytest.fixture(autouse=True)
def _disable_auth_bypass_by_default(monkeypatch):
    """Keep local auth-bypass settings from changing the backend test baseline."""
    monkeypatch.setenv("VASSILFLOW_AUTH_DISABLED", "0")


@pytest.fixture()
def provisioner_module():
    """Load docker/provisioner/app.py as an importable test module.

    Shared by test_provisioner_kubeconfig and test_provisioner_pvc_volumes so
    that any change to the provisioner entry-point path or module name only
    needs to be updated in one place.
    """
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "docker" / "provisioner" / "app.py"
    spec = importlib.util.spec_from_file_location("provisioner_app_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Auto-set user context for every test unless marked no_auto_user
# ---------------------------------------------------------------------------
#
# Repository methods read ``user_id`` from a contextvar by default
# (see ``vassilflow.runtime.user_context``). Without this fixture, every
# pre-existing persistence test would raise RuntimeError because the
# contextvar is unset. The fixture sets a default test user on every
# test; tests that explicitly want to verify behaviour *without* a user
# context should mark themselves ``@pytest.mark.no_auto_user``.


@pytest.fixture(autouse=True)
def _reset_skill_storage_singleton():
    """Reset the SkillStorage singleton between tests to prevent cross-test contamination."""
    try:
        from vassilflow.skills.storage import reset_skill_storage
    except ImportError:
        yield
        return
    reset_skill_storage()
    try:
        yield
    finally:
        reset_skill_storage()


@pytest.fixture(autouse=True)
def _restore_title_config_singleton():
    """Reset ``_title_config`` to its pristine default after every test.

    ``AppConfig.from_file()`` writes the on-disk ``title`` block into the
    module-level singleton (``config/app_config.py`` calls
    ``load_title_config_from_dict``). Any test that loads the real
    ``config.yaml`` therefore leaves the singleton in a state that
    ``test_title_middleware_core_logic.py`` does not expect; that suite
    relies on the pristine ``TitleConfig()`` default (``enabled=True``).
    We restore the default after every test so test files stay
    independent regardless of order.
    """
    try:
        from vassilflow.config.title_config import reset_title_config
    except ImportError:
        yield
        return

    try:
        yield
    finally:
        reset_title_config()


@pytest.fixture(autouse=True)
def _auto_user_context(request):
    """Inject a default ``test-user-autouse`` into the contextvar.

    Opt-out via ``@pytest.mark.no_auto_user``. Uses lazy import so that
    tests which don't touch the persistence layer never pay the cost
    of importing runtime.user_context.
    """
    if request.node.get_closest_marker("no_auto_user"):
        yield
        return

    try:
        from vassilflow.runtime.user_context import (
            reset_current_user,
            set_current_user,
        )
    except ImportError:
        yield
        return

    user = SimpleNamespace(id="test-user-autouse", email="test@local")
    token = set_current_user(user)
    try:
        yield
    finally:
        reset_current_user(token)


@pytest.fixture
def sample_builtin_registry(monkeypatch):
    """Install a sample domain only in tests exercising curated Agent contracts."""
    from sample_agent_fixture import SAMPLE_AGENT

    from vassilflow.config import builtin_agents

    monkeypatch.setattr(builtin_agents, "_BUILTIN_AGENTS", (SAMPLE_AGENT,))
    monkeypatch.setattr(builtin_agents, "_BUILTIN_AGENTS_BY_NAME", {SAMPLE_AGENT.name: SAMPLE_AGENT})
