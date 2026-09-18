from datetime import date
from pathlib import Path

import pytest

from literature_graph_map.models import (
    Entry,
    Evidence,
    ImportPacket,
    Inspection,
    ItemEvidence,
    MetadataSource,
    Relation,
    Summary,
    Topic,
    Version,
    Work,
)
from literature_graph_map.storage import Snapshot

DAY = date(2026, 9, 17)


def make_work(number: int, kind: str = "published") -> Work:
    key = f"P{number:06d}"
    version = Version(
        version_id=f"V{number:06d}",
        kind=kind,
        year=2000 + number % 20,
        doi=f"10.5555/fixture-{number}",
        venue="架空の検証用誌",
        publisher=None,
    )
    return Work(
        paper_id=key,
        title=f"検証用架空文献 {number}",
        authors=[f"Example {number}"],
        representative_version_id=version.version_id,
        versions=[version],
        record_url=f"https://example.org/papers/{number}",
        metadata_sources=[
            MetadataSource(
                provider="架空の検証データ",
                url=f"https://example.org/papers/{number}",
                checked_at=DAY,
            )
        ],
    )


def make_entry(work: Work) -> Entry:
    evidence = Evidence(
        paper_id=work.paper_id,
        version_id=work.representative_version_id,
        url=work.record_url,
        source_type="full_text",
        locator="検証用の架空の節",
        checked_at=DAY,
    )
    return Entry(
        paper_id=work.paper_id,
        group="general",
        role="検証用役割",
        summary=Summary(
            question="架空の問いを比較する。",
            method="架空のモデルを使う。",
            contribution="これは実在研究の成果ではない。",
        ),
        evidence_by_item=ItemEvidence(
            question=[evidence], method=[evidence], contribution=[evidence]
        ),
        inspection=Inspection(
            level="full_text",
            version_id=work.representative_version_id,
            checked_by="ai",
            checked_at=DAY,
        ),
    )


@pytest.fixture
def snapshot() -> Snapshot:
    works = [make_work(i) for i in range(1, 5)]
    entries = [make_entry(w) for w in works]
    relations = [
        Relation(
            relation_id="R000001",
            source=works[0].paper_id,
            target=works[1].paper_id,
            type="extends",
            basis="explicit",
            state="checked",
            aspect="架空モデル",
            reason="表示検証用の架空の拡張関係。",
            evidence=[entries[1].evidence_by_item.method[0]],
            checked_by="ai",
            checked_at=DAY,
        ),
        Relation(
            relation_id="R000002",
            source=works[1].paper_id,
            target=works[2].paper_id,
            type="compares_with",
            basis="comparison",
            state="checked",
            aspect="架空条件",
            reason="表示検証用の架空の比較関係。",
            evidence=[entries[1].evidence_by_item.method[0], entries[2].evidence_by_item.method[0]],
            checked_by="ai",
            checked_at=DAY,
        ),
        Relation(
            relation_id="R000003",
            source=works[2].paper_id,
            target=works[3].paper_id,
            type="tests",
            basis="explicit",
            state="candidate",
            aspect="候補",
            reason="根拠未確認の検証候補。",
        ),
    ]
    topic = Topic(
        topic_id="demo",
        title="動作確認用の架空テーマ",
        question="全論文・著者・関係・出典は架空の検証用データです。実際の調査結果ではありません。",
        public=True,
        entries=entries,
        relations=relations,
    )
    return Snapshot(
        works={w.paper_id: w for w in works},
        topics={"demo": topic},
        paths={"demo": Path("topics/demo")},
    )


@pytest.fixture
def packet(snapshot) -> ImportPacket:
    return ImportPacket(works=list(snapshot.works.values()), topic=snapshot.topics["demo"])
