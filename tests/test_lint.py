import json
from pathlib import Path

import pytest

from literature_graph_map.cli import main
from literature_graph_map.lint import review_citation_gaps
from literature_graph_map.models import LineageStep, LineageTrack, ReviewSection, Topic
from literature_graph_map.storage import write_files


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
