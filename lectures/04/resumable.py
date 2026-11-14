"""第4回 宿題（実装）: 回答の生成と採点を、1 件ずつ保存しながら最後まで進める。

講座の app/judge.py は変えずに、その部品（読み書き・採点のプロンプト・集計）をそのまま使う。

使い方（リポジトリの一番上で実行）:
    # 回答の生成：1 件生成するごとに --cases へ保存する。answer が空の件だけを生成する
    uv run python lectures/04/resumable.py generate --cases data/eval/my_cases.jsonl

    # 採点：1 件採点するごとに途中結果（<out の名前>.partial.json）へ保存する。
    # 全件終わったら app.judge と同じ形式で --out に保存し、一致率などを表示する
    uv run python lectures/04/resumable.py judge --cases data/eval/my_cases.jsonl \
        --labels lectures/04/my_labels.jsonl --out lectures/04/my_judge_result.json

レート制限（429）やモデルの混雑（503）が出たら、その件だけを --retry-wait 秒待ってやり直す（--retries 回まで）。
それでも通らないときは、そこまでの分を保存したまま終わる。時間をおいて同じコマンドを実行すると、続きから進む。

参考: matsuolab/lecture-ai-engineering-2026 の PR #467（1 件ごとに保存して再実行で続きから進める）。
こちらは講座のファイルを変えない別スクリプトにし、待ってやり直す処理を足している。
"""

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TypeVar

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior  # noqa: E402

from app.config import MODEL  # noqa: E402
from app.judge import (  # noqa: E402
    DEFAULT_RUBRIC,
    LLM_CRITERIA,
    JudgeResult,
    build_judge,
    build_llm_model,
    build_test_model,
    check_lecture_mark,
    judge_prompt,
    load_labels,
    print_summary,
    read_jsonl,
    summarize,
    write_jsonl,
)

# 待ってやり直す HTTP ステータス（レート制限と、サーバー側の一時的なエラー）
RETRY_STATUS = {429, 500, 502, 503, 504}
STATUS_NAME = {429: "レート制限（429）", 503: "モデルの混雑（503）"}

T = TypeVar("T")


def rel(path: Path) -> Path:
    path = path if path.is_absolute() else ROOT / path
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def run_with_retry(fn: Callable[[], T], label: str, retries: int, retry_wait: float) -> T:
    """fn を呼ぶ。429 / 5xx と、出力の形式の崩れ（UnexpectedModelBehavior）のときは、待ってやり直す。"""
    for attempt in range(1, retries + 2):
        try:
            return fn()
        except ModelHTTPError as e:
            if e.status_code not in RETRY_STATUS or attempt > retries:
                raise
            why = STATUS_NAME.get(e.status_code, f"API エラー（{e.status_code}）")
        except UnexpectedModelBehavior:
            if attempt > retries:
                raise
            why = "出力の形式の崩れ"
        print(f"\n  {label}: {why}。{retry_wait:.0f} 秒待ってやり直します（{attempt}/{retries}）", flush=True)
        time.sleep(retry_wait)
    raise AssertionError("unreachable")


def stop_message(e: Exception, saved: str) -> str:
    if isinstance(e, ModelHTTPError):
        head = f"{STATUS_NAME.get(e.status_code, f'API エラー（{e.status_code}）')}が続いたので止めました: {str(e.body)[:200]}"
        if e.status_code in (400, 401, 403, 404):
            head = f"API キーかモデル名に問題があります（{e.status_code}）: {str(e.body)[:200]}"
    else:
        head = f"LLM の出力の形式が崩れたまま直りませんでした: {str(e)[:200]}"
    return f"\n{head}\n{saved}"


# ---------------------------------------------------------------- 回答の生成
def cmd_generate(args: argparse.Namespace) -> None:
    from app.agent import agent, build_model  # 第3回で作った自分のエージェント

    cases = read_jsonl(args.cases)
    if args.force:
        backup = args.cases.with_name(args.cases.stem + "_before_force.jsonl")
        write_jsonl(backup, cases)
        cases = [{**c, "answer": ""} for c in cases]
        write_jsonl(args.cases, cases)
        print(f"--force: 今の回答を {rel(backup)} に控え、全件の回答を空にしました")

    todo = [i for i, c in enumerate(cases) if not c.get("answer")]
    print(f"[model] {MODEL}")
    print(f"回答を生成中 未生成 {len(todo)} / {len(cases)} 件")
    if not todo:
        print("すべての回答が生成済みです。生成し直すには --force を付けてください")
        return

    model = build_model()
    saved = f"生成済みの回答は {rel(args.cases)} に保存されています。時間をおいて同じコマンドを実行すると、未生成分から続けます。"
    for n, i in enumerate(todo, start=1):
        case = cases[i]
        label = f"#{case['id']}"
        try:
            result = run_with_retry(
                lambda: agent.run_sync(case["question"], model=model), label, args.retries, args.retry_wait
            )
        except (ModelHTTPError, UnexpectedModelBehavior) as e:
            print(stop_message(e, saved))
            raise SystemExit(1)
        cases = [{**c, "answer": str(result.output)} if j == i else c for j, c in enumerate(cases)]
        write_jsonl(args.cases, cases)  # 1 件ごとに保存
        print(f"  {label} を保存しました（{n}/{len(todo)}）", flush=True)
        if n < len(todo):
            time.sleep(args.wait)

    print(f"→ {rel(args.cases)} の回答がすべてそろいました。次に tools/annotate.py でラベルを付けてください")


