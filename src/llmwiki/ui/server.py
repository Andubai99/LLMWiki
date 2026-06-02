from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import mimetypes
import secrets
import socket
import webbrowser

from .actions import UiActionError, enqueue_add_source_job, run_add_source_job
from .api import (
    get_ask_job,
    get_config_status,
    get_ui_job,
    get_workspace_status,
    list_ask_jobs,
    list_pages,
    list_runs,
    list_sources,
    list_ui_jobs,
)
from .ask_actions import (
    AskUiActionError,
    enqueue_ask_job,
    enqueue_synthesis_preview_job,
    enqueue_synthesis_writeback_job,
)
from .jobs import UiJobManager, mark_stale_running_jobs_interrupted
from .models import UI_SCHEMA_VERSION, sanitize_ui_text


STATIC_ROOT = Path(__file__).parent / "static"


@dataclass(frozen=True)
class UiServerConfig:
    root: Path
    host: str = "127.0.0.1"
    port: int = 8765
    action_token: str | None = None


class LLMWikiUiServer(ThreadingHTTPServer):
    root: Path
    action_token: str
    job_manager: UiJobManager

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        root: Path,
        action_token: str,
        job_manager: UiJobManager,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.root = root
        self.action_token = action_token
        self.job_manager = job_manager

    def server_close(self) -> None:
        self.job_manager.stop()
        super().server_close()


def find_available_port(host: str, preferred_port: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, preferred_port))
        return int(sock.getsockname()[1])


def create_ui_server(config: UiServerConfig) -> ThreadingHTTPServer:
    root = config.root.resolve()
    port = find_available_port(config.host, config.port)
    action_token = config.action_token or secrets.token_urlsafe(32)
    mark_stale_running_jobs_interrupted(root)
    job_manager = UiJobManager(root, worker=lambda job: run_add_source_job(root, job))

    class LLMWikiUiHandler(BaseHTTPRequestHandler):
        server_version = "LLMWikiUI/3.3"

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            try:
                handle_get(self)
            except Exception as exc:  # pragma: no cover - exercised through tests
                write_json(
                    self,
                    500,
                    {
                        "schema_version": UI_SCHEMA_VERSION,
                        "error": "internal_error",
                        "message": sanitize_server_error(exc),
                    },
                )

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            try:
                handle_post(self)
            except Exception as exc:  # pragma: no cover - defensive
                write_json(
                    self,
                    500,
                    {
                        "schema_version": UI_SCHEMA_VERSION,
                        "error": "internal_error",
                        "message": sanitize_server_error(exc),
                    },
                )

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib name
            return

    return LLMWikiUiServer(
        (config.host, port),
        LLMWikiUiHandler,
        root=root,
        action_token=action_token,
        job_manager=job_manager,
    )


