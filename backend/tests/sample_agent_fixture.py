"""Test-only domain used to exercise reusable Agent extension contracts."""

from langchain.agents.middleware import AgentMiddleware
from langchain.tools import tool

from vassilflow.capabilities import CapabilityReadinessCheck
from vassilflow.config.builtin_agents import BuiltinAgentDefinition
from vassilflow.config.paths import get_paths
from vassilflow.persistence.file_repository import UserScopedFileRecordRepository
from vassilflow.persistence.project_repository import ProjectRepositoryDescriptor, ProjectRepositorySchema


@tool
def sample_inspect_tool() -> str:
    """Inspect sample data."""
    return "sample"


@tool
def sample_generate_tool() -> str:
    """Generate sample data."""
    return "sample"


@tool
def sample_edit_tool() -> str:
    """Edit sample data."""
    return "sample"


@tool
def sample_render_tool() -> str:
    """Preview sample data."""
    return "sample"


# Public tool identities deliberately differ from Python variable names.
sample_inspect_tool.name = "sample_inspect"
sample_generate_tool.name = "sample_generate"
sample_edit_tool.name = "sample_edit"
sample_render_tool.name = "sample_render"

PROJECT_SCHEMA = "vassilflow.sample.project.v1"
REVISION_SCHEMA = "vassilflow.sample.revision.v1"
TEMPLATE_SCHEMA = "vassilflow.sample.template.v1"
TEMPLATE_VERSION_SCHEMA = "vassilflow.sample.template_version.v1"


class SampleProjectRepository(UserScopedFileRecordRepository):
    descriptor = ProjectRepositoryDescriptor(
        key="sample.projects",
        display_name="Sample Projects",
        storage_kind="filesystem",
        deployment_mode="single_writer",
        migration_safety="maintenance_window",
        scope="user",
        schemas=(ProjectRepositorySchema(record_kind="project", current_schema=PROJECT_SCHEMA), ProjectRepositorySchema(record_kind="revision", current_schema=REVISION_SCHEMA)),
    )
    relative_collection = ("sample", "projects")
    record_files = {"project.json": "project", "revision.json": "revision"}


class SampleTemplateRepository(UserScopedFileRecordRepository):
    descriptor = ProjectRepositoryDescriptor(
        key="sample.templates",
        display_name="Sample Templates",
        storage_kind="filesystem",
        deployment_mode="single_writer",
        migration_safety="maintenance_window",
        scope="user",
        schemas=(ProjectRepositorySchema(record_kind="template", current_schema=TEMPLATE_SCHEMA), ProjectRepositorySchema(record_kind="template_version", current_schema=TEMPLATE_VERSION_SCHEMA)),
    )
    relative_collection = ("sample", "templates")
    record_files = {"template.json": "template", "version.json": "template_version"}


class SampleSelectionContextMiddleware(AgentMiddleware):
    pass


class SampleSelectionApprovalMiddleware(AgentMiddleware):
    pass


class SampleAgentCapabilityAdapter:
    key = "sample"

    def resolve_input(self, kind, payload, *, context):
        return dict(payload)

    def build_middlewares(self):
        return (SampleSelectionContextMiddleware(), SampleSelectionApprovalMiddleware())

    def check_readiness(self, *, context):
        return (CapabilityReadinessCheck(key="sample.preview", status="ready", required=False, detail="Sample preview is ready."),)

    def build_project_repositories(self, *, context):
        return (SampleProjectRepository(get_paths().base_dir, user_id=context.user_id), SampleTemplateRepository(get_paths().base_dir, user_id=context.user_id))


SAMPLE_AGENT = BuiltinAgentDefinition(
    name="sample",
    display_name="Sample",
    description="Work with sample data.",
    category="create",
    icon="files",
    launch_kind="project",
    launch_path="/workspace/sample",
    project_kind="sample",
    tool_groups=("file:read", "file:write"),
    required_tools=("sample_inspect", "sample_generate", "sample_edit", "sample_render"),
    allowed_tools=("sample_inspect", "sample_generate", "sample_edit", "sample_render", "ls", "read_file", "glob", "grep", "write_file", "str_replace", "present_files", "ask_clarification", "view_image", "write_todos"),
    skills=("sample-skill",),
    data_access=("thread_uploads", "thread_workspace", "thread_outputs"),
    starter_prompts=("Inspect sample data.",),
    capability_adapters=("sample_agent_fixture:SampleAgentCapabilityAdapter",),
    chat_extension="sample-selection",
    soul="Use structured sample tools to complete the requested task.",
)
