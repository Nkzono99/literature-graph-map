from html.parser import HTMLParser
from pathlib import Path

import pytest
import yaml
from conftest import DAY, make_entry, make_work
from pydantic import ValidationError

from literature_graph_map.cli import main
from literature_graph_map.models import (
    ImportPacket,
    LineageStep,
    LineageTrack,
    Location,
    ReviewSection,
    Topic,
    Version,
    VersionLink,
    Work,
    public_url,
)
from literature_graph_map.operations import commit, export_snapshot, import_packet
from literature_graph_map.render import (
    access_cell,
    citation_labels,
    preprint_cell,
    render,
    summary_block,
    topic_page,
)
from literature_graph_map.storage import MapError, load, yaml_text


def test_offline_survey_end_to_end(tmp_path):
    repo, private = tmp_path / "repo", tmp_path / "private"
    common = ["--repo", str(repo), "--private-dir", str(private)]
    assert main(common + ["survey", "月面ダストの帯電", "--id", "dust", "--offline"]) == 0
    assert main(common + ["check"]) == 0
    assert main(common + ["render"]) == 0
    page = (repo / "_site/topics/dust/index.html").read_text(encoding="utf-8")
    assert "文献一覧" in page
    assert not list(repo.rglob("README.md"))
    assert 'id="review"' not in page
    assert (private / "dust/RESEARCH_REQUEST.md").exists()
    assert not (repo / "responses").exists()


def test_deterministic_render_and_all_papers(tmp_path, snapshot):
    commit(tmp_path, snapshot)
    render(tmp_path, snapshot)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    render(tmp_path, load(tmp_path))
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    page = (tmp_path / "_site/topics/demo/index.html").read_text(encoding="utf-8")
    assert page.count('class="paper"') == len(snapshot.works)
    for label in ("問い", "方法", "判明点"):
        assert page.count(f"<strong>{label}</strong>") == len(snapshot.works)
    assert "Example 1" in page and "架空の検証用誌" in page
    assert "OA・無料公開：未確認" in page and "Preprint：未確認" in page
    assert "検証用の架空の節" in page and "本文確認（出版版）" in page


def test_render_replaces_generated_html_and_removes_moved_pages(tmp_path, snapshot):
    commit(tmp_path, snapshot)
    (tmp_path / "README.md").write_text("リポジトリの操作案内", encoding="utf-8")
    render(tmp_path, snapshot)
    old = tmp_path / "_site/topics/demo/index.html"
    old.write_text("古い生成結果", encoding="utf-8")
    snapshot.paths["demo"] = Path("topics/renamed")
    snapshot.works["P000001"].title = "正本から更新"
    render(tmp_path, snapshot)
    assert not old.exists()
    assert "正本から更新" in (tmp_path / "_site/topics/renamed/index.html").read_text(
        encoding="utf-8"
    )
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "リポジトリの操作案内"


def test_site_omits_editorial_logs_and_private_topics(tmp_path, snapshot):
    topic = snapshot.topics["demo"]
    topic.survey.provider_names = ["INTERNAL_PROVIDER"]
    topic.survey.queries = ["INTERNAL_QUERY"]
    topic.survey.coverage_note = "INTERNAL_COVERAGE"
    topic.survey.changes = "INTERNAL_CHANGE"
    topic.survey.limitations = ["INTERNAL_BACKLOG"]
    snapshot.topics["private"] = Topic(
        topic_id="private", title="PRIVATE_TOPIC", question="private", public=False
    )
    snapshot.paths["private"] = Path("topics/private")
    render(tmp_path, snapshot)
    pages = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "_site").rglob("*.html"))
    assert "INTERNAL_" not in pages and "PRIVATE_TOPIC" not in pages
    assert "調査範囲と更新" not in pages and "AI確認" not in pages
    assert not list((tmp_path / "_site").rglob("*.yaml"))
    assert not list((tmp_path / "_site").rglob("*.jsonl"))


def test_summary_without_inspection_does_not_claim_review(snapshot):
    data = snapshot.topics["demo"].model_dump()
    data["entries"][0].pop("inspection")
    data["entries"][0].pop("evidence_by_item")
    topic = Topic.model_validate(data)
    text = summary_block(topic.entries[0], snapshot.works["P000001"])
    assert "架空の問いを比較する。" in text
    assert "本文確認" not in text and "人間" not in text and "None" not in text


