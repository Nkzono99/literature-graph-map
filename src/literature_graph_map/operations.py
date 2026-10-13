"""Survey, bibliographic refresh, and publication orchestration."""

import copy
import hashlib
import json
import re
from datetime import date
from pathlib import Path

from .models import Entry, Topic, Work, reading
from .providers import Crossref, crossref_work, seed_identifiers
from .render import COPYRIGHT, copyright_text, rendered_files
from .storage import (
    MapError,
    Snapshot,
    inside,
    json_text,
    next_paper_id,
    publication_issues,
    write_files,
)


def prepare_commit(repo: Path, snapshot: Snapshot) -> dict[Path, str]:
    snapshot.validate()
    files = snapshot.source_files(repo)
    copyright_path = inside(repo, repo / "COPYRIGHT.md")
    if not copyright_path.exists():
        files[copyright_path] = COPYRIGHT
    for path, text in files.items():
        issues = publication_issues(text)
        if issues:
            raise MapError(
                f"publication check failed ({path.relative_to(repo)}): {', '.join(issues)}"
            )
    return files


def commit(repo: Path, snapshot: Snapshot) -> None:
    write_files(repo, prepare_commit(repo, snapshot))


def merge_bibliography(existing: Work, incoming: Work, conflicts: list[str]) -> Work:
    """Refresh provider bibliography; verified records and the reading stay as recorded."""
    original = existing.model_dump()
    data = copy.deepcopy(original)
    fresh = incoming.model_dump()
    versions = {v.version_id: v.model_dump() for v in existing.versions}
    for version in incoming.versions:
        duplicate = next(
            (v for v in existing.versions if version.doi and version.doi == v.doi), None
        )
        if duplicate and duplicate.version_id != version.version_id:
            raise MapError("an existing DOI's version ID is immutable; use the ledger's version ID")
        item = version.model_dump()
        if version.version_id in versions:
            previous = versions[version.version_id]
            for key in ("doi", "repository_id"):
                if previous[key] is not None and item[key] not in (None, previous[key]):
                    raise MapError("an existing version's bibliographic identity is immutable")
            item["locations"] = previous["locations"]
            item["repository_id"] = previous["repository_id"]
            for key, value in list(item.items()):
                if value is None:
                    item[key] = previous[key]
        versions[version.version_id] = item
    data["versions"] = list(versions.values())
    data["title"] = fresh["title"]
    data["authors"] = fresh["authors"]
    data["missing_note"] = fresh["missing_note"]
    sources = {source.url: source.model_dump() for source in existing.metadata_sources}
    sources.update({source.url: source.model_dump() for source in incoming.metadata_sources})
    data["metadata_sources"] = list(sources.values())
    for key in existing.locked_fields:
        if data[key] != original[key]:
            conflicts.append(
                f"{existing.paper_id}.{key}: locked value preserved; review incoming evidence"
            )
            data[key] = original[key]
    return Work.model_validate(data)


def referenced_papers(topic: Topic, works: dict[str, Work]) -> set[str]:
    """Works listed in the topic plus the works their displayed sources point to."""
    references = {e.paper_id for e in topic.entries}
    for entry in topic.entries:
        evidence = reading(entry, works[entry.paper_id]).evidence_by_item
        for key in ("question", "method", "contribution"):
            references.update(e.paper_id for e in getattr(evidence, key))
    return references


