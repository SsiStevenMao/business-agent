import argparse
from functools import partial

from business_agent.agent import BusinessAgent
from business_agent.config import load_settings
from business_agent.database import QueryError, initialize_database
from business_agent.llm import OllamaAgentError, OllamaModel
from business_agent.roles import ROLES
from business_agent.seed import seed_database
from ollama import RequestError, ResponseError


def main() -> int:
    parser = argparse.ArgumentParser(description="Local business data agent")
    parser.add_argument(
        "--role",
        choices=sorted(ROLES),
        default="sales_analyst",
        help="Select the agent role and its read permissions.",
    )
    args = parser.parse_args()

    settings = load_settings()
    initialize_database(settings.database_path)
    seed_database(settings.database_path)
    role = ROLES[args.role]
    agent = BusinessAgent(
        settings.database_path,
        OllamaModel(settings.ollama_host, settings.ollama_model),
        role,
    )

    print(
        f"Business Agent | role: {role.name} | model: {settings.ollama_model}\n"
        "Ask about orders, customers, or products. Type 'exit' to quit."
    )
    while True:
        try:
            question = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if question.lower() in {"exit", "quit"}:
            return 0
        if not question:
            continue
        try:
            sql, answer = agent.answer(
                question,
                on_progress=partial(print, end="\n", flush=True),
            )
        except (OllamaAgentError, QueryError, RequestError, ResponseError) as error:
            print(f"Agent error: {error}")
            continue
        print(f"\nAgent> {answer}")
        if sql:
            print(f"SQL> {sql}")


if __name__ == "__main__":
    raise SystemExit(main())
