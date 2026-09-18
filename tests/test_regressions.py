import json
from pathlib import Path

import httpx
import pytest
from conftest import DAY
from test_providers import record

from literature_graph_map.cli import parser
from literature_graph_map.models import ImportPacket, Version, VersionLink
from literature_graph_map.operations import (
    add_seeds,
    commit,
    discover,
    import_packet,
    research_handoff,
)
from literature_graph_map.providers import Crossref, Settings, seed_identifiers
from literature_graph_map.storage import MapError, Snapshot, load, read_yaml


def test_topic_path_alias_cannot_overwrite_another_topic(tmp_path, snapshot, packet):
    repo = tmp_path / "repo"
    commit(repo, snapshot)
    packet = packet.model_copy(deep=True)
    packet.topic.topic_id = "other"
    original = (repo / "topics/demo/topic.yaml").read_bytes()
    with pytest.raises(MapError, match="occupied"):
        import_packet(repo, snapshot, packet, tmp_path / "private", "topics/unused/../demo")
    assert (repo / "topics/demo/topic.yaml").read_bytes() == original


def test_existing_version_cannot_change_doi(tmp_path, snapshot, packet):
    packet = packet.model_copy(deep=True)
    packet.works[0].versions[0].doi = "10.5555/different"
    with pytest.raises(MapError, match="immutable"):
        import_packet(tmp_path / "repo", snapshot, packet, tmp_path / "private")
    assert not (tmp_path / "repo/data/works.jsonl").exists()


def test_relation_lock_protects_endpoints_and_qualifications(tmp_path, snapshot, packet):
    snapshot.topics["demo"].relations[0].locked_fields = ["type"]
    packet = packet.model_copy(deep=True)
    packet.topic.relations[0].source = "P000004"
    packet.topic.relations[0].limitation = "不適切な変更"
    conflicts = import_packet(tmp_path / "repo", snapshot, packet, tmp_path / "private")
    relation = load(tmp_path / "repo").topics["demo"].relations[0]
    assert relation.source == "P000001" and relation.limitation is None
    assert any("source" in c for c in conflicts)


def test_scope_changes_update_generated_prose(tmp_path, snapshot, packet):
    repo = tmp_path / "repo"
    commit(repo, snapshot)
    packet = packet.model_copy(deep=True)
    packet.topic.question = "更新後の問い。"
    packet.topic.scope.include = ["更新後の対象条件"]
    import_packet(repo, snapshot, packet, tmp_path / "private")
    page = (repo / "topics/demo/README.md").read_text(encoding="utf-8")
    assert "更新後の問い。" in page and "更新後の対象条件" in page
    assert "全論文・著者・関係・出典は架空" not in page


def test_work_version_lock_preserves_dependent_fields(tmp_path, snapshot, packet):
    snapshot.works["P000001"].locked_fields = ["versions"]
    packet = packet.model_copy(deep=True)
    incoming = packet.works[0]
    incoming.versions.append(Version(version_id="Vnew", kind="published", doi="10.5555/new"))
    incoming.version_links.append(
        VersionLink(
            source="V000001", target="Vnew", evidence_url=incoming.record_url, checked_at=DAY
        )
    )
    incoming.representative_version_id = "Vnew"
    conflicts = import_packet(tmp_path / "repo", snapshot, packet, tmp_path / "private")
    work = load(tmp_path / "repo").works["P000001"]
    assert conflicts and len(work.versions) == 1 and work.version_links == []
    assert work.representative_version_id == "V000001"


def test_import_does_not_depend_on_cached_response_contents(tmp_path, snapshot, packet):
    private = tmp_path / "private"
    (private / "responses").mkdir(parents=True)
    (private / "responses/record.json").write_text("incomplete cached response", encoding="utf-8")
    import_packet(tmp_path / "repo", snapshot, packet, private)
    assert (
        load(tmp_path / "repo").topics["demo"].entries[0].summary == packet.topic.entries[0].summary
    )


