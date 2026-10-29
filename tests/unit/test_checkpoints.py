import json

from localdub.core.jobs.checkpoints import CheckpointStore, atomic_write_json, fingerprint


def test_fingerprint_tracks_params_and_file_content(tmp_path):
    source = tmp_path / "input.txt"
    source.write_text("a")
    first = fingerprint({"x": 1}, [source])
    assert fingerprint({"x": 2}, [source]) != first
    source.write_text("b")
    assert fingerprint({"x": 1}, [source]) != first


def test_checkpoint_lifecycle_and_missing_output(tmp_path):
    output = tmp_path / "out.dat"
    output.write_text("ok")
    store = CheckpointStore(tmp_path)
    store.mark_complete("tts", "abc", [output], 0.2)
    assert store.is_complete("tts", "abc")
    assert not store.is_complete("tts", "changed")
    output.unlink()
    assert not store.is_complete("tts", "abc")
    store.invalidate(["tts"])
    assert not store.records()


def test_atomic_write_json(tmp_path):
    p = tmp_path / "dir" / "data.json"
    atomic_write_json(p, {"word": "ľšč"})
    assert json.loads(p.read_text(encoding="utf-8")) == {"word": "ľšč"}
    assert not p.with_name("data.json.tmp").exists()
