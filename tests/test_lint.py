import json
from pathlib import Path

import pytest

from literature_graph_map.cli import main
from literature_graph_map.lint import plain_author_gaps, review_citation_gaps, summary_gaps
from literature_graph_map.models import (
    LineageStep,
    LineageTrack,
    Overview,
    ReviewSection,
    Summary,
    Topic,
)
from literature_graph_map.storage import MapError, write_files


def test_lint_reports_all_entries_without_an_overview(snapshot):
    gaps = review_citation_gaps(snapshot)
    assert [gap["paper_id"] for gap in gaps] == list(snapshot.works)
    assert gaps[0] == {
        "topic_id": "demo",
        "path": "topics/demo/topic.yaml",
        "paper_id": "P000001",
        "citation": "1 2001",
        "title": "検証用架空文献 1",
    }


def test_only_inline_paragraph_citations_count(snapshot):
    topic = snapshot.topics["demo"]
    topic.review = [
        ReviewSection(
            heading="見出しだけの引用 [@P000003]",
            paragraphs=["比較 [@P000001][@P000002]。", "繰り返し [@P000001]。"],
        )
    ]
    topic.lineage = [
        LineageTrack(
            title="系譜",
            steps=[LineageStep(paper_id="P000003", title="節目", significance="説明")],
        )
    ]
    topic.reading_notes = ["補足 [@P000004]"]
    assert [gap["paper_id"] for gap in review_citation_gaps(snapshot)] == ["P000003", "P000004"]


def test_citations_are_checked_separately_for_each_nested_topic(snapshot):
    parent = snapshot.topics["demo"]
    parent.review = [
        ReviewSection(
            heading="概観", paragraphs=["".join(f"[@{e.paper_id}]" for e in parent.entries)]
        )
    ]
    child = parent.model_copy(deep=True)
    child.topic_id = "child"
    child.navigation.parent = "demo"
    child.review = []
    child.public = False
    snapshot.topics["child"] = child
    snapshot.paths["child"] = Path("topics/demo/nested")
    gaps = review_citation_gaps(snapshot)
    assert len(gaps) == 4
    assert all(gap["path"] == "topics/demo/nested/topic.yaml" for gap in gaps)
    assert review_citation_gaps(snapshot, "demo") == []


def test_empty_category_has_no_citation_gaps(snapshot):
    snapshot.topics["category"] = Topic(topic_id="category", title="分類", question="入口")
    snapshot.paths["category"] = Path("topics/category")
    snapshot.topics["demo"].navigation.parent = "category"
    assert review_citation_gaps(snapshot, "category") == []


@pytest.mark.parametrize("complete", [False, True])
def test_cli_json_status_and_read_only_operation(tmp_path, snapshot, capsys, complete):
    if complete:
        snapshot.topics["demo"].review = [
            ReviewSection(
                heading="概観",
                paragraphs=["".join(f"[@{paper_id}]" for paper_id in snapshot.works)],
            )
        ]
    repo = tmp_path / "repo"
    write_files(repo, snapshot.source_files(repo))
    before = {path: path.read_bytes() for path in repo.rglob("*") if path.is_file()}
    private = tmp_path / "private"
    status = main(["--repo", str(repo), "--private-dir", str(private), "lint", "demo", "--json"])
    output = json.loads(capsys.readouterr().out)
    assert status == (0 if complete else 1)
    assert output["topics_checked"] == 1
    assert output["missing_count"] == (0 if complete else 4)
    assert len(output["missing_citations"]) == output["missing_count"]
    assert output["missing_summaries"] == []
    assert before == {path: path.read_bytes() for path in repo.rglob("*") if path.is_file()}
    assert not private.exists()
    assert not (repo / "_site").exists()


def test_cli_text_and_unknown_topic(tmp_path, snapshot, capsys):
    write_files(tmp_path, snapshot.source_files(tmp_path))
    args = ["--repo", str(tmp_path), "lint"]
    assert main(args) == 1
    output = capsys.readouterr()
    assert "topics/demo/topic.yaml: review: 未引用 P000001 / 1 2001" in output.out
    assert "1テーマ / 未引用4件" in output.out
    assert main(args + ["unknown"]) == 1
    assert "unknown topic: unknown" in capsys.readouterr().err


def test_missing_summary_reports_each_item(snapshot):
    assert summary_gaps(snapshot) == []
    snapshot.works["P000001"].summary = None
    gaps = summary_gaps(snapshot)
    assert [gap["field"] for gap in gaps] == ["question", "method", "contribution"]
    assert gaps[0] == {
        "topic_id": "demo",
        "path": "data/works.jsonl",
        "paper_id": "P000001",
        "citation": "1 2001",
        "title": "検証用架空文献 1",
        "field": "question",
        "reason": "missing",
    }
    assert all(gap["reason"] == "missing" for gap in gaps)


@pytest.mark.parametrize(
    "text",
    [
        "準備中",
        "準備中です。",
        "要点は準備中です。",
        "未記入",
        "未確認。",
        "未作成",
        " TODO. ",
        "tBd",
    ],
)
def test_placeholder_item_is_reported_without_flagging_real_prose(snapshot, text):
    summary = snapshot.works["P000001"].summary
    summary.question = "準備中の観測装置が対象とする現象を調べる。"
    summary.method = text
    summary.contribution = "原論文は未確認とする課題の所在を整理した。"
    gaps = summary_gaps(snapshot)
    assert len(gaps) == 1
    assert gaps[0]["field"] == "method"
    assert gaps[0]["reason"] == "placeholder"


