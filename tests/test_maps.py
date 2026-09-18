from pathlib import Path

import pytest
import yaml
from conftest import DAY, make_entry, make_work
from pydantic import ValidationError

from literature_graph_map.cli import main
from literature_graph_map.models import (
    ImportPacket,
    Location,
    Topic,
    Version,
    VersionLink,
    Work,
    public_url,
)
from literature_graph_map.operations import commit, export_snapshot, import_packet
from literature_graph_map.render import (
    access_cell,
    check_rendered,
    graph_batches,
    preprint_cell,
    render,
    summary_cell,
    topic_page,
)
from literature_graph_map.storage import MapError, load, yaml_text


def test_offline_survey_end_to_end(tmp_path):
    repo, private = tmp_path / "repo", tmp_path / "private"
    common = ["--repo", str(repo), "--private-dir", str(private)]
    assert main(common + ["survey", "月面ダストの帯電", "--id", "dust", "--offline"]) == 0
    assert main(common + ["check"]) == 0
    page = (repo / "topics/dust/README.md").read_text(encoding="utf-8")
    assert "先行研究比較表" in page and "論文間の関係図" in page
    assert list(repo.rglob("README.md")) == [repo / "README.md", repo / "topics/dust/README.md"]
    assert (private / "dust/RESEARCH_REQUEST.md").exists()
    assert not (repo / "responses").exists()


def test_deterministic_render_and_all_tables(tmp_path, snapshot):
    commit(tmp_path, snapshot)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    render(tmp_path, load(tmp_path))
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    page = (tmp_path / "topics/demo/README.md").read_text(encoding="utf-8")
    assert (
        "| ID | タイトル | 著者 | 年 | 掲載誌／出版社 | OA・無料公開 | Preprint | 3項目要点 |"
        in page
    )
    assert "R000001" in page and "R000002" in page and "R000003 検証・仮" in page
    assert "nP000001 -->" in page and "nP000002 -.-" in page
    assert "nP000004[" in page
    assert check_rendered(tmp_path, snapshot) == []


def test_manual_prose_preserved_and_generated_edit_is_replaced(tmp_path, snapshot):
    commit(tmp_path, snapshot)
    path = tmp_path / "topics/demo/README.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n手動で追記した比較上の注意。\n", encoding="utf-8"
    )
    snapshot.topics["demo"].survey.changes = "書誌訂正"
    commit(tmp_path, snapshot)
    assert "手動で追記した" in path.read_text(encoding="utf-8")
    path.write_text(
        path.read_text(encoding="utf-8").replace("検証用架空文献 1", "手動編集した題名"),
        encoding="utf-8",
    )
    assert check_rendered(tmp_path, snapshot)
    snapshot.works["P000001"].title = "正本も更新"
    commit(tmp_path, snapshot)
    page = path.read_text(encoding="utf-8")
    assert "正本も更新" in page and "手動編集した題名" not in page
    assert "手動で追記した" in page and "sha256:" not in page
    assert check_rendered(tmp_path, load(tmp_path)) == []


def test_missing_marker_is_a_conflict(tmp_path, snapshot):
    commit(tmp_path, snapshot)
    path = tmp_path / "topics/demo/README.md"
    text = path.read_text(encoding="utf-8").replace("<!-- END GENERATED: paper-tables -->", "")
    path.write_text(text, encoding="utf-8")
    with pytest.raises(MapError, match="markers"):
        render(tmp_path, snapshot)


def test_summary_without_inspection_does_not_claim_review(snapshot):
    data = snapshot.topics["demo"].model_dump()
    data["entries"][0].pop("inspection")
    data["entries"][0].pop("evidence_by_item")
    topic = Topic.model_validate(data)
    text = summary_cell(topic.entries[0], snapshot.works["P000001"])
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
    assert page.count("| ID | タイトル |") == 3


def test_escape_external_text(snapshot):
    snapshot.works["P000001"].title = 'A | <script>alert("x")</script> [link]\nnext'
    snapshot.topics["demo"].entries[0].role = 'x"] --> injected["x'
    page = topic_page(snapshot.topics["demo"], snapshot)
    assert "<script>" not in page and "A |" not in page
    assert "&#124;" in page and "#34;" in page
    assert 'injected["x' not in page


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


def test_access_displays_available_links_with_api_attribution(snapshot):
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
    assert "出版版OA" in access_cell(work) and "API情報" in access_cell(work)
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
    for topic in loaded.topics.values():
        assert topic.entries[0].inspection.version_id == "V000001"
        assert topic.entries[0].inspection.recheck
        assert topic.relations[0].state == "recheck"
        assert "R000001 拡張・見直し予定" in (
            tmp_path / "repo" / loaded.paths[topic.topic_id] / "README.md"
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
    assert "../../README.md" in (tmp_path / "topics/parent/deep/renamed/README.md").read_text(
        encoding="utf-8"
    )
    assert "deep/renamed/README.md" in (tmp_path / "topics/parent/README.md").read_text(
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
    assert export_snapshot(repo, snapshot, out) == 6
    assert not (out / "topics/private").exists()
    assert not (out / "secret.pdf").exists()
    assert "P000999" not in (out / "data/works.jsonl").read_text(encoding="utf-8")
    assert "R000003" in (out / "topics/demo/topic.yaml").read_text(encoding="utf-8")
    assert check_rendered(out, load(out)) == []
    with pytest.raises(MapError, match="already exists"):
        export_snapshot(repo, snapshot, out)


def test_export_detects_leak_in_manual_prose_before_writing(tmp_path, snapshot):
    repo, out = tmp_path / "repo", tmp_path / "public"
    commit(repo, snapshot)
    (repo / "LICENSE").write_text("Fixture license.", encoding="utf-8")
    page = repo / "topics/demo/README.md"
    page.write_text(
        page.read_text(encoding="utf-8") + "\nC:\\Users\\private\\file.pdf\n", encoding="utf-8"
    )
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
