"""Bounded metadata acquisition. API responses and candidates remain private."""

import hashlib
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote

import httpx
from pydantic import Field, ValidationError

from .models import MetadataSource, Model, Version, Work, normalize_doi
from .storage import MapError, json_text, read_yaml, write_files


class Settings(Model):
    max_candidates: int = Field(default=30, ge=1, le=100)
    max_search_calls: int = Field(default=8, ge=0, le=100)
    timeout_seconds: int = Field(default=20, ge=1, le=60)
    mailto: str | None = None


def settings(private: Path) -> Settings:
    path = private / "settings.yaml"
    data = read_yaml(path) if path.exists() else {}
    data.pop("external_ai_text", None)  # Obsolete setting in earlier CLI versions.
    return Settings.model_validate(data)


class Crossref:
    def __init__(self, private: Path, config: Settings, client: httpx.Client | None = None):
        self.private = private
        self.config = config
        self.calls = 0
        self.owned_client = client is None
        self.client = client or httpx.Client(timeout=config.timeout_seconds)
        self.events = []

    def close(self) -> None:
        if self.owned_client:
            self.client.close()

    def request(self, path: str, params: dict | None = None) -> dict:
        if self.calls >= self.config.max_search_calls:
            self.events.append({"status": "budget", "route": path})
            raise MapError("Crossref: configured request limit reached")
        self.calls += 1
        params = dict(params or {})
        if self.config.mailto:
            params["mailto"] = self.config.mailto
        url = "https://api.crossref.org/" + path
        try:
            response = self.client.get(
                url, params=params, headers={"User-Agent": "literature-graph-map/0.1"}
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            label = (
                "rate_limited" if status == 429 else "not_found" if status == 404 else "http_error"
            )
            self.events.append({"status": label, "http_status": status, "route": path})
            raise MapError(f"Crossref: {label} (HTTP {status})") from None
        except (httpx.RequestError, ValueError):
            self.events.append({"status": "failed", "route": path})
            raise MapError("Crossref: network failure or invalid JSON response") from None
        if not isinstance(data, dict) or not isinstance(data.get("message"), dict):
            self.events.append({"status": "invalid_response", "route": path})
            raise MapError("Crossref: invalid metadata response")
        key = hashlib.sha256((url + repr(sorted(params.items()))).encode()).hexdigest()
        write_files(self.private, {self.private / "responses" / f"{key}.json": json_text(data)})
        self.events.append({"status": "ok", "route": path, "checked_at": date.today().isoformat()})
        return data["message"]

    def resolve(self, doi: str) -> dict:
        return self.request("works/" + quote(normalize_doi(doi), safe=""))

    def search(self, query: str, since: str | None = None) -> list[dict]:
        params = {"query.bibliographic": query, "rows": self.config.max_candidates}
        if since:
            params["filter"] = "from-pub-date:" + since
        data = self.request("works", params)
        if not isinstance(data.get("items"), list):
            raise MapError("Crossref: invalid search result")
        return data["items"][: self.config.max_candidates]


def text_without_markup(value: str) -> str:
    import html

    return " ".join(html.unescape(re.sub(r"<[^>]*>", "", value)).split())


def crossref_work(item: dict, paper_id: str) -> Work:
    """Project bibliographic fields only; never copy Abstract/link payloads."""
    try:
        doi = normalize_doi(item["DOI"])
        title = text_without_markup(item["title"][0])
        authors = [
            text_without_markup(
                a.get("name") or " ".join(filter(None, [a.get("given"), a.get("family")]))
            )
            for a in item.get("author", [])
        ]
        authors = [a for a in authors if a]
        date_parts = item.get("published-print", item.get("published", item.get("issued", {}))).get(
            "date-parts", [[]]
        )
        online = item.get("published-online", {}).get("date-parts", [[]])
        preprint = item.get("subtype") == "preprint"
        published = item.get("type") in {
            "journal-article",
            "proceedings-article",
            "book",
            "book-chapter",
            "monograph",
        }
        kind = "submitted" if preprint else "published" if published else "unknown"
        version = Version(
            version_id="V" + hashlib.sha256(doi.encode()).hexdigest()[:16],
            kind=kind,
            doi=doi,
            year=date_parts[0][0] if date_parts and date_parts[0] else None,
            online_year=online[0][0] if online and online[0] else None,
            venue=text_without_markup(item["container-title"][0])
            if item.get("container-title")
            else None,
            publisher=text_without_markup(item["publisher"]) if item.get("publisher") else None,
            status="preprint" if preprint else "published" if published else "unknown",
        )
        return Work(
            paper_id=paper_id,
            title=title,
            authors=authors,
            representative_version_id=version.version_id,
            versions=[version],
            record_url="https://doi.org/" + quote(doi, safe="/"),
            metadata_sources=[
                MetadataSource(
                    provider="Crossref",
                    url="https://api.crossref.org/works/" + quote(doi, safe=""),
                    checked_at=date.today(),
                )
            ],
            missing_note="Crossref書誌を参照。欠損書誌・無料公開・プレプリント対応は未確認。",
        )
    except (KeyError, IndexError, TypeError, ValueError, ValidationError):
        raise MapError("Crossref: record lacks valid bibliographic identity") from None


def seed_identifiers(value: str) -> list[str]:
    """DOIs in BibTeX, RIS, text, and user-provided PDFs are discovery hints only."""
    try:
        return [normalize_doi(value)]
    except ValueError:
        pass
    path = Path(value)
    if path.is_file():
        if path.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            from pypdf.errors import PyPdfError

            try:
                source = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
            except (PyPdfError, ValueError):
                raise MapError("PDF could not be read; supply a readable PDF or a DOI") from None
        elif path.suffix.lower() in {".bib", ".ris", ".txt", ".md"}:
            source = path.read_text(encoding="utf-8-sig")
        else:
            raise MapError("seed files must be BibTeX, RIS, Markdown, text, or PDF")
        identifiers = set()
        for match in re.findall(r"10\.\d{4,9}/[^\s<>\"{}]+", source):
            match = match.rstrip(".,;}>\"'")
            for opening, closing in (("(", ")"), ("[", "]")):
                while match.endswith(closing) and match.count(closing) > match.count(opening):
                    match = match[:-1]
            identifiers.add(normalize_doi(match))
        dois = sorted(identifiers)
        if not dois:
            raise MapError("no DOI found in seed file; use --query for title discovery")
        return dois
    raise MapError("seed is not a DOI/doi.org URL or supported file; use --query for titles")
