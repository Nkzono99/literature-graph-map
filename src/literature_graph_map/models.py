"""The public data contract. Unknown fields are errors, never silently published."""

import ipaddress
import re
from datetime import date
from typing import Annotated, Literal, NamedTuple, Self
from urllib.parse import unquote, urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def public_url(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or any(c.isspace() or ord(c) < 32 for c in value)
        or "\\" in value
        or host.lower() == "localhost"
        or host.lower().endswith((".local", ".localhost", ".internal"))
    ):
        raise ValueError("a public http(s) URL without credentials is required")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host:
            raise ValueError("a public hostname is required") from None
    else:
        if not address.is_global:
            raise ValueError("private network URLs cannot be published")
    return value


def normalize_doi(value: str) -> str:
    value = value.strip()
    if re.match(r"https?://(dx\.)?doi\.org/", value, re.I):
        value = unquote(urlsplit(value).path.lstrip("/"))
    value = re.sub(r"^doi:\s*", "", value, flags=re.I).lower()
    if not re.fullmatch(r"10\.\d{4,9}/[^\s]+", value):
        raise ValueError("expected a DOI or doi.org URL")
    return value


URL = Annotated[str, AfterValidator(public_url)]
DOI = Annotated[str, AfterValidator(normalize_doi)]
Text = Annotated[str, Field(min_length=1)]
PaperID = Annotated[str, Field(pattern=r"^P[0-9]{6,}$")]
PAPER_CITATION = re.compile(r"\[@(P[0-9]{6,})\]")
TOPIC_CITATION = re.compile(r"\[@topic:([a-z0-9]+(?:-[a-z0-9]+)*)\]")
VersionID = Annotated[str, Field(pattern=r"^V[A-Za-z0-9_-]+$")]
TopicID = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
Actor = Literal["ai", "human"]
Kind = Literal["published", "accepted", "submitted", "unknown"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MetadataSource(Model):
    provider: Text
    url: URL
    checked_at: date | None = None


class Location(Model):
    url: URL
    host: Text
    access_status: Literal["free", "closed", "unknown"] = "unknown"
    license_id: str | None = None
    license_url: URL | None = None
    checked_at: date | None = None
    source: str = ""
    verification_method: Literal["api", "public_record", "full_text", "unspecified"] = "unspecified"


class Version(Model):
    version_id: VersionID
    kind: Kind = "unknown"
    doi: DOI | None = None
    repository_id: str | None = None
    year: int | None = Field(default=None, ge=1500, le=2200)
    online_year: int | None = Field(default=None, ge=1500, le=2200)
    venue: str | None = None
    publisher: str | None = None
    status: Literal["published", "preprint", "accepted", "unknown"] = "unknown"
    locations: list[Location] = Field(default_factory=list)


class VersionLink(Model):
    source: VersionID
    target: VersionID
    evidence_url: URL | None = None
    checked_at: date | None = None


class Evidence(Model):
    paper_id: PaperID
    version_id: VersionID
    url: URL
    source_type: Literal["full_text", "abstract", "metadata", "review", "unspecified"] = (
        "unspecified"
    )
    locator: str = ""
    checked_at: date | None = None


class Summary(Model):
    question: Text
    method: Text
    contribution: Text


class ItemEvidence(Model):
    question: list[Evidence] = Field(default_factory=list)
    method: list[Evidence] = Field(default_factory=list)
    contribution: list[Evidence] = Field(default_factory=list)


class Inspection(Model):
    level: Literal["metadata_only", "abstract", "full_text", "preprint"] = "metadata_only"
    version_id: VersionID | None = None
    checked_by: Actor | None = None
    checked_at: date | None = None
    recheck: bool = False


class Work(Model):
    """Shared bibliography plus the default reading (summary, sources, inspection)."""

    paper_id: PaperID
    title: Text
    authors: list[Text]
    citation_author: Text | None = None
    representative_version_id: VersionID
    versions: list[Version] = Field(min_length=1)
    metadata_sources: list[MetadataSource] = Field(default_factory=list)
    record_url: URL
    access_check: Literal["not_checked", "not_found", "limited_not_found", "checked", "failed"] = (
        "not_checked"
    )
    preprint_check: Literal[
        "not_checked",
        "not_found",
        "limited_not_found",
        "found",
        "uncertain",
        "failed",
        "not_applicable",
    ] = "not_checked"
    version_links: list[VersionLink] = Field(default_factory=list)
    missing_note: str = "未取得の書誌項目は未確認。"
    summary: Summary | None = None
    evidence_by_item: ItemEvidence = Field(default_factory=ItemEvidence)
    inspection: Inspection = Field(default_factory=Inspection)
    locked_fields: list[
        Literal[
            "title",
            "authors",
            "citation_author",
            "representative_version_id",
            "versions",
            "record_url",
        ]
    ] = Field(default_factory=list)

    @model_validator(mode="after")
    def versions_are_consistent(self) -> Self:
        ids = [v.version_id for v in self.versions]
        if len(set(ids)) != len(ids) or self.representative_version_id not in ids:
            raise ValueError("duplicate version ID or missing representative version")
        identifiers = [v.doi for v in self.versions if v.doi]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("duplicate DOI within work")
        if self.preprint_check == "found" and not any(
            v.repository_id and v.kind in {"submitted", "accepted"} and v.locations
            for v in self.versions
        ):
            raise ValueError(
                "preprint_check=found requires an identified repository version and URL"
            )
        for link in self.version_links:
            if link.source not in ids or link.target not in ids or link.source == link.target:
                raise ValueError("version link must reference two distinct versions of this work")
        if self.inspection.version_id is not None and self.inspection.version_id not in ids:
            raise ValueError("inspection references an unknown version of this work")
        return self

    def version(self, version_id: str | None = None) -> Version:
        key = version_id or self.representative_version_id
        return next(v for v in self.versions if v.version_id == key)


class Entry(Model):
    """A work's place in one topic. Reading fields override the work's defaults when set."""

    paper_id: PaperID
    group: TopicID
    role: Text = "内容未確認"
    summary: Summary | None = None
    evidence_by_item: ItemEvidence | None = None
    inspection: Inspection | None = None


class Reading(NamedTuple):
    summary: Summary | None
    evidence_by_item: ItemEvidence
    inspection: Inspection


def reading(entry: Entry, work: Work) -> Reading:
    """The summary, sources, and inspection shown for an entry: its own, else the work's."""
    return Reading(
        entry.summary if entry.summary is not None else work.summary,
        entry.evidence_by_item if entry.evidence_by_item is not None else work.evidence_by_item,
        entry.inspection if entry.inspection is not None else work.inspection,
    )


class Scope(Model):
    include: list[Text] = Field(default_factory=list)
    exclude: list[Text] = Field(default_factory=list)


class Navigation(Model):
    parent: TopicID | None = None
    related: list[TopicID] = Field(default_factory=list)


class Group(Model):
    id: TopicID
    title: Text


class Survey(Model):
    searched_at: date | None = None
    scope_period: Text = "制限なし"
    provider_names: list[Text] = Field(default_factory=list)
    queries: list[Text] = Field(default_factory=list)
    coverage_note: Text = "未記録"
    limitations: list[Text] = Field(default_factory=list)
    changes: Text = "新規作成"
    publication_status: Literal["draft", "human_reviewed"] = "draft"
    reviewed_at: date | None = None


class ReviewSection(Model):
    heading: Text
    paragraphs: list[Text] = Field(min_length=1)


class Overview(Model):
    review: list[ReviewSection] = Field(default_factory=list)


class LineageStep(Model):
    paper_id: PaperID
    title: Text
    significance: Text
    connection: str = ""


class LineageTrack(Model):
    title: Text
    steps: list[LineageStep] = Field(min_length=1)

    @model_validator(mode="after")
    def connections(self) -> Self:
        if self.steps[0].connection or any(not step.connection for step in self.steps[1:]):
            raise ValueError("label the connection to each step after the first")
        return self


class Topic(Model):
    schema_version: Literal[1] = 1
    topic_id: TopicID
    title: Text
    question: Text
    review: list[ReviewSection] = Field(default_factory=list)
    lineage: list[LineageTrack] = Field(default_factory=list)
    public: bool = True
    scope: Scope = Field(default_factory=Scope)
    navigation: Navigation = Field(default_factory=Navigation)
    groups: list[Group] = Field(
        default_factory=lambda: [Group(id="general", title="先行研究")], min_length=1
    )
    entries: list[Entry] = Field(default_factory=list)
    survey: Survey = Field(default_factory=Survey)
    reading_notes: list[Text] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def references(self) -> Self:
        papers = [e.paper_id for e in self.entries]
        groups = [g.id for g in self.groups]
        if any(len(set(ids)) != len(ids) for ids in (papers, groups)):
            raise ValueError("duplicate paper or group ID in topic")
        if any(e.group not in groups for e in self.entries):
            raise ValueError("entry references an unknown group")
        milestones = [step.paper_id for track in self.lineage for step in track.steps]
        if len(set(milestones)) != len(milestones) or not set(milestones) <= set(papers):
            raise ValueError("lineage steps must reference distinct papers in the topic's list")
        for section in self.review:
            for paragraph in section.paragraphs:
                if not set(PAPER_CITATION.findall(paragraph)) <= set(papers):
                    raise ValueError("review citations must appear in the topic's paper list")
        return self
