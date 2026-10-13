"""Find missing overview citations, unfinished summary items, and unlinked author names."""

import re

from .models import PAPER_CITATION, reading
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

# "Stubbs et al. (2014)", "Pacaudら（2025）", "Furman・Pivi（2002）": an author named in plain
# text with a year. The citation syntax renders the same label as a link, so prose should
# cite with [@P000001] instead of naming the author and appending the citation.
NAME = r"[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’\-]*"
PLAIN_AUTHOR_YEAR = re.compile(
    rf"{NAME}(?:\s*(?:et al\.?|ほか|ら)|\s*(?:・|&|and|,)\s*{NAME})*\s*[（(]\d{{4}}[a-z]?[)）]"
)


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
            work = snapshot.works[entry.paper_id]
            summary = reading(entry, work).summary
            for field in SUMMARY_LABELS:
                text = getattr(summary, field).strip() if summary is not None else ""
                if not text:
                    reason = "missing"
                elif text.rstrip("。.").casefold() in SUMMARY_PLACEHOLDERS:
                    reason = "placeholder"
                else:
                    continue
                gaps.append(
                    {
                        "topic_id": key,
                        "path": (
                            (snapshot.paths[key] / "topic.yaml").as_posix()
                            if entry.summary is not None
                            else "data/works.jsonl"
                        ),
                        "paper_id": entry.paper_id,
                        "citation": labels[entry.paper_id],
                        "title": work.title,
                        "field": field,
                        "reason": reason,
                    }
                )
    return gaps


def plain_author_gaps(snapshot: Snapshot, topic_id: str | None = None) -> list[dict[str, str]]:
    """Author names written in plain text where a citation link should carry the name."""
    sources = [
        (key, (snapshot.paths[key] / "topic.yaml").as_posix(), snapshot.topics[key].review)
        for key in _topic_ids(snapshot, topic_id)
    ]
    if topic_id is None and snapshot.overview is not None:
        sources.append(("overview", "overview.yaml", snapshot.overview.review))
    gaps = []
    for key, path, review in sources:
        for section in review:
            for paragraph in section.paragraphs:
                for match in PLAIN_AUTHOR_YEAR.findall(paragraph):
                    gaps.append(
                        {"topic_id": key, "path": path, "heading": section.heading, "text": match}
                    )
    return gaps
