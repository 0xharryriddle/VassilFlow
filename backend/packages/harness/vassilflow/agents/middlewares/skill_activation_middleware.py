"""Middleware for explicit slash skill activation."""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import posixpath
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage

from vassilflow.runtime.secret_context import (
    _SECRETS_BINDING_AUDIT_KEY,
    _SLASH_SECRET_SOURCE_KEY,
    ACTIVE_SECRETS_CONTEXT_KEY,
    extract_request_secrets,
)
from vassilflow.skills.slash import parse_slash_skill_reference, resolve_slash_skill
from vassilflow.skills.storage import get_or_new_skill_storage
from vassilflow.skills.storage.skill_storage import SkillStorage
from vassilflow.skills.types import SKILL_MD_FILE, SecretRequirement, Skill, skill_reference_matches
from vassilflow.utils.messages import get_original_user_content_text

if TYPE_CHECKING:
    from vassilflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)

_SLASH_SKILL_ACTIVATION_KEY = "slash_skill_activation"
_SLASH_SKILL_ACTIVATION_TARGET_ID_KEY = "slash_skill_activation_target_id"
_SUMMARY_MESSAGE_NAME = "summary"


@dataclass(frozen=True, slots=True)
class _Activation:
    skill_name: str
    category: str
    container_file_path: str
    skill_content: str
    content_hash: str
    remaining_text: str
    required_secrets: tuple[SecretRequirement, ...] = ()


@dataclass(frozen=True, slots=True)
class _ActivationResolution:
    activation: _Activation | None = None
    failure_message: str | None = None


def is_slash_skill_activation_reminder(message: object) -> bool:
    """Return whether a message is hidden slash-skill activation context."""
    return isinstance(message, HumanMessage) and bool(message.additional_kwargs.get(_SLASH_SKILL_ACTIVATION_KEY))


def _is_user_activation_target(message: object) -> bool:
    if not isinstance(message, HumanMessage):
        return False
    if message.name == _SUMMARY_MESSAGE_NAME:
        return False
    if message.additional_kwargs.get("hide_from_ui"):
        return False
    return True


