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


def test_smoke_test_skill_uses_vassilflow_identity():
    skill_path = REPO_ROOT / ".agent" / "skills" / "smoke-test" / "SKILL.md"
    metadata = _frontmatter(skill_path)
    body = skill_path.read_text(encoding="utf-8")
    docker_template = (
        REPO_ROOT
        / ".agent"
        / "skills"
        / "smoke-test"
        / "templates"
        / "report.docker.template.md"
    ).read_text(encoding="utf-8")

    assert "VassilFlow" in metadata["description"]
    assert "# VassilFlow Smoke Test Skill" in body
    assert "VassilFlow Smoke Test Report" in docker_template
    assert "vassilflow-nginx" in docker_template
    assert "deer-flow-nginx" not in docker_template


def test_smoke_test_scripts_detect_vassilflow_and_legacy_names():
    health_check = (
        REPO_ROOT / ".agent" / "skills" / "smoke-test" / "scripts" / "health_check.sh"
    ).read_text(encoding="utf-8")
    check_docker = (
        REPO_ROOT / ".agent" / "skills" / "smoke-test" / "scripts" / "check_docker.sh"
    ).read_text(encoding="utf-8")

    assert "vassilflow_containers_running()" in health_check
    assert "vassilflow|deer-flow|deerflow" in health_check
    assert "vassilflow_process_found" in check_docker
    assert "*[Vv]assil[Ff]low*" in check_docker
    assert "*[Dd]eer[Ff]low*" in check_docker


def test_blocking_io_guard_skill_uses_vassilflow_paths_and_scope():
    skill_path = REPO_ROOT / ".agent" / "skills" / "blocking-io-guard" / "SKILL.md"
    reference_path = (
        REPO_ROOT
        / ".agent"
        / "skills"
        / "blocking-io-guard"
        / "references"
        / "good-anchor-rules.md"
    )
    metadata = _frontmatter(skill_path)
    body = skill_path.read_text(encoding="utf-8")
    reference = reference_path.read_text(encoding="utf-8")

    assert "packages/harness/vassilflow/" in metadata["description"]
    assert "VassilFlow's blocking-IO CI gate" in body
    assert ".vassilflow/blocking-io-findings.json" in body
    assert ".deer-flow/blocking-io-findings.json" not in body
    assert "`vassilflow.*`" in reference


def test_public_frontend_design_skill_uses_vassilflow_branding():
    body = (REPO_ROOT / "skills" / "public" / "frontend-design" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "Created By VassilFlow" in body
    assert "https://github.com/linhlln1104/VassilFlow" in body
    assert "Created By Deerflow" not in body
    assert "https://deerflow.tech" not in body


def test_public_github_deep_research_template_uses_vassilflow_identity():
    template = (
        REPO_ROOT
        / "skills"
        / "public"
        / "github-deep-research"
        / "assets"
        / "report_template.md"
    ).read_text(encoding="utf-8")

    assert "Github Deep Research by VassilFlow" in template
    assert "Github Deep Research by DeerFlow" not in template


def test_public_slr_skill_uses_vassilflow_runtime_branding():
    skill_body = (
        REPO_ROOT / "skills" / "public" / "systematic-literature-review" / "SKILL.md"
    ).read_text(encoding="utf-8")
    search_script = (
        REPO_ROOT
        / "skills"
        / "public"
        / "systematic-literature-review"
        / "scripts"
        / "arxiv_search.py"
    ).read_text(encoding="utf-8")

    assert "The VassilFlow runtime enforces `MAX_CONCURRENT_SUBAGENTS = 3`" in skill_body
    assert "what VassilFlow users most often want to survey" in skill_body
    assert "vassilflow-slr-skill/0.1" in search_script
    assert "The DeerFlow runtime enforces" not in skill_body
    assert "deerflow-slr-skill/0.1" not in search_script
