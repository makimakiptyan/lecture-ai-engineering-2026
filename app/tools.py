"""第3回: エージェントに持たせるツール。

ここに書いた関数の docstring と型ヒントが、そのままモデルへの「ツールの説明文」になる。
説明文を書き換えると、モデルがツールを使うかどうか・どんな引数で呼ぶかが変わる。
"""

import json
import random
from datetime import datetime, timedelta, timezone
from functools import cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_RESULTS = 3

# 第3回 宿題（実装）: 学習の記録の保存先。.gitignore 済みなので commit されない
LOG_DIR = Path(__file__).resolve().parent.parent / "learning_log"
MAX_TITLE_CHARS = 60
MAX_LOG_CHARS = 2000
# Codespaces の時計は UTC なので、日本時間に固定する
JST = timezone(timedelta(hours=9), "JST")

@cache
def load_glossary() -> list[dict]:
    with open(DATA_DIR / "glossary.json", encoding="utf-8") as f:
        return json.load(f)["terms"]


def _normalize(text: str) -> str:
    return text.casefold().replace(" ", "").replace("　", "")


def _names(entry: dict) -> list[str]:
    return [_normalize(entry["term"]), _normalize(entry["id"])] + [
        _normalize(a) for a in entry["aliases"]
    ]


def search_glossary(query: str) -> str:
    """講座の用語集から用語を検索し、定義と、どの回で扱うかを返す。

    AIエンジニアリングの用語や、この講座（AIE2026）に固有の言葉について
    答える前に使うこと。query には調べたい用語を1つだけ入れる（例: "LoRA"）。
    """
    q = _normalize(query)
    if not q:
        return "検索語が空です。調べたい用語を1つ指定してください。"
    glossary = load_glossary()

    exact = [e for e in glossary if q in _names(e)]
    # 「r」のような短い別名が何にでも当たらないよう、名前側が短いものは除く
    partial = [
        e for e in glossary
        if e not in exact and any(q in n or (len(n) >= 3 and n in q) for n in _names(e))
    ]
    in_definition = [
        e for e in glossary
        if e not in exact and e not in partial and q in _normalize(e["definition"])
    ]
    hits = (exact + partial + in_definition)[:MAX_RESULTS]

    if not hits:
        return f"用語集に「{query}」は見つかりませんでした。"
    return json.dumps(
        [
            {
                "term": e["term"],
                "lecture": e["lecture"],
                "definition": e["definition"],
                "related": e["related"],
            }
            for e in hits
        ],
        ensure_ascii=False,
    )


def get_lecture_summary(lecture: int) -> str:
    """指定した回（1始まりの整数）の講義の要点を返す。

    「第3回では何を学ぶ？」のように、回の内容や関係を聞かれたときに使う。
    """
    path = DATA_DIR / "lectures" / f"{lecture:02d}.md"
    if not path.exists():
        available = sorted(p.stem for p in (DATA_DIR / "lectures").glob("*.md"))
        return f"第{lecture}回の要点はまだありません。用意されている回: {', '.join(available)}"
    return path.read_text(encoding="utf-8")

def make_quiz(lecture: int) -> str:
    """指定した回（1始まりの整数）の用語から確認問題を1問作り、問題と答えを返す。

    「第2回の確認問題を出して」「第3回の復習クイズがほしい」のように、
    復習用の問題を求められたときに使う。lecture には回の番号を入れる（例: 2）。
    返り値の answer は採点用なので、利用者が答えるまでは見せない。
    """
    terms = [e for e in load_glossary() if e["lecture"] == lecture]
    if not terms:  # 第0回など、用語が無い回（pytest はこれで呼ぶ）
        available = sorted({e["lecture"] for e in load_glossary()})
        return (
            f"第{lecture}回の用語は用語集にありません。"
            f"問題を作れる回: {', '.join(f'第{n}回' for n in available)}"
        )
    term = random.choice(terms)
    return json.dumps(
        {"question": f"「{term['term']}」の意味は？", "answer": term["definition"]},
        ensure_ascii=False,
    )

def save_learning_log(title: str, content: str) -> str:
    """学習の記録を learning_log/ フォルダに保存する（今日の日付のファイルに追記する）。

    利用者が「今日の学びを記録して」「この説明をメモに残して」のように、
    記録を残すことをはっきり頼んだときだけ使う。頼まれていないときは使わない。
    title には見出しを短く（例: "LoRAとQLoRAの違い"）、content には残す内容を
    箇条書きで簡潔にまとめて入れる。保存の前に、利用者の承認を求める。
    """
    title = " ".join(title.split())  # 改行や連続した空白を1つにして、見出しを1行にする
    content = content.strip()
    if not title or not content:
        return "title と content の両方が必要です。保存していません。"
    if len(title) > MAX_TITLE_CHARS:
        return f"title が長すぎます（{len(title)}字、上限{MAX_TITLE_CHARS}字）。短くしてください。保存していません。"
    if len(content) > MAX_LOG_CHARS:
        return f"content が長すぎます（{len(content)}字、上限{MAX_LOG_CHARS}字）。要点にまとめてください。保存していません。"

    now = datetime.now(JST)
    # ファイル名は日付だけで決める。モデルが作る文字列をパスに使わないので、
    # 「../」などで learning_log/ の外へ書き込まれることがない
    path = LOG_DIR / f"{now:%Y-%m-%d}.md"
    LOG_DIR.mkdir(exist_ok=True)
    # 追記（"a"）なので、前の記録を上書きしない
    with path.open("a", encoding="utf-8") as f:
        f.write(f"## {now:%H:%M} {title}\n\n{content}\n\n")
    return f"learning_log/{path.name} に「{title}」を保存しました。"
