"""Tool error handling middleware and shared runtime middleware builders."""

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from vassilflow.agents.middlewares.skill_context import (
    SKILL_CONTEXT_ENTRY_KEY,
    _tool_call_path,
    build_skill_entry_metadata_from_read,
)
from vassilflow.agents.middlewares.tool_result_meta import (
    normalize_tool_result,
    stamp_exception_meta,
)
from vassilflow.config.app_config import AppConfig
from vassilflow.subagents.status_contract import (
    extract_subagent_status,
    make_subagent_additional_kwargs,
)

if TYPE_CHECKING:
    from vassilflow.tools.builtins.tool_search import DeferredToolSetup

logger = logging.getLogger(__name__)

_MISSING_TOOL_CALL_ID = "missing_tool_call_id"
_TASK_TOOL_NAME = "task"
_DEFAULT_SKILLS_CONTAINER_PATH = "/mnt/skills"


def _stamp_task_subagent_status(message: ToolMessage, *, tool_name: str, error: str | None = None) -> ToolMessage:
    """Centralised stamping of ``additional_kwargs.subagent_status``.

    VassilFlow issue #3146: the frontend now reads the subagent
    status from a structured field instead of parsing the leading text of
    the task tool's return string. That contract is enforced here, in the
    one place every task tool result flows through, rather than at the 5
    normal-return + 3 ``Error:`` pre-execution branches inside
    ``task_tool.py``. Centralisation prevents the "added a new return
    path, forgot the stamp" drift mode.

    For non-``task`` tools this is a no-op so other tools' additional_kwargs
    conventions are untouched.
    """
    if tool_name != _TASK_TOOL_NAME:
        return message
    content = message.content if isinstance(message.content, str) else ""
    status = extract_subagent_status(content)
    if status is None:
        # Non-terminal streaming chunks or unrecognised shapes leave the
        # field unset so the frontend can keep the card on its in-progress
        # placeholder until a real terminal frame arrives.
        return message
    stamp = make_subagent_additional_kwargs(status, error=error)
    existing = dict(message.additional_kwargs or {})
    existing.update(stamp)
    message.additional_kwargs = existing
    return message


class ToolErrorHandlingMiddleware(AgentMiddleware[AgentState]):
    """Convert tool exceptions into error ToolMessages so the run can continue."""

    def __init__(self, *, app_config: AppConfig | None = None) -> None:
        super().__init__()
        self._app_config = app_config
        if app_config is None:
            self._skill_read_tool_names = frozenset({"read_file", "read", "view", "cat"})
            self._skills_root = _DEFAULT_SKILLS_CONTAINER_PATH
        else:
            self._skill_read_tool_names = frozenset(app_config.summarization.skill_file_read_tool_names)
            self._skills_root = app_config.skills.container_path

    def _build_error_message(self, request: ToolCallRequest, exc: Exception) -> ToolMessage:
        tool_name = str(request.tool_call.get("name") or "unknown_tool")
        tool_call_id = str(request.tool_call.get("id") or _MISSING_TOOL_CALL_ID)
        detail = str(exc).strip() or exc.__class__.__name__
        if len(detail) > 500:
            detail = detail[:497] + "..."

        content = f"Error: Tool '{tool_name}' failed with {exc.__class__.__name__}: {detail}. Continue with available context, or choose an alternative tool."
        message = ToolMessage(
            content=content,
            tool_call_id=tool_call_id,
            name=tool_name,
            status="error",
        )
        # Stamp the structured subagent status on the wrapper too: the
        # frontend would otherwise have to fall back to prefix-matching
        # ``Error: Tool 'task' failed ...`` on the wire. The ``subagent_error``
        # carries the same ``ExcClass: detail`` shape the wrapper string
        # uses so debugging artifacts stay aligned.
        structured_error = f"{exc.__class__.__name__}: {detail}"
        message = _stamp_task_subagent_status(message, tool_name=tool_name, error=structured_error)
        return stamp_exception_meta(message, structured_error)

    def _stamp_skill_read_metadata(
        self,
        message: ToolMessage,
        request: ToolCallRequest,
        *,
        tool_name: str,
    ) -> ToolMessage:
        if tool_name not in self._skill_read_tool_names:
            return message
        if getattr(message, "status", "success") == "error":
            return message
        content = message.content if isinstance(message.content, str) else None
        if content is None:
            return message
        path = _tool_call_path(request.tool_call)
        if path is None:
            return message
        entry = build_skill_entry_metadata_from_read(path, content, skills_root=self._skills_root)
        if entry is None:
            return message
        existing = dict(message.additional_kwargs or {})
        existing[SKILL_CONTEXT_ENTRY_KEY] = dict(entry)
        message.additional_kwargs = existing
        return message

    def _maybe_stamp_skill_read(self, result: ToolMessage | Command, request: ToolCallRequest) -> ToolMessage | Command:
        if not isinstance(result, ToolMessage):
            return result
        tool_name = str(request.tool_call.get("name") or "")
        return self._stamp_skill_read_metadata(result, request, tool_name=tool_name)

    @staticmethod
    def _maybe_stamp(result: ToolMessage | Command, request: ToolCallRequest) -> ToolMessage | Command:
        """Apply the subagent stamp to successful task tool returns.

        ``Command`` results bypass the stamp — they encode LangGraph
        control flow rather than user-facing tool output.
        """
        if not isinstance(result, ToolMessage):
            return result
        tool_name = str(request.tool_call.get("name") or "")
        return _stamp_task_subagent_status(result, tool_name=tool_name)

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        try:
            result = handler(request)
        except GraphBubbleUp:
            # Preserve LangGraph control-flow signals (interrupt/pause/resume).
            raise
        except Exception as exc:
            logger.exception("Tool execution failed (sync): name=%s id=%s", request.tool_call.get("name"), request.tool_call.get("id"))
            return self._build_error_message(request, exc)
        return normalize_tool_result(self._maybe_stamp_skill_read(self._maybe_stamp(result, request), request))

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        try:
            result = await handler(request)
        except GraphBubbleUp:
            # Preserve LangGraph control-flow signals (interrupt/pause/resume).
            raise
        except Exception as exc:
            logger.exception("Tool execution failed (async): name=%s id=%s", request.tool_call.get("name"), request.tool_call.get("id"))
            return self._build_error_message(request, exc)
        return normalize_tool_result(self._maybe_stamp_skill_read(self._maybe_stamp(result, request), request))


