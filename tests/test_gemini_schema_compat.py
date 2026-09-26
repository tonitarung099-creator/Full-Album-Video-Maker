from __future__ import annotations

import pytest

from full_album_maker import gemini_agent
from full_album_maker.controller import ProjectController
from full_album_maker.gemini_schema_compat import sanitized_tools
from full_album_maker.project import Project


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def test_all_gemini_enum_values_are_strings_after_sanitizing():
    tools = sanitized_tools(gemini_agent.TOOLS)

    for node in _walk(tools):
        enum_values = node.get("enum") if isinstance(node, dict) else None
        if enum_values is not None:
            assert all(isinstance(value, str) for value in enum_values)


def test_fps_tool_keeps_integer_type_but_drops_numeric_enum():
    tools = sanitized_tools(gemini_agent.TOOLS)
    fps_tool = next(tool for tool in tools if tool["name"] == "set_fps")
    fps_schema = fps_tool["parameters"]["properties"]["fps"]

    assert fps_schema["type"] == "integer"
    assert "enum" not in fps_schema
    assert "24, 25, 30, 50, 60" in fps_schema["description"]


def test_local_controller_still_enforces_supported_fps_values():
    project = Project()
    controller = ProjectController(project)

    with pytest.raises(ValueError, match="fps harus"):
        controller.execute("set_fps", {"fps": 26})

    controller.execute("set_fps", {"fps": 30})
    assert project.settings.fps == 30
