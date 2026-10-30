from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from localdub.core.youtube import tools, ytdlp
from localdub.core.youtube.ytdlp import YoutubeError

FAKE = Path(__file__).with_name("fake_ytdlp.py")


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc123",
        "https://youtu.be/abc123?t=5",
        "https://m.youtube.com/watch?v=abc",
        "https://music.youtube.com/watch?v=abc",
        "https://www.youtube-nocookie.com/embed/abc",
        "  https://youtube.com/shorts/abc  ",
    ],
)
def test_real_youtube_links_are_accepted(url):
    assert ytdlp.validate_youtube_url(url).startswith("https://")


@pytest.mark.parametrize(
    "url",
    [
        "http://www.youtube.com/watch?v=abc",  # not https
        "https://youtube.com.evil.example/watch?v=abc",  # lookalike suffix
        "https://evilyoutube.com/watch?v=abc",  # lookalike prefix
        "https://notyoutu.be/abc",
        "https://youtube.com@evil.example/watch?v=abc",  # user-info trick
        "https://user:pw@www.youtube.com/watch?v=abc",
        "https://vimeo.com/123",
        "file:///C:/Windows/win.ini",
        "javascript:alert(1)",
        "youtube.com/watch?v=abc",
        "",
        "--exec calc.exe",
    ],
)
def test_everything_else_is_refused(url):
    with pytest.raises(YoutubeError) as exc:
        ytdlp.validate_youtube_url(url)
    assert exc.value.code == "invalid_url"


def test_options_are_enumerated():
    ytdlp.validate_options("1080", "edge")
    for quality, browser in (("999", "none"), ("auto", "safari"), ("auto; calc", "none")):
        with pytest.raises(YoutubeError):
            ytdlp.validate_options(quality, browser)


def test_format_selector_caps_the_height_and_falls_back():
    assert ytdlp.format_selector("auto") == "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b"
    assert "height<=720" in ytdlp.format_selector("720")
    assert ytdlp.format_selector("2160").endswith("/bv*+ba/b")  # never "no format available"


def test_download_arguments_are_a_list_without_user_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "find_deno", lambda: Path("C:/tools/deno.exe"))
    dest = tmp_path / "input" / "source.mp4"
    args = ytdlp.build_download_args("https://youtu.be/abc", dest, "720", "firefox", Path("C:/ff"))
    assert args[0] == "--no-config" and args[-1] == "https://youtu.be/abc"
    assert args[args.index("-P") + 1] == str(dest.parent)
    assert args[args.index("-o") + 1] == "source.%(ext)s"
    assert args[args.index("--merge-output-format") + 1] == "mp4"
    assert args[args.index("--js-runtimes") + 1] == "deno:" + str(Path("C:/tools/deno.exe"))
    assert args[args.index("--cookies-from-browser") + 1] == "firefox"
    assert args[args.index("--ffmpeg-location") + 1] == str(Path("C:/ff"))
    assert "--no-playlist" in args
    assert "--cookies-from-browser" not in ytdlp.build_download_args(
        "https://youtu.be/a", dest, "auto", "none", None
    )


def test_progress_lines_are_parsed():
    assert ytdlp.parse_progress("__LD_PROGRESS__ 42.5%|1.2MiB/s|00:12") == (
        42.5,
        "1.2MiB/s",
        "00:12",
    )
    assert ytdlp.parse_progress("__LD_PROGRESS__100%|NA|NA") == (100.0, None, None)
    assert ytdlp.parse_progress("__LD_PROGRESS__garbage")[0] is None
    assert ytdlp.parse_progress("[download] 50% of 10MiB") is None


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Sign in to confirm you're not a bot", "login_required"),
        ("ERROR: This video may be inappropriate. Sign in to confirm your age", "age_restricted"),
        ("PO Token required", "po_token"),
        ("HTTP Error 403: Forbidden", "forbidden"),
        ("Video unavailable", "unavailable"),
        ("ERROR: [youtube] aaaaaaaaaaa: This video is unavailable", "unavailable"),
        ("ffmpeg not found", "missing_ffmpeg"),
        ("No supported JavaScript runtime could be found", "missing_js_runtime"),
        ("Unsupported URL: https://x", "unsupported"),
        ("something odd", "unknown"),
    ],
)
def test_errors_are_classified_into_advice(text, code):
    assert ytdlp.classify_error(text) == code
    err = ytdlp.friendly_error("noise\n" + text + "\n")
    assert err.code == code and text.split("\n")[0][:20] in str(err)


