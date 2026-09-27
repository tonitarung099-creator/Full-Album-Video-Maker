from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from full_album_maker.agent_actions import AgentAction
from full_album_maker.ai_editor import (
    AIEditorAmbiguity,
    AIEditorEnvelope,
    AIEditorError,
    AIEditorExecutor,
    EDITOR_SYSTEM,
    EDITOR_TOOLS,
    EditorAIContextBuilder,
    deterministic_action_id,
)
from full_album_maker.editor_controller import EditorController, RevisionConflict
from full_album_maker.editor_models import (
    Layer,
    MediaAsset,
    ProjectDocument,
    SongInstance,
    TimeBinding,
    seconds_to_tick,
)
from full_album_maker.gemini_agent import GeminiAgent
from full_album_maker.render_service_v2 import EditorRenderService


class FakePool:
    def __init__(self, response):
        self.response = response
        self.payloads = []

    def request_json(self, url, payload):
        self.payloads.append((url, payload))
        return self.response


class FailingTemplateStore:
    def create_from_document(self, *args, **kwargs):
        raise OSError("disk penuh")

    def load(self, template_id):
        raise AssertionError("load tidak diharapkan")


def _doc(*, duplicate_titles: bool = False) -> ProjectDocument:
    doc = ProjectDocument.new_empty("S09")
    for index in range(3):
        asset = MediaAsset(
            kind="audio",
            locator=f"C:/RAHASIA/audio-{index}.wav",
            source_duration_tick=seconds_to_tick(1.0),
        )
        doc.media.append(asset)
        title = "Duka" if duplicate_titles and index < 2 else f"Lagu {index + 1}"
        doc.playlist.entries.append(
            SongInstance(
                asset_id=asset.asset_id,
                source_out_tick=asset.source_duration_tick,
                display_title=title,
                display_artist=f"Artis {index + 1}",
            )
        )
    track = next(item for item in doc.tracks if item.kind == "visual")
    doc.layers.append(
        Layer(
            track_id=track.track_id,
            type="text",
            name="Judul Utama",
            order=0,
            time_binding=TimeBinding(kind="album"),
            properties={"text": "Awal", "font_size": 48, "color": "#ffffff"},
        )
    )
    doc.validate()
    return doc


def _envelope(doc: ProjectDocument, request_id: str, actions: list[AgentAction]) -> AIEditorEnvelope:
    return AIEditorEnvelope(
        action_id=deterministic_action_id(doc.project_id, doc.revision, request_id, actions),
        project_id=doc.project_id,
        expected_revision=doc.revision,
        actions=tuple(actions),
    )


def test_context_budget_redacts_paths_and_truncates_large_project():
    doc = _doc()
    source = doc.playlist.entries[0]
    for index in range(80):
        doc.playlist.entries.append(
            SongInstance(
                asset_id=source.asset_id,
                source_out_tick=source.source_out_tick,
                display_title=f"Tambahan {index}",
            )
        )
    builder = EditorAIContextBuilder(max_songs=12, max_layers=8)
    context = builder.build(doc, user_text="lagu tambahan")
    raw = json.dumps(context, ensure_ascii=False)
    assert len(context["songs"]) == 12
    assert context["truncated"]["songs"] is True
    assert "RAHASIA" not in raw
    assert "locator" not in raw
    assert "api_key" not in raw.casefold()
    assert context["project_id"] == doc.project_id
    assert context["revision"] == doc.revision


def test_stale_revision_and_wrong_project_id_do_not_mutate():
    doc = _doc()
    controller = EditorController(doc)
    before = controller.snapshot().content_signature()
    executor = AIEditorExecutor(controller)
    action = AgentAction("set_background", {"color": "#112233"})

    stale = AIEditorEnvelope("stale", doc.project_id, doc.revision + 1, (action,))
    with pytest.raises(RevisionConflict, match="stale"):
        executor.execute(stale)
    assert controller.snapshot().content_signature() == before
    assert controller.revision == doc.revision

    wrong = AIEditorEnvelope("wrong", "00000000-0000-4000-8000-000000000001", doc.revision, (action,))
    with pytest.raises(AIEditorError, match="project_id"):
        executor.execute(wrong)
    assert controller.snapshot().content_signature() == before


def test_invalid_batch_is_atomic_and_does_not_apply_earlier_actions():
    doc = _doc()
    controller = EditorController(doc)
    before = controller.snapshot().content_signature()
    actions = [
        AgentAction("set_background", {"color": "#223344"}),
        AgentAction("resize_layer", {"layer_query": "Judul Utama", "width": 0.001, "height": 0.2}),
    ]
    with pytest.raises(AIEditorError, match="0.02"):
        AIEditorExecutor(controller).execute(_envelope(doc, "atomic-fail", actions))
    assert controller.snapshot().content_signature() == before
    assert controller.revision == doc.revision


