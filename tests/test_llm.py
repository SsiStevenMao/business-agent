import unittest
from types import SimpleNamespace
from unittest.mock import patch

from business_agent.llm import OllamaAgentError, OllamaModel


class OllamaModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = OllamaModel("http://localhost:11434", "test-model")

    def test_intent_routing_keeps_thinking_enabled(self) -> None:
        response = SimpleNamespace(
            message=SimpleNamespace(
                content='{"intent":"business_query","sql":"SELECT 1","answer":""}'
            )
        )
        with patch.object(self.model.client, "chat", return_value=response) as chat:
            result = self.model.route_request("test", "schema")

        self.assertEqual(result["intent"], "business_query")
        self.assertEqual(result["sql"], "SELECT 1")
        self.assertTrue(chat.call_args.kwargs["think"])
        self.assertEqual(chat.call_args.kwargs["options"]["num_predict"], 4096)

    def test_empty_model_answer_reports_reasoning_budget_issue(self) -> None:
        response = SimpleNamespace(message=SimpleNamespace(content=""))
        with patch.object(self.model.client, "chat", return_value=response):
            with self.assertRaisesRegex(OllamaAgentError, "reasoning budget"):
                self.model.route_request("test", "schema")


if __name__ == "__main__":
    unittest.main()
