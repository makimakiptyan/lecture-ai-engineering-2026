"""第4回 宿題（実装）: コードで判定できる基準を、自分のラベルと比べる（API は呼ばない）。

使い方:
    uv run python lectures/04/code_checks.py \
        --cases data/eval/my_cases.jsonl --labels lectures/04/my_labels.jsonl

    # 演習の評価セットと講師のラベルで、規則そのものを先に確かめる
    uv run python lectures/04/code_checks.py \
        --cases data/eval/lec04_cases.jsonl --labels lectures/04/reference/labels_instructor.jsonl

LLM に聞かず、文字列だけで決める規則を 3 つ用意し、人のラベルとの一致を出す。
一致が高い規則は「コードで判定してよい」、低い規則は「コードでは測れない（LLM か人に任せる）」の根拠になる。
規則の中身や上限の字数は、自分の評価セットに合わせて変えてよい。
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.judge import check_lecture_mark, load_labels, read_jsonl  # noqa: E402

DEFERRED_PREFIX = "DeferredToolRequests("


def rule_lecture_mark(case: dict, _max_chars: int) -> str:
    """回の表示：最後の行に「第N回」があるか（app/judge.py と同じ規則）。"""
    return check_lecture_mark(case["answer"])


def rule_hint_no_code(case: dict, _max_chars: int) -> str:
    """ヒント：宿題についての質問に、コードブロック（```）で答えていたら fail。宿題と無関係なら pass。"""
    if "宿題" not in case["question"]:
        return "pass"
    return "fail" if "```" in case["answer"] else "pass"


def rule_clarity_length(case: dict, max_chars: int) -> str:
    """分かりやすさ（の代わり）：コードブロックを除いた本文が max_chars 字を超えたら fail。"""
    body = re.sub(r"```.*?```", "", case["answer"], flags=re.S)
    return "fail" if len(body.strip()) > max_chars else "pass"


# (表示名, 比べる人のラベルの列, 規則)
RULES = [
    ("回の表示：末尾の第N回", "lecture_mark", rule_lecture_mark),
    ("ヒント：宿題にコードブロック", "hint", rule_hint_no_code),
    ("分かりやすさ：本文の字数", "clarity", rule_clarity_length),
]


def format_problems(case: dict) -> str | None:
    """人のラベルの列はないが、コードで必ず見つけたい形の問題（空の回答・承認待ちのまま）。"""
    answer = case["answer"].strip()
    if not answer:
        return "回答が空"
    if answer.startswith(DEFERRED_PREFIX):
        return "承認待ち（DeferredToolRequests）のまま。利用者向けの文になっていない"
    return None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="コードで判定できる基準を、自分のラベルと比べる")
    parser.add_argument("--cases", type=Path, default=ROOT / "data" / "eval" / "my_cases.jsonl")
    parser.add_argument("--labels", type=Path, default=ROOT / "lectures" / "04" / "my_labels.jsonl")
    parser.add_argument("--max-chars", type=int, default=400, help="分かりやすさの規則で使う本文の上限（字）")
    args = parser.parse_args(argv)

    cases = read_jsonl(args.cases)
    labels = load_labels(args.labels)
    ids = [c["id"] for c in cases if c["id"] in labels]
    print(f"コードの規則と人のラベルの一致（{len(ids)} 件、分かりやすさの上限 {args.max_chars} 字）")

    for name, key, rule in RULES:
        agree, rows = 0, []
        for case in cases:
            if case["id"] not in labels:
                continue
            code, human = rule(case, args.max_chars), labels[case["id"]].get(key)
            if code == human:
                agree += 1
            else:
                kind = "見逃し" if code == "pass" else "過検出"
                rows.append(f"    #{case['id']} {kind}（コード={code} 人={human}）")
        print(f"  {name}  {agree}/{len(ids)}")
        for row in rows:
            print(row)

    problems = [(c["id"], p) for c in cases if (p := format_problems(c))]
    print(f"\n形の問題 {len(problems)} 件（人のラベルの列はない。コードで必ず拾う）")
    for cid, problem in problems:
        print(f"  #{cid} {problem}")


if __name__ == "__main__":
    main()
