from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from localdub.api.app import create_app
from localdub.config import Settings
from localdub.core.youtube import tools, ytdlp
from localdub.core.youtube.ytdlp import VideoInfo, YoutubeError

URL = "https://www.youtube.com/watch?v=abc123"
INFO = VideoInfo(
    "abc123", "A talk about dubbing", "Someone", "https://i.ytimg.com/x.jpg", 125.4, False, URL
)


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings, start_queue=False)) as c:
        yield c


@pytest.fixture(autouse=True)
def fake_tools(monkeypatch):
    monkeypatch.setattr(ytdlp, "fetch_info", lambda url, cookies="none", timeout=90.0: INFO)
    ok = tools.ToolInfo(True, None, "2026.10.29")
    monkeypatch.setattr(
        tools, "status", lambda: {"yt_dlp": ok, "deno": tools.ToolInfo(True, None, "2.5")}
    )


def make(client, **over):
    return client.post("/api/projects/from-youtube", json={"url": URL, **over})


def test_status_lists_the_tools_and_the_allowed_choices(client):
    d = client.get("/api/youtube/status").json()
    assert d["installed"] is True and d["yt_dlp"]["version"] == "2026.10.29"
    assert "1080" in d["qualities"] and "edge" in d["browsers"]


def test_status_says_when_a_tool_is_missing(client, monkeypatch):
    monkeypatch.setattr(
        tools,
        "status",
        lambda: {"yt_dlp": tools.ToolInfo(False), "deno": tools.ToolInfo(True, None, "2")},
    )
    assert client.get("/api/youtube/status").json()["installed"] is False


def test_a_link_becomes_a_project_with_the_video_title_and_a_queued_job(client):
    r = make(client, quality="720", cookies_browser="edge", voice="M2", original_audio="mute")
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["name"] == "A talk about dubbing" and p["source_url"] == URL
    assert p["duration"] == pytest.approx(125.4) and p["download_quality"] == "720"
    assert p["voice"] == "M2" and p["original_audio"] == "mute"
    assert p["latest_job"]["status"] == "queued"
    row = client.app.state.db.get_project(p["id"])  # type: ignore[attr-defined]
    assert row["cookies_browser"] == "edge" and row["input_rel"] == "input/source.mp4"


def test_without_starting_nothing_is_queued(client):
    p = make(client, start=False).json()
    assert p["latest_job"] is None


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"url": "http://www.youtube.com/watch?v=abc"}, 422),
        ({"url": "https://evil.example/watch?v=abc"}, 422),
        ({"quality": "4320"}, 422),
        ({"cookies_browser": "safari"}, 422),
        ({"voice": "ZZ"}, 422),
        ({"source_lang": "xx"}, 422),
        ({"clone_voice": True}, 422),  # no consent
    ],
)
def test_bad_requests_create_nothing(client, body, status):
    r = client.post("/api/projects/from-youtube", json={"url": URL, **body})
    assert r.status_code == status, r.text
    assert client.get("/api/projects").json() == []


def test_missing_tools_give_a_409_the_ui_can_act_on(client, monkeypatch):
    def no_tools(url, cookies="none", timeout=90.0):
        raise YoutubeError(
            "missing_tools", "yt-dlp is not installed. Install the YouTube tools first."
        )

    monkeypatch.setattr(ytdlp, "fetch_info", no_tools)
    r = make(client)
    assert r.status_code == 409 and "not installed" in r.json()["detail"]
    assert client.get("/api/projects").json() == []


def test_youtube_problems_are_shown_as_they_are(client, monkeypatch):
    def blocked(url, cookies="none", timeout=90.0):
        raise YoutubeError("age_restricted", "This video is age-restricted. Choose a browser...")

    monkeypatch.setattr(ytdlp, "fetch_info", blocked)
    r = client.post("/api/youtube/info", json={"url": URL})
    assert r.status_code == 422 and "age-restricted" in r.json()["detail"]


def test_live_streams_and_very_long_videos_are_refused(client, monkeypatch):
    live = VideoInfo("x", "Live", None, None, None, True, URL)
    monkeypatch.setattr(ytdlp, "fetch_info", lambda url, cookies="none", timeout=90.0: live)
    assert "Live streams" in make(client).json()["detail"]
    long = VideoInfo("x", "Long", None, None, 5 * 3600.0, False, URL)
    monkeypatch.setattr(ytdlp, "fetch_info", lambda url, cookies="none", timeout=90.0: long)
    assert "longer than 4 hours" in make(client).json()["detail"]
    assert client.get("/api/projects").json() == []


def test_info_returns_what_the_card_needs(client):
    d = client.post("/api/youtube/info", json={"url": URL}).json()
    assert d["title"] == "A talk about dubbing" and d["duration"] == pytest.approx(125.4)
    assert d["thumbnail"].startswith("https://") and d["is_live"] is False
    assert client.post("/api/youtube/info", json={"url": "https://vimeo.com/1"}).status_code == 422


def test_updating_is_blocked_while_a_job_runs(client, monkeypatch):
    monkeypatch.setattr(tools, "update_ytdlp", lambda: "Updated to 2026.11.01")
    assert client.post("/api/youtube/update").json() == {"message": "Updated to 2026.11.01"}
    make(client)  # queues a job
    assert client.post("/api/youtube/update").status_code == 409


def test_the_tools_show_up_on_the_models_page_with_their_own_download(client, monkeypatch):
    monkeypatch.setattr(tools, "is_installed", lambda: False)
    rows = {m["id"]: m for m in client.get("/api/models").json()["models"]}
    assert rows["youtube"]["installed"] is False and rows["youtube"]["group"] == "youtube"
    assert rows["youtube"]["required"] is False and rows["youtube"]["available"] is True


def test_a_project_whose_video_is_still_downloading_says_so(client, settings):
    p = make(client).json()
    assert p["has_input"] is False
    assert client.get(f"/api/projects/{p['id']}/source").status_code == 404
    video = settings.data_dir / "projects" / str(p["id"]) / "input" / "source.mp4"
    video.write_bytes(b"x")
    assert client.get(f"/api/projects/{p['id']}").json()["has_input"] is True
    assert client.get(f"/api/projects/{p['id']}/source").status_code == 200
