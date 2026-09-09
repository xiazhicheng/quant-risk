from scripts.quantrisk.snapshot import read_snapshot, write_snapshot


def test_snapshot_is_canonical_and_replayable(tmp_path):
    payload = {"market": "cn", "items": [{"code": "600000", "score": 80}], "run": "x"}
    first = write_snapshot(payload, tmp_path / "snapshot.json")
    second = write_snapshot({"run": "x", "items": [{"score": 80, "code": "600000"}], "market": "cn"}, tmp_path / "snapshot.json")
    assert first["snapshot_hash"] == second["snapshot_hash"]
    assert read_snapshot(tmp_path / "snapshot.json") == payload
