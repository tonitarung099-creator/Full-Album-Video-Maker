from __future__ import annotations

from full_album_maker.playlist_feature import install_feature
from full_album_maker.ui import run


install_feature()

if __name__ == "__main__":
    raise SystemExit(run())
