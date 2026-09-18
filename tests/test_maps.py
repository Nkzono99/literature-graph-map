from html import unescape
from pathlib import Path

import pytest
import yaml
from conftest import DAY, make_entry, make_work
from pydantic import ValidationError

from literature_graph_map.cli import main
from literature_graph_map.models import (
    ImportPacket,
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
    graph_batches,
    graph_source,
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
    assert "文献一覧" in page and "論文間の関係図" in page
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
    assert "候補：検証（仮）" in page
    assert "nP000001 -->" in unescape(page) and "nP000002 -.-" in page
    assert "nP000004[" in page


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


def test_scale_splits_without_losing_nodes_or_edges(snapshot):
    works = [make_work(i) for i in range(1, 82)]
    topic = snapshot.topics["demo"]
    topic.entries = [make_entry(w) for w in works]
    topic.relations = []
    from literature_graph_map.models import Relation

    for i in range(1, 81):
        entry = topic.entries[i]
        topic.relations.append(
            Relation(
                relation_id=f"R{i:06d}",
                source=works[i - 1].paper_id,
                target=works[i].paper_id,
                type="extends",
                basis="explicit",
                state="checked",
                aspect="検証",
                reason="架空の拡張。",
                evidence=entry.evidence_by_item.method,
                checked_by="ai",
                checked_at=DAY,
            )
        )
    snapshot.works = {w.paper_id: w for w in works}
    batches = graph_batches(topic)
    assert all(len(nodes) <= 20 and len(edges) <= 30 for _, nodes, edges in batches)
    assert {n for _, nodes, _ in batches for n in nodes} == set(snapshot.works)
    assert {r.relation_id for _, _, edges in batches for r in edges} == {
        r.relation_id for r in topic.relations
    }
    page = topic_page(topic, snapshot)
    assert page.count('class="paper"') == 81


def test_escape_external_text(snapshot):
    snapshot.works["P000001"].title = 'A | <script>alert("x")</script> [link]\nnext'
    snapshot.topics["demo"].entries[0].role = 'x"] --> injected["x'
    page = topic_page(snapshot.topics["demo"], snapshot)
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "#34;" in page
    assert 'injected["x' not in page


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


def test_import_remaps_inline_review_citations(tmp_path, snapshot):
    incoming = snapshot.works["P000001"].model_copy(update={"paper_id": "P999999"}, deep=True)
    packet = ImportPacket(
        works=[incoming],
        topic=Topic(
            topic_id="with-review",
            title="概観付きテーマ",
            question="研究のつながりを読む。",
            entries=[make_entry(incoming)],
            review=[ReviewSection(heading="基礎", paragraphs=["[@P999999]から始める。"])],
        ),
    )
    import_packet(tmp_path / "repo", snapshot, packet, tmp_path / "private")
    loaded = load(tmp_path / "repo")
    topic = loaded.topics["with-review"]
    assert topic.review[0].paragraphs == ["[@P000001]から始める。"]
    assert topic.entries[0].paper_id == "P000001"
    assert '<a href="#P000001">1 2001</a>から始める。' in topic_page(topic, loaded)


def test_graph_uses_explanations_and_escapes_labels(snapshot):
    topic = snapshot.topics["demo"]
    topic.relations[0].graph_label = '測定した分布を使用 | "条件" <script>'
    labels = citation_labels(snapshot.works)
    source = graph_source(list(snapshot.works), topic.relations, topic, labels)
    assert 'nP000001["1 2001<br/>検証用役割"]:::paper_P000001' in source
    assert "測定した分布を使用 #124; #34;条件#34; #60;script#62;" in source
    assert "R000001" not in source and "R000002" not in source
    assert "架空条件：比較" in source and "候補：検証（仮）" in source


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
        assert "架空モデル：拡張（見直し予定）" in (
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
