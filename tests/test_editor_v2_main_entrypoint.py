from pathlib import Path


def test_main_entrypoint_imports_v14_window_after_legacy_installers():
    path = Path("src/full_album_maker/main.py")
    source = path.read_text(encoding="utf-8")
    entrypoint = "from full_album_maker.v14_window import run"
    assert entrypoint in source
    assert source.index("install_async_import()") < source.index(entrypoint)
    assert "from full_album_maker.editor_window import run" not in source
