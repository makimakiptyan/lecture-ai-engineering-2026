"""第1回: 素のLLMに1回だけ質問するスクリプト。

使い方:
    uv run python -m app.ask "LoRAとは何ですか？"
    uv run python -m app.ask            # 質問を省略すると、講座に固有の質問をする

ツールも会話履歴も持たない「素の」呼び出し。
講座に固有のことを聞くと、「分からない」と答えるか、一般論でもっともらしく答える
（講座の実際とは違う）ことを確かめよう。
（第3回で、用語集を検索できるエージェントにして改善する）
"""

import argparse

from google import genai
from google.genai import errors

from app.config import MODEL, api_error_message, get_api_key

# 講座に固有の質問。正しい答えは data/glossary.json の homework-levels にある
DEFAULT_QUESTION = "AIE2026の講座の宿題にある「3レベル」とは何ですか？"

# 対話モードを終える入力
EXIT_WORDS = {"exit", "quit", "終了"}


def print_usage(response) -> None:
    """入力トークン数と出力トークン数を表示する。"""
    usage = response.usage_metadata
    if usage:
        print(f"[tokens] 入力 {usage.prompt_token_count} / 出力 {usage.candidates_token_count}")


def ask(question: str) -> str:
    client = genai.Client(api_key=get_api_key())
    response = client.models.generate_content(model=MODEL, contents=question)
    print_usage(response)
    return response.text


def chat() -> None:
    """会話履歴を保ったまま、続けて質問する（第1回 宿題・実装）。

    モデル自体は前のやりとりを覚えていない。session が履歴を持ち、
    送るたびに「これまでの履歴 + 今回の質問」をまとめて送るので、入力トークン数が増えていく。
    """
    client = genai.Client(api_key=get_api_key())
    session = client.chats.create(model=MODEL)
    print("続けて質問できます。終了は exit または Ctrl+D。\n")

    while True:
        try:
            question = input("あなた> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question in EXIT_WORDS:
            break

        try:
            response = session.send_message(question)
        except errors.APIError as e:
            # 失敗したやりとりは履歴に残らない。少し待って同じ質問を送り直せばよい
            print(api_error_message(e.code, e.message))
            continue

        print(f"\nAI> {response.text}")
        print_usage(response)
        print(f"[履歴] {len(session.get_history()) // 2} 往復\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="素のLLMに質問する")
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument("--chat", action="store_true", help="会話履歴を保ったまま続けて質問する")
    args = parser.parse_args()

    print(f"[model] {MODEL}")
    if args.chat:
        chat()
        return

    print(f"[質問] {args.question}\n")
    try:
        print(ask(args.question))
    except errors.APIError as e:
        print(api_error_message(e.code, e.message))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
