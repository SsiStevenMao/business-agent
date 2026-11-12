from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from business_agent.database import initialize_database
from business_agent.web import AgentWebServer


class WebServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "web.db"
        initialize_database(self.database_path)
        self.model = Mock()
        self.model.route_request.return_value = {
            "intent": "general",
            "sql": "",
            "answer": "Hello from the assistant.",
        }
        self.server = AgentWebServer(
            ("127.0.0.1", 0),
            model=self.model,
            database_path=self.database_path,
            provider="test",
            model_name="test-model",
        )
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def _post(self, path: str, payload: dict[str, object]) -> tuple[int, dict]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_serves_bilingual_ui_and_model_configuration(self) -> None:
        with urlopen(self.base_url, timeout=3) as response:
            html = response.read().decode("utf-8")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertIn('id="language-select"', html)
        self.assertIn("Northstar", html)

        with urlopen(f"{self.base_url}/styles.css", timeout=3) as response:
            stylesheet = response.read().decode("utf-8")
        self.assertNotIn("fonts.googleapis.com", stylesheet)

        with urlopen(f"{self.base_url}/api/config", timeout=3) as response:
            config = json.loads(response.read())
        self.assertEqual(config["provider"], "test")
        self.assertEqual(config["model"], "test-model")
        self.assertIn("sales_analyst", [role["id"] for role in config["roles"]])

    def test_chat_endpoint_routes_message_and_returns_answer(self) -> None:
        status, response = self._post(
            "/api/chat",
            {
                "message": "Hello",
                "role": "admin",
                "show_trace": True,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["answer"], "Hello from the assistant.")
        self.assertGreaterEqual(response["elapsed_seconds"], 0)
        self.model.route_request.assert_called_once()

    def test_chat_endpoint_blocks_general_questions_for_non_admin(self) -> None:
        status, response = self._post(
            "/api/chat",
            {"message": "Hello", "role": "sales_analyst"},
        )

        self.assertEqual(status, 200)
        self.assertIn("admin role", response["answer"])
        self.model.route_request.assert_not_called()

    def test_chat_endpoint_rejects_empty_message_and_unknown_role(self) -> None:
        status, response = self._post(
            "/api/chat",
            {"message": " ", "role": "sales_analyst"},
        )
        self.assertEqual(status, 400)
        self.assertIn("empty", response["error"])

        status, response = self._post(
            "/api/chat",
            {"message": "hello", "role": "owner"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(response["error"], "Unknown role.")

    def test_reset_endpoint_clears_role_conversation(self) -> None:
        agent = self.server.agents["sales_analyst"]
        agent._remember_turn("question", "answer")
        status, response = self._post(
            "/api/reset",
            {"role": "sales_analyst"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(response["ok"])
        self.assertEqual(agent._conversation_history, [])


if __name__ == "__main__":
    unittest.main()