def test_large_topic_keeps_all_papers(snapshot):
    works = [make_work(i) for i in range(1, 82)]
    topic = snapshot.topics["demo"]
    topic.entries = [make_entry(w) for w in works]
    topic.relations = []
    snapshot.works = {w.paper_id: w for w in works}
    page = topic_page(topic, snapshot)
    assert page.count('class="paper"') == 81
    assert all(f'id="{work.paper_id}"' in page for work in works)


def test_escape_external_text(snapshot):
    snapshot.works["P000001"].title = 'A | <script>alert("x")</script> [link]\nnext'
    snapshot.topics["demo"].entries[0].role = '<script>alert("role")</script>'
    page = topic_page(snapshot.topics["demo"], snapshot)
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "&lt;script&gt;alert(&#34;role&#34;)&lt;/script&gt;" in page


def test_citations_disambiguate_author_year_and_preserve_compound_names(snapshot):
    first, second, compound, unknown = snapshot.works.values()
    first.authors = ["Jin Nakazono"]
    second.authors = ["Nakazono, Jin"]
    first.versions[0].year = second.versions[0].year = 2025
    compound.authors = ["José H. Pagán Muñoz"]
    compound.citation_author = "Pagán Muñoz"
    unknown.authors = []
    unknown.versions[0].year = None
    labels = citation_labels(snapshot.works)
    assert labels[first.paper_id] == "Nakazono 2025-1"
    assert labels[second.paper_id] == "Nakazono 2025-2"
    assert labels[compound.paper_id] == "Pagán Muñoz 2003"
    assert labels[unknown.paper_id] == "著者未確認 年未確認"
    assert citation_labels(dict(reversed(list(snapshot.works.items())))) == labels
    page = topic_page(snapshot.topics["demo"], snapshot)
    assert ">Nakazono 2025-1</a>" in page and ">Nakazono 2025-2</a>" in page
    assert ">P000001</a>" not in page and ">R000001</span>" not in page


def test_review_renders_inline_citations_from_current_bibliography(tmp_path, snapshot):
    topic = snapshot.topics["demo"]
    topic.review = [
        ReviewSection(
            heading="研究のつながり",
            paragraphs=['<script>alert("x")</script> [@P000001]から[@P000002]へ。'],
        )
    ]
    snapshot.works["P000001"].citation_author = "A & B"
    commit(tmp_path, snapshot)
    loaded = load(tmp_path)
    render(tmp_path, loaded)
    page = (tmp_path / "_site/topics/demo/index.html").read_text(encoding="utf-8")
    review = page[page.index('<section id="review"') : page.index('<section id="papers"')]
    assert '<a href="#P000001">A &amp; B 2001</a>から<a href="#P000002">2 2002</a>' in review
    assert "<script>" not in review and "&lt;script&gt;" in review
    assert "[@P" not in review
    assert loaded.topics["demo"].review == topic.review
    loaded.works["P000001"].versions[0].year = 2026
    assert '<a href="#P000001">A &amp; B 2026</a>' in topic_page(loaded.topics["demo"], loaded)


def test_review_citations_require_a_paper_in_the_topic(snapshot):
    data = snapshot.topics["demo"].model_dump()
    data["review"] = [{"heading": "概観", "paragraphs": ["未掲載の[@P999999]。"]}]
    with pytest.raises(ValidationError, match="review citations"):
        Topic.model_validate(data)


def test_import_remaps_review_and_lineage_references(tmp_path, snapshot):
    incoming = snapshot.works["P000001"].model_copy(update={"paper_id": "P999999"}, deep=True)
    packet = ImportPacket(
        works=[incoming],
        topic=Topic(
            topic_id="with-review",
            title="概観付きテーマ",
            question="研究のつながりを読む。",
            entries=[make_entry(incoming)],
            review=[ReviewSection(heading="基礎", paragraphs=["[@P999999]から始める。"])],
            lineage=[
                LineageTrack(
                    title="基礎",
                    steps=[
                        LineageStep(paper_id="P999999", title="節目", significance="変化の説明")
                    ],
                )
            ],
        ),
    )
    import_packet(tmp_path / "repo", snapshot, packet, tmp_path / "private")
    loaded = load(tmp_path / "repo")
    topic = loaded.topics["with-review"]
    assert topic.review[0].paragraphs == ["[@P000001]から始める。"]
    assert topic.entries[0].paper_id == "P000001"
    assert topic.lineage[0].steps[0].paper_id == "P000001"
    assert '<a href="#P000001">1 2001</a>から始める。' in topic_page(topic, loaded)


