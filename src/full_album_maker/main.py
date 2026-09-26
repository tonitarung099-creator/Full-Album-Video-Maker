from __future__ import annotations

from full_album_maker.gemini_schema_compat import install_gemini_schema_compat
from full_album_maker.playlist_feature import install_feature
from full_album_maker.playlist_hardening import install_playlist_hardening
from full_album_maker.ui import run


install_feature()
install_gemini_schema_compat()
install_playlist_hardening()

if __name__ == "__main__":
    raise SystemExit(run())
