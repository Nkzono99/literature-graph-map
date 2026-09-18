"""Survey, incremental import, update, and publication orchestration."""

import copy
import hashlib
import re
from datetime import date
from pathlib import Path

from .models import Entry, ImportPacket, Inspection, Topic, Work
from .providers import Crossref, crossref_work, seed_identifiers
from .render import COPYRIGHT, check_rendered, index_page, rendered_files
from .storage import (
    MapError,
    Snapshot,
    inside,
    json_text,
    next_paper_id,
    publication_issues,
    write_files,
    yaml_text,
)


def prepare_commit(repo: Path, snapshot: Snapshot) -> dict[Path, str]:
    pages = rendered_files(repo, snapshot)
    files = {**snapshot.source_files(repo), **pages}
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


def find_work(snapshot: Snapshot, incoming: Work) -> Work | None:
    dois = {v.doi for v in incoming.versions if v.doi}
    repositories = {v.repository_id for v in incoming.versions if v.repository_id}
    matches = [
        w
        for w in snapshot.works.values()
        if any(v.doi in dois or v.repository_id in repositories for v in w.versions)
    ]
    if len(matches) > 1:
        raise MapError("versions already belong to distinct works; reconcile their IDs explicitly")
    return matches[0] if matches else None


def merge_work(
    existing: Work, incoming: Work, conflicts: list[str], metadata_only: bool = False
) -> Work:
    data = incoming.model_dump()
    data["paper_id"] = existing.paper_id
    versions = {v.version_id: v.model_dump() for v in existing.versions}
    for version in incoming.versions:
        duplicate = next(
            (v for v in existing.versions if version.doi and version.doi == v.doi), None
        )
        if duplicate and duplicate.version_id != version.version_id:
            raise MapError("an existing DOI's version ID is immutable; use the ledger's version ID")
        fresh = version.model_dump()
        if metadata_only and version.version_id in versions:
            fresh["locations"] = versions[version.version_id]["locations"]
            fresh["repository_id"] = versions[version.version_id]["repository_id"]
            for key, value in list(fresh.items()):
                if value is None:
                    fresh[key] = versions[version.version_id][key]
        if version.version_id in versions:
            for key in ("doi", "repository_id"):
                previous = versions[version.version_id][key]
                if previous is not None and fresh[key] != previous:
                    raise MapError("an existing version's bibliographic identity is immutable")
        versions[version.version_id] = fresh
    data["versions"] = list(versions.values())
    data["version_links"] = [v.model_dump() for v in existing.version_links]
    for item in incoming.version_links:
        if item.model_dump() not in data["version_links"]:
            data["version_links"].append(item.model_dump())
    sources = {source.url: source.model_dump() for source in existing.metadata_sources}
    sources.update({source.url: source.model_dump() for source in incoming.metadata_sources})
    data["metadata_sources"] = list(sources.values())
    if metadata_only:
        for key in ("access_check", "preprint_check", "representative_version_id", "record_url"):
            data[key] = getattr(existing, key)
    data["locked_fields"] = sorted(set(existing.locked_fields + incoming.locked_fields))
    locked = set(existing.locked_fields)
    if "versions" in locked:
        locked.update(("versions", "version_links", "representative_version_id"))
    for key in locked:
        before = existing.model_dump()[key]
        if data[key] != before:
            conflicts.append(
                f"{existing.paper_id}.{key}: locked value preserved; review incoming evidence"
            )
            data[key] = before
    return Work.model_validate(data)


def invalidate_versions(snapshot: Snapshot, changed: set[str]) -> None:
    for topic in snapshot.topics.values():
        affected = changed & {e.paper_id for e in topic.entries}
        if not affected:
            continue
        topic.survey.publication_status = "draft"
        topic.survey.reviewed_at = None
        for entry in topic.entries:
            if entry.paper_id in affected and entry.inspection.level != "metadata_only":
                entry.inspection.recheck = True
        for relation in topic.relations:
            if {relation.source, relation.target} & affected and relation.state == "checked":
                relation.state = "recheck"
        topic.survey.changes = (
            "版情報の更新。参照版を維持し、影響する要点・関係を再確認待ちに変更。"
        )


def referenced_papers(topic: Topic) -> set[str]:
    references = {e.paper_id for e in topic.entries}
    references.update(e.paper_id for r in topic.relations for e in r.evidence)
    for entry in topic.entries:
        for key in ("question", "method", "contribution"):
            references.update(e.paper_id for e in getattr(entry.evidence_by_item, key))
    return references


