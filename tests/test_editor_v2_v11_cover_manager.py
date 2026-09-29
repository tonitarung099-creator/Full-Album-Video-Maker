from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication
import pytest

from full_album_maker.cover_manager import (
    CoverAssignmentService,
    CoverManagerPanel,
    normalize_cover_key,
)
from full_album_maker.editor_commands import CommandError
from full_album_maker.editor_controller import EditorController
from full_album_maker.editor_models import (
    MediaAsset,
    ProjectDocument,
    SongInstance,
    seconds_to_tick,
)
from full_album_maker.s11_workspace import S11EditorWorkspace


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _cover_doc() -> tuple[ProjectDocument, list[SongInstance], list[MediaAsset]]:
    doc = ProjectDocument.new_empty("Cover Manager v1.1")
    duration = seconds_to_tick(60)

    song_specs = [
        ("C:/music/01 - Mr. Brightside.wav", "Mr. Brightside", "The Killers"),
        ("C:/music/02 - Second Song.wav", "", "Artist B"),
        ("C:/music/03 - Ambiguous Song.wav", "Ambiguous Song", "Artist C"),
        ("C:/music/04 - No Cover.wav", "No Cover", "Artist D"),
    ]
    songs: list[SongInstance] = []
    for locator, title, artist in song_specs:
        audio = MediaAsset(
            kind="audio",
            locator=locator,
            original_name=locator.rsplit("/", 1)[-1],
            source_duration_tick=duration,
        )
        doc.media.append(audio)
        song = SongInstance(
            asset_id=audio.asset_id,
            source_out_tick=duration,
            display_title=title,
            display_artist=artist,
        )
        doc.playlist.entries.append(song)
        songs.append(song)

    images = [
        MediaAsset(kind="image", locator="C:/covers/01 - Mr. Brightside.png", original_name="01 - Mr. Brightside.png"),
        MediaAsset(kind="image", locator="C:/covers/Second Song.jpg", original_name="Second Song.jpg"),
        MediaAsset(kind="image", locator="C:/covers/Ambiguous Song.png", original_name="Ambiguous Song.png"),
        MediaAsset(kind="image", locator="C:/covers/Ambiguous Song.webp", original_name="Ambiguous Song.webp"),
    ]
    doc.media.extend(images)
    doc.validate()
    return doc, songs, images


def test_normalizer_keeps_real_title_dots_and_removes_track_prefixes():
    assert normalize_cover_key("Mr. Brightside") == "mr brightside"
    assert normalize_cover_key("01 - Mr. Brightside.png") == "mr brightside"
    assert normalize_cover_key("02_Second Song.wav") == "second song"
    assert normalize_cover_key("  Café—Live  ") == "café live"


def test_auto_match_uses_exact_unique_names_and_refuses_ambiguity():
    doc, songs, images = _cover_doc()
    report = CoverAssignmentService.auto_match(doc)

    assert report.matches[songs[0].song_id] == images[0].asset_id
    assert report.matches[songs[1].song_id] == images[1].asset_id
    assert songs[2].song_id in report.ambiguous_song_ids
    assert songs[3].song_id in report.unmatched_song_ids
    assert songs[2].song_id not in report.matches
    assert songs[3].song_id not in report.matches


def test_auto_match_only_empty_preserves_existing_cover_and_can_explicitly_replace():
    doc, songs, images = _cover_doc()
    songs[0].cover_asset_id = images[1].asset_id
    doc.validate()

    protected = CoverAssignmentService.auto_match(doc, only_empty=True)
    assert songs[0].song_id in protected.skipped_existing_song_ids
    assert songs[0].song_id not in protected.matches

    replace = CoverAssignmentService.auto_match(doc, only_empty=False)
    assert replace.matches[songs[0].song_id] == images[0].asset_id


def test_bulk_assignment_is_one_controller_transaction_and_one_undo():
    doc, songs, images = _cover_doc()
    controller = EditorController(doc)
    start_revision = controller.revision
    commands = CoverAssignmentService.bulk_commands(
        controller.snapshot(),
        [songs[0].song_id, songs[1].song_id, songs[0].song_id],
        images[0].asset_id,
    )
    assert len(commands) == 2

    controller.dispatch(commands)
    changed = controller.snapshot()
    assert changed.revision == start_revision + 1
    assert changed.song_map()[songs[0].song_id].cover_asset_id == images[0].asset_id
    assert changed.song_map()[songs[1].song_id].cover_asset_id == images[0].asset_id

    controller.undo()
    reverted = controller.snapshot()
    assert reverted.song_map()[songs[0].song_id].cover_asset_id is None
    assert reverted.song_map()[songs[1].song_id].cover_asset_id is None


def test_bulk_assignment_rejects_unknown_song_and_non_image_asset():
    doc, songs, _ = _cover_doc()
    audio_asset_id = songs[0].asset_id
    with pytest.raises(CommandError, match="image"):
        CoverAssignmentService.bulk_commands(doc, [songs[0].song_id], audio_asset_id)
    with pytest.raises(CommandError, match="Lagu tidak ditemukan"):
        CoverAssignmentService.bulk_commands(doc, ["not-a-song"], None)


def test_cover_panel_supports_multi_selection_by_stable_song_id():
    _app()
    doc, songs, images = _cover_doc()
    panel = CoverManagerPanel()
    panel.set_document(doc)

    assert panel.table.rowCount() == 4
    assert panel.cover_combo.count() == len(images)
    selection = panel.table.selectionModel()
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    selection.select(panel.table.model().index(0, 0), flags)
    selection.select(panel.table.model().index(2, 0), flags)
    assert set(panel.selected_song_ids()) == {songs[0].song_id, songs[2].song_id}
    assert panel.assign_button.isEnabled()
    assert panel.clear_button.isEnabled()


def test_workspace_exposes_cover_tab_and_bulk_action_remains_one_undo(tmp_path):
    _app()
    doc, songs, images = _cover_doc()
    workspace = S11EditorWorkspace(
        doc,
        custom_template_root=tmp_path / "templates",
        template_preview_enabled=False,
    )

    tab_names = [workspace.tabs.tabText(index) for index in range(workspace.tabs.count())]
    assert "Cover" in tab_names
    revision = workspace.session.revision
    workspace._assign_covers_v11(
        [songs[0].song_id, songs[1].song_id], images[0].asset_id
    )
    assert workspace.session.revision == revision + 1
    changed = workspace.session.snapshot().song_map()
    assert changed[songs[0].song_id].cover_asset_id == images[0].asset_id
    assert changed[songs[1].song_id].cover_asset_id == images[0].asset_id

    workspace.undo()
    reverted = workspace.session.snapshot().song_map()
    assert reverted[songs[0].song_id].cover_asset_id is None
    assert reverted[songs[1].song_id].cover_asset_id is None