def test_lineage_links_to_bibliography_and_uses_current_citations(tmp_path, snapshot):
    topic = snapshot.topics["demo"]
    assert 'id="lineage"' not in topic_page(topic, snapshot)
    topic.lineage = [
        LineageTrack(
            title="理論から観測へ",
            steps=[
                LineageStep(paper_id="P000001", title="<基準モデル>", significance="出発点。"),
                LineageStep(
                    paper_id="P000002",
                    title="観測で検討",
                    significance="条件を絞る。",
                    connection="予測を測定と比較",
                ),
            ],
        )
    ]
    work = snapshot.works["P000002"]
    work.citation_author = "Revised"
    work.version().year = 2026
    work.version().kind = "unknown"
    work.version().status = "preprint"
    commit(tmp_path, snapshot)
    restored = load(tmp_path)
    assert restored.topics["demo"].lineage == topic.lineage
    page = topic_page(restored.topics["demo"], restored)
    lineage = page.split('<section id="lineage"')[1].split('<section id="papers"')[0]
    assert 'href="#P000002"' in lineage
    assert "Revised 2026" in lineage
    assert "プレプリント・未査読" in lineage
    assert "予測を測定と比較" in lineage
    assert "&lt;基準モデル&gt;" in lineage and "<基準モデル>" not in lineage
    assert '<a class="milestone-tag" href="#lineage-P000002">' in page
    assert '<a class="milestone-tag" href="#lineage-P000003">' not in page


@pytest.mark.parametrize(
    "ids, connections, message",
    [
        (["P999999"], [""], "lineage steps"),
        (["P000001", "P000001"], ["", "比較"], "lineage steps"),
        (["P000001", "P000002"], ["", ""], "label the connection"),
        (["P000001"], ["前段がない"], "label the connection"),
    ],
)
def test_lineage_rejects_broken_references_or_connections(snapshot, ids, connections, message):
    data = snapshot.topics["demo"].model_dump()
    data["lineage"] = [
        {
            "title": "経路",
            "steps": [
                {"paper_id": pid, "title": "節目", "significance": "内容", "connection": connection}
                for pid, connection in zip(ids, connections, strict=True)
            ],
        }
    ]
    with pytest.raises(ValidationError, match=message):
        Topic.model_validate(data)


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///C:/secret",
        "https://user:pass@example.org/a",
        "http://127.0.0.1",
        "http://localhost/a",
        "https://example.org\\evil",
    ],
)
def test_reject_nonpublic_urls(url):
    with pytest.raises(ValueError):
        public_url(url)


def test_access_displays_available_links(snapshot):
    work = snapshot.works["P000001"]
    work.versions[0].locations = [
        Location(
            url="https://example.org/free",
            host="example.org",
            access_status="free",
            license_id="cc-by",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            checked_at=DAY,
            source="test",
            verification_method="api",
        )
    ]
    assert "出版版OA" in access_cell(work) and "API情報" not in access_cell(work)
    work.versions[0].locations[0].verification_method = "public_record"
    assert "出版版OA" in access_cell(work)
    work.versions[0].locations[0].license_id = None
    assert "ライセンス未確認" in access_cell(work)
    work.versions[0].locations = []
    work.access_check = "not_found"
    work.preprint_check = "not_found"
    assert access_cell(work) == "無料版未検出" and preprint_cell(work) == "未検出"
    work.access_check = "failed"
    assert access_cell(work) == "未確認"


def test_multiple_versions_do_not_require_provenance(snapshot):
    data = snapshot.works["P000001"].model_dump()
    data["versions"].append(
        Version(version_id="Vpre", kind="submitted", repository_id="arxiv:1234.56789").model_dump()
    )
    work = Work.model_validate(data)
    assert len(work.versions) == 2 and work.version_links == []


def test_new_version_keeps_old_evidence_and_marks_every_topic(tmp_path, snapshot, packet):
    other = snapshot.topics["demo"].model_copy(deep=True)
    other.topic_id = "other"
    snapshot.topics["other"] = other
    snapshot.paths["other"] = Path("topics/other")
    commit(tmp_path / "repo", snapshot)
    packet = packet.model_copy(deep=True)
    work = packet.works[0]
    work.versions.append(Version(version_id="Vnew", kind="published", doi="10.5555/new"))
    work.version_links.append(
        VersionLink(source="V000001", target="Vnew", evidence_url=work.record_url, checked_at=DAY)
    )
    work.representative_version_id = "Vnew"
    import_packet(tmp_path / "repo", snapshot, packet, tmp_path / "private")
    loaded = load(tmp_path / "repo")
    render(tmp_path / "repo", loaded)
    for topic in loaded.topics.values():
        assert topic.entries[0].inspection.version_id == "V000001"
        assert topic.entries[0].inspection.recheck
        assert topic.relations[0].state == "recheck"
        assert "旧版に基づく記述" in (
            tmp_path / "repo" / "_site" / loaded.paths[topic.topic_id] / "index.html"
        ).read_text(encoding="utf-8")
        pending = ImportPacket.model_validate(
            yaml.safe_load(
                (tmp_path / "private" / topic.topic_id / "review-packet.yaml").read_text(
                    encoding="utf-8"
                )
            )
        )
        assert pending.topic.relations[0].state == "recheck"
    assert len(loaded.works) == 4