def research_packet(topic: Topic, snapshot: Snapshot) -> ImportPacket:
    """Collect the topic and its referenced works for optional import editing."""
    return ImportPacket(
        works=[snapshot.works[key] for key in sorted(referenced_papers(topic))], topic=topic
    )


def import_packet(
    repo: Path,
    snapshot: Snapshot,
    packet: ImportPacket,
    private: Path,
    topic_path: str | None = None,
) -> list[str]:
    snapshot = copy.deepcopy(snapshot)
    if not packet.topic.public:
        if packet.topic.topic_id in snapshot.topics:
            raise MapError(
                "cannot hide an existing published topic by importing a private draft; remove its public files explicitly"
            )
        write_files(
            private, {private / packet.topic.topic_id / "review-packet.yaml": yaml_text(packet)}
        )
        return []
    conflicts = []
    mapping = {}
    changed = set()
    seen_ids = set()
    for incoming in packet.works:
        if incoming.paper_id in seen_ids:
            raise MapError("duplicate work ID in import packet")
        seen_ids.add(incoming.paper_id)
        same = find_work(snapshot, incoming)
        by_id = snapshot.works.get(incoming.paper_id)
        if by_id and same and by_id.paper_id != same.paper_id:
            raise MapError("incoming paper ID belongs to another work")
        if by_id and not same:
            # DOI-free corrections may still share the explicitly confirmed record URL.
            if by_id.record_url != incoming.record_url:
                raise MapError("cannot replace a paper ID with a different bibliographic identity")
            same = by_id
        if same:
            mapping[incoming.paper_id] = same.paper_id
            merged = merge_work(same, incoming, conflicts)
            if merged.representative_version_id != same.representative_version_id or {
                v.version_id for v in merged.versions
            } != {v.version_id for v in same.versions}:
                changed.add(same.paper_id)
            snapshot.works[same.paper_id] = merged
        else:
            mapping[incoming.paper_id] = incoming.paper_id
            snapshot.works[incoming.paper_id] = incoming
    data = packet.topic.model_dump()

    def remap(value):
        if isinstance(value, dict):
            return {
                key: (
                    mapping.get(item, item)
                    if key in {"paper_id", "source", "target"} and isinstance(item, str)
                    else [mapping.get(n, n) for n in item]
                    if key in {"nodes", "overview_nodes"} and isinstance(item, list)
                    else remap(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [remap(item) for item in value]
        return value

    data = remap(data)
    old = snapshot.topics.get(packet.topic.topic_id)
    if old:
        if topic_path and Path(topic_path) != snapshot.paths[old.topic_id]:
            raise MapError(
                "move a topic directory explicitly, then run render to update relative links"
            )
        old_entries = {e.paper_id: e for e in old.entries}
        incoming_ids = {e["paper_id"] for e in data["entries"]}
        if any(e.locked_fields and e.paper_id not in incoming_ids for e in old.entries):
            raise MapError("import would remove a locked entry")
        for entry in data["entries"]:
            previous = old_entries.get(entry["paper_id"])
            if previous:
                preserve_locks(
                    previous, entry, conflicts, bundle={"summary", "evidence_by_item", "inspection"}
                )
        old_relations = {r.relation_id: r for r in old.relations}
        relation_ids = {r["relation_id"] for r in data["relations"]}
        if any(
            r.locked_fields and r.relation_id not in relation_ids for r in old_relations.values()
        ):
            raise MapError("import would remove a locked relation")
        for relation in data["relations"]:
            previous = old_relations.get(relation["relation_id"])
            if previous:
                preserve_locks(
                    previous,
                    relation,
                    conflicts,
                    bundle={
                        "state",
                        "basis",
                        "type",
                        "reason",
                        "evidence",
                        "aspect",
                        "comparability",
                        "checked_by",
                        "checked_at",
                        "source",
                        "target",
                        "limitation",
                    },
                )
    topic = Topic.model_validate(data)
    snapshot.topics[topic.topic_id] = topic
    if topic.topic_id not in snapshot.paths:
        path = Path(topic_path) if topic_path else Path("topics") / topic.topic_id
        resolved = inside(repo, repo / path / "topic.yaml")
        if not resolved.is_relative_to((repo / "topics").resolve()):
            raise MapError("topic path must be inside topics/")
        path = resolved.parent.relative_to(repo.resolve())
        if path in snapshot.paths.values():
            raise MapError("topic path is already occupied")
        snapshot.paths[topic.topic_id] = path
    invalidate_versions(snapshot, changed)
    snapshot.validate()
    public = public_snapshot(snapshot)
    public_files = prepare_commit(repo, public)
    private_files = {}
    for key, current in snapshot.topics.items():
        if key == topic.topic_id or changed & {e.paper_id for e in current.entries}:
            pending = research_packet(current, snapshot)
            private_files[private / key / "review-packet.yaml"] = yaml_text(pending)
    write_files(private, private_files)
    write_files(repo, public_files)
    write_files(
        private,
        {
            private / "import-report.json": json_text(
                {"conflicts": conflicts, "remapped_ids": mapping}
            )
        },
    )
    return conflicts


def preserve_locks(previous, incoming: dict, conflicts: list[str], bundle: set[str]) -> None:
    original = previous.model_dump()
    locked = set(previous.locked_fields)
    if locked & bundle:
        locked |= bundle
    for key in locked:
        if original[key] != incoming[key]:
            conflicts.append(
                f"{original.get('paper_id', original.get('relation_id'))}.{key}: locked value preserved"
            )
            incoming[key] = original[key]
    incoming["locked_fields"] = sorted(set(previous.locked_fields + incoming["locked_fields"]))


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
                topic.entries.append(
                    Entry(
                        paper_id=work.paper_id,
                        group=topic.groups[0].id,
                        inspection=Inspection(version_id=work.representative_version_id),
                    )
                )
                accepted.append(
                    {
                        "paper_id": work.paper_id,
                        "reason": "利用者がこのテーマの種文献として指定。内容と関連性は要確認。",
                    }
                )
    if accepted:
        existing_path = private / topic.topic_id / "adoptions.json"
        import json

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
    packet = research_packet(topic, snapshot)
    instruction = f"""# 調査メモ：{topic.title}

テーマの問い：{topic.question}

このテーマの文献を比較表と関係図に整理します。調査方法や利用するAI・検索・プラグインは自由です。情報が揃った部分から反映し、誤りや不足は随時修正します。

補助ファイル：`packet.generated.yaml` は現在のデータ、`packet.yaml` は編集用コピーです。既存の編集用コピーは上書きしません。検索を行った場合の候補は `candidates.json`、取得応答は作業領域の `responses/` にあります。

正本の `data/works.jsonl` と `topics/*/topic.yaml` を直接編集して `lgm render` で反映できます。コピーを使う場合は `lgm --repo <対象repo> import <packet.yaml>`。入力形式の詳細は `docs/USAGE.md` と `lgm schema --output schemas` を参照してください。
"""
    files = {
        target / "packet.generated.yaml": yaml_text(packet),
        target / "RESEARCH_REQUEST.md": instruction,
        target / "search-report.json": json_text(events),
    }
    if not (target / "packet.yaml").exists():
        files[target / "packet.yaml"] = yaml_text(packet)
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
            # Crossref refresh does not change evidence/version identifiers already assigned by a researcher.
            incoming.versions[0].version_id = work.version().version_id
            incoming.representative_version_id = work.version().version_id
            snapshot.works[work.paper_id] = merge_work(
                work, incoming, conflicts, metadata_only=True
            )
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
    papers = {paper for topic in topics.values() for paper in referenced_papers(topic)}
    result = Snapshot(
        works={key: snapshot.works[key] for key in sorted(papers)},
        topics=topics,
        paths={key: snapshot.paths[key] for key in topics},
    )
    result.validate()
    return result


def export_snapshot(repo: Path, snapshot: Snapshot, destination: Path) -> int:
    issues = check_rendered(repo, snapshot)
    if issues:
        raise MapError("; ".join(issues))
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
    # Rebuild navigational regions against the selected public snapshot, preserving manual prose.
    for path, text in rendered_files(repo, public).items():
        files[destination / path.relative_to(repo)] = (
            index_page(public) if path == repo / "README.md" else text
        )
    files[destination / "COPYRIGHT.md"] = COPYRIGHT
    if license_path.is_file():
        files[destination / "LICENSE"] = license_path.read_text(encoding="utf-8")
    for path, text in files.items():
        problems = publication_issues(text)
        if problems:
            raise MapError(
                f"publication check failed ({path.relative_to(destination)}): {', '.join(problems)}"
            )
    write_files(destination, files)
    return len(files)
