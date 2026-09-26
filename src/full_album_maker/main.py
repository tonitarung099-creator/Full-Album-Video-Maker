from __future__ import annotations

from full_album_maker.gemini_schema_compat import install_gemini_schema_compat
from full_album_maker.playlist_feature import install_feature
from full_album_maker.playlist_hardening import install_playlist_hardening
from full_album_maker.visual_feature import install_visual_feature
from full_album_maker.engine_hardening import install_engine_hardening
from full_album_maker.source_integrity import install_source_integrity
from full_album_maker.ui_hardening import install_ui_hardening
from full_album_maker.render_lifecycle import install_render_lifecycle
from full_album_maker.ui import run


install_feature()
install_gemini_schema_compat()
install_playlist_hardening()
install_visual_feature()
install_engine_hardening()
install_source_integrity()
install_ui_hardening()
install_render_lifecycle()

if __name__ == "__main__":
    raise SystemExit(run())