def _build_runtime_middlewares(
    *,
    app_config: AppConfig,
    include_uploads: bool,
    include_dangling_tool_call_patch: bool,
    lazy_init: bool = True,
) -> list[AgentMiddleware]:
    """Build shared base middlewares for agent execution."""
    from vassilflow.agents.middlewares.input_sanitization_middleware import InputSanitizationMiddleware
    from vassilflow.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware
    from vassilflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
    from vassilflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware
    from vassilflow.agents.middlewares.tool_result_sanitization_middleware import ToolResultSanitizationMiddleware
    from vassilflow.sandbox.middleware import SandboxMiddleware

    # InputSanitizationMiddleware is first so it becomes the outermost
    # wrap_model_call wrapper — sanitised messages are what every inner
    # middleware (including LLMErrorHandlingMiddleware retries) sees.
    middlewares: list[AgentMiddleware] = [
        InputSanitizationMiddleware(),
        ToolOutputBudgetMiddleware.from_app_config(app_config),
        ToolResultSanitizationMiddleware(),
        ThreadDataMiddleware(lazy_init=lazy_init),
        SandboxMiddleware(lazy_init=lazy_init),
    ]

    if include_uploads:
        from vassilflow.agents.middlewares.uploads_middleware import UploadsMiddleware

        middlewares.insert(3, UploadsMiddleware())

    if include_dangling_tool_call_patch:
        from vassilflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

        middlewares.append(DanglingToolCallMiddleware())

    middlewares.append(LLMErrorHandlingMiddleware(app_config=app_config))

    # Guardrail middleware (if configured)
    guardrails_config = app_config.guardrails
    if guardrails_config.enabled and guardrails_config.provider:
        import inspect

        from vassilflow.guardrails.middleware import GuardrailMiddleware
        from vassilflow.reflection import resolve_variable

        provider_cls = resolve_variable(guardrails_config.provider.use)
        provider_kwargs = dict(guardrails_config.provider.config) if guardrails_config.provider.config else {}
        # Pass framework hint if the provider accepts it (e.g. for config discovery).
        # Built-in providers like AllowlistProvider don't need it, so only inject
        # when the constructor accepts 'framework' or '**kwargs'.
        if "framework" not in provider_kwargs:
            try:
                sig = inspect.signature(provider_cls.__init__)
                if "framework" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                    provider_kwargs["framework"] = "vassilflow"
            except (ValueError, TypeError):
                pass
        provider = provider_cls(**provider_kwargs)
        middlewares.append(GuardrailMiddleware(provider, fail_closed=guardrails_config.fail_closed, passport=guardrails_config.passport))

    from vassilflow.agents.middlewares.sandbox_audit_middleware import SandboxAuditMiddleware

    middlewares.append(SandboxAuditMiddleware())

    if app_config.read_before_write.enabled:
        from vassilflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware

        middlewares.append(ReadBeforeWriteMiddleware())

    tool_progress_config = app_config.tool_progress
    _ToolProgressMiddleware = None
    if tool_progress_config.enabled:
        from vassilflow.agents.middlewares.tool_progress_middleware import ToolProgressMiddleware as _ToolProgressMiddleware

        middlewares.append(_ToolProgressMiddleware.from_config(tool_progress_config))

    middlewares.append(ToolErrorHandlingMiddleware(app_config=app_config))

    if _ToolProgressMiddleware is not None:
        progress_idx = next((i for i, m in enumerate(middlewares) if isinstance(m, _ToolProgressMiddleware)), None)
        error_idx = next((i for i, m in enumerate(middlewares) if isinstance(m, ToolErrorHandlingMiddleware)), None)
        if progress_idx is not None and error_idx is not None and progress_idx > error_idx:
            raise RuntimeError(f"ToolProgressMiddleware must be outer (index {progress_idx}) of ToolErrorHandlingMiddleware (index {error_idx}); check middleware append order")
    return middlewares


