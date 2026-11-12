import json
from typing import Protocol

from openai import APIError, OpenAI
from ollama import Client, RequestError, ResponseError

from business_agent.config import Settings


SQL_RESPONSE_FORMAT = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["business_query", "clarification", "general"],
        },
        "sql": {"type": "string"},
        "answer": {"type": "string"},
    },
    "required": ["intent", "sql", "answer"],
    "additionalProperties": False,
}


class ModelProviderError(RuntimeError):
    """Raised when a configured language model cannot produce a usable answer."""


class LanguageModel(Protocol):
    def route_request(self, question: str, system_prompt: str) -> dict[str, str]: ...


def parse_route_response(content: str | None) -> dict[str, str]:
    if not content or not content.strip():
        raise ModelProviderError(
            "The model returned an empty response. Try a more specific question."
        )
    try:
        result = json.loads(content)
    except json.JSONDecodeError as error:
        raise ModelProviderError("The model returned an invalid JSON route.") from error
    if not isinstance(result, dict) or not isinstance(result.get("sql"), str):
        raise ModelProviderError("The model response did not contain a valid route.")
    intent = result.get("intent")
    if not isinstance(intent, str) or intent not in {
        "business_query",
        "clarification",
        "general",
    }:
        raise ModelProviderError("The model returned an unsupported request intent.")
    if not isinstance(result.get("answer"), str):
        raise ModelProviderError("The model response did not contain a text answer.")
    return result


class OllamaModel:
    def __init__(self, host: str, model: str) -> None:
        self.client = Client(host=host)
        self.model = model

    def route_request(self, question: str, system_prompt: str) -> dict[str, str]:
        try:
            response = self.client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
                format=SQL_RESPONSE_FORMAT,
                think=True,
                options={"temperature": 0.1, "num_ctx": 8192, "num_predict": 4096},
                keep_alive="10m",
            )
        except (RequestError, ResponseError) as error:
            raise ModelProviderError(f"Ollama request failed: {error}") from error
        return parse_route_response(response.message.content)


class GroqModel:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
            timeout=120.0,
            max_retries=1,
        )
        self.model = model

    def route_request(self, question: str, system_prompt: str) -> dict[str, str]:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_completion_tokens=4096,
            )
        except APIError as error:
            status = f" (HTTP {error.status_code})" if error.status_code else ""
            raise ModelProviderError(f"Groq API request failed{status}: {error.message}") from error
        return parse_route_response(response.choices[0].message.content)


def create_model(settings: Settings) -> LanguageModel:
    if settings.model_provider == "groq":
        if not settings.groq_api_key:
            raise ModelProviderError(
                "GROQ_API_KEY is missing. Add it to your local .env file."
            )
        return GroqModel(settings.groq_api_key, settings.groq_model)
    if settings.model_provider == "ollama":
        return OllamaModel(settings.ollama_host, settings.ollama_model)
    raise ModelProviderError(
        f"Unsupported MODEL_PROVIDER '{settings.model_provider}'. Use 'groq' or 'ollama'."
    )
