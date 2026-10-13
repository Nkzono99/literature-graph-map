import json
from pathlib import Path

import httpx
import pytest
from conftest import DAY, make_entry, make_work
from test_providers import record

from literature_graph_map.cli import main, parser
from literature_graph_map.models import Evidence, Summary, Topic, Version, Work
from literature_graph_map.operations import (
    add_seeds,
    commit,
    discover,
    export_snapshot,
    merge_bibliography,
    research_handoff,
)
from literature_graph_map.providers import Crossref, Settings, seed_identifiers
from literature_graph_map.render import render
from literature_graph_map.storage import MapError, Snapshot, load


def test_existing_version_cannot_change_doi(snapshot):
    incoming = snapshot.works["P000001"].model_copy(deep=True)
    incoming.versions[0].doi = "10.5555/different"
    with pytest.raises(MapError, match="immutable"):
        merge_bibliography(snapshot.works["P000001"], incoming, [])


def test_bibliographic_refresh_keeps_reading_and_locked_fields(snapshot):
    existing = snapshot.works["P000001"]
    existing.locked_fields = ["title"]
    incoming = Work(
        paper_id=existing.paper_id,
        title="Provider title",
        authors=["Provider Author"],
        representative_version_id=existing.representative_version_id,
        versions=[Version(version_id=existing.representative_version_id, year=2001)],
        record_url="https://example.org/provider",
        missing_note="Provider note",
    )
    conflicts = []
    merged = merge_bibliography(existing, incoming, conflicts)
    assert conflicts and merged.title == existing.title
    assert merged.authors == ["Provider Author"] and merged.missing_note == "Provider note"
    assert merged.record_url == existing.record_url
    assert merged.version().doi == "10.5555/fixture-1" and merged.version().venue
    assert merged.summary == existing.summary
    assert merged.evidence_by_item == existing.evidence_by_item
    assert merged.inspection == existing.inspection


def test_scope_changes_update_generated_prose(tmp_path, snapshot):
    repo = tmp_path / "repo"
    commit(repo, snapshot)
    topic = snapshot.topics["demo"]
    topic.question = "更新後の問い。"
    topic.scope.include = ["更新後の対象条件"]
    commit(repo, snapshot)
    render(repo, load(repo))
    page = (repo / "_site/topics/demo/index.html").read_text(encoding="utf-8")
    assert "更新後の問い。" in page and "更新後の対象条件" in page
    assert "全論文・著者・出典は架空" not in page


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
    added = snapshot.works[topic.entries[-1].paper_id]
    assert added.summary is None and added.inspection.level == "metadata_only"
    assert added.inspection.version_id == added.representative_version_id


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


def test_partial_research_can_be_published_without_evidence_or_license(tmp_path):
    works = [
        Work.model_validate(
            {
                "paper_id": f"P{i:06d}",
                "title": f"Synthetic work {i}",
                "authors": [],
                "record_url": f"https://example.org/paper/{i}",
                "representative_version_id": "V1",
                "versions": [{"version_id": "V1"}],
            }
        )
        for i in (1, 2)
    ]
    topic = Topic.model_validate(
        {
            "topic_id": "minimal",
            "title": "最小構成の文献マップ",
            "question": "研究間の違いは何か",
            "entries": [
                {
                    "paper_id": work.paper_id,
                    "group": "general",
                    "summary": {
                        "question": "共通の現象を調べる。",
                        "method": "二つのモデルを比較する。",
                        "contribution": "同じ傾向を示す。",
                    },
                }
                for work in works
            ],
        }
    )
    snapshot = Snapshot(
        works={w.paper_id: w for w in works},
        topics={"minimal": topic},
        paths={"minimal": Path("topics/minimal")},
    )
    repo, private, out = tmp_path / "repo", tmp_path / "private", tmp_path / "export"
    commit(repo, snapshot)
    assert main(["--repo", str(repo), "--private-dir", str(private), "check", "--public"]) == 0
    assert export_snapshot(repo, load(repo), out) > 0
    page = (out / "_site/topics/minimal/index.html").read_text(encoding="utf-8")
    assert "誤りや抜け" in page and "共通の現象を調べる。" in page
    papers = page.split('<section id="papers"')[1].split("</section>")[0]
    assert "本文確認" not in papers and "人間確認" not in papers and "None" not in papers


@pytest.mark.parametrize("level", ["full_text", "preprint", "abstract"])
def test_unspecified_inspection_version_is_not_inferred_after_update(tmp_path, snapshot, level):
    repo = tmp_path / "repo"
    work = snapshot.works["P000001"]
    work.versions[0].kind = "submitted"
    work.inspection.version_id = None
    work.inspection.level = level
    work.versions.append(Version(version_id="Vnew", kind="published"))
    work.representative_version_id = "Vnew"
    work.inspection.recheck = True
    commit(repo, snapshot)
    render(repo, load(repo))
    page = (repo / "_site/topics/demo/index.html").read_text(encoding="utf-8")
    paper = page.split('id="P000001"', 1)[1].split("</article>", 1)[0]
    assert "参照版未記録" in paper and "旧版に基づく記述" in paper
    assert "本文確認（出版版）" not in paper and "要旨確認（出版版）" not in paper


