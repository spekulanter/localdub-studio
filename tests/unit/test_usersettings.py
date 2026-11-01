from __future__ import annotations

import json

from localdub.core import usersettings


def test_the_upload_limit_must_be_a_sensible_whole_number():
    assert usersettings.valid_upload_mb(4096)
    assert usersettings.valid_upload_mb(usersettings.MIN_UPLOAD_MB)
    assert not usersettings.valid_upload_mb(usersettings.MIN_UPLOAD_MB - 1)
    assert not usersettings.valid_upload_mb(usersettings.MAX_UPLOAD_MB + 1)
    assert not usersettings.valid_upload_mb(True)  # a bool is an int in Python
    assert not usersettings.valid_upload_mb("4096")
    assert not usersettings.valid_upload_mb(None)


def test_saved_settings_come_back_and_survive_a_second_save(tmp_path):
    path = tmp_path / "sub" / "user-settings.json"
    assert usersettings.load(path) == {}
    usersettings.save(path, {"max_upload_mb": 8192})
    assert usersettings.load(path) == {"max_upload_mb": 8192}
    usersettings.save(path, {})
    assert usersettings.load(path) == {}
    assert not path.with_suffix(".tmp").exists()


def test_a_damaged_or_hostile_file_is_ignored(tmp_path):
    path = tmp_path / "user-settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert usersettings.load(path) == {}
    path.write_text(json.dumps({"max_upload_mb": -5}), encoding="utf-8")
    assert usersettings.load(path) == {}
    path.write_text(json.dumps([1, 2]), encoding="utf-8")
    assert usersettings.load(path) == {}
