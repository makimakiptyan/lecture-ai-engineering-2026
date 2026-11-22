"""第5回 宿題（実装）: 通常の検索と「前後1ページ付きの検索」を、同じ質問で比べる。

使い方（リポジトリのルートで）:
    uv run python lectures/05/compare_neighbors.py              # 3問 × 2方式を1回ずつ実行して保存
    uv run python lectures/05/compare_neighbors.py --repeat 2   # 2回ずつ（実行済みの分は飛ばす）
    uv run python lectures/05/compare_neighbors.py --report     # 保存した結果を表にする（APIを使わない）

- 結果は1回ごとに lectures/05/neighbor_runs.jsonl へ追記する。途中で止まっても、もう一度実行すれば続きから。
- レート制限（429）や混雑（503）は、その回だけ60秒待ってやり直す（5回まで）。
  検索ツールの中の埋め込みAPIが429になると、エラーがツールの結果としてモデルに渡り、
  モデルは「確認できない」と答えてしまう。この場合も比較に使えないので、待ってやり直す。
- 講座の app/agent.py の agent をそのまま使い、変えるのは config.RAG_NEIGHBOR_WINDOW（0 と 1）だけ。
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from statistics import mean
from time import perf_counter

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ToolCallPart, ToolReturnPart

# lectures/05/ から実行しても app/ を読めるよう、リポジトリのルートを探索先に加える
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import config  # noqa: E402
from app.agent import agent, build_model  # noqa: E402

OUT = Path(__file__).resolve().parent / "neighbor_runs.jsonl"

# 演習資料の「比較に使う質問」の3種類。自分の質問を足すときはここに1行加える。
QUESTIONS = [
    ("single", "第2回の説明では、LoRAは何を固定し何を学習しますか？ QLoRAは何を加えますか？", "第2回 p.52"),
    ("multi", "第3回の例では、コンパクションとセッションをまたぐメモリはどう違いますか。日々のメモはすべて長期メモリに入りますか", "第3回 p.13, 39, 40"),
    ("none", "今回作ったRAGの実測平均応答時間と正答率を教えてください", "資料にない（確認できないと答えるのが正しい）"),
]
MODES = [("通常の検索", 0), ("前後1ページ付き", 1)]
RETRYABLE = (429, 503)
WAIT_SECONDS = 60
MAX_TRIES = 5


class Retry(Exception):
    pass


def run_once(question: str, window: int, model) -> dict:
    config.RAG_NEIGHBOR_WINDOW = window
    started = perf_counter()
    result = agent.run_sync(question, model=model)
    elapsed = perf_counter() - started

    queries, pages, errors = [], [], []
    for message in result.all_messages():
        for part in message.parts:
            if isinstance(part, ToolCallPart) and part.tool_name == "search_materials":
                queries.append(part.args_as_dict().get("query"))
            elif isinstance(part, ToolReturnPart) and part.tool_name == "search_materials":
                data = json.loads(part.content)
                if "error" in data:
                    errors.append(data["error"])
                pages += [{"lecture": r["lecture"], "page": r["page"], "match": r.get("match", "search")}
                          for r in data.get("results", [])]
    if errors and not pages:
        raise Retry(f"検索ツールがエラーを返しました: {errors[0]}")
    usage = result.usage
    return {
        "elapsed": round(elapsed, 2),
        "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
        "requests": usage.requests, "cost": usage.cost,
        "queries": queries, "returned_pages": pages, "tool_errors": errors,
        # 「第N回・PDF p.N」の形の引用を拾う（「p.51、52」のような並びは先頭だけになることがある）
        "cited": sorted(set(re.findall(r"第\s*(\d+)\s*回\D{0,6}p\.?\s*(\d+)", str(result.output)))),
        "output": str(result.output),
    }


def load_runs() -> list[dict]:
    if not OUT.exists():
        return []
    return [json.loads(line) for line in OUT.read_text(encoding="utf-8").splitlines() if line.strip()]


def run(repeat: int) -> None:
    done = {(r["qid"], r["window"], r["rep"]) for r in load_runs()}
    model = build_model()
    for rep in range(1, repeat + 1):
        for qid, question, _ in QUESTIONS:
            for label, window in MODES:  # 同じ質問の2方式を続けて実行し、時間帯の差を小さくする
                if (qid, window, rep) in done:
                    continue
                for attempt in range(1, MAX_TRIES + 1):
                    print(f"[{qid} / {label} / {rep}回目] 実行中…（{attempt}回目の試行）")
                    try:
                        record = run_once(question, window, model)
                        break
                    except ModelHTTPError as e:
                        if e.status_code not in RETRYABLE:
                            raise
                        reason = config.api_error_message(e.status_code)
                    except Retry as e:
                        reason = str(e)
                    if attempt == MAX_TRIES:
                        raise SystemExit(f"{MAX_TRIES}回試しても進みません。時間をおいて同じコマンドを実行すると続きから再開します。")
                    print(f"  {reason} → {WAIT_SECONDS}秒待って再試行します")
                    time.sleep(WAIT_SECONDS)
                record = {"qid": qid, "question": question, "mode": label, "window": window, "rep": rep,
                          "model": config.MODEL, **record}
                with OUT.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(f"  {record['elapsed']}秒 / 入力{record['input_tokens']:,} 出力{record['output_tokens']:,} tokens"
                      f" / 返したページ{len(record['returned_pages'])} / 引用 {record['cited']}")


def report() -> None:
    runs = load_runs()
    if not runs:
        raise SystemExit(f"{OUT} がありません。先に --report なしで実行してください。")
    print(f"モデル: {', '.join(sorted({r['model'] for r in runs}))}\n")
    for qid, question, expected in QUESTIONS:
        print(f"### {question}\n\n期待する根拠：{expected}\n")
        print("| 方式 | 回数 | 時間（秒） | 入力／出力トークン | モデル応答 | 生成API推定費用（USD） | 返したページ（前後で足した分） | 回答の引用 |")
        print("|---|---|---|---|---|---|---|---|")
        for label, window in MODES:
            rows = [r for r in runs if r["qid"] == qid and r["window"] == window]
            if not rows:
                print(f"| {label} | 0 | 未実行 | | | | | |")
                continue
            costs = [r["cost"] for r in rows if r["cost"] is not None]
            cost = f"{mean(costs):.6f}" if len(costs) == len(rows) else "算定不可を含む"
            returned = mean(len(r["returned_pages"]) for r in rows)
            added = mean(sum(p["match"] == "neighbor" for p in r["returned_pages"]) for r in rows)
            cited = " / ".join(", ".join(f"第{l}回 p.{p}" for l, p in r["cited"]) or "なし" for r in rows)
            print(f"| {label} | {len(rows)} | {mean(r['elapsed'] for r in rows):.2f}"
                  f" | {mean(r['input_tokens'] for r in rows):,.0f}／{mean(r['output_tokens'] for r in rows):,.0f}"
                  f" | {mean(r['requests'] for r in rows):.1f} | {cost} | {returned:.1f}（{added:.1f}） | {cited} |")
        print("\n<!-- 複数回の場合は平均。引用は回ごとに / で区切る。回答の正しさは本文を読んで自分で判定する -->\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="通常の検索と前後1ページ付きの検索を、同じ質問で比べる")
    parser.add_argument("--repeat", type=int, default=1, help="各質問・各方式を何回ずつ実行するか")
    parser.add_argument("--report", action="store_true", help="保存した結果を表にする（APIを使わない）")
    args = parser.parse_args()
    report() if args.report else run(args.repeat)