def topic_slug(theme: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", theme.lower()).strip("-")[:60].rstrip("-")
    return slug or "theme-" + hashlib.sha256(theme.encode()).hexdigest()[:10]


def new_topic(snapshot: Snapshot, theme: str, topic_id: str | None, parent: str | None) -> Topic:
    key = topic_id or topic_slug(theme)
    if key in snapshot.topics:
        raise MapError("topic already exists; use add/update or a different --id")
    if parent and parent not in snapshot.topics:
        raise MapError("unknown parent topic")
    topic = Topic(topic_id=key, title=theme, question=theme, public=True)
    topic.navigation.parent = parent
    snapshot.topics[key] = topic
    base = snapshot.paths[parent] if parent else Path("topics")
    snapshot.paths[key] = base / key
    return topic


def add_seeds(
    snapshot: Snapshot, topic: Topic, seeds: list[str], provider: Crossref, private: Path
) -> list[str]:
    limitations = []
    accepted = []
    for seed in seeds:
        try:
            identifiers = seed_identifiers(seed)
        except (MapError, OSError, ValueError) as exc:
            limitations.append(str(exc))
            continue
        for doi in identifiers:
            existing = next(
                (w for w in snapshot.works.values() if any(v.doi == doi for v in w.versions)), None
            )
            try:
                work = existing or crossref_work(provider.resolve(doi), next_paper_id(snapshot))
            except MapError as exc:
                limitations.append(f"{doi}: {exc}")
                continue
            snapshot.works[work.paper_id] = work
            if work.paper_id not in {e.paper_id for e in topic.entries}:
                topic.entries.append(Entry(paper_id=work.paper_id, group=topic.groups[0].id))
                accepted.append(
                    {
                        "paper_id": work.paper_id,
                        "reason": "利用者がこのテーマの種文献として指定。内容と関連性は要確認。",
                    }
                )
    if accepted:
        existing_path = private / topic.topic_id / "adoptions.json"
        previous = (
            json.loads(existing_path.read_text(encoding="utf-8")) if existing_path.exists() else []
        )
        write_files(private, {existing_path: json_text(previous + accepted)})
    return limitations


def discover(
    topic: Topic, provider: Crossref, queries: list[str], since: str | None = None
) -> list[str]:
    if not queries:
        return []
    candidates = {}
    limitations = []
    for query in queries:
        if len(candidates) >= provider.config.max_candidates:
            limitations.append("候補件数上限に到達。追加検索は保留。")
            break
        try:
            items = provider.search(query, since)
            for item in items:
                doi = item.get("DOI") if isinstance(item, dict) else None
                if doi:
                    candidates[doi.lower()] = item
                if len(candidates) >= provider.config.max_candidates:
                    break
        except MapError as exc:
            limitations.append(str(exc))
    if queries:
        write_files(
            provider.private,
            {
                provider.private / topic.topic_id / "candidates.json": json_text(
                    list(candidates.values())
                )
            },
        )
    topic.survey.searched_at = date.today()
    topic.survey.provider_names = list(dict.fromkeys(topic.survey.provider_names + ["Crossref"]))
    topic.survey.queries = list(dict.fromkeys(topic.survey.queries + queries))
    note = f"Crossrefキーワード検索の候補{len(candidates)}件。検索順位は採用判断ではありません。"
    if since:
        note += f"今回の新規候補は{since}以降を探索。"
    previous = topic.survey.coverage_note
    topic.survey.coverage_note = (
        note
        if previous in {"未実行", "未記録"}
        else previous
        if note in previous
        else previous + " " + note
    )
    limitations.append("Crossrefの候補検索のみ。必要に応じて別の情報源も利用できます。")
    return limitations


def research_handoff(private: Path, topic: Topic, snapshot: Snapshot, events: list[dict]) -> Path:
    target = private / topic.topic_id
    instruction = f"""# 調査メモ：{topic.title}

テーマの問い：{topic.question}

このテーマを引用リンク付きの概説と文献一覧に整理します。調査方法や利用するAI・検索・プラグインは自由です。情報が揃った部分から反映し、誤りや不足は随時修正します。

正本は `data/works.jsonl`（書誌と要点の既定値）と `topics/**/topic.yaml`（テーマの分類・概説・系譜）です。直接編集して `lgm lint` と `lgm render` で確認します。検索を行った場合の候補は `candidates.json`、取得応答は作業領域の `responses/` にあります。入力形式の詳細は `docs/USAGE.md` と `lgm schema --output schemas` を参照してください。
"""
    files = {
        target / "RESEARCH_REQUEST.md": instruction,
        target / "search-report.json": json_text(events),
    }
    write_files(private, files)
    return target / "RESEARCH_REQUEST.md"


def refresh(snapshot: Snapshot, topic: Topic, provider: Crossref) -> list[str]:
    limitations = []
    conflicts = []
    for entry in topic.entries:
        work = snapshot.works[entry.paper_id]
        doi = work.version().doi
        if not doi:
            limitations.append(f"{work.paper_id}: DOI未登録のため書誌更新を保留。")
            continue
        try:
            incoming = crossref_work(provider.resolve(doi), work.paper_id)
            # Crossref refresh does not change version identifiers already assigned by a researcher.
            incoming.versions[0].version_id = work.version().version_id
            incoming.representative_version_id = work.version().version_id
            snapshot.works[work.paper_id] = merge_bibliography(work, incoming, conflicts)
        except MapError as exc:
            limitations.append(f"{work.paper_id}: {exc}")
    limitations.extend(conflicts)
    return limitations


def public_snapshot(snapshot: Snapshot) -> Snapshot:
    topics = {}
    for key, source in snapshot.topics.items():
        if not source.public:
            continue
        topic = source.model_copy(deep=True)
        if topic.navigation.parent and not snapshot.topics[topic.navigation.parent].public:
            raise MapError(f"{key}: public topic has a private parent")
        topic.navigation.related = [
            key for key in topic.navigation.related if snapshot.topics[key].public
        ]
        topics[key] = topic
    papers = set()
    for topic in topics.values():
        papers |= referenced_papers(topic, snapshot.works)
    pending = list(papers)
    while pending:
        work = snapshot.works[pending.pop()]
        for key in ("question", "method", "contribution"):
            for ref in getattr(work.evidence_by_item, key):
                if ref.paper_id not in papers:
                    papers.add(ref.paper_id)
                    pending.append(ref.paper_id)
    result = Snapshot(
        overview=copy.deepcopy(snapshot.overview),
        works={key: snapshot.works[key] for key in sorted(papers)},
        topics=topics,
        paths={key: snapshot.paths[key] for key in topics},
    )
    result.validate()
    return result


def export_snapshot(repo: Path, snapshot: Snapshot, destination: Path) -> int:
    destination = destination.resolve()
    if destination.is_relative_to(repo) or repo.is_relative_to(destination):
        raise MapError("export destination must be separate from the working repository")
    if destination.exists():
        raise MapError("export destination already exists; choose a new empty snapshot path")
    license_path = inside(repo, repo / "LICENSE")
    public = public_snapshot(snapshot)
    if not public.topics:
        raise MapError("no topics are marked public: true")
    files = public.source_files(destination)
    files.update(rendered_files(repo, public, destination=destination))
    files[destination / "COPYRIGHT.md"] = copyright_text(repo)
    if license_path.is_file():
        files[destination / "LICENSE"] = license_path.read_text(encoding="utf-8-sig")
    for path, text in files.items():
        problems = publication_issues(text)
        if problems:
            raise MapError(
                f"publication check failed ({path.relative_to(destination)}): {', '.join(problems)}"
            )
    write_files(destination, files)
    return len(files)