def test_import_preserves_locked_summary(tmp_path, snapshot, packet):
    snapshot.topics["demo"].entries[0].locked_fields = ["summary"]
    commit(tmp_path / "repo", snapshot)
    packet = packet.model_copy(deep=True)
    packet.topic.entries[0].summary.question = "上書きしようとした問い。"
    packet.topic.entries[0].locked_fields = []
    conflicts = import_packet(tmp_path / "repo", snapshot, packet, tmp_path / "private")
    assert conflicts
    entry = load(tmp_path / "repo").topics["demo"].entries[0]
    assert entry.summary.question == "架空の問いを比較する。"
    assert entry.locked_fields == ["summary"]


def test_navigation_links_follow_paths(tmp_path, snapshot):
    parent = Topic(topic_id="parent", title="親", question="親テーマ")
    snapshot.topics["parent"] = parent
    snapshot.paths["parent"] = Path("topics/parent")
    snapshot.topics["demo"].navigation.parent = "parent"
    snapshot.paths["demo"] = Path("topics/parent/deep/renamed")
    commit(tmp_path, snapshot)
    render(tmp_path, snapshot)
    assert "../../index.html" in (
        tmp_path / "_site/topics/parent/deep/renamed/index.html"
    ).read_text(encoding="utf-8")
    assert "deep/renamed/index.html" in (tmp_path / "_site/topics/parent/index.html").read_text(
        encoding="utf-8"
    )


def test_nested_themes_and_private_parent_remain_reachable(tmp_path, snapshot):
    for key, title, parent, public in (
        ("parent", "親テーマ", None, True),
        ("child", "子テーマ", "parent", True),
        ("grandchild", "孫テーマ", "child", True),
        ("private", "PRIVATE_PARENT", None, False),
        ("orphan", "公開の子", "private", True),
    ):
        snapshot.topics[key] = Topic(
            topic_id=key,
            title=title,
            question="検証用",
            public=public,
            navigation={"parent": parent},
        )
        snapshot.paths[key] = Path("topics") / key
    render(tmp_path, snapshot)
    index = (tmp_path / "_site/index.html").read_text(encoding="utf-8")
    # The index uses navigation ancestry even when filesystem paths are siblings.
    content = index[index.index('<section aria-labelledby="themes">') :]
    assert (
        content.index(">親テーマ</a>")
        < content.index(">子テーマ</a>")
        < content.index(">孫テーマ</a>")
    )
    assert content.count("<ul>") == 2
    assert "公開の子" in content and "PRIVATE_PARENT" not in index
    parent = (tmp_path / "_site/topics/parent/index.html").read_text(encoding="utf-8")
    assert 'href="../child/index.html"' in parent
    assert 'id="papers"' not in parent and 'href="#papers"' not in parent
    assert "<b>1</b> テーマ" in parent
    assert '<h2 id="themes">収録テーマ</h2><span>3件</span>' in index
    grandchild = (tmp_path / "_site/topics/grandchild/index.html").read_text(encoding="utf-8")
    breadcrumb = grandchild.split('<nav class="breadcrumb"')[1].split("</nav>")[0]
    assert breadcrumb.index('href="../parent/index.html"') < breadcrumb.index(
        'href="../child/index.html"'
    )
    orphan = (tmp_path / "_site/topics/orphan/index.html").read_text(encoding="utf-8")
    assert "PRIVATE_PARENT" not in orphan and "../private/" not in orphan


