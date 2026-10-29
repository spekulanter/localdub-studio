from __future__ import annotations

import socket

from localdub.config import Settings
from localdub.desktop import ERROR_PAGE, EmbeddedServer, healthy


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_embedded_server_starts_answers_and_stops(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", api_port=free_port())
    server = EmbeddedServer(settings)
    assert not healthy(server.url, 0.3)
    server.start()
    try:
        assert server.wait_ready(30)
        assert healthy(server.url)
        assert server.has_active_jobs() is False
        server.app.state.db.create_project(
            name="p", original_name="p.mp4", input_rel="input/p.mp4", duration=1.0,
            source_lang="en", voice="F1", llm_model="m",
        )  # fmt: skip
        pid = server.app.state.db.list_projects()[0]["id"]
        server.app.state.db.create_job(pid)
        assert server.has_active_jobs() is True  # the window asks before closing
    finally:
        server.stop()
    assert not healthy(server.url, 0.3)


def test_port_in_use_is_reported_not_hung(tmp_path):
    port = free_port()
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", port))
        blocker.listen()
        server = EmbeddedServer(Settings(data_dir=tmp_path / "data", api_port=port))
        server.start()
        assert server.wait_ready(10) is False  # a stranger owns the port: no false "ready"
        server.stop()


def test_error_page_escapes_nothing_unexpected():
    html = ERROR_PAGE.format(message="boom", log="C:\\x\\app.log")
    assert "boom" in html and "app.log" in html