def _download(tmp_path, mode):
    os.environ["FAKE_YTDLP_MODE"] = mode
    seen: list[tuple] = []
    dest = tmp_path / "input" / "source.mp4"
    result = ytdlp.download(
        "https://www.youtube.com/watch?v=abc", dest, "auto", "none", None,
        lambda p, s, m: seen.append((p, s, m)), launcher=[sys.executable, str(FAKE)],
    )  # fmt: skip
    return result, dest, seen


def test_a_download_reports_progress_and_returns_the_file(tmp_path):
    result, dest, seen = _download(tmp_path, "ok")
    assert result == dest and dest.read_bytes() == b"not really a video"
    percents = [p for p, _, _ in seen if p is not None]
    assert percents == [4.5, 45.0, 90.0]  # one stream: the video share (0-90 %) of the bar
    assert any(m and "Merger" in m for _, _, m in seen)


def test_a_file_with_another_name_is_moved_to_the_expected_path(tmp_path):
    result, dest, _ = _download(tmp_path, "odd_name")
    assert result == dest and dest.is_file()
    assert not list((tmp_path / "input").glob("Some Title*"))


def test_a_failed_download_explains_what_to_do(tmp_path):
    with pytest.raises(YoutubeError) as exc:
        _download(tmp_path, "fail_age")
    assert exc.value.code == "age_restricted" and "cookies" in str(exc.value).lower()


def test_undecodable_bytes_from_the_tool_do_not_break_error_handling(tmp_path):
    with pytest.raises(YoutubeError) as exc:
        _download(tmp_path, "fail_bytes")
    assert exc.value.code == "unavailable"


def test_download_refuses_bad_input_before_starting_anything(tmp_path):
    with pytest.raises(YoutubeError):
        ytdlp.download(
            "https://evil.example/x", tmp_path / "a.mp4", "auto", "none", None, lambda *a: None
        )
    with pytest.raises(YoutubeError):
        ytdlp.download(
            "https://youtu.be/x", tmp_path / "a.mp4", "9999", "none", None, lambda *a: None
        )


@pytest.fixture(autouse=True)
def _clean_mode():
    yield
    os.environ.pop("FAKE_YTDLP_MODE", None)


def test_video_then_audio_gives_one_monotonic_bar(tmp_path):
    _, _, seen = _download(tmp_path, "two_streams")
    percents = [p for p, _, _ in seen if p is not None]
    assert percents == sorted(percents)  # never goes back when the audio stream starts
    assert (
        percents[2] == 90.0 and 95.0 <= percents[-1] <= 99.9
    )  # video done at 90 %, audio the rest
    assert all(0 <= p <= 100 for p in percents)


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/watch?v=abc\n--exec calc.exe",
        "https://youtube.com/watch?v=abc --exec calc.exe",
        "https://youtube.com/watch?v=abc\x00",
        "https://youtube.com/watch?v=a\tb",
    ],
)
def test_links_with_spaces_or_control_characters_are_refused_with_a_clear_message(url):
    with pytest.raises(YoutubeError, match="spaces or line breaks"):
        ytdlp.validate_youtube_url(url)


def test_the_link_comes_after_a_double_dash_so_it_can_never_be_an_option(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "find_deno", lambda: None)
    args = ytdlp.build_download_args(
        "https://youtu.be/abc", tmp_path / "s.mp4", "auto", "none", None
    )
    assert args[-2:] == ["--", "https://youtu.be/abc"]


def test_running_downloads_can_be_stopped_by_the_worker(tmp_path, monkeypatch):
    import subprocess
    import threading

    killed: list[int] = []
    monkeypatch.setattr(ytdlp, "kill_tree", lambda pid: killed.append(pid))
    slow = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with ytdlp._active_lock:
            ytdlp._active.add(slow)
        ytdlp.terminate_active()
        assert killed == [slow.pid]
    finally:
        slow.kill()
        with ytdlp._active_lock:
            ytdlp._active.discard(slow)
    assert threading.active_count() >= 1
    killed.clear()
    ytdlp.terminate_active()  # nothing registered any more: nothing to stop
    assert killed == []


def test_a_finished_download_leaves_nothing_in_the_registry(tmp_path):
    _download(tmp_path, "ok")
    assert not ytdlp._active