@pytest.mark.parametrize("reference", ["work", "entry"])
def test_reference_only_work_survives_commit_and_export(tmp_path, snapshot, reference):
    source = make_work(99)
    snapshot.works[source.paper_id] = source
    evidence = Evidence(
        paper_id=source.paper_id,
        version_id=source.representative_version_id,
        url=source.record_url,
    )
    entry = snapshot.topics["demo"].entries[0]
    if reference == "work":
        snapshot.works[entry.paper_id].evidence_by_item.question = [evidence]
    else:
        entry.evidence_by_item = snapshot.works[entry.paper_id].evidence_by_item.model_copy(
            update={"question": [evidence]}
        )
    repo, private, out = tmp_path / "repo", tmp_path / "private", tmp_path / "export"
    commit(repo, snapshot)
    loaded = load(repo)
    assert "P000099" in loaded.works
    assert "P000099" not in {entry.paper_id for entry in loaded.topics["demo"].entries}
    assert main(["--repo", str(repo), "--private-dir", str(private), "check", "--public"]) == 0
    export_snapshot(repo, loaded, out)
    assert "P000099" in load(out).works


def test_handoff_writes_request_without_packet_copies(tmp_path, snapshot):
    private = tmp_path / "private"
    request = research_handoff(private, snapshot.topics["demo"], snapshot, [{"status": "ok"}])
    assert request.read_text(encoding="utf-8").startswith("# 調査メモ：動作確認用の架空テーマ")
    assert "works.jsonl" in request.read_text(encoding="utf-8")
    assert json.loads((private / "demo/search-report.json").read_text(encoding="utf-8"))
    assert not list(private.rglob("*.yaml"))


def test_default_is_current_repository():
    assert parser().parse_args(["render"]).repo == Path(".")


def test_doi_parentheses_are_not_removed_from_bibtex(tmp_path):
    bib = tmp_path / "seed.bib"
    bib.write_text("@article{x, doi={10.5555/test(2001)}}", encoding="utf-8")
    assert seed_identifiers(str(bib)) == ["10.5555/test(2001)"]


def test_public_check_rejects_unmanaged_source_files(tmp_path, snapshot):
    repo = tmp_path / "repo"
    private = tmp_path / "private"
    commit(repo, snapshot)
    (repo / "topics/demo/source.pdf").write_bytes(b"private source")
    assert main(["--repo", str(repo), "--private-dir", str(private), "check", "--public"]) == 1


def test_public_check_scans_original_yaml_comments(tmp_path, snapshot):
    repo, private = tmp_path / "repo", tmp_path / "private"
    commit(repo, snapshot)
    path = repo / "topics/demo/topic.yaml"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n# C:\\Users\\private\\source.pdf\n", encoding="utf-8"
    )
    assert main(["--repo", str(repo), "--private-dir", str(private), "check", "--public"]) == 1


def test_public_check_also_scans_decoded_source_values(tmp_path, snapshot):
    repo, private = tmp_path / "repo", tmp_path / "private"
    commit(repo, snapshot)
    path = repo / "data/works.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    fake = "sk-FAKE" + "X" * 32
    records[0]["metadata_sources"][0]["provider"] = fake
    text = "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n"
    path.write_text(text.replace(fake, "\\u0073" + fake[1:]), encoding="utf-8")
    assert main(["--repo", str(repo), "--private-dir", str(private), "check", "--public"]) == 1


def test_export_index_is_self_contained(tmp_path, snapshot):
    repo, dest = tmp_path / "repo", tmp_path / "export"
    commit(repo, snapshot)
    index = repo / "README.md"
    index.write_text("[開発者向け説明](docs/USAGE.md)\n", encoding="utf-8")
    (repo / "LICENSE").write_text("Synthetic data license.", encoding="utf-8")
    export_snapshot(repo, snapshot, dest)
    assert "docs/USAGE.md" not in (dest / "_site/index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("relative", ["topics/moved/README.md", "COPYRIGHT.md", "LICENSE"])
def test_public_check_scans_manual_publication_documents(tmp_path, snapshot, relative):
    repo, private = tmp_path / "repo", tmp_path / "private"
    commit(repo, snapshot)
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("C:\\Users\\private\\document.pdf", encoding="utf-8")
    assert main(["--repo", str(repo), "--private-dir", str(private), "check", "--public"]) == 1


def test_shared_summary_is_stored_once_and_corrected_everywhere(tmp_path, snapshot):
    other = Topic(
        topic_id="other",
        title="別のテーマ",
        question="共通文献",
        entries=[make_entry(snapshot.works["P000001"])],
    )
    snapshot.topics["other"] = other
    snapshot.paths["other"] = Path("topics/other")
    repo = tmp_path / "repo"
    commit(repo, snapshot)
    for key in ("demo", "other"):
        text = (repo / f"topics/{key}/topic.yaml").read_text(encoding="utf-8")
        assert "summary:" not in text and "evidence_by_item" not in text
    loaded = load(repo)
    loaded.works["P000001"].summary = Summary(
        question="訂正した問い。", method="訂正した方法。", contribution="訂正した判明点。"
    )
    loaded.works["P000001"].inspection.checked_at = DAY
    commit(repo, loaded)
    render(repo, load(repo))
    for key in ("demo", "other"):
        page = (repo / f"_site/topics/{key}/index.html").read_text(encoding="utf-8")
        paper = page.split('id="P000001"', 1)[1].split("</article>", 1)[0]
        assert "訂正した問い。" in paper and "架空の問いを比較する。" not in paper
