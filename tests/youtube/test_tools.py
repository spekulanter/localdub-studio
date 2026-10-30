from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import httpx
import pytest

from localdub.core.youtube import tools
from localdub.core.youtube.tools import ToolsError

EXE = b"MZ fake yt-dlp"


def deno_zip(member: str = "deno.exe") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(member, b"MZ fake deno")
    return buf.getvalue()


def make_client(exe: bytes = EXE, zipped: bytes | None = None, *, wrong_sum: bool = False):
    zipped = zipped if zipped is not None else deno_zip()
    sums = {
        tools.YTDLP_SUMS_URL: f"{hashlib.sha256(exe).hexdigest()}  yt-dlp.exe\n"
        f"{'0' * 64}  yt-dlp_x86.exe\n",
        tools.DENO_SUM_URL: f"{hashlib.sha256(zipped).hexdigest()}  {tools.DENO_ZIP}\n",
    }
    if wrong_sum:
        sums[tools.YTDLP_SUMS_URL] = f"{'a' * 64}  yt-dlp.exe\n"
    files = {tools.YTDLP_URL: exe, tools.DENO_URL: zipped}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in sums:
            return httpx.Response(200, text=sums[url])
        if url in files:
            return httpx.Response(
                200, content=files[url], headers={"content-length": str(len(files[url]))}
            )
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def managed(tmp_path, monkeypatch):
    monkeypatch.setenv(tools.TOOLS_ENV, str(tmp_path / "tools"))
    monkeypatch.setattr(
        tools,
        "status",
        lambda: {k: tools.ToolInfo(True, Path("x"), "1") for k in ("yt_dlp", "deno")},
    )
    return tmp_path / "tools"


def test_parse_checksum_picks_the_right_line_and_tolerates_a_bare_hash():
    text = f"{'1' * 64}  yt-dlp_x86.exe\n{'2' * 64} *yt-dlp.exe\n"
    assert tools.parse_checksum(text, "yt-dlp.exe") == "2" * 64
    assert tools.parse_checksum(f"{'ABCDEF1234' * 6}abcd\n", "deno.zip") == (
        "abcdef1234" * 6 + "abcd"
    )
    with pytest.raises(ToolsError):
        tools.parse_checksum("nothing here", "yt-dlp.exe")
    with pytest.raises(ToolsError):
        tools.parse_checksum(f"{'1' * 64}  other.exe\n{'2' * 64}  more.exe\n", "yt-dlp.exe")


DENO_REAL = (
    "\r\nAlgorithm : SHA256\r\nHash      : CBA84B26E0DF5AE7F74FC66B86A95B866872A86292EBD84FA1E9599"
    "27EDD93BF\r\nPath      : C:\\a\\deno\\deno\\target\\release\\deno-x86_64-pc-windows-msvc.zip\r\n\r\n"
)


def test_denos_real_checksum_format_is_understood():
    got = tools.parse_checksum(DENO_REAL, "deno-x86_64-pc-windows-msvc.zip")
    assert got == "cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf"
    # but a file that lists several hashes never matches by guesswork
    with pytest.raises(ToolsError):
        tools.parse_checksum(
            DENO_REAL + f"Hash : {'1' * 64}\r\n", "deno-x86_64-pc-windows-msvc.zip"
        )


def test_install_downloads_verifies_extracts_and_cleans_up(managed):
    events: list[tuple[int, int, str]] = []
    tools.install(lambda d, t, m: events.append((d, t, m)), client=make_client())
    assert (managed / "yt-dlp.exe").read_bytes() == EXE
    assert (managed / "deno.exe").read_bytes() == b"MZ fake deno"
    assert sorted(p.name for p in managed.iterdir()) == ["deno.exe", "yt-dlp.exe"]  # no leftovers
    assert events[0][2] == "Reading the checksums..." and events[-1][2] == "Done"
    assert all(d <= t for d, t, _ in events)
    assert any(m == "Downloading yt-dlp" for _, _, m in events) and any(
        m == "Downloading Deno" for _, _, m in events
    )


def test_a_checksum_mismatch_installs_nothing(managed):
    with pytest.raises(ToolsError, match="checksum mismatch"):
        tools.install(lambda *a: None, client=make_client(wrong_sum=True))
    assert not (managed / "yt-dlp.exe").exists() and not (managed / "deno.exe").exists()
    assert not (managed / ".download").exists()


def test_a_deno_archive_without_deno_exe_is_rejected(managed):
    with pytest.raises(ToolsError, match="does not contain deno.exe"):
        tools.install(lambda *a: None, client=make_client(zipped=deno_zip("..\\evil.exe")))
    assert not (managed.parent / "evil.exe").exists() and not (managed / "yt-dlp.exe").exists()


def test_network_problems_are_explained(managed):
    def boom(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(ToolsError, match="internet connection"):
        tools.install(lambda *a: None, client=httpx.Client(transport=httpx.MockTransport(boom)))


def test_the_managed_folder_wins_over_path(managed, monkeypatch):
    managed.mkdir()
    (managed / "yt-dlp.exe").write_bytes(b"x")
    monkeypatch.setattr(tools.shutil, "which", lambda name: "C:/elsewhere/yt-dlp.exe")
    assert tools.find_ytdlp() == managed / "yt-dlp.exe"
    (managed / "yt-dlp.exe").unlink()
    assert tools.find_ytdlp() == Path("C:/elsewhere/yt-dlp.exe")
