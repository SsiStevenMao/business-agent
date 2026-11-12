import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from typing import Any
from urllib.parse import urlparse

from business_agent.agent import BusinessAgent
from business_agent.config import load_settings
from business_agent.database import QueryError, initialize_database
from business_agent.llm import ModelProviderError, create_model
from business_agent.roles import ROLES
from business_agent.seed import seed_database


STATIC_ROOT = Path(__file__).resolve().parent / "static"
MAX_REQUEST_BYTES = 16_384


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class AgentWebServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        model: Any,
        database_path: Path,
        provider: str,
        model_name: str,
    ) -> None:
        super().__init__(server_address, AgentRequestHandler)
        self.model = model
        self.database_path = database_path
        self.provider = provider
        self.model_name = model_name
        self.agents = {
            role_key: BusinessAgent(database_path, model, role)
            for role_key, role in ROLES.items()
        }
        self.agent_lock = threading.Lock()


class AgentRequestHandler(BaseHTTPRequestHandler):
    server: AgentWebServer

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/config":
            roles = [
                {
                    "id": role.key,
                    "name": role.name,
                    "description": role.description,
                }
                for role in ROLES.values()
            ]
            self._send_json(
                200,
                {
                    "roles": roles,
                    "provider": self.server.provider,
                    "model": self.server.model_name,
                },
            )
            return

        static_files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        }
        file_entry = static_files.get(path)
        if file_entry is None:
            self._send_json(404, {"error": "Not found."})
            return

        filename, content_type = file_entry
        try:
            content = (STATIC_ROOT / filename).read_bytes()
        except OSError as error:
            self.log_error("Could not read UI asset %s: %s", filename, error)
            self._send_json(500, {"error": "The user interface could not be loaded."})
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self._add_security_headers()
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {"/api/chat", "/api/reset"}:
            self._send_json(404, {"error": "Not found."})
            return

        try:
            payload = self._read_json()
        except ValueError as error:
            self._send_json(400, {"error": str(error)})
            return

        role_key = payload.get("role", "sales_analyst")
        if not isinstance(role_key, str) or role_key not in self.server.agents:
            self._send_json(400, {"error": "Unknown role."})
            return

        with self.server.agent_lock:
            agent = self.server.agents[role_key]
            if path == "/api/reset":
                agent.clear_conversation()
                self._send_json(200, {"ok": True})
                return

            question = payload.get("message")
            if not isinstance(question, str) or not question.strip():
                self._send_json(400, {"error": "Message must not be empty."})
                return
            question = question.strip()
            if len(question) > 4000:
                self._send_json(400, {"error": "Message exceeds the 4,000-character limit."})
                return

            trace_enabled = payload.get("show_trace", False)
            if not isinstance(trace_enabled, bool):
                self._send_json(400, {"error": "show_trace must be a boolean."})
                return

            trace: list[str] = []
            started_at = time.perf_counter()
            try:
                sql, answer = agent.answer(
                    question,
                    on_trace=trace.append if trace_enabled else None,
                )
            except ModelProviderError as error:
                self._send_json(502, {"error": str(error)})
                return
            except QueryError as error:
                self._send_json(400, {"error": str(error)})
                return

            self._send_json(
                200,
                {
                    "answer": answer,
                    "sql": sql,
                    "trace": trace,
                    "elapsed_seconds": round(time.perf_counter() - started_at, 2),
                },
            )

    def _read_json(self) -> dict[str, Any]:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            raise ValueError("Content-Length header is required.")
        try:
            request_size = int(content_length)
        except ValueError as error:
            raise ValueError("Invalid Content-Length header.") from error
        if request_size < 0 or request_size > MAX_REQUEST_BYTES:
            raise ValueError("Request body exceeds the allowed size.")
        try:
            payload = json.loads(self.rfile.read(request_size))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Request body must be valid JSON.") from error
        if not isinstance(payload, dict):
            raise ValueError("Request JSON must be an object.")
        return payload

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        content = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self._add_security_headers()
        self.end_headers()
        self.wfile.write(content)

    def _add_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )

    def log_message(self, format_string: str, *args: Any) -> None:
        if urlparse(self.path).path.startswith("/api/"):
            return
        super().log_message(format_string, *args)


def main() -> int:
    parser = argparse.ArgumentParser(description="Business Agent web interface")
    parser.add_argument("--port", type=int, default=8000, help="Local web server port.")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535.")

    settings = load_settings()
    initialize_database(settings.database_path)
    seed_database(settings.database_path)
    try:
        model = create_model(settings)
    except ModelProviderError as error:
        parser.exit(2, f"Configuration error: {error}\n")

    model_name = (
        settings.groq_model
        if settings.model_provider == "groq"
        else settings.ollama_model
    )
    try:
        server = AgentWebServer(
            ("127.0.0.1", args.port),
            model=model,
            database_path=settings.database_path,
            provider=settings.model_provider,
            model_name=model_name,
        )
    except OSError as error:
        parser.exit(2, f"Could not start local web server: {error}\n")

    url = f"http://127.0.0.1:{args.port}"
    print(f"Business Agent UI is running at {url}")
    print("Press Ctrl+C to stop the server. The server only accepts local connections.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Business Agent UI.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
