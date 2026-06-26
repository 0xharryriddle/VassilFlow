"""Static coverage for repository-owned agent skill metadata."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _frontmatter(path: Path) -> dict:
    content = path.read_text(encoding="utf-8")
    _prefix, metadata, _body = content.split("---", 2)
    return yaml.safe_load(metadata)


def test_maintainer_orchestrator_skill_uses_vassilflow_identity():
    skill_path = REPO_ROOT / ".agent" / "skills" / "vassilflow-maintainer-orchestrator" / "SKILL.md"
    legacy_path = REPO_ROOT / ".agent" / "skills" / "deerflow-maintainer-orchestrator"

    assert skill_path.exists()
    assert not legacy_path.exists()

    metadata = _frontmatter(skill_path)
    assert metadata["name"] == "vassilflow-maintainer-orchestrator"
    assert "VassilFlow maintainer" in metadata["description"]
    assert "DeerFlow maintainer" not in metadata["description"]


def test_maintainer_orchestrator_design_links_vassilflow_skill():
    content = (REPO_ROOT / "docs" / "agents" / "maintainer-orchestrator-design.md").read_text(
        encoding="utf-8"
    )

    assert ".agent/skills/vassilflow-maintainer-orchestrator/SKILL.md" in content
    assert "deerflow-maintainer-orchestrator" not in content


def test_public_claude_skill_uses_vassilflow_identity():
    skill_path = REPO_ROOT / "skills" / "public" / "claude-to-vassilflow" / "SKILL.md"
    legacy_path = REPO_ROOT / "skills" / "public" / "claude-to-deerflow"

    assert skill_path.exists()
    assert not legacy_path.exists()

    metadata = _frontmatter(skill_path)
    assert metadata["name"] == "claude-to-vassilflow"
    assert "VassilFlow" in metadata["description"]


def test_readme_documents_public_claude_vassilflow_skill():
    content = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "claude-to-vassilflow" in content
    assert "skills/public/claude-to-vassilflow/SKILL.md" in content
    assert "claude-to-deerflow" not in content
