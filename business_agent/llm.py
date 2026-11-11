import json

from ollama import Client


SQL_RESPONSE_FORMAT = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["business_query", "general"]},
        "sql": {"type": "string"},
        "answer": {"type": "string"},
    },
    "required": ["intent", "sql", "answer"],
    "additionalProperties": False,
}


class OllamaAgentError(RuntimeError):
    """Raised when Ollama cannot produce a usable answer."""


class OllamaModel:
    def __init__(self, host: str, model: str) -> None:
        self.client = Client(host=host)
        self.model = model

    def route_request(self, question: str, system_prompt: str) -> dict[str, str]:
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
        content = response.message.content.strip()
        if not content:
            raise OllamaAgentError(
                "Ollama used its reasoning budget without returning SQL. "
                "Try a more specific question or increase num_predict in llm.py."
            )
        try:
            result = json.loads(content)
        except json.JSONDecodeError as error:
            raise OllamaAgentError("Ollama returned a non-JSON SQL plan.") from error
        if not isinstance(result, dict) or not isinstance(result.get("sql"), str):
            raise OllamaAgentError("Ollama response did not contain a valid route.")
        if result.get("intent") not in {"business_query", "general"}:
            raise OllamaAgentError("Ollama returned an unsupported request intent.")
        if not isinstance(result.get("answer"), str):
            raise OllamaAgentError("Ollama response did not contain a text answer.")
        return result
