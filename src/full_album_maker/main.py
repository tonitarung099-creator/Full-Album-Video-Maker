from __future__ import annotations

import sys

from full_album_maker.gemini_schema_compat import install_gemini_schema_compat
from full_album_maker.playlist_feature import install_feature
from full_album_maker.playlist_hardening import install_playlist_hardening
from full_album_maker.visual_feature import install_visual_feature
from full_album_maker.engine_hardening import install_engine_hardening
from full_album_maker.source_integrity import install_source_integrity
from full_album_maker.ui_hardening import install_ui_hardening
from full_album_maker.atomic_bundle import install_atomic_bundle
from full_album_maker.render_lifecycle import install_render_lifecycle
from full_album_maker.project_dirty import install_project_dirty_state
from full_album_maker.async_import import install_async_import


install_feature()
install_gemini_schema_compat()
install_playlist_hardening()
install_visual_feature()
install_engine_hardening()
install_source_integrity()
install_ui_hardening()
install_atomic_bundle()
install_render_lifecycle()
install_project_dirty_state()
install_async_import()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--portable-smoke" in args:
        from full_album_maker.release_smoke import run_portable_smoke

        return run_portable_smoke()

    # Import after installing the legacy compatibility layers so the v1.4 window
    # inherits the proven Editor V2 shell while extending only Gemini intents/context.
    from full_album_maker.v14_window import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
