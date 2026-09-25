from __future__ import annotations

from full_album_maker.agent_actions import (
    AgentAction,
    AgentDecision,
    AppIntentExecutor,
)
from full_album_maker.gemini_agent import GeminiAgent, TOOLS
from full_album_maker.project import MediaItem, Project


class FakePool:
    def __init__(self, response):
        self.response = response
        self.payloads = []

    def request_json(self, url, payload):
        self.payloads.append((url, payload))
        return self.response


def test_gemini_translates_human_command_into_ordered_app_intents():
    pool = FakePool(
        {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "text": "Saya pahami: kunci slowmo 50 persen lalu susun."
                            },
                            {
                                "functionCall": {
                                    "name": "set_slowmo",
                                    "args": {"speed": 0.5},
                                }
                            },
                            {
                                "functionCall": {
                                    "name": "auto_build_timeline",
                                    "args": {},
                                }
                            },
                        ],
                    }
                }
            ]
        }
    )
    agent = GeminiAgent(pool, model="gemini-test")
    decision = agent.interpret(
        "slowmo 50 lalu susun semua lagu dan video",
        {
            "video_count": 1,
            "audio_count": 2,
            "video_duration_seconds": 2400,
            "album_duration_seconds": 3600,
        },
    )

    assert [x.name for x in decision.actions] == [
        "set_slowmo",
        "auto_build_timeline",
    ]
    assert decision.actions[0].args["speed"] == 0.5
    assert "slowmo" in decision.message.lower()
    assert len(pool.payloads) == 1


def test_gemini_can_return_text_without_changing_app():
    pool = FakePool(
        {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [{"text": "Audio menjadi master timeline."}],
                    }
                }
            ]
        }
    )
    agent = GeminiAgent(pool)
    decision = agent.interpret("audio jadi master ya?", {"audio_count": 3})

    assert decision.actions == []
    assert "master timeline" in decision.message.lower()


def test_gemini_has_no_render_tool():
    names = {tool["name"] for tool in TOOLS}
    assert "render" not in names
    assert "render_video" not in names
    assert "auto_build_timeline" in names


def test_local_executor_applies_settings_then_builds_timeline(tmp_path):
    project = Project(
        videos=[MediaItem("video.mp4", 2400.0)],
        audios=[MediaItem("album.mp3", 3600.0)],
    )
    executor = AppIntentExecutor(
        project,
        timeline_output_path=str(tmp_path / "Timeline_Auto.json"),
    )
    execution = executor.execute(
        [
            AgentAction("set_slowmo", {"speed": 0.5}),
            AgentAction("auto_build_timeline", {}),
        ]
    )

    assert project.settings.auto_speed is False
    assert project.settings.manual_speed == 0.5
    assert execution.project_changed is True
    assert execution.timeline_plan is not None
    assert execution.timeline_plan.duration == 3600.0
    assert execution.timeline_plan.auto_cut_seconds == 1200.0
    assert execution.timeline_plan.video_clips[0].source_out == 1800.0
    assert (tmp_path / "Timeline_Auto.json").exists()


def test_local_executor_human_style_sequence_youtube_then_auto(tmp_path):
    project = Project(
        videos=[MediaItem("video.mp4", 1800.0)],
        audios=[MediaItem("album.mp3", 3600.0)],
    )
    executor = AppIntentExecutor(
        project,
        timeline_output_path=str(tmp_path / "Timeline_Auto.json"),
    )
    execution = executor.execute(
        [
            AgentAction("optimize_youtube", {"quality": "1080p"}),
            AgentAction("auto_build_timeline", {}),
        ]
    )

    assert project.settings.width == 1920
    assert project.settings.height == 1080
    assert project.settings.fps == 30
    assert project.settings.codec == "h264"
    assert execution.timeline_plan is not None
    assert execution.timeline_plan.planned_speed == 0.5


def test_local_executor_moves_and_removes_media(tmp_path):
    project = Project(
        videos=[
            MediaItem("b.mp4", 30.0),
            MediaItem("a.mp4", 30.0),
        ],
        audios=[
            MediaItem("03.mp3", 20.0),
            MediaItem("01.mp3", 20.0),
            MediaItem("02.mp3", 20.0),
        ],
    )
    executor = AppIntentExecutor(
        project,
        timeline_output_path=str(tmp_path / "Timeline_Auto.json"),
    )

    executor.execute(
        [
            AgentAction("sort_audio_by_name", {}),
            AgentAction("move_video", {"from_position": 2, "to_position": 1}),
            AgentAction("remove_audio", {"position": 3}),
        ]
    )

    assert [x.name for x in project.audios] == ["01.mp3", "02.mp3"]
    assert [x.name for x in project.videos] == ["a.mp4", "b.mp4"]
