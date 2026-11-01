from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import httpx
import pytest
from packaging.tags import Tag

from localdub import extras
from localdub.extras import ExtrasError, Wheel


@pytest.fixture(autouse=True)
def _windows_markers(monkeypatch):
    """The export fixtures below are Windows lock lines; evaluate their markers as on Windows."""
    monkeypatch.setattr(
        extras, "MARKER_ENV", {"sys_platform": "win32", "platform_machine": "AMD64"}
    )


EXPORT_BASE = """annotated-types==0.8.0 ; sys_platform == 'win32' \\
    --hash=sha256:aa \\
    --hash=sha256:bb
    # via pydantic
numpy==2.4.0 ; sys_platform == 'win32' \\
    --hash=sha256:cc
    # via
    #   demucs
"""
EXPORT_FULL = (
    EXPORT_BASE
    + """torch==2.9.1+cu128 ; sys_platform == 'win32' \\
    --hash=sha256:dd
    # via demucs
Sym_Py==1.14.0 ; sys_platform == 'win32' \\
    --hash=sha256:ee
"""
)


def test_parse_pins_ignores_hashes_comments_and_normalises_names():
    pins = extras.parse_pins(EXPORT_FULL)
    assert pins == {
        "annotated-types": "0.8.0", "numpy": "2.4.0", "torch": "2.9.1+cu128", "sym-py": "1.14.0",
    }  # fmt: skip


def test_extra_only_keeps_added_and_changed_pins():
    base = extras.parse_pins(EXPORT_BASE)
    full = extras.parse_pins(EXPORT_FULL)
    assert extras.extra_only(base, full) == {"torch": "2.9.1+cu128", "sym-py": "1.14.0"}
    changed = {**full, "numpy": "2.5.0"}
    assert extras.extra_only(base, changed)["numpy"] == "2.5.0"


PKG = {
    "name": "safetensors",
    "version": "0.8.0",
    "wheels": [
        {"url": "https://x/safetensors-0.8.0-cp310-abi3-win_amd64.whl", "hash": "sha256:" + "a" * 64, "size": 10},
        {"url": "https://x/safetensors-0.8.0-cp312-cp312-manylinux_2_17_x86_64.whl", "hash": "sha256:" + "b" * 64},
        {"url": "https://x/safetensors-0.8.0-cp312-cp312-win_amd64.whl", "hash": "sha256:" + "c" * 64, "size": 11},
    ],
}  # fmt: skip
WIN312 = [Tag("cp312", "cp312", "win_amd64"), Tag("cp310", "abi3", "win_amd64")]


def test_pick_wheel_prefers_the_best_matching_tag_and_skips_other_platforms():
    w = extras.pick_wheel(PKG, WIN312)
    assert w.url.endswith("cp312-cp312-win_amd64.whl") and w.sha256 == "c" * 64 and w.size == 11
    only_abi3 = {**PKG, "wheels": [PKG["wheels"][0], PKG["wheels"][1]]}
    assert extras.pick_wheel(only_abi3, WIN312).sha256 == "a" * 64


def test_pick_wheel_refuses_without_compatible_wheel_or_without_hash():
    with pytest.raises(ExtrasError, match="No prebuilt wheel"):
        extras.pick_wheel({**PKG, "wheels": [PKG["wheels"][1]]}, WIN312)
    no_hash = {**PKG, "wheels": [{"url": PKG["wheels"][2]["url"]}]}
    with pytest.raises(ExtrasError, match="no SHA-256"):
        extras.pick_wheel(no_hash, WIN312)


def test_wheel_filename_is_url_decoded():
    w = Wheel(
        "torch",
        "2.9.1+cu128",
        "https://h/whl/torch-2.9.1%2Bcu128-cp312-cp312-win_amd64.whl",
        "x",
        None,
    )
    assert w.filename == "torch-2.9.1+cu128-cp312-cp312-win_amd64.whl"
    assert w.estimate == extras.SIZE_ESTIMATES["torch"]


