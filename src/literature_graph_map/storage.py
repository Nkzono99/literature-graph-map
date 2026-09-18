"""Filesystem boundaries, cross-record validation, and canonical serialization."""

import hashlib
import html
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

import yaml

from .models import Model, Topic, Work


class MapError(Exception):
    """A user-actionable data, publication, or operation error."""


def inside(root: Path, path: Path) -> Path:
    root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise MapError(f"path must stay inside the output directory: {path.name}")
    # Reject links even when their current target is inside the directory.
    cursor = path.absolute()
    while cursor != root and cursor != cursor.parent:
        if cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
            raise MapError("symlinks/junctions are not allowed in managed paths")
        cursor = cursor.parent
    return resolved


def private_directory(repo: Path, override: Path | None = None) -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
    suffix = hashlib.sha256(str(repo.resolve()).encode()).hexdigest()[:16]
    result = (override or base / "literature-graph-map" / suffix).resolve()
    root = repo.resolve()
    if result.is_relative_to(root) or root.is_relative_to(result):
        raise MapError("private work directory and repository must be separate directories")
    result.mkdir(parents=True, exist_ok=True)
    return result


def yaml_text(model: Model) -> str:
    return yaml.safe_dump(model.model_dump(mode="json"), allow_unicode=True, sort_keys=False)


def read_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise MapError(f"expected a YAML mapping: {path.name}")
    return data


def write_files(root: Path, files: dict[Path, str]) -> None:
    """Validate all targets and stage all bytes before replacing any managed file."""
    targets = {inside(root, path): content for path, content in files.items()}
    staged = []
    try:
        for path, text in targets.items():
            if path.exists() and path.read_text(encoding="utf-8") == text:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=path.parent,
                delete=False,
            ) as handle:
                handle.write(text)
                staged.append((Path(handle.name), path))
        for temp, path in staged:
            os.replace(temp, path)
    finally:
        for temp, _ in staged:
            temp.unlink(missing_ok=True)


@dataclass
class Snapshot:
    works: dict[str, Work] = field(default_factory=dict)
    topics: dict[str, Topic] = field(default_factory=dict)
    paths: dict[str, Path] = field(default_factory=dict)

    def validate(self) -> None:
        normalized_paths = [path.as_posix().casefold() for path in self.paths.values()]
        if len(set(normalized_paths)) != len(normalized_paths):
            raise MapError("topic paths must be unique")
        if any(path.is_absolute() or ".." in path.parts for path in self.paths.values()):
            raise MapError("topic paths must be normalized relative paths")
        seen_dois = {}
        seen_repositories = {}
        relation_signatures = {}
        for key, work in self.works.items():
            Work.model_validate(work.model_dump())
            if key != work.paper_id:
                raise MapError("work registry ID mismatch")
            for version in work.versions:
                for identifier, seen in (
                    (version.doi, seen_dois),
                    (version.repository_id, seen_repositories),
                ):
                    if identifier and identifier in seen:
                        raise MapError(
                            f"duplicate bibliographic identifier: {work.paper_id}, {seen[identifier]}"
                        )
                    if identifier:
                        seen[identifier] = work.paper_id
        for topic in self.topics.values():
            Topic.model_validate(topic.model_dump())
            nav = topic.navigation
            for target in ([nav.parent] if nav.parent else []) + nav.related:
                if target not in self.topics or target == topic.topic_id:
                    raise MapError(f"{topic.topic_id}: invalid navigation target {target}")
            ancestors = {topic.topic_id}
            parent = nav.parent
            while parent:
                if parent in ancestors:
                    raise MapError("topic parent cycle")
                ancestors.add(parent)
                parent = self.topics[parent].navigation.parent
            for entry in topic.entries:
                if entry.paper_id not in self.works:
                    raise MapError(f"{topic.topic_id}: unknown paper {entry.paper_id}")
                work = self.works[entry.paper_id]
                ids = {v.version_id for v in work.versions}
                if (
                    entry.inspection.version_id is not None
                    and entry.inspection.version_id not in ids
                ):
                    raise MapError(f"{entry.paper_id}: unknown inspection version")
                for evidence in entry.evidence_by_item.model_dump().values():
                    for item in evidence:
                        self.validate_evidence(item)
            for relation in topic.relations:
                signature = relation.model_dump(exclude={"locked_fields"})
                if (
                    relation.relation_id in relation_signatures
                    and relation_signatures[relation.relation_id] != signature
                ):
                    raise MapError(
                        f"{relation.relation_id}: relation ID has different meanings across topics"
                    )
                relation_signatures[relation.relation_id] = signature
                for evidence in relation.evidence:
                    self.validate_evidence(evidence.model_dump())

    def validate_evidence(self, evidence: dict) -> None:
        work = self.works.get(evidence["paper_id"])
        if not work or evidence["version_id"] not in {v.version_id for v in work.versions}:
            raise MapError("evidence references an unknown work/version")

    def source_files(self, repo: Path) -> dict[Path, str]:
        return {
            repo / "data" / "works.jsonl": "".join(
                self.works[key].model_dump_json() + "\n" for key in sorted(self.works)
            ),
            **{
                repo / self.paths[key] / "topic.yaml": yaml_text(topic)
                for key, topic in sorted(self.topics.items())
            },
        }


def load(repo: Path) -> Snapshot:
    snapshot = Snapshot()
    ledger = inside(repo, repo / "data" / "works.jsonl")
    if ledger.exists():
        for index, line in enumerate(ledger.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            work = Work.model_validate_json(line)
            if work.paper_id in snapshot.works:
                raise MapError(f"works.jsonl:{index}: duplicate paper ID")
            snapshot.works[work.paper_id] = work
    topics_root = inside(repo, repo / "topics")
    if topics_root.exists():
        for path in sorted(topics_root.rglob("topic.yaml")):
            inside(repo, path)
            topic = Topic.model_validate(read_yaml(path))
            if topic.topic_id in snapshot.topics:
                raise MapError(f"duplicate topic ID: {topic.topic_id}")
            snapshot.topics[topic.topic_id] = topic
            snapshot.paths[topic.topic_id] = path.parent.relative_to(repo.resolve())
    snapshot.validate()
    return snapshot


def next_paper_id(snapshot: Snapshot) -> str:
    return f"P{max((int(key[1:]) for key in snapshot.works), default=0) + 1:06d}"


FORBIDDEN_TEXT = [
    (r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,})", "credential"),
    (
        r"(?i)(?:api[_-]?key|secret|authorization|password)\s*[=:]\s*[^\s,}]{8,}",
        "secret assignment",
    ),
    (r"(?i)(?:(?<![a-z0-9])[a-z]:[\\/]|file://|/Users/|/home/|/tmp/|\\\\[a-z0-9])", "local path"),
]


def publication_issues(text: str) -> list[str]:
    readable = html.unescape(unquote(text))
    return [label for pattern, label in FORBIDDEN_TEXT if re.search(pattern, readable)]


def publication_files(repo: Path) -> list[str]:
    """Check managed publication directories, without scanning tools or test fixtures."""
    issues = []
    for name in ("data", "topics"):
        folder = inside(repo, repo / name)
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            inside(repo, path)
            if not path.is_file() or path.name == ".gitkeep":
                continue
            permitted = (
                (path == repo / "data" / "works.jsonl")
                if name == "data"
                else path.name in {"topic.yaml", "README.md"}
            )
            if not permitted:
                issues.append(f"unexpected file in publication data: {path.relative_to(repo)}")
    return issues


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"
