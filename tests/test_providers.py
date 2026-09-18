import json

import httpx
import pytest

from literature_graph_map.models import Topic
from literature_graph_map.operations import add_seeds, discover, refresh
from literature_graph_map.providers import Crossref, Settings, crossref_work, seed_identifiers
from literature_graph_map.storage import MapError, Snapshot, publication_issues


def record(doi="10.5555/test"):
    return {
        "DOI": doi,
        "title": ["A <i>realistic</i> title"],
        "author": [{"given": "A", "family": "Example"}],
        "type": "journal-article",
        "published-print": {"date-parts": [[2020, 1, 2]]},
        "abstract": "A source abstract that must remain in private storage.",
        "reference": [{"DOI": "10.5555/other"}],
    }


def test_metadata_projection_does_not_copy_abstract_or_infer_access():
    work = crossref_work(record(), "P000001")
    assert work.title == "A realistic title"
    assert "abstract" not in work.model_dump_json()
    assert work.access_check == "not_checked" and work.preprint_check == "not_checked"
    assert work.version().publisher is None
    assert publication_issues(work.model_dump_json()) == []


def test_provider_boundaries_partial_results_and_request_cap(tmp_path):
    def handler(request):
        if request.url.params.get("query.bibliographic") == "fail":
            return httpx.Response(429)
        return httpx.Response(200, json={"message": {"items": [record()]}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = Crossref(tmp_path, Settings(max_search_calls=2), client)
        topic = Topic(topic_id="dust", title="Dust", question="Dust")
        issues = discover(topic, provider, ["good", "fail", "over budget"])
    assert any("rate_limited" in message for message in issues)
    assert any("limit reached" in message for message in issues)
    assert provider.calls == 2
    assert [event["status"] for event in provider.events] == ["ok", "rate_limited", "budget"]
    candidates = json.loads((tmp_path / "dust/candidates.json").read_text(encoding="utf-8"))
    assert len(candidates) == 1
    assert topic.entries == []  # Search rank is never adoption.


def test_duplicate_doi_add_reuses_ledger_without_extra_calls(tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"message": record()})

    snapshot = Snapshot()
    topic = Topic(topic_id="a", title="A", question="A")
    other = Topic(topic_id="b", title="B", question="B")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = Crossref(tmp_path, Settings(), client)
        assert (
            add_seeds(
                snapshot,
                topic,
                ["https://doi.org/10.5555/TEST", "doi:10.5555/test"],
                provider,
                tmp_path,
            )
            == []
        )
        assert add_seeds(snapshot, other, ["10.5555/test"], provider, tmp_path) == []
    assert len(calls) == 1 and len(snapshot.works) == 1
    assert topic.entries[0].paper_id == other.entries[0].paper_id
    assert topic.entries[0].summary is None and topic.relations == []


def test_failed_seed_is_not_a_paper(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404))) as client:
        topic = Topic(topic_id="a", title="A", question="A")
        snapshot = Snapshot()
        issues = add_seeds(
            snapshot, topic, ["10.5555/missing"], Crossref(tmp_path, Settings(), client), tmp_path
        )
    assert "not_found" in issues[0] and not snapshot.works and not topic.entries


def test_bibtex_and_ris_discovery(tmp_path):
    bib = tmp_path / "seeds.bib"
    bib.write_text("@article{x, doi={10.5555/test}, title={Keep private}}", encoding="utf-8")
    ris = tmp_path / "seeds.ris"
    ris.write_text("TY  - JOUR\nDO  - 10.5555/test\nER  -\n", encoding="utf-8")
    assert seed_identifiers(str(bib)) == ["10.5555/test"]
    assert seed_identifiers(str(ris)) == ["10.5555/test"]


def test_refresh_preserves_summary_and_verified_access(tmp_path, snapshot):
    from conftest import DAY

    from literature_graph_map.models import Location

    work = snapshot.works["P000001"]
    work.locked_fields = ["title"]
    work.citation_author = "Pagán Muñoz"
    work.versions[0].locations.append(
        Location(
            url="https://example.org/free",
            host="example.org",
            access_status="free",
            source="record",
            verification_method="public_record",
            checked_at=DAY,
        )
    )
    before = snapshot.topics["demo"].entries[0].model_dump()
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"message": record("10.5555/fixture-1")})
        )
    ) as client:
        provider = Crossref(tmp_path, Settings(max_search_calls=1), client)
        issues = refresh(snapshot, snapshot.topics["demo"], provider)
    assert any("locked" in issue for issue in issues)
    assert snapshot.works["P000001"].title == work.title
    assert snapshot.works["P000001"].citation_author == "Pagán Muñoz"
    assert snapshot.works["P000001"].versions[0].locations[0].access_status == "free"
    assert snapshot.topics["demo"].entries[0].model_dump() == before


def test_invalid_crossref_payload_fails_cleanly(tmp_path):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    ) as client:
        provider = Crossref(tmp_path, Settings(), client)
        with pytest.raises(MapError, match="invalid metadata"):
            provider.resolve("10.5555/example")
