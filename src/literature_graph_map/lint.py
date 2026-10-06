"""Find missing overview citations and unfinished summary items."""

from .models import PAPER_CITATION
from .render import SUMMARY_LABELS, citation_labels
from .storage import MapError, Snapshot

SUMMARY_PLACEHOLDERS = {
    "準備中",
    "準備中です",
    "要点は準備中です",
    "未記入",
    "未確認",
    "未作成",
    "todo",
    "tbd",
}


def _topic_ids(snapshot: Snapshot, topic_id: str | None) -> list[str]:
    if topic_id is not None and topic_id not in snapshot.topics:
        raise MapError(f"unknown topic: {topic_id}")
    return [topic_id] if topic_id is not None else sorted(snapshot.topics)


def review_citation_gaps(snapshot: Snapshot, topic_id: str | None = None) -> list[dict[str, str]]:
    labels = citation_labels(snapshot.works)
    gaps = []
    for key in _topic_ids(snapshot, topic_id):
        topic = snapshot.topics[key]
        cited = {
            paper_id
            for section in topic.review
            for paragraph in section.paragraphs
            for paper_id in PAPER_CITATION.findall(paragraph)
        }
        for entry in topic.entries:
            if entry.paper_id not in cited:
                gaps.append(
                    {
                        "topic_id": key,
                        "path": (snapshot.paths[key] / "topic.yaml").as_posix(),
                        "paper_id": entry.paper_id,
                        "citation": labels[entry.paper_id],
                        "title": snapshot.works[entry.paper_id].title,
                    }
                )
    return gaps


def summary_gaps(snapshot: Snapshot, topic_id: str | None = None) -> list[dict[str, str]]:
    labels = citation_labels(snapshot.works)
    gaps = []
    for key in _topic_ids(snapshot, topic_id):
        for entry in snapshot.topics[key].entries:
            for field in SUMMARY_LABELS:
                text = getattr(entry.summary, field).strip() if entry.summary is not None else ""
                if not text:
                    reason = "missing"
                elif text.rstrip("。.").casefold() in SUMMARY_PLACEHOLDERS:
                    reason = "placeholder"
                else:
                    continue
                gaps.append(
                    {
                        "topic_id": key,
                        "path": (snapshot.paths[key] / "topic.yaml").as_posix(),
                        "paper_id": entry.paper_id,
                        "citation": labels[entry.paper_id],
                        "title": snapshot.works[entry.paper_id].title,
                        "field": field,
                        "reason": reason,
                    }
                )
    return gaps
