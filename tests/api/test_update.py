from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from localdub.api.app import create_app
from localdub.config import Settings
from localdub.core import updates

REAL_CLIENT = httpx.Client  # the fixture below replaces httpx.Client
BLOB = b"MZ pretend installer"
DIGEST = hashlib.sha256(BLOB).hexdigest()
BASE = updates.DOWNLOAD_PREFIX + "v9.9.9/"


def release(**over):
    data = {
        "tag_name": "v9.9.9", "draft": False, "prerelease": False, "body": "Notes here",
        "html_url": "https://github.com/spekulanter/localdub-studio/releases/tag/v9.9.9",
        "assets": [
            {"name": "LocalDub-Studio-9.9.9-Setup.exe", "size": len(BLOB),
             "browser_download_url": BASE + "LocalDub-Studio-9.9.9-Setup.exe"},
            {"name": "LocalDub-Studio-9.9.9-Setup.exe.sha256", "size": 99,
             "browser_download_url": BASE + "LocalDub-Studio-9.9.9-Setup.exe.sha256"},
            {"name": "LocalDub-Studio-9.9.9-macOS-arm64.dmg", "size": 5,
             "browser_download_url": BASE + "LocalDub-Studio-9.9.9-macOS-arm64.dmg"},
            {"name": "LocalDub-Studio-9.9.9-macOS-arm64.dmg.sha256", "size": 99,
             "browser_download_url": BASE + "LocalDub-Studio-9.9.9-macOS-arm64.dmg.sha256"},
        ],
    }
    data.update(over)
    return data


def github(data=None, status=200, blob=BLOB, digest=DIGEST):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == updates.API_URL:
            return httpx.Response(status, json=data if data is not None else release())
        if url.endswith(".sha256"):
            return httpx.Response(200, text=f"{digest}  {url.rsplit('/', 1)[1][:-7]}\n")
        if url.startswith(updates.DOWNLOAD_PREFIX):
            return httpx.Response(200, content=blob, headers={"content-length": str(len(blob))})
        return httpx.Response(404)

    return REAL_CLIENT(transport=httpx.MockTransport(handler))


def test_versions_are_compared_as_numbers():
    assert updates.is_newer("0.10.0", "0.9.9") and updates.is_newer("v1.0", "0.99")
    assert not updates.is_newer("0.5.2", "0.5.2") and not updates.is_newer("0.5.1", "0.5.2")
    assert not updates.is_newer("garbage", "0.5.2")


def test_the_current_version_is_the_one_in_pyproject():
    assert updates.current_version().count(".") == 2


def test_a_newer_normal_release_is_offered_with_this_systems_installer():
    win = updates.check(github(), "win32")
    mac = updates.check(github(), "darwin")
    assert win and win.asset == "LocalDub-Studio-9.9.9-Setup.exe" and win.version == "9.9.9"
    assert mac and mac.asset.endswith("macOS-arm64.dmg")
    assert win.notes == "Notes here" and win.sha_url.endswith(".sha256")


def test_pre_releases_drafts_and_old_versions_are_ignored():
    assert updates.check(github(release(prerelease=True)), "win32") is None
    assert updates.check(github(release(draft=True)), "win32") is None
    assert updates.check(github(release(tag_name="v0.0.1")), "win32") is None
    assert updates.check(github(status=404), "win32") is None  # no normal release at all


def test_a_release_without_this_systems_installer_or_checksum_is_not_offered():
    only_mac = release(assets=[a for a in release()["assets"] if "Setup" not in a["name"]])
    assert updates.check(github(only_mac), "win32") is None
    no_sum = release(assets=[a for a in release()["assets"] if not a["name"].endswith("Setup.exe.sha256")])
    assert updates.check(github(no_sum), "win32") is None


def test_files_from_somewhere_else_are_never_offered():
    evil = release()
    evil["assets"][0]["browser_download_url"] = "https://evil.example/Setup.exe"
    assert updates.check(github(evil), "win32") is None


def test_network_trouble_is_an_update_error():
    def boom(request):
        raise httpx.ConnectError("offline")

    with pytest.raises(updates.UpdateError, match="Could not ask GitHub"):
        updates.check(httpx.Client(transport=httpx.MockTransport(boom)), "win32")


def test_the_download_is_verified_and_kept(tmp_path):
    u = updates.check(github(), "win32")
    seen = []
    path = updates.download(u, tmp_path / "updates", lambda d, t: seen.append((d, t)), github())
    assert path.read_bytes() == BLOB and path.name == u.asset
    assert seen[-1] == (len(BLOB), len(BLOB))
    assert [p.name for p in path.parent.iterdir()] == [u.asset]  # no .part left


def test_a_damaged_download_is_discarded(tmp_path):
    u = updates.check(github(), "win32")
    with pytest.raises(updates.UpdateError, match="damaged"):
        updates.download(u, tmp_path / "updates", lambda d, t: None, github(digest="0" * 64))
    assert not (tmp_path / "updates").exists()


# ----- through the API ----------------------------------------------------------------------------


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings, start_queue=False)) as c:
        yield c


@pytest.fixture
def fake_github(monkeypatch):
    monkeypatch.setattr(updates.httpx, "Client", lambda *a, **k: github())  # a fresh one per use
    monkeypatch.setattr(updates, "current_version", lambda: "0.5.2")
    monkeypatch.setattr(updates.sys, "platform", "win32")


def test_the_api_offers_downloads_and_installs(client: TestClient, fake_github, monkeypatch):
    launched = []
    monkeypatch.setattr(updates, "launch_installer", lambda p: launched.append(p))
    state = client.get("/api/update").json()
    assert state["available"] and state["version"] == "9.9.9" and state["current"] == "0.5.2"
    assert client.post("/api/update/install", json={}).status_code == 409  # not downloaded yet
    assert client.post("/api/update/download").status_code == 202
    import time

    for _ in range(100):
        state = client.get("/api/update").json()
        if state["download"]["status"] != "running":
            break
        time.sleep(0.05)
    assert state["download"]["status"] == "ready", state
    left = []
    client.app.state.quit = lambda: left.append(True)  # type: ignore[attr-defined]
    assert client.post("/api/update/install", json={}).json() == {"closing": True}
    assert launched and Path(launched[0]).is_file()
    for _ in range(60):
        if left:
            break
        time.sleep(0.05)
    assert left == [True]


def test_nothing_to_download_without_a_newer_release(client: TestClient):
    assert client.post("/api/update/download").status_code == 409
