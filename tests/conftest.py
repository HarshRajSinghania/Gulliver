from __future__ import annotations

import pytest

from gulliver.config import load_settings
from gulliver.demo import build_demo


@pytest.fixture(scope="session")
def demo_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("data") / "demo.duckdb"
    build_demo(path, events=400_000, users=20_000)
    return str(path)


@pytest.fixture
def state(tmp_path, monkeypatch):
    home = tmp_path / "state"
    monkeypatch.setenv("GULLIVER_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    for key in ("GULLIVER_DSN", "GULLIVER_CONFIG", "GULLIVER_MAX_QUERY_USD", "GULLIVER_REHEARSE_OVER_BYTES"):
        monkeypatch.delenv(key, raising=False)
    return home


@pytest.fixture
def settings(demo_db, state):
    return load_settings(dsn=demo_db)
