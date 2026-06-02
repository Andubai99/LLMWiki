from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import mimetypes
import socket
import webbrowser

from .api import get_config_status, get_workspace_status, list_pages, list_runs, list_sources
from .models import sanitize_ui_text


STATIC_ROOT = Path(__file__).parent / "static"


@dataclass(frozen=True)
class UiServerConfig:
    root: Path
    host: str = "127.0.0.1"
    port: int = 8765


def find_available_port(host: str, preferred_port: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, preferred_port))
        return int(sock.getsockname()[1])


def create_ui_server(config: UiServerConfig) -> ThreadingHTTPServer:
    root = config.root.resolve()
    port = find_available_port(config.host, config.port)

    class LLMWikiUiHandler(BaseHTTPRequestHandler):
        server_version = "LLMWikiUI/3.1"

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            try:
                handle_get(self, root)
            except Exception as exc:  # pragma: no cover - exercised through tests
                write_json(
                    self,
                    500,
                    {
                        "schema_version": "ui.v3.1",
                        "error": "internal_error",
                        "message": sanitize_server_error(exc),
                    },
                )

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib name
            return

    return ThreadingHTTPServer((config.host, port), LLMWikiUiHandler)


def serve_ui(root: Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    server = create_ui_server(UiServerConfig(root=root, host=host, port=port))
    actual_host, actual_port = server.server_address
    url = f"http://{actual_host}:{actual_port}/"
    print(f"LLMWiki UI: {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def handle_get(handler: BaseHTTPRequestHandler, root: Path) -> None:
    path = handler.path.split("?", 1)[0]
    if path == "/":
        write_static(handler, "index.html")
        return
    if path.startswith("/static/"):
        write_static(handler, path.removeprefix("/static/"))
        return
    if path.startswith("/api/"):
        write_api(handler, root, path)
        return
    write_json(handler, 404, {"schema_version": "ui.v3.1", "error": "not_found"})


def write_api(handler: BaseHTTPRequestHandler, root: Path, path: str) -> None:
    routes = {
        "/api/status": lambda: get_workspace_status(root).to_dict(),
        "/api/sources": lambda: {"schema_version": "ui.v3.1", "sources": [item.to_dict() for item in list_sources(root)]},
        "/api/runs": lambda: {"schema_version": "ui.v3.1", "runs": [item.to_dict() for item in list_runs(root)]},
        "/api/pages": lambda: {"schema_version": "ui.v3.1", "pages": [item.to_dict() for item in list_pages(root)]},
        "/api/config": lambda: get_config_status(root).to_dict(),
    }
    route = routes.get(path)
    if route is None:
        write_json(handler, 404, {"schema_version": "ui.v3.1", "error": "not_found"})
        return
    write_json(handler, 200, route())


def write_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, object]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def sanitize_server_error(exc: Exception) -> str:
    message = sanitize_ui_text(exc, max_chars=240)
    if "Traceback" in message or "traceback" in message.lower():
        return "An internal dashboard error occurred."
    return message


def write_static(handler: BaseHTTPRequestHandler, relative_path: str) -> None:
    path = safe_static_path(relative_path)
    if path is None or not path.exists() or not path.is_file():
        write_json(handler, 404, {"schema_version": "ui.v3.1", "error": "not_found"})
        return
    body = path.read_bytes()
    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    if path.suffix == ".js":
        content_type = "text/javascript"
    handler.send_response(200)
    handler.send_header("Content-Type", f"{content_type}; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def safe_static_path(relative_path: str) -> Path | None:
    try:
        path = (STATIC_ROOT / relative_path).resolve()
        path.relative_to(STATIC_ROOT.resolve())
    except (ValueError, OSError):
        return None
    return path
