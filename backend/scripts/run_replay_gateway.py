"""Start a hermetic *replay* gateway for the full-stack (Layer 2) e2e.

Builds an ephemeral config that points the model at ``ReplayChatModel`` + a
recorded fixture, then runs uvicorn — no API key, deterministic. Used as a
Playwright ``webServer`` (see ``frontend/playwright.real-backend.config.ts``) and
runnable standalone for debugging::

    uv run python scripts/run_replay_gateway.py --port 8011

``tests/`` is put on the path so the config ``use: replay_provider:ReplayChatModel``
resolves; ``GATEWAY_CORS_ORIGINS`` is set so the frontend on :3000 can talk to it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "tests"))  # replay_provider + build_config_yaml live here

_DEFAULT_FIXTURES = (_BACKEND / "tests" / "fixtures" / "replay" / "write_read_file.ultra.json",)


def _set_hermetic_runtime_env(home: Path, cfg: Path, extensions_cfg: Path) -> None:
    os.environ["VASSILFLOW_HOME"] = str(home)
    os.environ["VASSILFLOW_CONFIG_PATH"] = str(cfg)
    os.environ["VASSILFLOW_EXTENSIONS_CONFIG_PATH"] = str(extensions_cfg)


def _combine_fixtures(paths: list[Path], output_path: Path) -> Path:
    turns: list[dict] = []
    hash_owners: dict[str, Path] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fixture_turns = payload.get("turns")
        if not isinstance(fixture_turns, list) or not fixture_turns:
            raise ValueError(f"Replay fixture has no turns: {path}")
        for turn in fixture_turns:
            input_hash = turn.get("input_hash") if isinstance(turn, dict) else None
            if not isinstance(input_hash, str) or not input_hash:
                raise ValueError(f"Replay fixture turn has no input_hash: {path}")
            owner = hash_owners.get(input_hash)
            if owner is not None and owner != path:
                raise ValueError(f"Replay fixtures have an ambiguous input hash: {input_hash} appears in {owner} and {path}")
            hash_owners[input_hash] = path
            turns.append(turn)
    output_path.write_text(
        json.dumps(
            {
                "scenario": "combined-replay-gateway",
                "fixtures": [path.name for path in paths],
                "turns": turns,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument(
        "--fixture",
        dest="fixtures",
        action="append",
        help="Replay fixture to load; repeat for multiple scenarios",
    )
    parser.add_argument("--cors", default="http://localhost:3000")
    args = parser.parse_args()

    from _replay_fixture import (
        REPLAY_MODEL_BLOCK,
        build_config_yaml,
        prepare_hermetic_extras,
    )

    home = Path(tempfile.mkdtemp(prefix="replay-gw-"))
    fixture_paths = [Path(value).resolve() for value in args.fixtures] if args.fixtures else list(_DEFAULT_FIXTURES)
    fixture_path = _combine_fixtures(
        fixture_paths,
        home / "combined-replay-fixture.json",
    )
    cfg = home / "config.yaml"
    cfg.write_text(
        build_config_yaml(
            model_block=REPLAY_MODEL_BLOCK,
            home=home,
        ),
        encoding="utf-8",
    )

    # Override (not setdefault): the replay gateway must be hermetic, so outer
    # runtime env vars can't leak in and shift prompt-affecting paths/skills.
    _set_hermetic_runtime_env(home, cfg, prepare_hermetic_extras(home))
    os.environ["VASSILFLOW_REPLAY_FIXTURE"] = str(fixture_path)
    os.environ.setdefault(
        "AUTH_JWT_SECRET",
        "ci-replay-secret-for-hermetic-tests",
    )
    os.environ["GATEWAY_CORS_ORIGINS"] = args.cors
    # Child / dynamic imports (resolve_class) search PYTHONPATH too.
    os.environ["PYTHONPATH"] = os.pathsep.join(p for p in (str(_BACKEND), str(_BACKEND / "tests"), os.environ.get("PYTHONPATH", "")) if p)

    import uvicorn

    target: str | object = "app.gateway.app:app"
    # Test-only: attach the run/message seeder used by the multi-run render-order
    # e2e (#3352). Imported from tests/ and mounted here only — never in the
    # production app. Pass the app object (not the import string) so the extra
    # router is registered before uvicorn serves it.
    if os.environ.get("VASSILFLOW_ENABLE_TEST_SEED") == "1":
        from seed_runs_router import router as seed_router

        from app.gateway.app import app as gateway_app

        gateway_app.include_router(seed_router)
        target = gateway_app
        print(
            "[replay-gw] test-only seed routers mounted under /api/test-only",
            flush=True,
        )

    print(
        f"[replay-gw] config={cfg} fixtures={[path.name for path in fixture_paths]} cors={args.cors} port={args.port}",
        flush=True,
    )
    uvicorn.run(target, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
