"""Find topic entries that are missing from the overview's inline citations."""

from .models import PAPER_CITATION
from .render import citation_labels
from .storage import MapError, Snapshot


def review_citation_gaps(snapshot: Snapshot, topic_id: str | None = None) -> list[dict[str, str]]:
    if topic_id is not None and topic_id not in snapshot.topics:
        raise MapError(f"unknown topic: {topic_id}")
    labels = citation_labels(snapshot.works)
    gaps = []
    for key in [topic_id] if topic_id is not None else sorted(snapshot.topics):
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
