from __future__ import annotations

from pathlib import Path

import pytest

from full_album_maker.editor_models import MediaAsset, ProjectDocument, SongInstance, seconds_to_tick
from full_album_maker.render_service_v2 import EditorRenderService, RenderErrorV2


class _MaterializingRunner:
    def run(self, args, **kwargs) -> None:
        output = Path(list(args)[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"FAKE-MP4")


def _minimal_render_doc(tmp_path: Path) -> ProjectDocument:
    source = tmp_path / "source.wav"
    source.write_bytes(b"not-decoded-by-fake-runner")
    document = ProjectDocument.new_empty("RC")
    asset = MediaAsset(
        kind="audio",
        locator=str(source),
        source_duration_tick=seconds_to_tick(0.25),
    )
    document.media.append(asset)
    document.playlist.entries.append(
        SongInstance(
            asset_id=asset.asset_id,
            source_out_tick=asset.source_duration_tick,
            display_title="RC Song",
        )
    )
    document.validate()
    return document


def test_render_service_appends_mp4_when_save_dialog_returns_no_suffix(tmp_path: Path):
    document = _minimal_render_doc(tmp_path)
    requested = tmp_path / "Album Final"

    result = EditorRenderService(
        ffmpeg="ffmpeg",
        runner=_MaterializingRunner(),
    ).render(document, str(requested))

    output = tmp_path / "Album Final.mp4"
    assert Path(result) == output.resolve()
    assert output.read_bytes() == b"FAKE-MP4"
    assert (tmp_path / "Album Final_YouTube_Chapter.txt").exists()
    assert (tmp_path / "Album Final_Tracklist.txt").exists()
    assert (tmp_path / "Album Final_Timeline_Final.json").exists()
    assert not requested.exists()


def test_render_service_rejects_misleading_non_mp4_suffix(tmp_path: Path):
    document = _minimal_render_doc(tmp_path)
    with pytest.raises(RenderErrorV2, match=r"\.mp4"):
        EditorRenderService(
            ffmpeg="ffmpeg",
            runner=_MaterializingRunner(),
        ).render(document, str(tmp_path / "Album Final.avi"))


def test_local_portable_build_keeps_s12_release_contract():
    root = Path(__file__).resolve().parents[1]
    script = (root / "build" / "build_portable.ps1").read_text(encoding="utf-8")

    required_fragments = (
        "pip==26.2.1",
        "build/requirements-windows.lock",
        "b745ed683204c8e154d627bf75f2e530b7b2eec51d14fabdc8771912423ba67e",
        "23e54b51ddffbc7713c583748e3bd86f62b1fa4a",
        "NotoSans.ttf",
        "write_release_capabilities.py",
        "--portable-smoke",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "Get-Command python",
        "Get-Command ffmpeg",
        "output_streams",
    )
    for fragment in required_fragments:
        assert fragment in script

    assert "pip install --upgrade pip" not in script
    assert "pip install -r requirements-dev.txt" not in script
