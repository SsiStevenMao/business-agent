import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from business_agent.config import Settings
from business_agent.llm import (
    GroqModel,
    ModelProviderError,
    OllamaModel,
    create_model,
    parse_route_response,
)


class ModelProviderTests(unittest.TestCase):
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
            with self.assertRaisesRegex(ModelProviderError, "empty response"):
                self.model.route_request("test", "schema")

    def test_model_factory_selects_groq_without_exposing_api_key(self) -> None:
        settings = Settings(
            model_provider="groq",
            groq_model="openai/gpt-oss-20b",
            groq_api_key="test-key",
            database_path=Path("business.db"),
        )

        model = create_model(settings)

        self.assertIsInstance(model, GroqModel)
        self.assertEqual(str(model.client.base_url), "https://api.groq.com/openai/v1/")
        self.assertNotIn("test-key", repr(settings))

    def test_model_factory_requires_key_for_groq(self) -> None:
        settings = Settings(
            model_provider="groq",
            database_path=Path("business.db"),
        )
        with self.assertRaisesRegex(ModelProviderError, "GROQ_API_KEY"):
            create_model(settings)

    def test_route_response_parser_checks_required_fields(self) -> None:
        result = parse_route_response(
            '{"intent":"general","sql":"","answer":"Hello"}'
        )
        self.assertEqual(result["intent"], "general")
        clarification = parse_route_response(
            '{"intent":"clarification","sql":"","answer":"Which date range?"}'
        )
        self.assertEqual(clarification["intent"], "clarification")
        with self.assertRaisesRegex(ModelProviderError, "unsupported request intent"):
            parse_route_response('{"intent":"other","sql":"","answer":""}')

    def test_groq_adapter_sends_structured_request(self) -> None:
        model = GroqModel("test-key", "openai/gpt-oss-20b")
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"intent":"general","sql":"","answer":"Hello"}'
                    )
                )
            ]
        )
        with patch.object(
            model.client.chat.completions,
            "create",
            return_value=response,
        ) as create:
            result = model.route_request("Hi", "Classify requests.")

        self.assertEqual(result["intent"], "general")
        self.assertEqual(create.call_args.kwargs["model"], "openai/gpt-oss-20b")
        self.assertEqual(
            create.call_args.kwargs["response_format"],
            {"type": "json_object"},
        )


if __name__ == "__main__":
    unittest.main()
