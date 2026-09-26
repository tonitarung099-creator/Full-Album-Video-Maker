from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import gemini_agent as gemini_agent_module

_installed = False
_original_tools: list[dict[str, Any]] | None = None


def _sanitize_schema(node: Any) -> None:
    if isinstance(node, dict):
        enum_values = node.get("enum")
        schema_type = str(node.get("type", "")).lower()
        if (
            isinstance(enum_values, list)
            and enum_values
            and schema_type in {"integer", "number"}
            and any(not isinstance(value, str) for value in enum_values)
        ):
            allowed = ", ".join(str(value) for value in enum_values)
            node.pop("enum", None)
            description = str(node.get("description", "")).strip()
            suffix = f"Nilai yang didukung engine lokal: {allowed}."
            node["description"] = f"{description} {suffix}".strip()

        for value in list(node.values()):
            _sanitize_schema(value)
    elif isinstance(node, list):
        for value in node:
            _sanitize_schema(value)


def sanitized_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return Gemini-compatible function declarations without numeric enum values.

    Gemini's Schema.enum field accepts string values. Numeric restrictions remain
    enforced by ProjectController, so stripping a numeric enum only affects the API
    declaration and never weakens local validation.
    """
    result = deepcopy(tools)
    _sanitize_schema(result)
    return result


def install_gemini_schema_compat() -> None:
    global _installed, _original_tools
    if _installed:
        return
    _original_tools = gemini_agent_module.TOOLS
    gemini_agent_module.TOOLS = sanitized_tools(gemini_agent_module.TOOLS)
    _installed = True


def uninstall_gemini_schema_compat() -> None:
    global _installed, _original_tools
    if not _installed:
        return
    if _original_tools is not None:
        gemini_agent_module.TOOLS = _original_tools
    _original_tools = None
    _installed = False