def test_bad_pdf_keeps_successful_seed_and_reports_failure(tmp_path, snapshot):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not a readable PDF")
    topic = snapshot.topics["demo"]
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"message": record()})
        )
    ) as client:
        issues = add_seeds(
            snapshot,
            topic,
            ["10.5555/test", str(bad)],
            Crossref(tmp_path / "private", Settings(), client),
            tmp_path / "private",
        )
    assert len(topic.entries) == 5
    assert any("PDF could not be read" in issue for issue in issues)


def test_metadata_only_update_preserves_research_provenance(tmp_path, snapshot):
    topic = snapshot.topics["demo"]
    topic.survey.provider_names = ["原著", "レビュー"]
    topic.survey.queries = ["original query"]
    topic.survey.coverage_note = "レビューと参考文献を確認した。"
    before = topic.survey.model_dump()
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        provider = Crossref(tmp_path, Settings(), client)
        assert discover(topic, provider, []) == []
    assert topic.survey.model_dump() == before


def test_public_import_keeps_provisional_relations_in_canonical_data(tmp_path, packet):
    repo, private = tmp_path / "repo", tmp_path / "private"
    import_packet(repo, Snapshot(), packet, private)
    assert "R000003" in (repo / "topics/demo/topic.yaml").read_text(encoding="utf-8")
    pending = ImportPacket.model_validate(read_yaml(private / "demo/review-packet.yaml"))
    assert pending.topic.relations[-1].state == "candidate"
    assert load(repo).topics["demo"].public


@pytest.mark.parametrize("state", [None, "checked", "recheck", "rejected"])
def test_partial_research_can_be_published_without_evidence_or_license(tmp_path, state):
    from literature_graph_map.cli import main
    from literature_graph_map.operations import export_snapshot
    from literature_graph_map.storage import yaml_text

    works = [
        {
            "paper_id": f"P{i:06d}",
            "title": f"Synthetic work {i}",
            "authors": [],
            "record_url": f"https://example.org/paper/{i}",
            "representative_version_id": "V1",
            "versions": [{"version_id": "V1"}],
        }
        for i in (1, 2)
    ]
    relation = {
        "relation_id": "R000001",
        "source": "P000001",
        "target": "P000002",
        "type": "supports",
        "aspect": "結果の比較",
        "reason": "同じ傾向を報告している。条件差はTODO。",
    }
    if state:
        relation["state"] = state
    packet = ImportPacket.model_validate(
        {
            "works": works,
            "topic": {
                "topic_id": "minimal",
                "title": "最小構成の文献マップ",
                "question": "研究間の違いは何か",
                "entries": [
                    {
                        "paper_id": work["paper_id"],
                        "group": "general",
                        "summary": {
                            "question": "共通の現象を調べる。",
                            "method": "二つのモデルを比較する。",
                            "contribution": "同じ傾向を示す。",
                        },
                    }
                    for work in works
                ],
                "relations": [relation],
            },
        }
    )
    path = tmp_path / "packet.yaml"
    path.write_text(yaml_text(packet), encoding="utf-8")
    repo, private, out = tmp_path / "repo", tmp_path / "private", tmp_path / "export"
    common = ["--repo", str(repo), "--private-dir", str(private)]
    assert main(common + ["import", str(path)]) == 0
    assert main(common + ["check", "--public"]) == 0
    snapshot = load(repo)
    assert export_snapshot(repo, snapshot, out) == 5
    assert len(load(out).topics["minimal"].relations) == 1
    page = (out / "topics/minimal/README.md").read_text(encoding="utf-8")
    assert "誤りや抜け" in page and "共通の現象を調べる。" in page
    assert "本文確認" not in page and "人間確認" not in page and "None" not in page
    if state == "rejected":
        assert "R000001" not in page
    else:
        assert "R000001" in page and "条件差はTODO。" in page
        if state is None:
            assert "R000001 支持・仮" in page
        elif state == "recheck":
            assert "R000001 支持・見直し予定" in page