def test_sidebar_theme_destinations_are_consistent_across_pages(tmp_path, snapshot):
    parent = Topic(
        topic_id="parent",
        title="親テーマ",
        question="検証用",
        review=[ReviewSection(heading="概観", paragraphs=["検証用の本文。"])],
    )
    snapshot.topics["parent"] = parent
    snapshot.paths["parent"] = Path("topics/parent")
    snapshot.topics["demo"].navigation.parent = "parent"
    snapshot.paths["demo"] = Path("topics/parent/child")
    render(tmp_path, snapshot)

    class Links(HTMLParser):
        def __init__(self, text):
            super().__init__()
            self.links = []
            self.feed(text)

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                self.links.append(dict(attrs))

    root = tmp_path / "_site"
    pages = {
        root / "index.html": set(),
        root / "topics/parent/index.html": {"#subtopics", "#review"},
        root / "topics/parent/child/index.html": {"#papers"},
    }
    for path, anchors in pages.items():
        page = path.read_text(encoding="utf-8")
        links = Links(page.split('<aside class="sidebar">')[1].split("</aside>")[0]).links
        destinations = {
            (path.parent / link["href"]).resolve()
            for link in links
            if not link["href"].startswith("#")
        }
        assert destinations == set(pages)
        assert {link["href"] for link in links if link["href"].startswith("#")} == anchors
        current = [link for link in links if link.get("aria-current") == "page"]
        if anchors:
            assert len(current) == 1
            assert (path.parent / current[0]["href"]).resolve() == path
        else:
            assert not current


def test_parent_with_papers_keeps_bibliography_and_excludes_private_children(snapshot):
    topic = snapshot.topics["demo"]
    for key, public in [("child", True), ("private", False)]:
        snapshot.topics[key] = Topic(
            topic_id=key,
            title=key,
            question="検証用",
            public=public,
            navigation={"parent": "demo"},
        )
        snapshot.paths[key] = Path("topics") / key
    page = topic_page(topic, snapshot)
    assert 'id="subtopics"' in page and 'id="papers"' in page
    assert "<b>4</b> 文献" in page and "../private/" not in page
    topic.entries = []
    topic.relations = []
    page = topic_page(topic, snapshot)
    assert "<b>1</b> テーマ" in page and 'id="papers"' not in page


def test_export_only_public_allowlisted_data(tmp_path, snapshot):
    repo = tmp_path / "repo"
    snapshot.topics["private"] = Topic(
        topic_id="private", title="非公開のテーマ", question="秘密の研究", public=False
    )
    snapshot.paths["private"] = Path("topics/private")
    snapshot.works["P000999"] = make_work(999)
    commit(repo, snapshot)
    (repo / "LICENSE").write_text("Fixture license for synthetic content.", encoding="utf-8")
    (repo / "secret.pdf").write_bytes(b"not for publication")
    out = tmp_path / "public"
    assert export_snapshot(repo, snapshot, out) > 0
    assert not (out / "topics/private").exists()
    assert not (out / "secret.pdf").exists()
    assert "P000999" not in (out / "data/works.jsonl").read_text(encoding="utf-8")
    assert "R000003" in (out / "topics/demo/topic.yaml").read_text(encoding="utf-8")
    assert (out / "_site/topics/demo/index.html").exists()
    with pytest.raises(MapError, match="already exists"):
        export_snapshot(repo, snapshot, out)


def test_export_detects_leak_before_writing(tmp_path, snapshot):
    repo, out = tmp_path / "repo", tmp_path / "public"
    commit(repo, snapshot)
    snapshot.topics["demo"].reading_notes = ["file:///private/paper.pdf"]
    with pytest.raises(MapError, match="local path"):
        export_snapshot(repo, snapshot, out)
    assert not out.exists()


def test_unknown_fields_are_reported(packet):
    data = packet.model_dump()
    data["works"][0]["abstract"] = "非公開要旨"
    with pytest.raises(ValidationError, match="Extra inputs"):
        ImportPacket.model_validate(data)


def test_import_rejects_path_escape(tmp_path, packet):
    from literature_graph_map.storage import Snapshot

    with pytest.raises(MapError):
        import_packet(tmp_path / "repo", Snapshot(), packet, tmp_path / "private", "../escape")
    assert not (tmp_path / "escape").exists()


def test_import_cli_and_schemas(tmp_path, packet):
    path = tmp_path / "packet.yaml"
    path.write_text(yaml_text(packet), encoding="utf-8")
    common = ["--repo", str(tmp_path / "repo"), "--private-dir", str(tmp_path / "private")]
    assert main(common + ["import", str(path)]) == 0
    assert main(common + ["check", "--public"]) == 0
    assert main(["schema", "--output", str(tmp_path / "schemas")]) == 0
    assert len(list((tmp_path / "schemas").glob("*.schema.json"))) == 3