def test_multi_action_batch_is_one_revision_and_one_undo():
    doc = _doc()
    controller = EditorController(doc)
    before = controller.snapshot().content_signature()
    actions = [
        AgentAction("set_background", {"color": "#123456"}),
        AgentAction("add_text", {"text": "Dari Gemini"}),
        AgentAction("hide_layer", {"layer_query": "Judul Utama"}),
    ]
    result = AIEditorExecutor(controller).execute(_envelope(doc, "one-batch", actions))
    assert result.project_changed is True
    assert controller.revision == doc.revision + 1
    current = controller.snapshot()
    assert current.canvas.background_color == "#123456"
    assert any(layer.properties.get("text") == "Dari Gemini" for layer in current.layers)
    assert current.layers[0].enabled is False

    controller.undo()
    restored = controller.snapshot()
    assert restored.content_signature() == before
    assert len(restored.layers) == len(doc.layers)


def test_duplicate_response_is_idempotent_even_after_revision_changes():
    doc = _doc()
    controller = EditorController(doc)
    executor = AIEditorExecutor(controller)
    actions = [AgentAction("set_background", {"color": "#334455"})]
    envelope = _envelope(doc, "same-request", actions)
    first = executor.execute(envelope)
    revision_after = controller.revision
    second = executor.execute(envelope)
    assert first.project_changed is True
    assert second.duplicate is True
    assert controller.revision == revision_after
    assert controller.snapshot().canvas.background_color == "#334455"


def test_ambiguous_song_name_returns_candidates_without_mutation():
    doc = _doc(duplicate_titles=True)
    controller = EditorController(doc)
    before = controller.snapshot().content_signature()
    action = AgentAction("remove_song", {"song_query": "Duka"})
    with pytest.raises(AIEditorAmbiguity) as exc:
        AIEditorExecutor(controller).execute(_envelope(doc, "ambiguity", [action]))
    assert len(exc.value.candidates) == 2
    assert all("song_id" in item for item in exc.value.candidates)
    assert controller.snapshot().content_signature() == before


def test_stable_song_id_move_does_not_depend_on_duplicate_title():
    doc = _doc(duplicate_titles=True)
    controller = EditorController(doc)
    target = doc.playlist.entries[1]
    action = AgentAction("move_song", {"song_id": target.song_id, "target_position": 1})
    AIEditorExecutor(controller).execute(_envelope(doc, "move-id", [action]))
    assert controller.snapshot().playlist.entries[0].song_id == target.song_id


def test_render_is_only_requested_by_explicit_render_intent():
    doc = _doc()
    controller = EditorController(doc)
    executor = AIEditorExecutor(controller)
    edit = [AgentAction("set_background", {"color": "#445566"})]
    result = executor.execute(_envelope(doc, "edit-only", edit))
    assert result.render_requested is False

    current = controller.snapshot()
    render = [AgentAction("render_project", {})]
    result = executor.execute(_envelope(current, "explicit-render", render))
    assert result.render_requested is True
    assert result.project_changed is False


def test_save_template_failure_does_not_rollback_valid_design_commit():
    doc = _doc()
    controller = EditorController(doc)
    executor = AIEditorExecutor(controller, template_store=FailingTemplateStore())
    actions = [
        AgentAction("set_background", {"color": "#556677"}),
        AgentAction("save_template", {"label": "Layout AI"}),
    ]
    result = executor.execute(_envelope(doc, "save-side-effect", actions))
    assert controller.snapshot().canvas.background_color == "#556677"
    assert controller.revision == doc.revision + 1
    assert "disk penuh" in result.side_effect_error
    assert "Desain diterapkan" in result.side_effect_error


def test_mock_gemini_editor_registry_is_deterministic_and_render_explicit():
    pool = FakePool(
        {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {"functionCall": {"name": "add_spectrum", "args": {"preset": "neon_bars"}}},
                            {"functionCall": {"name": "render_project", "args": {}}},
                        ],
                    }
                }
            ]
        }
    )
    agent = GeminiAgent(pool, model="gemini-test", tools=EDITOR_TOOLS, system_prompt=EDITOR_SYSTEM)
    doc = _doc()
    context = EditorAIContextBuilder().build(doc, user_text="tambah spectrum lalu render")
    decision = agent.interpret("tambah spectrum lalu render", context)
    assert [item.name for item in decision.actions] == ["add_spectrum", "render_project"]
    payload = pool.payloads[0][1]
    tool_names = {item["name"] for item in payload["tools"][0]["functionDeclarations"]}
    assert "render_project" in tool_names
    assert "remove_song" in tool_names
    assert doc.project_id in payload["systemInstruction"]["parts"][0]["text"]


def test_manual_render_remains_offline_and_needs_no_gemini_key(tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg tidak tersedia")
    wav = tmp_path / "offline.wav"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.35",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(wav),
        ],
        check=True,
    )
    doc = ProjectDocument.new_empty("Offline render")
    asset = MediaAsset(kind="audio", locator=str(wav), source_duration_tick=seconds_to_tick(0.35))
    doc.media.append(asset)
    doc.playlist.entries.append(
        SongInstance(asset_id=asset.asset_id, source_out_tick=asset.source_duration_tick, display_title="Offline")
    )
    doc.layers.append(
        Layer(
            track_id=doc.tracks[0].track_id,
            type="background",
            name="BG",
            time_binding=TimeBinding(kind="album"),
            properties={"mode": "solid", "color": "#101114"},
        )
    )
    output = tmp_path / "offline.mp4"
    result = EditorRenderService(ffmpeg=ffmpeg).render(doc, str(output))
    assert Path(result).exists() and Path(result).stat().st_size > 0
