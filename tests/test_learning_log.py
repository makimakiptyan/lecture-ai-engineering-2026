"""第3回 宿題（実装）のテスト: save_learning_log と、保存の前の承認（LLM も API キーも使わない）。"""

import json

import pytest
from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models.test import TestModel

from app import tools
from app.agent import agent, run_with_approval


@pytest.fixture(autouse=True)
def log_dir(tmp_path, monkeypatch):
    """本物の learning_log/ に書き込まないよう、保存先を一時フォルダに差し替える。"""
    path = tmp_path / "learning_log"
    monkeypatch.setattr(tools, "LOG_DIR", path)
    return path


def _saved(log_dir) -> str:
    files = list(log_dir.glob("*.md"))
    return "".join(f.read_text(encoding="utf-8") for f in files)


def test_save_appends_without_overwriting(log_dir):
    assert "保存しました" in tools.save_learning_log("LoRA", "- 一部だけ学習する")
    assert "保存しました" in tools.save_learning_log("QLoRA", "- 4bit で読み込む")
    text = _saved(log_dir)
    assert "LoRA" in text and "QLoRA" in text  # 2回目で1回目が消えていない
    assert len(list(log_dir.glob("*.md"))) == 1  # 同じ日の記録は1つのファイルにまとまる


def test_save_rejects_empty_or_too_long(log_dir):
    assert "保存していません" in tools.save_learning_log("", "内容")
    assert "保存していません" in tools.save_learning_log("見出し", "  ")
    assert "保存していません" in tools.save_learning_log("見出し", "あ" * (tools.MAX_LOG_CHARS + 1))
    assert not log_dir.exists()


def test_title_cannot_choose_the_file_path(log_dir):
    tools.save_learning_log("../../app/tools", "パスに見える見出し")
    assert [p.parent for p in log_dir.parent.rglob("*.md")] == [log_dir]


def test_make_quiz():
    quiz = json.loads(tools.make_quiz(2))
    assert quiz["question"].endswith("の意味は？") and quiz["answer"]
    assert "ありません" in tools.make_quiz(0)


def _run(answer: str):
    """TestModel に save_learning_log だけを呼ばせ、承認の問いに answer と答える。"""
    model = TestModel(call_tools=["save_learning_log"])
    with agent.override(model=model):
        first = agent.run_sync("今日の学びを記録して")
        result = run_with_approval(agent, "今日の学びを記録して", model, ask=lambda _: answer)
    return first, result


def test_run_stops_before_saving(log_dir):
    first, _ = _run("n")
    assert isinstance(first.output, DeferredToolRequests)  # 承認待ちで止まる
    assert [c.tool_name for c in first.output.approvals] == ["save_learning_log"]
    assert not log_dir.exists()  # 止まっている間、ツールの本体は実行されていない


def test_without_deferred_output_type_fails_when_called():
    """output_type に DeferredToolRequests が無いと、登録はできるが、呼ばれた時点でエラーになる。"""
    plain = Agent(instructions="test")
    plain.tool_plain(tools.save_learning_log, requires_approval=True)  # 登録の時点ではエラーにならない
    with pytest.raises(UserError, match="DeferredToolRequests"):
        plain.run_sync("記録して", model=TestModel(call_tools=["save_learning_log"]))


def test_usage_counts_both_runs(log_dir):
    """続きの実行に usage を渡しているので、requests は承認の前後を合わせた数になる。"""
    first, result = _run("y")
    assert result.usage.requests > first.usage.requests


def test_approved_call_is_saved(log_dir):
    _, result = _run("y")
    assert isinstance(result.output, str)
    assert _saved(log_dir)


def test_denied_call_is_not_saved(log_dir):
    _, result = _run("n")
    assert isinstance(result.output, str)
    assert not log_dir.exists()
    returns = [p for m in result.all_messages() for p in m.parts if isinstance(p, ToolReturnPart)]
    assert any("断りました" in str(p.content) for p in returns)  # 断ったことがモデルに伝わる