def test_summary_gaps_are_scoped_to_each_topic_including_private_children(snapshot):
    parent = snapshot.topics["demo"]
    child = parent.model_copy(deep=True)
    child.topic_id = "child"
    child.navigation.parent = "demo"
    child.public = False
    child.entries[0].summary = Summary(question="準備中", method="準備中", contribution="準備中")
    snapshot.topics["child"] = child
    snapshot.paths["child"] = Path("topics/demo/nested")
    snapshot.topics["category"] = Topic(topic_id="category", title="分類", question="入口")
    snapshot.paths["category"] = Path("topics/category")
    gaps = summary_gaps(snapshot)
    assert len(gaps) == 3
    assert all(gap["path"] == "topics/demo/nested/topic.yaml" for gap in gaps)
    assert summary_gaps(snapshot, "child") == gaps
    assert summary_gaps(snapshot, "demo") == []
    assert summary_gaps(snapshot, "category") == []
    with pytest.raises(MapError, match="unknown topic: unknown"):
        summary_gaps(snapshot, "unknown")


@pytest.mark.parametrize("cited", [False, True])
def test_cli_reports_summary_gaps_even_when_every_paper_is_cited(tmp_path, snapshot, capsys, cited):
    topic = snapshot.topics["demo"]
    if cited:
        topic.review = [
            ReviewSection(
                heading="概観",
                paragraphs=["".join(f"[@{paper_id}]" for paper_id in snapshot.works)],
            )
        ]
    snapshot.works["P000001"].summary = None
    topic.entries[1].summary = snapshot.works["P000002"].summary.model_copy(
        update={"method": "TODO"}
    )
    repo = tmp_path / "repo"
    private = tmp_path / "private"
    write_files(repo, snapshot.source_files(repo))
    before = {path: path.read_bytes() for path in repo.rglob("*") if path.is_file()}
    args = ["--repo", str(repo), "--private-dir", str(private), "lint", "demo"]
    assert main(args + ["--json"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["missing_count"] == (4 if cited else 8)
    assert len(output["missing_citations"]) == (0 if cited else 4)
    assert len(output["missing_summaries"]) == 4
    assert output["missing_summaries"][-1]["reason"] == "placeholder"
    assert main(args) == 1
    output = capsys.readouterr().out
    assert "data/works.jsonl: summary.question: 要点不足 P000001 / 問い / 1 2001" in output
    assert "topics/demo/topic.yaml: summary.method: 要点不足 P000002 / 方法 / 2 2002" in output
    assert "要点検査: 1テーマ / 不足4項目" in output
    assert before == {path: path.read_bytes() for path in repo.rglob("*") if path.is_file()}
    assert not private.exists()
    assert not (repo / "_site").exists()


def test_cli_rejects_blank_summary_items_without_writing(tmp_path, snapshot, capsys):
    snapshot.works["P000001"].summary.method = "   "
    write_files(tmp_path, snapshot.source_files(tmp_path))
    before = (tmp_path / "data/works.jsonl").read_bytes()
    assert main(["--repo", str(tmp_path), "lint", "--json"]) == 1
    output = capsys.readouterr()
    assert "summary.method" in output.err
    assert not output.out
    assert (tmp_path / "data/works.jsonl").read_bytes() == before


@pytest.mark.parametrize(
    "text",
    [
        "Stubbs et al. (2014) では放出電流を変えた。",
        "Pacaudら（2025）は粒子電荷を測った。",
        "Furman・Pivi（2002）の確率モデル。",
        "Örgerら（2017）は最大高度を比較した。",
        "Xuほか (2026a) の統計。",
    ],
)
def test_plain_author_names_are_reported_for_topics_and_overview(snapshot, text):
    topic = snapshot.topics["demo"]
    topic.review = [ReviewSection(heading="概観", paragraphs=[text + " [@P000001]"])]
    snapshot.overview = Overview(review=[{"heading": "つながり", "paragraphs": [text]}])
    gaps = plain_author_gaps(snapshot)
    assert [gap["path"] for gap in gaps] == ["topics/demo/topic.yaml", "overview.yaml"]
    assert gaps[0]["heading"] == "概観" and text.startswith(gaps[0]["text"])
    assert plain_author_gaps(snapshot, "demo") == gaps[:1]


@pytest.mark.parametrize(
    "text",
    [
        "[@P000001]では放出電流を変えた（2014年の計算）。",
        "LDEX (2014) の観測と Apollo 17 試料。",
        "ARTEMIS（2026）の統計は[@P000001]にある。",
        "Lunar Prospectorの1998年観測。",
    ],
)
def test_linked_citations_and_instrument_names_are_not_flagged(snapshot, text):
    snapshot.topics["demo"].review = [ReviewSection(heading="概観", paragraphs=[text])]
    assert plain_author_gaps(snapshot) == []


def test_cli_reports_plain_author_names(tmp_path, snapshot, capsys):
    topic = snapshot.topics["demo"]
    topic.review = [
        ReviewSection(
            heading="概観",
            paragraphs=[
                "Example et al. (2001) を含む " + "".join(f"[@{p}]" for p in snapshot.works)
            ],
        )
    ]
    write_files(tmp_path, snapshot.source_files(tmp_path))
    args = ["--repo", str(tmp_path), "lint", "demo"]
    assert main(args + ["--json"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["missing_count"] == 1 and output["missing_citations"] == []
    assert output["plain_author_names"][0]["text"] == "Example et al. (2001)"
    assert main(args) == 1
    text = capsys.readouterr().out
    assert "平文の著者名 Example et al. (2001) / 概観" in text
    assert "平文の著者名1件" in text