def make_client(payload: bytes, *, ranges: bool = True, record: list | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if record is not None:
            record.append(request.headers.get("range"))
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-length": str(len(payload))})
        rng = request.headers.get("range")
        if rng and ranges:
            start = int(rng.split("=")[1].rstrip("-"))
            return httpx.Response(206, content=payload[start:])
        return httpx.Response(200, content=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def wheel_for(payload: bytes, name: str = "pkg-1.0-py3-none-any.whl") -> Wheel:
    return Wheel(
        "pkg", "1.0", f"https://h/{name}", hashlib.sha256(payload).hexdigest(), len(payload)
    )


def test_download_verifies_hash_reports_bytes_and_reuses_a_finished_file(tmp_path: Path):
    payload = b"wheel-bytes" * 5000
    w = wheel_for(payload)
    seen: list[int] = []
    path = extras.download_wheel(w, len(payload), tmp_path, make_client(payload), seen.append)
    assert path.read_bytes() == payload and seen[-1] == len(payload)
    assert not list(tmp_path.glob("*.part"))
    calls: list = []
    again = extras.download_wheel(
        w, len(payload), tmp_path, make_client(payload, record=calls), lambda n: None
    )
    assert again == path and calls == []  # already complete: no request at all


def test_download_resumes_a_partial_file_with_a_range_request(tmp_path: Path):
    payload = bytes(range(256)) * 400
    w = wheel_for(payload)
    (tmp_path / (w.filename + ".part")).write_bytes(payload[:50_000])
    calls: list = []
    path = extras.download_wheel(
        w, len(payload), tmp_path, make_client(payload, record=calls), lambda n: None
    )
    assert path.read_bytes() == payload and calls == ["bytes=50000-"]


def test_download_restarts_when_the_server_ignores_the_range(tmp_path: Path):
    payload = b"x" * 40_000
    w = wheel_for(payload)
    (tmp_path / (w.filename + ".part")).write_bytes(payload[:1000])
    path = extras.download_wheel(
        w, len(payload), tmp_path, make_client(payload, ranges=False), lambda n: None
    )
    assert path.read_bytes() == payload


def test_download_rejects_and_removes_a_corrupted_file(tmp_path: Path):
    payload = b"good" * 1000
    w = wheel_for(payload)
    with pytest.raises(ExtrasError, match="checksum mismatch"):
        extras.download_wheel(
            w, len(payload), tmp_path, make_client(b"evil" * 1000), lambda n: None
        )
    assert list(tmp_path.iterdir()) == []


def test_resolve_sizes_uses_the_lock_and_asks_the_server_when_unknown():
    known = Wheel("a", "1", "https://h/a-1-py3-none-any.whl", "x", 123)
    unknown = Wheel("b", "1", "https://h/b-1-py3-none-any.whl", "x", None)
    sizes = extras.resolve_sizes([known, unknown], make_client(b"z" * 777))
    assert sizes == {known.filename: 123, unknown.filename: 777}


def test_activate_needs_the_complete_marker_and_appends_to_the_end_of_sys_path(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(extras.EXTRAS_ENV, str(tmp_path / "ex"))
    (tmp_path / "ex").mkdir()
    assert extras.activate() is False  # half-installed folder is ignored
    (tmp_path / "ex" / extras.COMPLETE).write_text("{}", encoding="utf-8")
    saved = list(sys.path)
    try:
        assert extras.activate() is True
        assert sys.path[-1] == str(tmp_path / "ex") and sys.path[: len(saved)] == saved
        assert extras.activate() is True and sys.path.count(str(tmp_path / "ex")) == 1
    finally:
        sys.path[:] = saved


def test_install_end_to_end_with_a_fake_uv(tmp_path, monkeypatch):
    payload = b"fake wheel" * 100
    w = wheel_for(payload, "pkg-1.0-py3-none-any.whl")
    monkeypatch.setattr(extras, "build_plan", lambda **kw: [w])
    monkeypatch.setenv(extras.EXTRAS_ENV, str(tmp_path / "extras"))
    ran: list[list[str]] = []

    def fake_run(cmd, *, cwd=None, env=None):
        ran.append([str(c) for c in cmd])
        target = Path(str(cmd[cmd.index("--target") + 1]))
        (target / "torch").mkdir(parents=True)
        (target / "torch" / "__init__.py").write_text("", encoding="utf-8")
        assert env and "UV_CACHE_DIR" in env
        return ""

    monkeypatch.setattr(extras, "_run", fake_run)
    events: list[tuple[int, int, str]] = []
    saved = list(sys.path)
    try:
        extras.install(
            lambda d, t, m: events.append((d, t, m)), client=make_client(payload), uv=Path("uv.exe")
        )
    finally:
        sys.path[:] = saved
    cmd = ran[0]
    assert cmd[1:3] == ["pip", "install"] and "--no-deps" in cmd and "--no-index" in cmd
    assert cmd[cmd.index("--python") + 1] == sys.executable
    assert (tmp_path / "extras" / extras.COMPLETE).is_file() and (
        tmp_path / "extras" / "torch"
    ).is_dir()
    assert not (tmp_path / "extras-download").exists() and not (tmp_path / "extras-new").exists()
    grand = len(payload) + int(len(payload) * extras.UNPACK_FACTOR)
    assert events[0][2] == "Preparing..." and events[-1] == (grand, grand, "Done")
    assert all(d <= t for d, t, _ in events)  # never above 100 %
    assert any(m.startswith("Downloading pkg (") and " of " in m for _, _, m in events)


def test_install_stops_before_downloading_when_the_disk_is_too_small(tmp_path, monkeypatch):
    w = wheel_for(b"x" * 100)
    monkeypatch.setattr(extras, "build_plan", lambda **kw: [w])
    monkeypatch.setattr(extras, "_free_bytes", lambda p: 10)
    monkeypatch.setenv(extras.EXTRAS_ENV, str(tmp_path / "extras"))
    calls: list = []
    with pytest.raises(ExtrasError, match="Not enough free disk space"):
        extras.install(
            lambda *a: None, client=make_client(b"x" * 100, record=calls), uv=Path("uv.exe")
        )
    assert calls == [] or calls == [None]  # at most the size lookup, never a download


def test_install_reports_a_network_failure_in_plain_words(tmp_path, monkeypatch):
    payload = b"y" * 100
    w = Wheel(
        "pkg", "1.0", "https://h/pkg-1.0-py3-none-any.whl", hashlib.sha256(payload).hexdigest(), 100
    )
    monkeypatch.setattr(extras, "build_plan", lambda **kw: [w])
    monkeypatch.setenv(extras.EXTRAS_ENV, str(tmp_path / "extras"))

    def boom(request):
        raise httpx.ConnectError("no route")

    client = httpx.Client(transport=httpx.MockTransport(boom))
    with pytest.raises(ExtrasError, match="Check your internet connection"):
        extras.install(lambda *a: None, client=client, uv=Path("uv.exe"))


def test_a_file_that_was_written_completely_but_never_renamed_is_verified_not_downloaded_again(
    tmp_path,
):
    payload = b"complete wheel" * 100
    w = wheel_for(payload)
    (tmp_path / (w.filename + ".part")).write_bytes(payload)
    calls: list = []
    path = extras.download_wheel(
        w, len(payload), tmp_path, make_client(payload, record=calls), lambda n: None
    )
    assert path.read_bytes() == payload and calls == []


def test_a_restarted_download_never_pulls_the_progress_back(tmp_path, monkeypatch):
    payload = b"w" * 40_000
    w = wheel_for(payload, "pkg-1.0-py3-none-any.whl")
    (tmp_path / "extras-download").mkdir()
    (tmp_path / "extras-download" / (w.filename + ".part")).write_bytes(payload[:30_000])
    monkeypatch.setattr(extras, "build_plan", lambda **kw: [w])
    monkeypatch.setenv(extras.EXTRAS_ENV, str(tmp_path / "extras"))
    monkeypatch.setattr(
        extras,
        "_run",
        lambda cmd, **kw: (Path(str(cmd[cmd.index("--target") + 1])).mkdir(parents=True), "")[1],
    )
    events: list[int] = []
    saved = list(sys.path)
    try:
        # this server ignores Range requests, so the download starts again from byte 0
        extras.install(
            lambda d, t, m: events.append(d),
            client=make_client(payload, ranges=False),
            uv=Path("uv.exe"),
        )
    finally:
        sys.path[:] = saved
    assert events == sorted(events)


def test_a_failed_unpack_removes_the_half_written_folder_but_keeps_the_wheels(
    tmp_path, monkeypatch
):
    payload = b"w" * 1000
    w = wheel_for(payload, "pkg-1.0-py3-none-any.whl")
    monkeypatch.setattr(extras, "build_plan", lambda **kw: [w])
    monkeypatch.setenv(extras.EXTRAS_ENV, str(tmp_path / "extras"))

    def failing_uv(cmd, **kw):
        target = Path(str(cmd[cmd.index("--target") + 1]))
        (target / "torch").mkdir(parents=True)
        raise ExtrasError("uv failed: disk full")

    monkeypatch.setattr(extras, "_run", failing_uv)
    with pytest.raises(ExtrasError, match="disk full"):
        extras.install(lambda *a: None, client=make_client(payload), uv=Path("uv.exe"))
    assert not (tmp_path / "extras-new").exists()  # no multi-GB leftovers
    assert (tmp_path / "extras-download" / w.filename).is_file()  # a retry does not download again


def test_replacing_an_installation_that_is_in_use_fails_cleanly_and_keeps_the_old_one(
    tmp_path, monkeypatch
):
    payload = b"w" * 1000
    w = wheel_for(payload, "pkg-1.0-py3-none-any.whl")
    folder = tmp_path / "extras"
    folder.mkdir()
    (folder / "old.txt").write_text("old install", encoding="utf-8")
    monkeypatch.setattr(extras, "build_plan", lambda **kw: [w])
    monkeypatch.setenv(extras.EXTRAS_ENV, str(folder))
    monkeypatch.setattr(
        extras,
        "_run",
        lambda cmd, **kw: (Path(str(cmd[cmd.index("--target") + 1])).mkdir(parents=True), "")[1],
    )
    real_replace = Path.replace

    def locked(self, target):
        if self == folder:  # Windows refuses to rename a folder with loaded DLLs
            raise PermissionError("[WinError 5] Access is denied")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", locked)
    with pytest.raises(ExtrasError, match="still in use"):
        extras.install(lambda *a: None, client=make_client(payload), uv=Path("uv.exe"))
    monkeypatch.undo()
    assert (folder / "old.txt").read_text(encoding="utf-8") == "old install"  # nothing was lost
