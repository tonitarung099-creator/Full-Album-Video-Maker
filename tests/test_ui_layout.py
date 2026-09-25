import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from full_album_maker.agent_actions import AgentAction, AgentDecision
from full_album_maker.controller import ProjectController
from full_album_maker.paths import asset_path
from full_album_maker.style import APP_STYLE
from full_album_maker.project import MediaItem, Project
from full_album_maker.timeline import TimelineEngine, project_signature
from full_album_maker.ui import MainWindow


def test_mockup_layout_has_no_overlap():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLE)

    window = MainWindow()
    window.resize(1180, 820)
    window.show()
    app.processEvents()

    assert asset_path("logo.svg").exists()
    assert window.splitter.count() == 3

    left, center, right = [window.splitter.widget(i) for i in range(3)]
    assert left.width() >= 280
    assert center.width() >= 500
    assert right.width() >= 295

    assert left.geometry().right() < center.geometry().left()
    assert center.geometry().right() < right.geometry().left()

    assert window.auto_timeline_btn.height() >= 54
    assert window.timeline_preview.height() >= 240
    assert window.render_btn.height() >= 34

    window.resize(1600, 900)
    app.processEvents()
    assert window.auto_timeline_btn.height() >= 68
    assert window.timeline_preview.height() >= 250
    assert window.render_btn.height() >= 42

    assert window.video_list.width() > 220
    assert window.audio_list.width() > 220
    assert window.chat.width() > 240

    assert len(window.bottom_labels) == 6
    for label in window.bottom_labels.values():
        assert label.height() >= 34

    assert window.timeline_status.text()
    assert window.video_total.text()
    assert window.audio_total.text()

    window.close()


def test_auto_timeline_starts_empty_without_media():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLE)

    window = MainWindow()
    assert window.timeline_ready is False
    assert window.project.videos == []
    assert window.project.audios == []
    window.close()


def test_ui_accepts_only_real_matching_timeline_plan():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLE)

    window = MainWindow()
    project = Project(
        videos=[MediaItem("video.mp4", 40.0)],
        audios=[MediaItem("song.mp3", 60.0)],
    )
    project.settings.min_speed = 0.5
    window.project = project
    window.controller.project = project

    plan = TimelineEngine().build(project)
    window.apply_timeline_plan(plan)
    app.processEvents()

    assert window.timeline_ready is True
    assert window.timeline_plan is plan
    assert window.timeline_preview.plan is plan
    assert "Timeline Siap" in window.timeline_status.text()

    project.audios.append(MediaItem("extra.mp3", 5.0))
    window.refresh()
    app.processEvents()

    assert window.timeline_ready is False
    assert window.timeline_plan is None
    assert window.timeline_preview.plan is None
    assert "Perlu Diperbarui" in window.timeline_status.text()
    window.close()


def test_auto_susun_timeline_builds_real_plan_and_json(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLE)

    import full_album_maker.ui as ui_module
    monkeypatch.setattr(ui_module, "output_dir", lambda: tmp_path)

    window = MainWindow()
    project = Project(
        videos=[MediaItem("video.mp4", 2400.0)],
        audios=[MediaItem("album.mp3", 3600.0)],
    )
    project.settings.auto_speed = False
    project.settings.manual_speed = 0.5
    project.settings.loop_mode = "loop"

    window.project = project
    window.controller.project = project
    window.refresh()

    window.auto_build_timeline()
    app.processEvents()

    assert window.timeline_ready is True
    assert window.timeline_plan is not None
    assert window.timeline_preview.plan is window.timeline_plan
    assert window.timeline_plan.duration == 3600.0
    assert window.timeline_plan.auto_cut_seconds == 1200.0
    assert window.timeline_plan.video_clips[0].source_out == 1800.0
    assert "Timeline Siap" in window.timeline_status.text()

    timeline_file = tmp_path / "Timeline_Auto.json"
    assert timeline_file.exists()
    assert window.timeline_file_path == str(timeline_file)
    assert "AUTO TIMELINE SELESAI" in window.chat.toPlainText()

    window.close()


def test_regenerate_replaces_old_timeline(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLE)

    import full_album_maker.ui as ui_module
    monkeypatch.setattr(ui_module, "output_dir", lambda: tmp_path)

    window = MainWindow()
    project = Project(
        videos=[MediaItem("video.mp4", 1200.0)],
        audios=[MediaItem("album.mp3", 3600.0)],
    )
    project.settings.auto_speed = True
    project.settings.min_speed = 0.5
    project.settings.loop_mode = "loop"

    window.project = project
    window.controller.project = project
    window.refresh()

    window.auto_build_timeline()
    first = window.timeline_plan
    assert first is not None
    assert first.loop_fill_seconds == 1200.0

    project.settings.min_speed = 0.4
    window.invalidate_timeline()
    window.auto_build_timeline()
    second = window.timeline_plan

    assert second is not None
    assert second is not first
    assert second.planned_speed == 0.4
    assert second.loop_fill_seconds == 600.0
    assert window.timeline_file_path == str(tmp_path / "Timeline_Auto.json")
    window.close()


def test_ui_executes_gemini_intents_through_local_app(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLE)

    import full_album_maker.ui as ui_module
    monkeypatch.setattr(ui_module, "output_dir", lambda: tmp_path)

    window = MainWindow()
    project = Project(
        videos=[MediaItem("video.mp4", 2400.0)],
        audios=[MediaItem("album.mp3", 3600.0)],
    )
    window.project = project
    window.controller = ProjectController(project)
    window.refresh()

    signature = project_signature(project)
    decision = AgentDecision(
        message="Saya pahami: slowmo 50 persen lalu susun semuanya.",
        actions=[
            AgentAction("set_slowmo", {"speed": 0.5}),
            AgentAction("auto_build_timeline", {}),
        ],
    )

    window._handle_agent_decision(decision, signature)
    app.processEvents()

    assert project.settings.auto_speed is False
    assert project.settings.manual_speed == 0.5
    assert window.timeline_ready is True
    assert window.timeline_plan is not None
    assert window.timeline_plan.auto_cut_seconds == 1200.0
    assert window.timeline_file_path == str(tmp_path / "Timeline_Auto.json")
    assert "GEMINI" in window.chat.toPlainText()
    assert "APP" in window.chat.toPlainText()
    window.close()


def test_ui_rejects_stale_gemini_intent(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLE)

    import full_album_maker.ui as ui_module
    monkeypatch.setattr(ui_module, "output_dir", lambda: tmp_path)

    window = MainWindow()
    project = Project(
        videos=[MediaItem("video.mp4", 60.0)],
        audios=[MediaItem("song.mp3", 60.0)],
    )
    window.project = project
    window.controller = ProjectController(project)
    old_signature = project_signature(project)

    project.audios.append(MediaItem("new-song.mp3", 20.0))
    decision = AgentDecision(
        message="Saya pahami perintahnya.",
        actions=[AgentAction("set_slowmo", {"speed": 0.4})],
    )

    window._handle_agent_decision(decision, old_signature)
    app.processEvents()

    assert project.settings.auto_speed is True
    assert project.settings.manual_speed == 1.0
    assert window.timeline_plan is None
    assert "tidak diterapkan" in window.chat.toPlainText()
    window.close()