class SkillActivationMiddleware(AgentMiddleware):
    """Inject full SKILL.md content when the user explicitly types /skill-name."""

    def __init__(
        self,
        *,
        available_skills: set[str] | None = None,
        app_config: AppConfig | None = None,
    ) -> None:
        super().__init__()
        self._available_skills = set(available_skills) if available_skills is not None else None
        self._app_config = app_config

    def _storage(self) -> SkillStorage:
        if self._app_config is not None:
            return get_or_new_skill_storage(app_config=self._app_config)
        return get_or_new_skill_storage()

    @staticmethod
    def _read_skill_content(skill_file: Path, skills_root: Path) -> str:
        if skill_file.name != SKILL_MD_FILE:
            raise ValueError(f"Expected {SKILL_MD_FILE}, got {skill_file.name}")
        resolved_root = skills_root.resolve()
        resolved_file = skill_file.resolve()
        try:
            resolved_file.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("Resolved skill file must stay within the configured skills root.") from exc
        if not resolved_file.is_file():
            raise FileNotFoundError(resolved_file)
        return resolved_file.read_text(encoding="utf-8")

    def _resolve_activation(self, text: str) -> _ActivationResolution | None:
        reference = parse_slash_skill_reference(text)
        if reference is None:
            return None

        storage = self._storage()
        skills = storage.load_skills(enabled_only=False)
        matching_by_name = [candidate for candidate in skills if candidate.name == reference.name]
        if not matching_by_name:
            return _ActivationResolution(failure_message=f"Skill `/{reference.name}` is not installed.")
        if not any(skill.enabled for skill in matching_by_name):
            return _ActivationResolution(failure_message=f"Skill `/{reference.name}` is installed but disabled. Enable it before using slash activation.")
        if self._available_skills is not None and not any(skill.enabled and any(skill_reference_matches(skill.name, skill.category, allowed) for allowed in self._available_skills) for skill in matching_by_name):
            return _ActivationResolution(failure_message=f"Skill `/{reference.name}` is not available for this agent.")
        enabled_matches = [skill for skill in matching_by_name if skill.enabled and (self._available_skills is None or any(skill_reference_matches(skill.name, skill.category, allowed) for allowed in self._available_skills))]
        if len(enabled_matches) > 1:
            choices = ", ".join(f"`{skill.category}:{skill.name}`" for skill in enabled_matches)
            return _ActivationResolution(failure_message=f"Skill `/{reference.name}` is ambiguous. Use a custom agent skill allowlist with one of: {choices}.")

        resolved = resolve_slash_skill(
            text,
            skills,
            available_skills=self._available_skills,
            container_base_path=storage.get_container_root(),
        )
        if resolved is None:
            return _ActivationResolution(failure_message=f"Skill `/{reference.name}` could not be resolved.")

        try:
            skill_content = self._read_skill_content(resolved.skill.skill_file, storage.get_skills_root_path())
        except (OSError, ValueError):
            logger.exception("Failed to read slash-activated skill %s", resolved.skill.name)
            return _ActivationResolution(failure_message=f"Skill `/{reference.name}` could not be loaded safely. Please check the skill installation.")

        content_hash = hashlib.sha256(skill_content.encode("utf-8")).hexdigest()
        return _ActivationResolution(
            activation=_Activation(
                skill_name=resolved.skill.name,
                category=str(resolved.skill.category),
                container_file_path=resolved.container_file_path,
                skill_content=skill_content,
                content_hash=content_hash,
                remaining_text=resolved.remaining_text,
                required_secrets=tuple(resolved.skill.required_secrets or ()),
            )
        )

    @staticmethod
    def _build_activation_reminder(activation: _Activation) -> str:
        user_request = activation.remaining_text or ("No additional task text was provided after the slash skill command. Ask the user what they want to do with this skill if the next step is unclear.")
        escaped_user_request = html.escape(user_request, quote=False)
        escaped_skill_content = html.escape(activation.skill_content, quote=False)
        escaped_skill_name = html.escape(activation.skill_name, quote=True)
        escaped_category = html.escape(activation.category, quote=True)
        escaped_path = html.escape(activation.container_file_path, quote=True)
        escaped_content_hash = html.escape(activation.content_hash, quote=True)
        return f"""<slash_skill_activation>
The user explicitly activated the `{activation.skill_name}` skill for this turn.
Treat the task text as:
<user_request>
{escaped_user_request}
</user_request>

Follow this skill before choosing a general workflow. Load supporting resources from the same skill directory only when needed.

<skill name="{escaped_skill_name}" category="{escaped_category}" path="{escaped_path}" sha256="{escaped_content_hash}">
<skill_content encoding="xml-escaped">
{escaped_skill_content}
</skill_content>
</skill>
</slash_skill_activation>"""

    @staticmethod
    def _has_existing_activation_for_target(messages: list, target_index: int, target: HumanMessage) -> bool:
        if target_index <= 0:
            return False

        if target.id:
            for previous in messages[:target_index]:
                if not is_slash_skill_activation_reminder(previous):
                    continue
                target_id = previous.additional_kwargs.get(_SLASH_SKILL_ACTIVATION_TARGET_ID_KEY)
                if target_id == target.id or previous.id == f"{target.id}__slash_activation":
                    return True

        previous = messages[target_index - 1]
        return is_slash_skill_activation_reminder(previous)

    def _find_activation_target(self, messages: list) -> tuple[int, HumanMessage, _ActivationResolution] | None:
        if not messages:
            return None

        target_index = next((idx for idx in range(len(messages) - 1, -1, -1) if _is_user_activation_target(messages[idx])), None)
        if target_index is None:
            return None

        target = messages[target_index]
        if target is None:
            return None
        if self._has_existing_activation_for_target(messages, target_index, target):
            return None

        content = get_original_user_content_text(target.content, target.additional_kwargs)
        resolution = self._resolve_activation(content)
        if resolution is None:
            return None
        return target_index, target, resolution

    @staticmethod
    def _record_activation(request: ModelRequest, activation: _Activation, *, hook: str) -> None:
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None)
        journal = context.get("__run_journal") if isinstance(context, dict) else None
        if journal is None:
            return
        try:
            journal.record_middleware(
                "skill_activation",
                name="SkillActivationMiddleware",
                hook=hook,
                action="activate",
                changes={
                    "skill_name": activation.skill_name,
                    "category": activation.category,
                    "path": activation.container_file_path,
                    "content_hash": activation.content_hash,
                },
            )
        except Exception:
            logger.debug("Failed to record slash skill activation audit event", exc_info=True)

    def _prepare_model_request(self, request: ModelRequest, *, hook: str) -> tuple[ModelRequest | AIMessage | None, _Activation | None]:
        target_and_resolution = self._find_activation_target(list(request.messages))
        if target_and_resolution is None:
            return None, None

        target_index, target, resolution = target_and_resolution
        if resolution.failure_message:
            return AIMessage(content=resolution.failure_message), None

        activation = resolution.activation
        if activation is None:
            return None, None

        logger.info(
            "SkillActivationMiddleware: activating slash skill %s category=%s path=%s hash=%s",
            activation.skill_name,
            activation.category,
            activation.container_file_path,
            activation.content_hash,
        )
        self._record_activation(request, activation, hook=hook)
        activation_msg = self._make_activation_message(target, self._build_activation_reminder(activation))
        messages = list(request.messages)
        messages.insert(target_index, activation_msg)
        return request.override(messages=messages), activation

    def _handle_model_request(self, request: ModelRequest, *, hook: str) -> ModelRequest | AIMessage:
        prepared, activation = self._prepare_model_request(request, hook=hook)
        if isinstance(prepared, AIMessage):
            return prepared
        effective = prepared if prepared is not None else request
        self._resolve_secret_bindings(effective, activation, hook=hook)
        return effective

    def _resolve_secret_bindings(self, request: ModelRequest, activation: _Activation | None, *, hook: str) -> None:
        """Recompute active skill secrets from slash activation and skill_context."""
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None)
        if not isinstance(context, dict):
            return

        if activation is not None:
            context[_SLASH_SECRET_SOURCE_KEY] = {"path": activation.container_file_path}

        request_secrets = extract_request_secrets(context)
        sources: list[tuple[str, tuple[SecretRequirement, ...]]] = []
        if request_secrets:
            registry = self._load_skill_registry_by_path()
            if registry is not None:
                slash_source = context.get(_SLASH_SECRET_SOURCE_KEY)
                slash_path = slash_source.get("path") if isinstance(slash_source, dict) else None
                slash_skill = self._resolve_registry_skill(registry, slash_path, require_autonomous=False)
                if slash_skill is not None:
                    sources.append((slash_skill.name, tuple(slash_skill.required_secrets)))
                sources.extend(self._in_context_secret_sources(request, registry))

        injected: dict[str, str] = {}
        bound_skills: set[str] = set()
        missing: dict[str, list[str]] = {}
        for skill_name, requirements in sources:
            for requirement in requirements:
                if requirement.name in request_secrets:
                    injected[requirement.name] = request_secrets[requirement.name]
                    bound_skills.add(skill_name)
                elif not requirement.optional:
                    missing.setdefault(skill_name, []).append(requirement.name)

        if injected:
            context[ACTIVE_SECRETS_CONTEXT_KEY] = injected
        else:
            context.pop(ACTIVE_SECRETS_CONTEXT_KEY, None)

        audit_state = {
            "skills": sorted(bound_skills),
            "secrets": sorted(injected),
            "missing": {name: sorted(values) for name, values in sorted(missing.items())},
        }
        previous = context.get(_SECRETS_BINDING_AUDIT_KEY)
        if previous == audit_state:
            return
        if previous is None and not injected and not missing:
            return
        context[_SECRETS_BINDING_AUDIT_KEY] = audit_state
        for skill_name, names in sorted(missing.items()):
            logger.warning(
                "Skill %s is active but required secrets are missing from the request context: %s",
                skill_name,
                ", ".join(names),
            )
        self._record_secret_binding(context, audit_state, hook=hook)

    def _load_skill_registry_by_path(self) -> dict[str, Skill] | None:
        try:
            storage = self._storage()
            skills = storage.load_skills(enabled_only=False)
            container_root = storage.get_container_root()
        except Exception:
            logger.exception("Failed to load skills while resolving secret bindings")
            return None
        return {posixpath.normpath(skill.get_container_file_path(container_root)): skill for skill in skills}

    def _resolve_registry_skill(self, registry: dict[str, Skill], path: object, *, require_autonomous: bool) -> Skill | None:
        if not isinstance(path, str) or not path:
            return None
        skill = registry.get(posixpath.normpath(path))
        if skill is None or not skill.enabled or not skill.required_secrets:
            return None
        if require_autonomous and not skill.secrets_autonomous:
            return None
        if self._available_skills is not None and not any(skill_reference_matches(skill.name, skill.category, allowed) for allowed in self._available_skills):
            return None
        return skill

    def _in_context_secret_sources(self, request: ModelRequest, registry: dict[str, Skill]) -> list[tuple[str, tuple[SecretRequirement, ...]]]:
        state = getattr(request, "state", None) or {}
        try:
            entries = state.get("skill_context") or []
        except AttributeError:
            return []

        sources: list[tuple[str, tuple[SecretRequirement, ...]]] = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            skill = self._resolve_registry_skill(registry, entry.get("path"), require_autonomous=True)
            if skill is None or skill.name in seen:
                continue
            seen.add(skill.name)
            sources.append((skill.name, tuple(skill.required_secrets)))
        return sources

    @staticmethod
    def _record_secret_binding(context: dict, audit_state: dict, *, hook: str) -> None:
        journal = context.get("__run_journal")
        if journal is None:
            return
        try:
            journal.record_middleware(
                "skill_secrets",
                name="SkillActivationMiddleware",
                hook=hook,
                action="bind_secrets",
                changes=audit_state,
            )
        except Exception:
            logger.debug("Failed to record skill secret binding audit event", exc_info=True)

    @staticmethod
    def _make_activation_message(target: HumanMessage, activation_content: str) -> HumanMessage:
        stable_id = target.id or str(uuid.uuid4())
        additional_kwargs = {
            "hide_from_ui": True,
            _SLASH_SKILL_ACTIVATION_KEY: True,
        }
        if target.id:
            additional_kwargs[_SLASH_SKILL_ACTIVATION_TARGET_ID_KEY] = target.id
        return HumanMessage(
            content=activation_content,
            id=f"{stable_id}__slash_activation",
            additional_kwargs=additional_kwargs,
        )

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse | AIMessage:
        prepared = self._handle_model_request(request, hook="wrap_model_call")
        if isinstance(prepared, AIMessage):
            return prepared
        return handler(prepared)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse | AIMessage:
        prepared = await asyncio.to_thread(self._handle_model_request, request, hook="awrap_model_call")
        if isinstance(prepared, AIMessage):
            return prepared
        return await handler(prepared)
