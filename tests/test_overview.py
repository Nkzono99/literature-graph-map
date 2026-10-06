from pathlib import Path

import pytest
from pydantic import ValidationError

from literature_graph_map.cli import main
from literature_graph_map.models import Overview, Topic
from literature_graph_map.operations import commit, export_snapshot
from literature_graph_map.render import render
from literature_graph_map.storage import MapError, load


@pytest.fixture
def overview_snapshot(snapshot):
    snapshot.overview = Overview(
        review=[
            {
                "heading": "検証用のテーマのつながり",
                "paragraphs": ['<script>alert("x")</script> 比較する（[@topic:demo]）。'],
            }
        ]
    )
    return snapshot


def test_overview_links_follow_topic_title_and_nested_path(tmp_path, overview_snapshot):
    snapshot = overview_snapshot
    snapshot.topics["demo"].title = "A & B <実験>"
    commit(tmp_path, snapshot)
    loaded = load(tmp_path)
    assert loaded.overview == snapshot.overview
    render(tmp_path, loaded)
    page = (tmp_path / "_site/index.html").read_text(encoding="utf-8")
    review = page[
        page.index('<section id="review"') : page.index('<section aria-labelledby="themes"')
    ]
    assert '<a href="topics/demo/index.html">A &amp; B &lt;実験&gt;</a>' in review
    assert "[@topic:" not in review
    assert "<script>" not in review and "&lt;script&gt;" in review
    loaded.topics["demo"].title = "更新したテーマ名"
    loaded.paths["demo"] = Path("topics/parent/moved")
    (tmp_path / "topics/demo/topic.yaml").unlink()
    commit(tmp_path, loaded)
    render(tmp_path, load(tmp_path))
    page = (tmp_path / "_site/index.html").read_text(encoding="utf-8")
    assert '<a href="topics/parent/moved/index.html">更新したテーマ名</a>' in page
    assert (tmp_path / "_site/topics/parent/moved/index.html").exists()
    assert not (tmp_path / "_site/topics/demo/index.html").exists()


@pytest.mark.parametrize("target", ["unknown", "private"])
def test_overview_rejects_unknown_or_private_topic(tmp_path, snapshot, target):
    snapshot.topics["private"] = Topic(
        topic_id="private", title="非公開", question="架空の検証用テーマ", public=False
    )
    snapshot.paths["private"] = Path("topics/private")
    snapshot.overview = Overview(
        review=[{"heading": "検証", "paragraphs": [f"引用する（[@topic:{target}]）。"]}]
    )
    with pytest.raises(MapError, match=f"citation requires a public topic: {target}"):
        render(tmp_path, snapshot)
    assert not (tmp_path / "_site").exists()


@pytest.mark.parametrize("overview", [None, Overview()])
def test_optional_overview_does_not_add_an_empty_section(tmp_path, snapshot, overview):
    snapshot.overview = overview
    commit(tmp_path, snapshot)
    render(tmp_path, load(tmp_path))
    page = (tmp_path / "_site/index.html").read_text(encoding="utf-8")
    assert 'id="review"' not in page and "テーマの概観へ" not in page
    assert "収録テーマ" in page


def test_export_preserves_overview_source_and_links(tmp_path, overview_snapshot):
    repo, destination = tmp_path / "repo", tmp_path / "export"
    commit(repo, overview_snapshot)
    source = (repo / "overview.yaml").read_bytes()
    export_snapshot(repo, load(repo), destination)
    assert load(destination).overview == overview_snapshot.overview
    assert (destination / "overview.yaml").read_bytes() == source
    assert (repo / "overview.yaml").read_bytes() == source
    page = (destination / "_site/index.html").read_text(encoding="utf-8")
    assert "検証用のテーマのつながり" in page
    assert 'href="topics/demo/index.html"' in page


def test_public_check_scans_overview_yaml_comments(tmp_path, overview_snapshot):
    repo, private = tmp_path / "repo", tmp_path / "private"
    commit(repo, overview_snapshot)
    path = repo / "overview.yaml"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n# C:\\Users\\private\\note\n", encoding="utf-8"
    )
    assert main(["--repo", str(repo), "--private-dir", str(private), "check", "--public"]) == 1


def test_load_reports_unknown_overview_fields(tmp_path, snapshot):
    commit(tmp_path, snapshot)
    (tmp_path / "overview.yaml").write_text("review: []\nunknown: unpublished\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="Extra inputs"):
        load(tmp_path)