def serve_ui(root: Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    server = create_ui_server(UiServerConfig(root=root, host=host, port=port))
    actual_host, actual_port = server.server_address
    url = f"http://{actual_host}:{actual_port}/"
    print(f"LLMWiki UI: {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.job_manager.start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def handle_get(handler: BaseHTTPRequestHandler) -> None:
    path = handler.path.split("?", 1)[0]
    if path == "/":
        write_static(handler, "index.html")
        return
    if path.startswith("/static/"):
        write_static(handler, path.removeprefix("/static/"))
        return
    if path.startswith("/api/"):
        write_api(handler, path)
        return
    write_json(handler, 404, {"schema_version": UI_SCHEMA_VERSION, "error": "not_found"})


def handle_post(handler: BaseHTTPRequestHandler) -> None:
    path = handler.path.split("?", 1)[0]
    if path.startswith("/api/"):
        write_post_api(handler, path)
        return
    write_json(handler, 404, {"schema_version": UI_SCHEMA_VERSION, "error": "not_found"})


def write_api(handler: BaseHTTPRequestHandler, path: str) -> None:
    server = ui_server(handler)
    root = server.root
    routes = {
        "/api/status": lambda: get_workspace_status(root).to_dict(),
        "/api/session": lambda: {
            "schema_version": UI_SCHEMA_VERSION,
            "action_token": server.action_token,
            "supported_actions": [
                "add_source",
                "ask_question",
                "synthesis_preview",
                "synthesis_writeback",
            ],
        },
        "/api/sources": lambda: {"schema_version": UI_SCHEMA_VERSION, "sources": [item.to_dict() for item in list_sources(root)]},
        "/api/runs": lambda: {"schema_version": UI_SCHEMA_VERSION, "runs": [item.to_dict() for item in list_runs(root)]},
        "/api/pages": lambda: {"schema_version": UI_SCHEMA_VERSION, "pages": [item.to_dict() for item in list_pages(root)]},
        "/api/jobs": lambda: list_ui_jobs(root).to_dict(),
        "/api/ask/jobs": lambda: list_ask_jobs(root).to_dict(),
        "/api/config": lambda: get_config_status(root).to_dict(),
    }
    route = routes.get(path)
    if route is None and path.startswith("/api/ask/jobs/"):
        job_id = path.removeprefix("/api/ask/jobs/")
        job = get_ask_job(root, job_id)
        if job is None:
            write_json(handler, 404, {"schema_version": UI_SCHEMA_VERSION, "error": "not_found"})
            return
        write_json(handler, 200, job.to_dict())
        return
    if route is None and path.startswith("/api/jobs/"):
        job_id = path.removeprefix("/api/jobs/")
        job = get_ui_job(root, job_id)
        if job is None:
            write_json(handler, 404, {"schema_version": UI_SCHEMA_VERSION, "error": "not_found"})
            return
        write_json(handler, 200, job.to_dict())
        return
    if route is None:
        write_json(handler, 404, {"schema_version": UI_SCHEMA_VERSION, "error": "not_found"})
        return
    write_json(handler, 200, route())


def write_post_api(handler: BaseHTTPRequestHandler, path: str) -> None:
    if (
        path not in {"/api/sources/add", "/api/ask"}
        and not is_synthesis_preview_path(path)
        and not is_synthesis_writeback_path(path)
    ):
        write_json(handler, 404, {"schema_version": UI_SCHEMA_VERSION, "error": "not_found"})
        return
    server = ui_server(handler)
    if handler.headers.get("X-LLMWiki-UI-Token", "") != server.action_token:
        write_json(handler, 403, {"schema_version": UI_SCHEMA_VERSION, "error": "forbidden"})
        return
    try:
        payload = read_json_body(handler)
        if path == "/api/sources/add":
            job = enqueue_add_source_job(server.root, payload, server.job_manager)
        elif path == "/api/ask":
            job = enqueue_ask_job(server.root, payload, server.job_manager)
        elif is_synthesis_preview_path(path):
            job = enqueue_synthesis_preview_job(
                server.root,
                ask_job_id_from_synthesis_path(path, suffix="/synthesis/preview"),
                payload,
                server.job_manager,
            )
        else:
            job = enqueue_synthesis_writeback_job(
                server.root,
                ask_job_id_from_synthesis_path(path, suffix="/synthesis/writeback"),
                payload,
                server.job_manager,
            )
    except (UiActionError, AskUiActionError) as exc:
        data = exc.to_dict()
        write_json(
            handler,
            int(data.get("status_code", 400)),
            {
                "schema_version": UI_SCHEMA_VERSION,
                "error": exc.code,
                "message": data["message"],
            },
        )
        return
    except json.JSONDecodeError as exc:
        write_json(
            handler,
            400,
            {
                "schema_version": UI_SCHEMA_VERSION,
                "error": "invalid_json",
                "message": sanitize_ui_text(exc),
            },
        )
        return
    write_json(handler, 202, {"schema_version": UI_SCHEMA_VERSION, "job": job.to_dict()})


def is_synthesis_preview_path(path: str) -> bool:
    return path.startswith("/api/ask/") and path.endswith("/synthesis/preview")


def is_synthesis_writeback_path(path: str) -> bool:
    return path.startswith("/api/ask/") and path.endswith("/synthesis/writeback")


def ask_job_id_from_synthesis_path(path: str, *, suffix: str) -> str:
    return path.removeprefix("/api/ask/").removesuffix(suffix)


def read_json_body(handler: BaseHTTPRequestHandler, max_bytes: int = 65536) -> object:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        raise UiActionError("invalid_json", "Invalid Content-Length.")
    if length <= 0:
        raise UiActionError("invalid_json", "Request body is required.")
    if length > max_bytes:
        raise UiActionError("payload_too_large", "Request body is too large.", status_code=413)
    body = handler.rfile.read(length).decode("utf-8", errors="replace")
    return json.loads(body)


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
        write_json(handler, 404, {"schema_version": UI_SCHEMA_VERSION, "error": "not_found"})
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


def ui_server(handler: BaseHTTPRequestHandler) -> LLMWikiUiServer:
    server = handler.server
    if not isinstance(server, LLMWikiUiServer):  # pragma: no cover - defensive
        raise RuntimeError("Unexpected UI server instance.")
    return server
