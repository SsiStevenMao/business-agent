import argparse
from functools import partial
import sys
import time

from business_agent.agent import BusinessAgent
from business_agent.config import load_settings
from business_agent.database import QueryError, initialize_database
from business_agent.llm import ModelProviderError, create_model
from business_agent.roles import ROLES
from business_agent.seed import seed_database


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
    try:
        model = create_model(settings)
    except ModelProviderError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    agent = BusinessAgent(
        settings.database_path,
        model,
        role,
    )

    print(
        f"Business Agent | role: {role.name} | "
        f"model: {settings.groq_model if settings.model_provider == 'groq' else settings.ollama_model}\n"
        "Ask about orders, customers, or products. Type '/clear' to clear chat memory; "
        "type 'exit' to quit."
    )
    while True:
        try:
            question = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if question.lower() in {"exit", "quit"}:
            return 0
        if question.lower() == "/clear":
            agent.clear_conversation()
            print("对话记忆已清除。")
            continue
        if not question:
            continue
        try:
            started_at = time.perf_counter()
            sql, answer = agent.answer(
                question,
                on_progress=partial(print, end="\n", flush=True),
            )
            elapsed = time.perf_counter() - started_at
        except (ModelProviderError, QueryError) as error:
            print(f"Agent error: {error}")
            continue
        print(f"\nAgent> {answer}\n耗时: {elapsed:.2f} 秒")
        if sql:
            print(f"SQL> {sql}")


if __name__ == "__main__":
    raise SystemExit(main())
