"""Static coverage for VassilFlow-owned documentation surfaces."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_guardrails_docs_use_vassilflow_framework_identity():
    content = (REPO_ROOT / "backend" / "docs" / "GUARDRAILS.md").read_text(encoding="utf-8")

    assert "aport setup --framework vassilflow" in content
    assert "~/.aport/vassilflow/config.yaml" in content
    assert 'framework="vassilflow"' in content
    assert "VassilFlow Tool Names" in content
    assert "Start DeerFlow" not in content
    assert "~/.aport/deerflow" not in content
    assert 'framework="deerflow"' not in content


def test_backend_claude_uses_vassilflow_project_identity():
    content = (REPO_ROOT / "backend" / "CLAUDE.md").read_text(encoding="utf-8")

    assert "VassilFlow is a LangGraph-based AI super agent system" in content
    assert "VASSILFLOW_CONFIG_PATH" in content
    assert "VassilFlow's application tables" in content
    assert "empty (no VassilFlow tables)" in content
    assert "VassilFlowClient` provides direct in-process access" in content
    assert "from vassilflow.agents import make_lead_agent" in content
    assert "from vassilflow.models import create_chat_model" in content
    assert "from vassilflow.config import get_app_config" in content
    assert "vassilflow.models.vllm_provider:VllmChatModel" in content
    assert "VassilFlowClient.stream" in content
    assert "why Gateway and VassilFlowClient are parallel paths" in content
    assert "vassilflow/          # Public facade imports" in content
    assert "VASSILFLOW_CHANNELS_LANGGRAPH_URL" in content
    assert "VASSILFLOW_CHANNELS_GATEWAY_URL" in content
    assert "VassilFlowSummarizationMiddleware" in content
    assert "DeerFlow is a LangGraph-based AI super agent system" not in content
    assert "DeerFlow's application tables" not in content
    assert "from deerflow.agents import make_lead_agent" not in content
    assert "from deerflow.models import create_chat_model" not in content
    assert "from deerflow.config import get_app_config" not in content
    assert "deerflow.models.vllm_provider:VllmChatModel" not in content
    assert "or set `DEER_FLOW_CHANNELS_LANGGRAPH_URL`" not in content
    assert "**SummarizationMiddleware** - Context reduction" not in content


def test_backend_docs_index_and_mcp_use_vassilflow_identity():
    docs_readme = (REPO_ROOT / "backend" / "docs" / "README.md").read_text(encoding="utf-8")
    mcp_docs = (REPO_ROOT / "backend" / "docs" / "MCP_SERVER.md").read_text(encoding="utf-8")

    assert "VassilFlow backend" in docs_readme
    assert "New to VassilFlow?" in docs_readme
    assert "VassilFlow supports configurable MCP servers" in mcp_docs
    assert "VassilFlow's built-in file tools" in mcp_docs
    assert "DeerFlow backend" not in docs_readme
    assert "New to DeerFlow?" not in docs_readme
    assert "DeerFlow supports configurable MCP servers" not in mcp_docs


def test_configuration_docs_use_vassilflow_identity_and_env_names():
    content = (REPO_ROOT / "backend" / "docs" / "CONFIGURATION.md").read_text(
        encoding="utf-8"
    )

    assert "configure VassilFlow for your environment" in content
    assert "VassilFlow supports multiple sandbox execution modes" in content
    assert "Set `VASSILFLOW_SANDBOX_BIND_HOST` explicitly" in content
    assert "Set `VASSILFLOW_PROJECT_ROOT` if the runtime starts elsewhere" in content
    assert "legacy `DEER_FLOW_SANDBOX_BIND_HOST` is still accepted" in content
    assert "configure DeerFlow for your environment" not in content
    assert "DeerFlow supports multiple sandbox execution modes" not in content
    assert "Set `DEER_FLOW_SANDBOX_BIND_HOST` explicitly" not in content


def test_architecture_docs_use_vassilflow_runtime_identity():
    content = (REPO_ROOT / "backend" / "docs" / "ARCHITECTURE.md").read_text(
        encoding="utf-8"
    )

    assert "overview of the VassilFlow backend architecture" in content
    assert "Local VassilFlow thread data cleanup" in content
    assert "VassilFlow-managed filesystem data" in content
    assert "**Entry Point**: `vassilflow.agents:make_lead_agent`" in content
    assert '"path": "vassilflow.agents:make_lead_agent"' in content
    assert "VassilFlowSummarizationMiddleware" in content
    assert "`{runtime_home}/threads/{thread_id}/user-data/workspace`" in content
    assert "`skills/` under the project root by default" in content
    assert "overview of the DeerFlow backend architecture" not in content
    assert "Local DeerFlow thread data cleanup" not in content
    assert (
        "**Entry Point**: `packages/harness/deerflow/agents/lead_agent/agent.py:make_lead_agent`"
        not in content
    )
    assert '"path": "deerflow.agents:make_lead_agent"' not in content
    assert "`backend/.deer-flow/threads/{thread_id}/user-data/workspace`" not in content


def test_im_channel_docs_use_vassilflow_identity():
    content = (REPO_ROOT / "backend" / "docs" / "IM_CHANNEL_CONNECTIONS.md").read_text(
        encoding="utf-8"
    )

    assert "VassilFlow supports user-owned IM channel bindings" in content
    assert "connect the channel from VassilFlow Settings" in content
    assert "Send /connect <code> to the VassilFlow Slack bot." in content
    assert "VassilFlow run user id" in content
    assert "`vassilflow.persistence.channel_connections`" in content
    assert "DeerFlow supports user-owned IM channel bindings" not in content
    assert "connect the channel from DeerFlow Settings" not in content
    assert "Send /connect <code> to the DeerFlow Slack bot." not in content
    assert "`deerflow.persistence.channel_connections`" not in content


def test_api_docs_use_vassilflow_identity_and_runtime_paths():
    content = (REPO_ROOT / "backend" / "docs" / "API.md").read_text(encoding="utf-8")

    assert "reference for the VassilFlow backend APIs" in content
    assert "VassilFlow backend exposes two sets of APIs" in content
    assert '".vassilflow/threads/abc123/user-data/uploads/document.pdf"' in content
    assert "Remove VassilFlow-managed local thread files" in content
    assert "VassilFlow enforces authentication" in content
    assert "reference for the DeerFlow backend APIs" not in content
    assert '".deer-flow/threads/abc123/user-data/uploads/document.pdf"' not in content
    assert "DeerFlow enforces authentication" not in content


def test_setup_docs_use_vassilflow_config_facade_examples():
    content = (REPO_ROOT / "backend" / "docs" / "SETUP.md").read_text(encoding="utf-8")

    assert "from vassilflow.config import get_app_config" in content
    assert "from vassilflow.config import AppConfig" in content
    assert "from deerflow.config import get_app_config" not in content
    assert "from deerflow.config.app_config import AppConfig" not in content


def test_sso_docs_use_vassilflow_realm_and_product_identity():
    content = (REPO_ROOT / "backend" / "docs" / "SSO.md").read_text(encoding="utf-8")

    assert "VassilFlow supports single sign-on" in content
    assert "issuer: http://localhost:8080/realms/vassilflow" in content
    assert "client_id: vassilflow" in content
    assert "Configure VassilFlow" in content
    assert "redirected back to the VassilFlow workspace" in content
    assert "DeerFlow supports single sign-on" not in content
    assert "issuer: http://localhost:8080/realms/deerflow" not in content
    assert "client_id: deerflow" not in content


def test_upload_path_docs_use_vassilflow_runtime_paths_and_facade():
    file_upload = (REPO_ROOT / "backend" / "docs" / "FILE_UPLOAD.md").read_text(
        encoding="utf-8"
    )
    path_examples = (REPO_ROOT / "backend" / "docs" / "PATH_EXAMPLES.md").read_text(
        encoding="utf-8"
    )

    assert "VassilFlow 后端提供了完整的文件上传功能" in file_upload
    assert "VassilFlow 的文件上传系统返回三种不同的路径" in path_examples
    assert "{runtime_home}/threads/{thread_id}/user-data/uploads/document.pdf" in file_upload
    assert "{runtime_home}/threads/{thread_id}/user-data/uploads/document.pdf" in path_examples
    assert "from vassilflow.config import get_paths" in path_examples
    assert "vassilflow.agents.middlewares.uploads_middleware" in file_upload
    assert "DeerFlow 后端提供了完整的文件上传功能" not in file_upload
    assert "DeerFlow 的文件上传系统返回三种不同的路径" not in path_examples
    assert ".deer-flow/threads/" not in file_upload
    assert ".deer-flow/threads/" not in path_examples
    assert "THREAD_DATA_BASE_DIR" not in path_examples


def test_auth_docs_use_vassilflow_identity_and_runtime_storage():
    auth_design = (REPO_ROOT / "backend" / "docs" / "AUTH_DESIGN.md").read_text(
        encoding="utf-8"
    )
    auth_upgrade = (REPO_ROOT / "backend" / "docs" / "AUTH_UPGRADE.md").read_text(
        encoding="utf-8"
    )
    auth_test_plan = (
        REPO_ROOT / "backend" / "docs" / "AUTH_TEST_PLAN.md"
    ).read_text(encoding="utf-8")
    auth_docker_gap = (
        REPO_ROOT / "backend" / "docs" / "AUTH_TEST_DOCKER_GAP.md"
    ).read_text(encoding="utf-8")

    assert "本文档描述 VassilFlow 当前内置认证模块的设计" in auth_design
    assert "认证模块的核心目标是把 VassilFlow" in auth_design
    assert "VassilFlow 使用 Double Submit Cookie" in auth_design
    assert "{runtime_home}/admin_initial_credentials.txt" in auth_design
    assert "{runtime_home}/data/vassilflow.db" in auth_design
    assert "vassilflow.runtime.user_context" in auth_design
    assert "vassilflow.config.auth_config" in auth_design
    assert "VassilFlow 内置了认证模块" in auth_upgrade
    assert "rm -f backend/.vassilflow/data/vassilflow.db" in auth_upgrade
    assert "VassilFlowClient" in auth_upgrade
    assert "sqlite3 backend/.vassilflow/data/vassilflow.db" in auth_test_plan
    assert "docker logs vassilflow-gateway" in auth_test_plan
    assert "VASSILFLOW_HOME" in auth_test_plan
    assert "`vassilflow.db` volume persistence" in auth_docker_gap
    assert "VASSILFLOW_HOME=$HOME/vassilflow-data" in auth_docker_gap
    assert "本文档描述 DeerFlow 当前内置认证模块的设计" not in auth_design
    assert "deerflow.runtime.user_context" not in auth_design
    assert "deerflow/runtime/user_context.py" not in auth_design
    assert "packages/harness/deerflow/config/auth_config.py" not in auth_design
    assert "DeerFlow 内置了认证模块" not in auth_upgrade
    assert "docker logs deer-flow-gateway" not in auth_test_plan
    assert "sqlite3 backend/.deer-flow/data/deerflow.db" not in auth_test_plan
    assert "`deerflow.db` volume persistence" not in auth_docker_gap
    assert "DEER_FLOW_HOME=$HOME/deer-flow-data" not in auth_docker_gap


def test_apple_container_docs_use_vassilflow_runtime_names():
    content = (REPO_ROOT / "backend" / "docs" / "APPLE_CONTAINER.md").read_text(
        encoding="utf-8"
    )

    assert "VassilFlow supports Apple Container" in content
    assert "VassilFlow automatically detects and uses Apple Container" in content
    assert "vassilflow.community.aio_sandbox:AioSandboxProvider" in content
    assert "./scripts/cleanup-containers.sh vassilflow-sandbox" in content
    assert "uv run python -m pytest tests/test_aio_sandbox_provider.py" in content
    assert "DeerFlow now supports Apple Container" not in content
    assert "# Clean up all DeerFlow sandbox containers" not in content
    assert "python test_container_runtime.py" not in content


def test_memory_docs_use_vassilflow_identity_and_runtime_home():
    summarization = (REPO_ROOT / "backend" / "docs" / "summarization.md").read_text(
        encoding="utf-8"
    )
    memory_review = (
        REPO_ROOT / "backend" / "docs" / "MEMORY_SETTINGS_REVIEW.md"
    ).read_text(encoding="utf-8")

    assert "VassilFlow includes automatic conversation summarization" in summarization
    assert "VassilFlowSummarizationMiddleware" in summarization
    assert "VassilFlowSummarizationMiddleware.before_model" in summarization
    assert "Start VassilFlow locally" in memory_review
    assert "backend/.vassilflow/memory.json" in memory_review
    assert "legacy `.deer-flow` is still used as a transition fallback" in memory_review
    assert "DeerFlow includes automatic conversation summarization" not in summarization
    assert "DeerFlowSummarizationMiddleware.before_model" not in summarization
    assert "Start DeerFlow locally" not in memory_review
    assert "backend/.deer-flow/memory.json" not in memory_review


def test_plan_mode_and_title_docs_use_vassilflow_public_imports():
    plan_mode = (REPO_ROOT / "backend" / "docs" / "plan_mode_usage.md").read_text(
        encoding="utf-8"
    )
    auto_title = (
        REPO_ROOT / "backend" / "docs" / "AUTO_TITLE_GENERATION.md"
    ).read_text(encoding="utf-8")
    title_implementation = (
        REPO_ROOT / "backend" / "docs" / "TITLE_GENERATION_IMPLEMENTATION.md"
    ).read_text(encoding="utf-8")

    assert "TodoList middleware in VassilFlow" in plan_mode
    assert "from vassilflow.agents.lead_agent.agent import make_lead_agent" in plan_mode
    assert "custom VassilFlow-style prompts" in plan_mode
    assert "VassilFlowSummarizationMiddleware" in plan_mode
    assert "vassilflow.agents:make_lead_agent" in auto_title
    assert "from vassilflow.config import TitleConfig, set_title_config" in auto_title
    assert (
        "from vassilflow.agents.middlewares.title_middleware import TitleMiddleware"
        in auto_title
    )
    assert 'SqliteSaver.from_conn_string("vassilflow.db")' in title_implementation
    assert '"lead_agent": "vassilflow.agents:make_lead_agent"' in title_implementation
    assert "TodoList middleware in DeerFlow" not in plan_mode
    assert "from deerflow.agents.lead_agent.agent import make_lead_agent" not in plan_mode
    assert "        ├─> SummarizationMiddleware (if enabled via global config)" not in plan_mode
    assert "/Users/hetao/workspace/deer-flow" not in plan_mode
    assert '"lead_agent": "deerflow.agents:lead_agent"' not in auto_title
    assert "from deerflow.config.title_config import TitleConfig" not in auto_title
    assert "from deerflow.agents.title_middleware import TitleMiddleware" not in auto_title
    assert 'SqliteSaver.from_conn_string("deerflow.db")' not in title_implementation
    assert '"lead_agent": "deerflow.agents:lead_agent"' not in title_implementation


def test_streaming_docs_use_vassilflow_client_vocabulary():
    content = (REPO_ROOT / "backend" / "docs" / "STREAMING.md").read_text(
        encoding="utf-8"
    )

    assert "# VassilFlow 流式输出设计" in content
    assert "VassilFlow 有**两条并行**的流式路径" in content
    assert "VassilFlowClient 路径" in content
    assert "`VassilFlowClient.stream(message)`" in content
    assert "## VassilFlowClient 路径：sync + in-process" in content
    assert "participant C as VassilFlowClient" in content
    assert "Gateway 和 VassilFlowClient 是两套独立实现" in content
    assert "# DeerFlow 流式输出设计" not in content
    assert "DeerFlow 有**两条并行**的流式路径" not in content
    assert "## DeerFlowClient 路径：sync + in-process" not in content


def test_contributing_docs_use_vassilflow_public_examples():
    content = (REPO_ROOT / "backend" / "CONTRIBUTING.md").read_text(
        encoding="utf-8"
    )

    assert "# Contributing to VassilFlow Backend" in content
    assert "contributing to VassilFlow" in content
    assert "git clone https://github.com/YOUR_USERNAME/VassilFlow.git" in content
    assert "backend/" in content
    assert "app/" in content
    assert "packages/harness/vassilflow/" in content
    assert "from vassilflow.models.factory import create_chat_model" in content
    assert "use: vassilflow.tools.builtins.my_tool:my_tool" in content
    assert "Thank you for contributing to VassilFlow!" in content
    assert "backend/src/" not in content
    assert "# Contributing to DeerFlow Backend" not in content
    assert "git clone https://github.com/YOUR_USERNAME/deer-flow.git" not in content
    assert "from deerflow.models.factory import create_chat_model" not in content
    assert "use: deerflow.tools.builtins.my_tool:my_tool" not in content


def test_sandbox_memory_profiling_docs_use_vassilflow_defaults():
    content = (
        REPO_ROOT / "backend" / "docs" / "SANDBOX_MEMORY_PROFILING.md"
    ).read_text(encoding="utf-8")

    assert "same VassilFlow workload" in content
    assert "--namespace vassilflow" in content
    assert "--selector app=vassilflow-sandbox" in content
    assert "reproducible VassilFlow workload data" in content
    assert "same DeerFlow workload" not in content
    assert "--namespace deer-flow" not in content
    assert "--selector app=deer-flow-sandbox" not in content


def test_rfc_docs_use_vassilflow_public_facades():
    sdk_rfc = (
        REPO_ROOT / "backend" / "docs" / "rfc-create-vassilflow-agent.md"
    ).read_text(encoding="utf-8")
    grep_glob_rfc = (
        REPO_ROOT / "backend" / "docs" / "rfc-grep-glob-tools.md"
    ).read_text(encoding="utf-8")
    shared_modules_rfc = (
        REPO_ROOT / "backend" / "docs" / "rfc-extract-shared-modules.md"
    ).read_text(encoding="utf-8")

    assert "from vassilflow.client import VassilFlowClient" in sdk_rfc
    assert "from vassilflow.agents.features import RuntimeFeatures" in sdk_rfc
    assert "create_vassilflow_agent" in sdk_rfc
    assert '"vassilflow.sandbox.local:LocalSandboxProvider"' in sdk_rfc
    assert '"vassilflow.sandbox.tools:bash_tool"' in sdk_rfc
    assert "from deerflow.client import" not in sdk_rfc
    assert "from deerflow.agents" not in sdk_rfc
    assert "create_deerflow_agent" not in sdk_rfc

    assert "# [RFC] 在 VassilFlow 中增加 `grep` 与 `glob` 文件搜索工具" in grep_glob_rfc
    assert "use: vassilflow.sandbox.tools:glob_tool" in grep_glob_rfc
    assert "use: vassilflow.sandbox.tools:grep_tool" in grep_glob_rfc
    assert "use: deerflow.sandbox.tools" not in grep_glob_rfc

    assert "vassilflow.skills.installer" in shared_modules_rfc
    assert "vassilflow.uploads.manager" in shared_modules_rfc
    assert "`VassilFlowClient`" in shared_modules_rfc
    assert "deerflow.skills.installer" not in shared_modules_rfc
    assert "deerflow.uploads.manager" not in shared_modules_rfc


def test_middleware_docs_use_vassilflow_factory_name():
    content = (
        REPO_ROOT / "backend" / "docs" / "middleware-execution-flow.md"
    ).read_text(encoding="utf-8")

    assert "create_vassilflow_agent" in content
    assert "VassilFlow 的实际情况" in content
    assert "create_deerflow_agent" not in content
    assert "DeerFlow 的实际情况" not in content
