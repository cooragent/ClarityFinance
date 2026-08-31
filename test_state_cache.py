from datetime import datetime
import sqlite3

import pytest

import api
from clarity.core.state_store import _location, read_state, state_history, write_state


def test_legacy_json_is_imported_then_sqlite_becomes_source_of_truth(tmp_path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text('{"value":1}', encoding="utf-8")

    assert read_state(legacy, {}) == {"value": 1}
    write_state(legacy, {"value": 2})

    assert read_state(legacy, {}) == {"value": 2}
    assert legacy.read_text(encoding="utf-8") == '{"value":1}'
    assert (tmp_path / "clarity.sqlite3").exists()


@pytest.mark.asyncio
async def test_hotspots_and_dashboard_keep_latest_state(tmp_path, monkeypatch):
    calls = 0

    async def fetch(limit):
        nonlocal calls
        assert limit == 100
        calls += 1
        return {"date": datetime.now().strftime("%Y-%m-%d"), "hotspots": [{"title": str(i)} for i in range(25)]}

    monkeypatch.setattr(api, "HOTSPOTS_CACHE_FILE", tmp_path / "hotspots.json")
    monkeypatch.setattr(api, "DASHBOARD_CACHE_FILE", tmp_path / "dashboard.json")
    monkeypatch.setattr(api, "get_today_hotspots", fetch)

    assert (await api.today_hotspots(10, True))["hotspots"][0]["title"] == "0"
    more = await api.today_hotspots(20, False)
    assert len(more["hotspots"]) == 20 and more["has_more"]
    assert calls == 1

    api._atomic_json(api.HOTSPOTS_CACHE_FILE, {"date": "2026-08-30", "cache_limit": 100, "hotspots": []})
    await api.today_hotspots(10, False)
    assert calls == 2

    api._atomic_json(api.DASHBOARD_CACHE_FILE, {"markdown": "# saved"})
    assert await api.latest_dashboard() == {"markdown": "# saved"}
    history = state_history(api.DASHBOARD_CACHE_FILE)
    assert history[-1]["value"] == {"markdown": "# saved"}
    database, key = _location(api.DASHBOARD_CACHE_FILE)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE state_snapshots SET value = '{}' WHERE key = ?", (key,))

    monkeypatch.setattr(api, "DASHBOARD_CACHE_FILE", tmp_path / "missing-dashboard.json")
    monkeypatch.setattr(api, "RUNTIME_DIR", tmp_path)
    (tmp_path / "dashboard_20260830.md").write_text("# previous", encoding="utf-8")
    assert await api.latest_dashboard() == {"markdown": "# previous"}
