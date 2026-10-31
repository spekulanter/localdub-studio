"""LocalDub Studio as a desktop program: its own window (Edge WebView2) around the local app.

The server runs inside this process; closing the window stops it (a running job is paused and
resumes the next time). If the window component is unavailable the app opens in the browser.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from localdub.config import Settings
from localdub.core.platform import disable_power_throttling

log = logging.getLogger("localdub.desktop")

TITLE = "LocalDub Studio"
APP_ID = "LocalDub.Studio"
MUTEX_NAME = "LocalDubStudioRunning"
ICON = Path(__file__).resolve().parent / "assets" / "localdub-orange.ico"

SPLASH = """<!doctype html><meta charset="utf-8"><title>LocalDub Studio</title>
<style>
  html,body{height:100%;margin:0;font-family:Segoe UI,system-ui,sans-serif}
  body{display:flex;align-items:center;justify-content:center;background:#12100d;color:#efe8d9}
  .box{text-align:center}
  h1{font-weight:600;margin:0 0 .4rem;font-family:Georgia,serif}
  p{color:#a39a87;margin:0}
  .dot{display:inline-block;width:10px;height:10px;margin:18px 4px 0;border-radius:50%;
       background:#ff6b3d;animation:b 1.2s infinite ease-in-out}
  .dot:nth-child(2){animation-delay:.2s}
  .dot:nth-child(3){animation-delay:.4s}
  @keyframes b{0%,80%,100%{opacity:.2}40%{opacity:1}}
</style>
<div class="box"><h1>LocalDub Studio</h1><p>Starting&hellip;</p>
<span class="dot"></span><span class="dot"></span><span class="dot"></span></div>"""

ERROR_PAGE = """<!doctype html><meta charset="utf-8"><title>LocalDub Studio</title>
<body style="font-family:Segoe UI,sans-serif;background:#12100d;color:#efe8d9;padding:3rem">
<h2>LocalDub Studio could not start</h2>
<pre style="white-space:pre-wrap;color:#ff8a80">{message}</pre>
<p>Details are in <code>{log}</code>.</p>"""


def healthy(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/ping", timeout=timeout) as resp:  # noqa: S310
            return bool(resp.status == 200)
    except OSError:
        return False


def message_box(text: str, title: str = TITLE) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)


def _setup_file_logging(settings: Settings) -> Path:
    """No console under pythonw: send logs and stray prints to a file."""
    log_dir = settings.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "app.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    if sys.stdout is None or sys.stderr is None:
        stream = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
    return path


class EmbeddedServer:
    """uvicorn in a background thread of this process."""

    def __init__(self, settings: Settings) -> None:
        import uvicorn

        from localdub.api.app import create_app

        self.app = create_app(settings)
        self.url = f"http://{settings.api_host}:{settings.api_port}"
        self._server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host=settings.api_host,
                port=settings.api_port,
                log_config=None,
                access_log=False,
            )
        )
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name="uvicorn", daemon=True)

    def _run(self) -> None:
        try:
            self._server.run()
        except BaseException as exc:  # noqa: BLE001 - reported to the user in the window
            log.exception("Server stopped with an error")
            self.error = exc

    def start(self) -> None:
        self._thread.start()

    def wait_ready(self, timeout: float = 90.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.error is not None or not self._thread.is_alive():
                return False
            if healthy(self.url, 1.0):
                return True
            time.sleep(0.25)
        return False

    def has_active_jobs(self) -> bool:
        return bool(self.app.state.db.any_active())

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=20)


def _set_window_icon(window: Any) -> None:
    """Put the LocalDub icon in the title bar and taskbar (pywebview cannot do it on Windows)."""
    try:
        from System.Drawing import Icon

        form = window.native
        icon = Icon(str(ICON))
        form.Invoke(lambda: setattr(form, "Icon", icon))  # keep it on the UI thread
    except Exception:  # noqa: BLE001 - cosmetic only
        log.debug("Could not set the window icon", exc_info=True)


def run_app(settings: Settings | None = None) -> int:
    settings = settings or Settings()
    log_path = _setup_file_logging(settings)
    if sys.platform == "win32":
        # Lets the installer notice a running app (AppMutex) and refuse to overwrite it.
        ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    disable_power_throttling()
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)

    url = f"http://{settings.api_host}:{settings.api_port}"
    server: EmbeddedServer | None = None
    if not healthy(url):
        try:
            server = EmbeddedServer(settings)
            server.start()
        except Exception as exc:  # noqa: BLE001
            log.exception("Could not start the server")
            message_box(f"LocalDub Studio could not start:\n\n{exc}\n\nLog: {log_path}")
            return 1

    try:
        import webview
    except Exception:  # noqa: BLE001 - window component missing: use the browser instead
        log.warning("pywebview is unavailable; falling back to the browser", exc_info=True)
        return _browser_fallback(server, url, log_path)

    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    window = webview.create_window(
        TITLE, html=SPLASH, width=1360, height=900, min_size=(1000, 700), background_color="#12100d"
    )
    assert window is not None

    def on_closing() -> bool | None:
        if server is not None and server.has_active_jobs():
            ok = window.create_confirmation_dialog(
                TITLE,
                "A dubbing job is still running or waiting.\n\n"
                "If you close the window it is paused and continues the next time you open "
                "LocalDub Studio.\n\nClose anyway?",
            )
            return None if ok else False
        return None

    def boot() -> None:
        _set_window_icon(window)
        if server is not None and not server.wait_ready():
            detail = f"{server.error}" if server.error else "The server did not respond in time."
            window.load_html(ERROR_PAGE.format(message=detail, log=log_path))
            return
        if server is None and not healthy(url):
            window.load_html(
                ERROR_PAGE.format(message="The server is not reachable.", log=log_path)
            )
            return
        window.load_url(url)

    window.events.closing += on_closing
    try:
        webview.start(boot, storage_path=str(settings.data_dir / "webview"), icon=str(ICON))
    except Exception:  # noqa: BLE001 - e.g. WebView2 runtime missing
        log.exception("The window could not be created; falling back to the browser")
        return _browser_fallback(server, url, log_path)
    finally:
        if server is not None:
            server.stop()
    return 0


def _browser_fallback(server: EmbeddedServer | None, url: str, log_path: Path) -> int:
    if server is not None and not server.wait_ready():
        message_box(f"LocalDub Studio could not start.\n\nLog: {log_path}")
        return 1
    webbrowser.open(url)
    message_box(
        "The Microsoft Edge WebView2 component is not available, so LocalDub Studio opened in "
        "your browser.\n\nClick OK to quit LocalDub Studio."
    )
    if server is not None:
        server.stop()
    return 0


def main() -> None:
    raise SystemExit(run_app())


if __name__ == "__main__":
    main()