@pytest.mark.parametrize("level", ["full_text", "preprint", "abstract"])
def test_unspecified_inspection_version_is_not_inferred_after_update(tmp_path, packet, level):
    repo, private = tmp_path / "repo", tmp_path / "private"
    packet = packet.model_copy(deep=True)
    entry = packet.topic.entries[0]
    entry.inspection.version_id = None
    entry.inspection.level = level
    packet.works[0].versions[0].kind = "submitted"
    import_packet(repo, Snapshot(), packet, private)
    packet.works[0].versions.append(Version(version_id="Vnew", kind="published"))
    packet.works[0].representative_version_id = "Vnew"
    import_packet(repo, load(repo), packet, private)
    page = (repo / "topics/demo/README.md").read_text(encoding="utf-8")
    row = next(line for line in page.splitlines() if line.startswith("| P000001 |"))
    assert "参照版未記録" in row and "旧版に基づく記述" in row
    assert "本文確認（出版版）" not in row and "要旨確認（出版版）" not in row


@pytest.mark.parametrize("reference", ["relation", "summary"])
def test_reference_only_work_survives_import_and_export(tmp_path, packet, reference):
    from conftest import make_work

    from literature_graph_map.cli import main
    from literature_graph_map.models import Evidence
    from literature_graph_map.operations import export_snapshot

    packet = packet.model_copy(deep=True)
    source = make_work(99)
    packet.works.append(source)
    evidence = Evidence(
        paper_id=source.paper_id,
        version_id=source.representative_version_id,
        url=source.record_url,
    )
    if reference == "relation":
        packet.topic.relations[0].evidence = [evidence]
    else:
        packet.topic.entries[0].evidence_by_item.question = [evidence]
    repo, private, out = tmp_path / "repo", tmp_path / "private", tmp_path / "export"
    import_packet(repo, Snapshot(), packet, private)
    snapshot = load(repo)
    assert "P000099" in snapshot.works
    assert "P000099" not in {entry.paper_id for entry in snapshot.topics["demo"].entries}
    backup = ImportPacket.model_validate(read_yaml(private / "demo/review-packet.yaml"))
    assert "P000099" in {work.paper_id for work in backup.works}
    assert main(["--repo", str(repo), "--private-dir", str(private), "check", "--public"]) == 0
    export_snapshot(repo, snapshot, out)
    assert "P000099" in load(out).works


def test_private_topic_stays_outside_repo(tmp_path, packet):
    packet = packet.model_copy(deep=True)
    packet.topic.public = False
    import_packet(tmp_path / "repo", Snapshot(), packet, tmp_path / "private")
    assert not (tmp_path / "repo").exists()
    assert (tmp_path / "private/demo/review-packet.yaml").exists()


def test_handoff_preserves_in_progress_packet(tmp_path, snapshot):
    private = tmp_path / "private"
    research_handoff(private, snapshot.topics["demo"], snapshot, [])
    packet_path = private / "demo/packet.yaml"
    packet_path.write_text("researcher's in-progress draft", encoding="utf-8")
    research_handoff(private, snapshot.topics["demo"], snapshot, [])
    assert packet_path.read_text(encoding="utf-8") == "researcher's in-progress draft"
    assert (private / "demo/packet.generated.yaml").exists()


def test_default_is_current_repository():
    assert parser().parse_args(["render"]).repo == Path(".")


def test_doi_parentheses_are_not_removed_from_bibtex(tmp_path):
    bib = tmp_path / "seed.bib"
    bib.write_text("@article{x, doi={10.5555/test(2001)}}", encoding="utf-8")
    assert seed_identifiers(str(bib)) == ["10.5555/test(2001)"]


def test_public_check_rejects_unmanaged_source_files(tmp_path, packet):
    from literature_graph_map.cli import main

    repo = tmp_path / "repo"
    private = tmp_path / "private"
    import_packet(repo, Snapshot(), packet, private)
    (repo / "topics/demo/source.pdf").write_bytes(b"private source")
    assert main(["--repo", str(repo), "--private-dir", str(private), "check", "--public"]) == 1


