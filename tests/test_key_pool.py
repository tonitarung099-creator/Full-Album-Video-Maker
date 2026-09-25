from pathlib import Path
from full_album_maker.key_pool import GeminiKeyPool

def test_pool_caps_at_100(tmp_path: Path):
    pool = GeminiKeyPool(tmp_path / "keys.dat")
    keys = [f"test-auth-key-{i:03d}-abcdefghijklmnopqrstuvwxyz" for i in range(120)]
    added, overflow = pool.add_keys(keys)
    assert added == 100
    assert overflow == 20
    assert len(pool.records) == 100

def test_pool_deduplicates(tmp_path: Path):
    pool = GeminiKeyPool(tmp_path / "keys.dat")
    key = "test-auth-key-abcdefghijklmnopqrstuvwxyz"
    added, _ = pool.add_keys([key, key])
    assert added == 1
