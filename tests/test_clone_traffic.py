from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "archive_clones.py"
spec = importlib.util.spec_from_file_location("archive_clones", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_overlapping_snapshots_preserve_history_and_partial_days(tmp_path: Path) -> None:
    snapshot, output = tmp_path / "snapshot.json", tmp_path / "archive"

    def collect(rows: list[dict]) -> dict:
        snapshot.write_text(json.dumps({"clones": rows}))
        module.archive(snapshot, output)
        return json.loads((output / "clones.json").read_text())

    def day(timestamp: str, count: int, uniques: int) -> dict:
        return {"timestamp": f"{timestamp}T00:00:00Z", "count": count, "uniques": uniques}

    first = [day("2026-11-01", 12, 3), day("2026-11-02", 5, 2)]
    assert collect(first)["total_clones"] == 17
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    collect(first)
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before

    data = collect([day("2026-11-02", 9, 4), day("2026-11-03", 7, 2)])
    assert data["total_clones"] == 28
    assert data["first_recorded_date"] == "2026-11-01"
    assert data["last_recorded_date"] == "2026-11-03"
    assert collect([day("2026-11-02", 2, 1)])["total_clones"] == 28
    assert collect([])["total_clones"] == 28
    assert "2026-11-02,9,4" in (output / "clones.csv").read_text()
    assert "Archived clones: 28" in (output / "clones.svg").read_text()


@pytest.mark.parametrize("payload", [{"message": "Forbidden"}, {"clones": [{"timestamp": "2026-11-01T00:00:00Z", "count": -1, "uniques": 0}]}])
def test_invalid_snapshot_leaves_archive_untouched(tmp_path: Path, payload: dict) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        module.archive(snapshot, tmp_path / "archive")
    assert not (tmp_path / "archive").exists()