def test_public_check_scans_original_yaml_comments(tmp_path, packet):
    from literature_graph_map.cli import main

    repo, private = tmp_path / "repo", tmp_path / "private"
    import_packet(repo, Snapshot(), packet, private)
    path = repo / "topics/demo/topic.yaml"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n# C:\\Users\\private\\source.pdf\n", encoding="utf-8"
    )
    assert main(["--repo", str(repo), "--private-dir", str(private), "check", "--public"]) == 1


def test_public_check_also_scans_decoded_source_values(tmp_path, packet):
    from literature_graph_map.cli import main

    repo, private = tmp_path / "repo", tmp_path / "private"
    import_packet(repo, Snapshot(), packet, private)
    path = repo / "data/works.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    fake = "sk-FAKE" + "X" * 32
    records[0]["metadata_sources"][0]["provider"] = fake
    text = "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n"
    path.write_text(text.replace(fake, "\\u0073" + fake[1:]), encoding="utf-8")
    assert main(["--repo", str(repo), "--private-dir", str(private), "check", "--public"]) == 1


def test_export_index_is_self_contained(tmp_path, snapshot):
    from literature_graph_map.operations import export_snapshot

    repo, dest = tmp_path / "repo", tmp_path / "export"
    commit(repo, snapshot)
    index = repo / "README.md"
    index.write_text(
        index.read_text(encoding="utf-8") + "\n[開発者向け説明](docs/USAGE.md)\n", encoding="utf-8"
    )
    (repo / "LICENSE").write_text("Synthetic data license.", encoding="utf-8")
    export_snapshot(repo, snapshot, dest)
    assert "docs/USAGE.md" not in (dest / "README.md").read_text(encoding="utf-8")


def test_shared_work_version_update_preserves_other_topics_pending_relations(tmp_path, packet):
    repo, private = tmp_path / "repo", tmp_path / "private"
    import_packet(repo, Snapshot(), packet, private)
    other = packet.model_copy(deep=True)
    other.topic.topic_id = "other"
    import_packet(repo, load(repo), other, private)
    incoming = packet.model_copy(deep=True)
    work = incoming.works[0]
    work.versions.append(Version(version_id="Vnew", kind="published", doi="10.5555/new"))
    work.version_links.append(
        VersionLink(source="V000001", target="Vnew", evidence_url=work.record_url, checked_at=DAY)
    )
    work.representative_version_id = "Vnew"
    import_packet(repo, load(repo), incoming, private)
    saved = ImportPacket.model_validate(read_yaml(private / "other/review-packet.yaml"))
    states = {r.relation_id: r.state for r in saved.topic.relations}
    assert states["R000001"] == "recheck" and states["R000003"] == "candidate"


def test_review_packet_does_not_include_unrelated_metadata(tmp_path, snapshot, packet):
    from conftest import make_work

    snapshot.works["P000099"] = make_work(99)
    import_packet(tmp_path / "repo", snapshot, packet, tmp_path / "private")
    saved = ImportPacket.model_validate(read_yaml(tmp_path / "private/demo/review-packet.yaml"))
    assert "P000099" not in {w.paper_id for w in saved.works}


def test_rejected_import_does_not_overwrite_private_recovery_packet(tmp_path, packet):
    repo, private = tmp_path / "repo", tmp_path / "private"
    import_packet(repo, Snapshot(), packet, private)
    path = private / "demo/review-packet.yaml"
    before = path.read_bytes()
    packet = packet.model_copy(deep=True)
    packet.topic.title = "C:\\Users\\private\\document"
    with pytest.raises(MapError, match="local path"):
        import_packet(repo, load(repo), packet, private)
    assert path.read_bytes() == before


@pytest.mark.parametrize("relative", ["topics/moved/README.md", "COPYRIGHT.md", "LICENSE"])
def test_public_check_scans_manual_publication_documents(tmp_path, packet, relative):
    from literature_graph_map.cli import main

    repo, private = tmp_path / "repo", tmp_path / "private"
    import_packet(repo, Snapshot(), packet, private)
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("C:\\Users\\private\\document.pdf", encoding="utf-8")
    assert main(["--repo", str(repo), "--private-dir", str(private), "check", "--public"]) == 1
