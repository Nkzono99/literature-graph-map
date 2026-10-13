from datetime import date
from pathlib import Path

import pytest

from literature_graph_map.models import (
    Entry,
    Evidence,
    Inspection,
    ItemEvidence,
    MetadataSource,
    Summary,
    Topic,
    Version,
    Work,
)
from literature_graph_map.storage import Snapshot

DAY = date(2026, 9, 17)


def make_work(number: int, kind: str = "published") -> Work:
    """A synthetic work whose default reading (summary, sources, inspection) is complete."""
    key = f"P{number:06d}"
    version = Version(
        version_id=f"V{number:06d}",
        kind=kind,
        year=2000 + number % 20,
        doi=f"10.5555/fixture-{number}",
        venue="架空の検証用誌",
        publisher=None,
    )
    record_url = f"https://example.org/papers/{number}"
    evidence = Evidence(
        paper_id=key,
        version_id=version.version_id,
        url=record_url,
        source_type="full_text",
        locator="検証用の架空の節",
        checked_at=DAY,
    )
    return Work(
        paper_id=key,
        title=f"検証用架空文献 {number}",
        authors=[f"Example {number}"],
        representative_version_id=version.version_id,
        versions=[version],
        record_url=record_url,
        metadata_sources=[
            MetadataSource(provider="架空の検証データ", url=record_url, checked_at=DAY)
        ],
        summary=Summary(
            question="架空の問いを比較する。",
            method="架空のモデルを使う。",
            contribution="これは実在研究の成果ではない。",
        ),
        evidence_by_item=ItemEvidence(
            question=[evidence], method=[evidence], contribution=[evidence]
        ),
        inspection=Inspection(
            level="full_text", version_id=version.version_id, checked_by="ai", checked_at=DAY
        ),
    )


def make_entry(work: Work) -> Entry:
    """An entry that inherits the work's reading."""
    return Entry(paper_id=work.paper_id, group="general", role="検証用役割")


@pytest.fixture
def snapshot() -> Snapshot:
    works = [make_work(i) for i in range(1, 5)]
    topic = Topic(
        topic_id="demo",
        title="動作確認用の架空テーマ",
        question="全論文・著者・出典は架空の検証用データです。実際の調査結果ではありません。",
        public=True,
        entries=[make_entry(w) for w in works],
    )
    return Snapshot(
        works={w.paper_id: w for w in works},
        topics={"demo": topic},
        paths={"demo": Path("topics/demo")},
    )
