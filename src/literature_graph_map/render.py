"""Build the public HTML site from the canonical literature data."""

import os
import shutil
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .models import PAPER_CITATION, RELATION_LABELS, Entry, Relation, Topic, Work
from .storage import Snapshot, inside, write_files

DISCLAIMER = "この文献マップには誤りや抜けが含まれる可能性があります。気づいた点をご指摘いただければ、その都度修正します。"
KIND_LABELS = {
    "published": "出版版",
    "accepted": "著者最終稿",
    "submitted": "プレプリント",
    "unknown": "版未確認",
}
SUMMARY_LABELS = {"question": "問い", "method": "方法", "contribution": "判明点"}
WEB = Path(__file__).with_name("web")
TEMPLATES = Environment(
    loader=FileSystemLoader(WEB),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def link(label: object, url: str) -> Markup:
    return Markup('<a href="{}">{}</a>').format(url, label)


def relative_url(source: Path, target: Path) -> str:
    return quote(Path(os.path.relpath(target, source)).as_posix(), safe="/.-_")


def access_cell(work: Work) -> Markup | str:
    locations = sorted(
        (
            (version, location)
            for version in work.versions
            for location in version.locations
            if location.access_status == "free"
        ),
        key=lambda pair: (list(KIND_LABELS).index(pair[0].kind), pair[1].url),
    )
    if locations:
        version, location = locations[0]
        if version.kind == "published":
            label = (
                "出版版OA"
                if location.license_id and location.license_url
                else "出版版無料・ライセンス未確認"
            )
        else:
            label = {
                "accepted": "著者最終稿公開",
                "submitted": "プレプリントのみ確認",
                "unknown": "公開版あり・版未確認",
            }[version.kind]
        return link(label, location.url)
    return "無料版未検出" if work.access_check == "not_found" else "未確認"


def preprint_cell(work: Work) -> Markup | str:
    if work.preprint_check == "uncertain":
        return "対応未確定"
    records = [
        (version, location)
        for version in work.versions
        for location in version.locations
        if version.repository_id and version.kind in {"submitted", "accepted"}
    ]
    if records:
        version, location = sorted(
            records, key=lambda pair: (pair[0].kind != "submitted", pair[1].url)
        )[0]
        label = (
            "あり（プレプリント）" if version.kind == "submitted" else "公開記録あり（著者最終稿）"
        )
        return link(label, location.url)
    return "未検出" if work.preprint_check == "not_found" else "未確認"


def inspection_label(entry: Entry, work: Work) -> str:
    if entry.inspection.level == "metadata_only":
        status = ""
    elif entry.inspection.version_id is None:
        status = {
            "abstract": "要旨確認",
            "preprint": "プレプリント参照",
            "full_text": "本文確認",
        }[entry.inspection.level] + "（参照版未記録）"
    else:
        kind = work.version(entry.inspection.version_id).kind
        if entry.inspection.level == "abstract":
            status = f"要旨確認（{KIND_LABELS[kind]}）"
        elif kind == "submitted":
            status = "プレプリント参照"
        else:
            status = f"本文確認（{KIND_LABELS[kind]}）"
    if status and entry.inspection.recheck:
        status += "・旧版に基づく記述"
    return status


def summary_block(entry: Entry, work: Work) -> Markup:
    return Markup(
        TEMPLATES.get_template("summary.html").render(
            entry=entry,
            status=inspection_label(entry, work),
            labels=SUMMARY_LABELS,
        )
    )


def paper_groups(topic: Topic, works: dict[str, Work]) -> list[dict]:
    groups = []
    for group in topic.groups:
        entries = sorted(
            (e for e in topic.entries if e.group == group.id),
            key=lambda e: (
                works[e.paper_id].version().year or 9999,
                (works[e.paper_id].authors or [""])[0],
                e.paper_id,
            ),
        )
        if entries:
            groups.append({"id": group.id, "title": group.title, "entries": entries})
    return groups


def authors_label(work: Work) -> str:
    return (
        "、".join(work.authors) if len(work.authors) <= 3 else f"{work.authors[0]} et al."
    ) or "未確認"


def title_url(work: Work) -> str:
    return (
        f"https://doi.org/{quote(work.version().doi, safe='/')}"
        if work.version().doi
        else work.record_url
    )


def citation_labels(works: dict[str, Work]) -> dict[str, str]:
    """Use the same author/year labels across all themes in the library."""
    groups = defaultdict(list)
    for paper_id, work in sorted(works.items()):
        author = (work.authors or ["著者未確認"])[0]
        name = work.citation_author or (
            author.split(",", 1)[0].strip() if "," in author else author.split()[-1]
        )
        groups[f"{name} {work.version().year or '年未確認'}"].append(paper_id)
    return {
        paper_id: f"{label}-{index}" if len(papers) > 1 else label
        for label, papers in groups.items()
        for index, paper_id in enumerate(papers, 1)
    }


def relation_label(relation: Relation) -> str:
    label = relation.graph_label or f"{relation.aspect}：{RELATION_LABELS[relation.type]}"
    return label + {"candidate": "（仮）", "recheck": "（見直し予定）"}.get(relation.state, "")


def review_paragraph(text: str, citations: dict[str, str]) -> Markup:
    return Markup("").join(
        link(citations[part], f"#{part}") if index % 2 else part
        for index, part in enumerate(PAPER_CITATION.split(text))
    )


def mermaid_label(value: str) -> str:
    return "".join(f"#{ord(c)};" if c in '#"&<>|`[]{}\\' else c for c in " ".join(value.split()))


def graph_batches(topic: Topic) -> list[tuple[str, list[str], list[Relation]]]:
    pending = {
        r.relation_id: r
        for r in sorted(topic.relations, key=lambda r: r.relation_id)
        if r.state != "rejected"
    }
    batches = []
    seen_nodes = set()
    preferences = [("概観", topic.view.overview_nodes)] if topic.view.overview_nodes else []
    preferences += [(g.title, g.nodes) for g in topic.view.graphs]
    preferences += [
        (g.title, [e.paper_id for e in topic.entries if e.group == g.id]) for g in topic.groups
    ]
    preferences += [("分類をまたぐ関係", [e.paper_id for e in topic.entries])]
    for title, preferred in preferences:
        nodes = set()
        edges = []
        for rid, relation in list(pending.items()):
            pair = {relation.source, relation.target}
            if not pair <= set(preferred):
                continue
            if edges and (
                len(nodes | pair) > topic.view.graph_nodes or len(edges) >= topic.view.graph_edges
            ):
                batches.append((title, sorted(nodes), edges))
                seen_nodes.update(nodes)
                nodes, edges = set(), []
            nodes.update(pair)
            edges.append(relation)
            del pending[rid]
        if nodes:
            batches.append((title, sorted(nodes), edges))
            seen_nodes.update(nodes)
    for group in topic.groups:
        remaining = sorted(
            e.paper_id
            for e in topic.entries
            if e.group == group.id and e.paper_id not in seen_nodes
        )
        for start in range(0, len(remaining), topic.view.graph_nodes):
            batches.append(
                (
                    group.title + "（関係未登録）",
                    remaining[start : start + topic.view.graph_nodes],
                    [],
                )
            )
    return batches


def graph_source(
    nodes: list[str], edges: list[Relation], topic: Topic, citations: dict[str, str]
) -> str:
    entries = {entry.paper_id: entry for entry in topic.entries}
    lines = ["flowchart LR"]
    for node in nodes:
        label = mermaid_label(citations[node]) + "<br/>" + mermaid_label(entries[node].role)
        lines.append(f'    n{node}["{label}"]:::paper_{node}')
    for relation in edges:
        if relation.basis == "explicit":
            arrow = "---" if relation.type == "compares_with" else "-->"
        else:
            arrow = "-.-" if relation.type == "compares_with" else "-.->"
        label = mermaid_label(relation_label(relation))
        lines.append(f'    n{relation.source} {arrow}|"{label}"| n{relation.target}')
    return "\n".join(lines)


def page_context(snapshot: Snapshot, path: Path) -> dict:
    return {
        "home_url": relative_url(path, Path("index.html")),
        "asset_url": relative_url(path, Path("assets")),
        "copyright_url": relative_url(path, Path("copyright.html")),
        "disclaimer": DISCLAIMER,
        "topic_links": [
            {
                "title": topic.title,
                "url": relative_url(path, snapshot.paths[key] / "index.html"),
                "count": len(topic.entries),
                "question": topic.question,
            }
            for key, topic in sorted(snapshot.topics.items())
            if topic.public
        ],
    }


def topic_page(topic: Topic, snapshot: Snapshot) -> str:
    path = snapshot.paths[topic.topic_id]
    citations = citation_labels(snapshot.works)
    nav = topic.navigation
    navigation = []
    for label, keys in (
        ("親テーマ", [nav.parent] if nav.parent else []),
        (
            "子テーマ",
            sorted(k for k, t in snapshot.topics.items() if t.navigation.parent == topic.topic_id),
        ),
        ("関連テーマ", nav.related),
    ):
        for key in keys:
            if snapshot.topics[key].public:
                navigation.append(
                    {
                        "label": label,
                        "title": snapshot.topics[key].title,
                        "url": relative_url(path, snapshot.paths[key] / "index.html"),
                    }
                )
    return TEMPLATES.get_template("topic.html").render(
        **page_context(snapshot, path),
        title=topic.title,
        topic=topic,
        groups=paper_groups(topic, snapshot.works),
        works=snapshot.works,
        citations=citations,
        graphs=[
            {"title": title, "source": graph_source(nodes, edges, topic, citations)}
            for title, nodes, edges in graph_batches(topic)
        ],
        navigation=navigation,
    )


def index_page(snapshot: Snapshot) -> str:
    return TEMPLATES.get_template("index.html").render(
        **page_context(snapshot, Path(".")),
        title="テーマ別文献マップ",
    )


COPYRIGHT = """# 原著と公開コンテンツの権利境界

このリポジトリには、書誌情報、原著へのリンク、独自の比較・分類・関係図を掲載します。参照先論文、Abstract、本文、図表、PDFの権利は各権利者に帰属します。

LICENSEは管理者が自ら許諾できる自作部分にのみ適用され、参照先の論文や第三者素材には適用されません。無料で読めることと、再配布・改変の許諾は別です。
"""


TEMPLATES.globals.update(
    access=access_cell,
    preprint=preprint_cell,
    summary=summary_block,
    authors=authors_label,
    title_url=title_url,
    review_paragraph=review_paragraph,
)


def rendered_files(repo: Path, snapshot: Snapshot) -> dict[Path, str]:
    snapshot.validate()
    output = inside(repo, repo / "_site")
    files = {
        output / "index.html": index_page(snapshot),
        output / "copyright.html": TEMPLATES.get_template("copyright.html").render(
            **page_context(snapshot, Path(".")),
            title="著作権について",
            paragraphs=COPYRIGHT.split("\n\n")[1:],
        ),
        **{
            output / snapshot.paths[key] / "index.html": topic_page(topic, snapshot)
            for key, topic in sorted(snapshot.topics.items())
            if topic.public
        },
        **{
            output / "assets" / name: (WEB / name).read_text(encoding="utf-8")
            for name in ("site.css", "site.js")
        },
        output / ".nojekyll": "",
    }
    for path in files:
        inside(output, path)
    return files


def render(repo: Path, snapshot: Snapshot) -> None:
    files = rendered_files(repo, snapshot)
    # _site is exclusively generated output; remove pages of deleted/moved topics too.
    output = inside(repo, repo / "_site")
    if output.exists():
        shutil.rmtree(output)
    write_files(repo, files)