# ---------------------------------------------------------------- 採点
def progress_key(model_name: str, rubric: str, cases: list[dict]) -> dict:
    """途中結果を使ってよいかの条件。モデル・基準・評価セット（回答を含む）のどれかが変わったら使わない。"""
    sha = lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest()  # noqa: E731
    return {
        "model": model_name,
        "rubric_sha256": sha(rubric),
        "cases_sha256": sha(json.dumps(cases, ensure_ascii=False, sort_keys=True)),
    }


def load_progress(path: Path, key: dict) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or any(data.get(k) != v for k, v in key.items()):
        return {}
    verdicts = data.get("verdicts")
    return verdicts if isinstance(verdicts, dict) else {}


def save_progress(path: Path, key: dict, verdicts: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**key, "verdicts": verdicts}, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_judge(args: argparse.Namespace) -> None:
    cases = read_jsonl(args.cases)
    if not args.labels.exists():
        raise SystemExit(
            f"{rel(args.labels)} がありません。先に tools/annotate.py で 10 件のラベルを付けて保存してください"
            "（サイドバーの「評価セット」と「ラベルの保存先」を変えてから）"
        )
    empty = [c["id"] for c in cases if not c.get("answer")]
    if empty:
        raise SystemExit(f"回答が空の件があります: {', '.join('#' + i for i in empty)}。先に generate で回答を生成してください")
    labels = load_labels(args.labels)
    rubric = args.rubric.read_text(encoding="utf-8")

    model_name = args.model or MODEL
    if model_name == "test":
        model = build_test_model()
        print("[model] test（API を呼ばず、簡単な規則で判定する偽モデル。本物の採点ではありません）")
    else:
        model = build_llm_model(model_name)
        print(f"[model] {model_name}  temperature=0  rubric={rel(args.rubric)}")
    judge = build_judge(model, rubric)

    partial = args.out.with_name(args.out.stem + ".partial.json")
    key = progress_key(model_name, rubric, cases)
    ids = {c["id"] for c in cases}
    verdicts = {cid: v for cid, v in load_progress(partial, key).items() if cid in ids}
    if verdicts:
        print(f"前回の途中結果 {len(verdicts)} 件を {rel(partial)} から読み込みました。続きから採点します")
    todo = [c for c in cases if c["id"] not in verdicts]
    print(f"採点中 未採点 {len(todo)} / {len(cases)} 件")

    saved = f"採点済みの結果は {rel(partial)} に保存されています。時間をおいて同じコマンドを実行すると、未採点分から続けます。"
    for n, case in enumerate(todo, start=1):
        label = f"#{case['id']}"
        try:
            result = run_with_retry(
                lambda: judge.run_sync(judge_prompt(case)), label, args.retries, args.retry_wait
            )
        except (ModelHTTPError, UnexpectedModelBehavior) as e:
            print(stop_message(e, saved))
            raise SystemExit(1)
        out: JudgeResult = result.output
        one = {k: getattr(out, k).model_dump() for k, _ in LLM_CRITERIA}
        one["lecture_mark"] = {
            "reason": "末尾（最後の行）に「第N回」があるかをコードで判定",
            "verdict": check_lecture_mark(case["answer"]),
        }
        verdicts = {**verdicts, case["id"]: one}
        save_progress(partial, key, verdicts)  # 1 件ごとに保存
        print(f"  {label} を採点しました（{n}/{len(todo)}）", flush=True)
        if n < len(todo):
            time.sleep(args.wait)

    summary = summarize(cases, verdicts, labels)
    print_summary(summary)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {"model": model_name, "rubric": str(rel(args.rubric)), "run_at": datetime.now().isoformat(timespec="seconds"),
             "verdicts": verdicts, "summary": summary},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    partial.unlink(missing_ok=True)
    print(f"\n→ {rel(args.out)} に保存しました")


# ---------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="回答の生成と採点を、1 件ずつ保存しながら最後まで進める")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, wait: float) -> None:
        p.add_argument("--cases", type=Path, default=Path("data/eval/my_cases.jsonl"), help="評価セット（jsonl）")
        p.add_argument("--wait", type=float, default=wait, help=f"1 件ごとに待つ秒数（既定 {wait:g}）")
        p.add_argument("--retries", type=int, default=5, help="429 / 503 などのとき、1 件をやり直す回数（既定 5）")
        p.add_argument("--retry-wait", type=float, default=60.0, help="やり直す前に待つ秒数（既定 60）")

    g = sub.add_parser("generate", help="自分のエージェントで回答を生成する（answer が空の件だけ）")
    common(g, wait=2.0)
    g.add_argument("--force", action="store_true", help="今の回答を控えてから、全件を空にして生成し直す")

    j = sub.add_parser("judge", help="LLM に採点させ、自分のラベルとの一致率を出す")
    common(j, wait=4.0)
    j.add_argument("--labels", type=Path, default=Path("lectures/04/my_labels.jsonl"), help="自分のラベル（jsonl）")
    j.add_argument("--rubric", type=Path, default=DEFAULT_RUBRIC, help="採点の基準（markdown）")
    j.add_argument("--out", type=Path, default=Path("lectures/04/my_judge_result.json"), help="採点結果の保存先（json）")
    j.add_argument("--model", default=None, help="採点に使うモデル。既定は AIE_MODEL。'test' で API を呼ばない偽モデル")

    args = parser.parse_args(argv)
    for name in ("cases", "labels", "rubric", "out"):
        p = getattr(args, name, None)
        if p is not None and not p.is_absolute():
            setattr(args, name, ROOT / p)

    if args.command == "generate":
        cmd_generate(args)
    else:
        cmd_judge(args)


if __name__ == "__main__":
    main()
