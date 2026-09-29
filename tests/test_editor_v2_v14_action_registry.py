from full_album_maker.agent_actions import AgentAction
from full_album_maker.ai_editor_v14 import V14_EDITOR_TOOLS


def test_every_v14_editor_tool_is_a_valid_agent_action():
    names = [item["name"] for item in V14_EDITOR_TOOLS]
    assert len(names) == len(set(names))
    for name in names:
        action = AgentAction(name, {})
        assert action.name == name
