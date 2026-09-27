from pathlib import Path


def test_main_entrypoint_imports_editor_window_after_legacy_installers():
    path = Path("src/full_album_maker/main.py")
    source = path.read_text(encoding="utf-8")
    assert "from full_album_maker.editor_window import run" in source
    assert source.index("install_async_import()") < source.index("from full_album_maker.editor_window import run")
