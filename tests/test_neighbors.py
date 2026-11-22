"""第5回 宿題（実装）: 前後ページを付ける検索のテスト。検索（埋め込みAPI）は差し替え、APIは呼ばない。"""

import json

import pytest

from app import config, retrieval, tools


def _page(doc: str, page: int) -> dict:
    return {"page_id": f"{doc}-p{page:03d}", "document_id": doc, "lecture": int(doc[3:5]),
            "document_title": doc, "section": "章", "title": f"{doc} {page}", "page": page,
            "content": f"{doc} の {page} ページ"}


@pytest.fixture
def two_documents(tmp_path, monkeypatch):
    """資料Aは5ページ、資料Bは3ページ。どちらも検索対象にする。"""
    source = tmp_path / "lectures.json"
    pages = {"lec01-main": 5, "lec02-main": 3}
    source.write_text(json.dumps([
        {"id": doc, "title": doc, "content": [{"section": "章", "content": [
            {"id": f"{doc}-p{n:03d}", "title": f"{doc} {n}", "page": n, "content": f"{doc} の {n} ページ"}
            for n in range(1, count + 1)]}]}
        for doc, count in pages.items()
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(retrieval, "RAG_SOURCE", source)
    monkeypatch.setattr(retrieval, "RAG_DOCUMENT_IDS", tuple(pages))


def _hits(monkeypatch, *pages):
    hits = [{**_page(doc, n), "distance": 0.1 * rank} for rank, (doc, n) in enumerate(pages, 1)]
    monkeypatch.setattr(retrieval, "search", lambda query: hits)


def _ids(results):
    return [r["page_id"] for r in results]


def test_adds_previous_and_next_page_within_the_same_document(two_documents, monkeypatch):
    _hits(monkeypatch, ("lec01-main", 3), ("lec02-main", 1))
    results = retrieval.search_with_neighbors("質問", window=1)
    assert _ids(results) == ["lec01-main-p002", "lec01-main-p003", "lec01-main-p004",
                             "lec02-main-p001", "lec02-main-p002"]
    # 資料Bの1ページ目の「前」は資料Aの最後のページではない（資料をまたがない）
    assert "lec01-main-p005" not in _ids(results)
    neighbor = results[0]
    assert neighbor["match"] == "neighbor" and neighbor["neighbor_of"] == "lec01-main-p003"
    assert neighbor["offset"] == -1 and neighbor["distance"] is None
    assert neighbor["content"] == "lec01-main の 2 ページ"
    assert results[1]["match"] == "search" and results[1]["rank"] == 1


def test_same_page_is_returned_once_and_hits_keep_their_rank(two_documents, monkeypatch):
    _hits(monkeypatch, ("lec01-main", 2), ("lec01-main", 3))
    results = retrieval.search_with_neighbors("質問", window=1)
    assert _ids(results) == ["lec01-main-p001", "lec01-main-p002", "lec01-main-p003", "lec01-main-p004"]
    assert len(set(_ids(results))) == len(results)
    second = results[2]
    assert second["match"] == "search" and second["rank"] == 2 and second["distance"] == pytest.approx(0.2)


def test_first_and_last_pages_have_only_one_neighbor(two_documents, monkeypatch):
    _hits(monkeypatch, ("lec01-main", 5), ("lec02-main", 1))
    assert _ids(retrieval.search_with_neighbors("質問", window=1)) == [
        "lec01-main-p004", "lec01-main-p005", "lec02-main-p001", "lec02-main-p002"]


def test_window_zero_returns_the_search_result_unchanged(two_documents, monkeypatch):
    _hits(monkeypatch, ("lec01-main", 3))
    assert retrieval.search_with_neighbors("質問", window=0) == retrieval.search("質問")


def test_real_material_lora_page_gets_pages_51_and_53(monkeypatch):
    """同梱の lectures.json で、第2回 p.52 の前後が p.51 と p.53 になることを確かめる。"""
    p52 = next(p for p in retrieval.load_pages() if p["page_id"] == "lec02-main-p052")
    monkeypatch.setattr(retrieval, "search", lambda query: [{**p52, "distance": 0.2}])
    results = retrieval.search_with_neighbors("LoRA QLoRA 違い", window=1)
    assert [r["page"] for r in results] == [51, 52, 53]
    assert {r["document_id"] for r in results} == {"lec02-main"}


def test_tool_switches_by_setting(two_documents, monkeypatch):
    _hits(monkeypatch, ("lec01-main", 3))
    monkeypatch.setattr(config, "RAG_NEIGHBOR_WINDOW", 0)
    assert len(json.loads(tools.search_materials("質問"))["results"]) == 1
    monkeypatch.setattr(config, "RAG_NEIGHBOR_WINDOW", 1)
    assert len(json.loads(tools.search_materials("質問"))["results"]) == 3