def build_lead_runtime_middlewares(*, app_config: AppConfig, lazy_init: bool = True) -> list[AgentMiddleware]:
    """Middlewares shared by lead agent runtime before lead-only middlewares."""
    return _build_runtime_middlewares(
        app_config=app_config,
        include_uploads=True,
        include_dangling_tool_call_patch=True,
        lazy_init=lazy_init,
    )


def build_subagent_runtime_middlewares(
    *,
    app_config: AppConfig | None = None,
    model_name: str | None = None,
    lazy_init: bool = True,
    deferred_setup: "DeferredToolSetup | None" = None,
) -> list[AgentMiddleware]:
    """Middlewares shared by subagent runtime before subagent-only middlewares."""
    if app_config is None:
        from vassilflow.config import get_app_config

        app_config = get_app_config()

    middlewares = _build_runtime_middlewares(
        app_config=app_config,
        include_uploads=False,
        include_dangling_tool_call_patch=True,
        lazy_init=lazy_init,
    )

    if model_name is None and app_config.models:
        model_name = app_config.models[0].name

    model_config = app_config.get_model_config(model_name) if model_name else None
    if model_config is not None and model_config.supports_vision:
        from vassilflow.agents.middlewares.view_image_middleware import ViewImageMiddleware

        middlewares.append(ViewImageMiddleware())

    # Hide deferred (MCP) tool schemas from the subagent's model binding until
    # tool_search promotes them. This is the same wiring the lead agent gets. The deferred
    # set + catalog hash come from the build-time setup (assembled after
    # tool-policy filtering); promotion is read from graph state. Empty/None
    # setup (deferral disabled or no MCP tool survived) is a pure no-op.
    if deferred_setup is not None and deferred_setup.deferred_names:
        from vassilflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware

        middlewares.append(DeferredToolFilterMiddleware(deferred_setup.deferred_names, deferred_setup.catalog_hash))

    # Subagents inherit none of the lead agent's runaway guards unless they are
    # wired here. Add loop detection before SafetyFinishReasonMiddleware so
    # degenerate tool loops stop before they burn through max_turns.
    loop_detection_config = app_config.loop_detection
    if loop_detection_config.enabled:
        from vassilflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware

        middlewares.append(LoopDetectionMiddleware.from_config(loop_detection_config))

    # Same provider safety-termination guard the lead agent uses — subagents
    # are equally exposed to truncated tool_calls returned with
    # finish_reason=content_filter (and friends), and the bad call would then
    # propagate back to the lead agent via the task tool result.
    safety_config = app_config.safety_finish_reason
    if safety_config.enabled:
        from vassilflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware

        middlewares.append(SafetyFinishReasonMiddleware.from_config(safety_config))

    return middlewares
