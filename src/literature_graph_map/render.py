"""Deterministic, escaped Markdown and evidence-preserving Mermaid rendering."""

import html
import os
import re
from pathlib import Path
from urllib.parse import quote

from .models import RELATION_LABELS, Entry, Relation, Topic, Work
from .storage import MapError, Snapshot, inside, write_files

REGION = re.compile(
    r"<!-- BEGIN GENERATED: ([a-z-]+) -->\n(.*?)<!-- END GENERATED: \1 -->",
    re.S,
)

DISCLAIMER = "この文献マップには誤りや抜けが含まれる可能性があります。気づいた点をご指摘いただければ、その都度修正します。"


def plain(value: object) -> str:
    text = " ".join(str(value).split())
    text = html.escape(text, quote=True)
    for char in "|[]`*_\\{}!":
        text = text.replace(char, f"&#{ord(char)};")
    return text


def link(label: object, url: str) -> str:
    return f"[{plain(label)}](<{quote(url, safe='/:?&=%+~@#.-_')}>)"


def relative_link(label: str, source: Path, target: Path) -> str:
    return link(label, Path(os.path.relpath(target, source)).as_posix())


def region(name: str, body: str) -> str:
    body = body.rstrip() + "\n"
    return f"<!-- BEGIN GENERATED: {name} -->\n{body}<!-- END GENERATED: {name} -->"


def read_regions(text: str) -> dict[str, str]:
    result = {}
    for match in REGION.finditer(text):
        name = match.group(1)
        if name in result:
            raise MapError(f"duplicate generated region: {name}")
        result[name] = match.group(0)
    if text.count("<!-- BEGIN GENERATED:") != len(result) or text.count(
        "<!-- END GENERATED:"
    ) != len(result):
        raise MapError("README has missing, duplicate, or damaged generated-region markers")
    return result


def merge_page(existing: str | None, fresh: str) -> str:
    if existing is None:
        return fresh
    old_regions = read_regions(existing)
    new_regions = read_regions(fresh)
    if old_regions.keys() != new_regions.keys():
        raise MapError(
            "README generated regions are missing; preserve the file and reconcile it with YAML"
        )
    return REGION.sub(lambda match: new_regions[match.group(1)], existing)


KIND_LABELS = {
    "published": "出版版",
    "accepted": "著者最終稿",
    "submitted": "プレプリント",
    "unknown": "版未確認",
}


def access_cell(work: Work) -> str:
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
        suffix = "（API情報）" if location.verification_method == "api" else ""
        return link(label, location.url) + suffix
    return "無料版未検出" if work.access_check == "not_found" else "未確認"


def preprint_cell(work: Work) -> str:
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
        return link(label, location.url) + (
            "（API情報）" if location.verification_method == "api" else ""
        )
    return "未検出" if work.preprint_check == "not_found" else "未確認"


def evidence_label(evidence, work: Work) -> str:
    parts = [
        evidence.paper_id,
        KIND_LABELS[work.version(evidence.version_id).kind],
        evidence.version_id,
    ]
    if evidence.locator:
        parts.append(evidence.locator)
    if evidence.checked_at:
        parts.append(str(evidence.checked_at))
    label = " / ".join(parts)
    return link(label, evidence.url)


def summary_cell(entry: Entry, work: Work) -> str:
    if entry.summary is None:
        return "内容未確認"
    labels = {"question": "問い", "method": "方法", "contribution": "判明点・適用範囲"}
    items = []
    for key, label in labels.items():
        refs = "・".join(
            link(e.locator or "参考", e.url) for e in getattr(entry.evidence_by_item, key)
        )
        items.append(
            f"{label}：{plain(getattr(entry.summary, key))}" + (f"（{refs}）" if refs else "")
        )
    if entry.inspection.level == "metadata_only":
        return "<br>".join(items)
    if entry.inspection.version_id is None:
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
    if entry.inspection.recheck:
        status += "・旧版に基づく記述"
    return "<br>".join(items) + f"<br>〔{status}〕"


TABLE_HEADER = "| ID | タイトル | 著者 | 年 | 掲載誌／出版社 | OA・無料公開 | Preprint | 3項目要点 |\n|---|---|---|---|---|---|---|---|"


def paper_tables(topic: Topic, works: dict[str, Work]) -> str:
    parts = []
    for group in topic.groups:
        entries = sorted(
            (e for e in topic.entries if e.group == group.id),
            key=lambda e: (
                works[e.paper_id].version().year or 9999,
                (works[e.paper_id].authors or [""])[0],
                e.paper_id,
            ),
        )
        for offset in range(0, len(entries), topic.view.table_rows):
            suffix = (
                f"（{offset // topic.view.table_rows + 1}）"
                if len(entries) > topic.view.table_rows
                else ""
            )
            rows = [f"### {plain(group.title)}{suffix}", "", TABLE_HEADER]
            for entry in entries[offset : offset + topic.view.table_rows]:
                work = works[entry.paper_id]
                version = work.version()
                authors = (
                    "、".join(work.authors)
                    if len(work.authors) <= 3
                    else f"{work.authors[0]} et al."
                )
                title_url = (
                    f"https://doi.org/{quote(version.doi, safe='/')}"
                    if version.doi
                    else work.record_url
                )
                title = link(work.title, title_url)
                if version.kind == "submitted":
                    title += (
                        "<br>〔プレプリント・未査読〕"
                        if version.status == "preprint"
                        else "<br>〔査読状態未確認〕"
                    )
                cells = [
                    entry.paper_id,
                    title,
                    plain(authors or "未確認"),
                    str(version.year or "未確認"),
                    plain(version.venue or "未確認")
                    + "<br>"
                    + plain(version.publisher or "未確認"),
                    access_cell(work),
                    preprint_cell(work),
                    summary_cell(entry, work),
                ]
                rows.append("| " + " | ".join(cells) + " |")
            parts.append("\n".join(rows))
    return "\n\n".join(parts) if parts else TABLE_HEADER + "\n\n採用文献はまだありません。"


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


def relation_graphs(topic: Topic, works: dict[str, Work]) -> str:
    entries = {e.paper_id: e for e in topic.entries}
    parts = []
    for index, (title, nodes, edges) in enumerate(graph_batches(topic), 1):
        lines = [f"### {plain(title)} · {index}", "", "```mermaid", "flowchart LR"]
        for node in nodes:
            work = works[node]
            author = (work.authors or ["著者未確認"])[0]
            label = f"{node}・{author}・{work.version().year or '年未確認'}・{entries[node].role}"
            lines.append(f'    n{node}["{mermaid_label(label)}"]')
        for relation in edges:
            if relation.basis == "explicit":
                arrow = "---" if relation.type == "compares_with" else "-->"
            else:
                arrow = "-.-" if relation.type == "compares_with" else "-.->"
            status = {"candidate": "・仮", "recheck": "・見直し予定"}.get(relation.state, "")
            label = f"{relation.relation_id} {RELATION_LABELS[relation.type]}{status}"
            lines.append(f'    n{relation.source} {arrow}|"{label}"| n{relation.target}')
        lines.append("```")
        parts.append("\n".join(lines))
    if not any(r.state != "rejected" for r in topic.relations):
        parts.insert(0, "関係はまだ登録されていません。")
    parts.append(
        "図に未掲載の文献：該当なし。"
        if topic.entries
        else "図に掲載する採用文献はまだありません。"
    )
    return "\n\n".join(parts)


def relation_evidence(topic: Topic, works: dict[str, Work]) -> str:
    rows = [
        "| 関係ID | 論文間の関係 | このように整理した理由 | 参考情報・参照版 | 区分 |",
        "|---|---|---|---|---|",
    ]
    for r in sorted(topic.relations, key=lambda r: r.relation_id):
        if r.state == "rejected":
            continue
        direction = "—" if r.type == "compares_with" else "→"
        reason = plain(r.aspect) + "：" + plain(r.reason)
        if r.comparability:
            reason += (
                "<br>比較条件："
                + plain(r.comparability.conditions)
                + "<br>条件差："
                + plain(r.comparability.differences)
            )
        if r.limitation:
            reason += "<br>限定：" + plain(r.limitation)
        evidence = "<br>".join(evidence_label(e, works[e.paper_id]) for e in r.evidence) or "未記録"
        basis = "文献中の言及" if r.basis == "explicit" else "本マップの比較整理"
        basis += {"candidate": "<br>仮の整理", "recheck": "<br>見直し予定"}.get(r.state, "")
        if r.checked_by:
            basis += f"<br>{'AI' if r.checked_by == 'ai' else '人間'}確認"
        if r.checked_at:
            basis += f"・{r.checked_at}"
        rows.append(
            f"| {r.relation_id} | {r.source} {direction} {r.target}：{RELATION_LABELS[r.type]} | {reason} | {evidence} | {basis} |"
        )
    return "\n".join(rows) if len(rows) > 2 else "関係はまだ登録されていません。"


def topic_page(topic: Topic, snapshot: Snapshot) -> str:
    path = snapshot.paths[topic.topic_id]
    header = f"# {plain(topic.title)}\n\n" + relative_link("全体索引", path, Path("README.md"))
    if topic.navigation.parent:
        key = topic.navigation.parent
        header += " ／ " + relative_link(
            snapshot.topics[key].title, path, snapshot.paths[key] / "README.md"
        )
    survey = topic.survey
    status = (
        f"調査日：{survey.searched_at or '未記録'} ｜ 対象期間：{plain(survey.scope_period)} ｜ 採用文献：{len(topic.entries)}件  \n"
        f"\n{DISCLAIMER}"
    )
    scope = plain(topic.question)
    if topic.scope.include:
        scope += "\n対象：" + plain("、".join(topic.scope.include)) + "。"
    if topic.scope.exclude:
        scope += "\n除外：" + plain("、".join(topic.scope.exclude)) + "。"
    notes = (
        "検索経路："
        + plain("、".join(survey.provider_names) or "未記録")
        + "。検索語："
        + plain("、".join(survey.queries) or "未記録")
        + "  \n"
        + "採否方針："
        + plain("、".join(topic.scope.include) or "テーマの問いに関連する文献")
        + "。  \n"
        + "除外範囲："
        + plain("、".join(topic.scope.exclude) or "指定なし")
        + "。  \n"
        + "調査範囲："
        + plain(survey.coverage_note)
        + "  \n"
        + "未確認範囲："
        + plain("；".join(survey.limitations) or "記録なし")
        + "  \n"
        + "今回の更新："
        + plain(survey.changes)
    )
    navigation = []
    children = sorted(
        t.topic_id for t in snapshot.topics.values() if t.navigation.parent == topic.topic_id
    )
    for label, keys in (("子テーマ", children), ("関連テーマ", topic.navigation.related)):
        for key in keys:
            navigation.append(
                f"- {label}："
                + relative_link(snapshot.topics[key].title, path, snapshot.paths[key] / "README.md")
            )
    reading = (
        "## 比較の読み方\n\n" + "\n".join("- " + plain(note) for note in topic.reading_notes)
        if topic.reading_notes
        else ""
    )
    parts = [
        region("topic-header", header),
        region("topic-scope", scope),
        region("survey-status", status),
        "## 先行研究比較表",
        "要点は「問い／方法／判明点・適用範囲」の3項目です。OA・無料公開欄には利用できるリンクを記載します。API由来の情報にはその旨を添えます。",
        region("paper-tables", paper_tables(topic, snapshot.works)),
        "## 論文間の関係図",
        "実線は文献中の言及、点線は本マップでの比較整理を表します。矢印は基礎・対象側から、それを拡張・利用・検証する側へ向きます。仮の関係には「仮」を添えます。",
        region("relation-graphs", relation_graphs(topic, snapshot.works)),
        "## 関係の説明・参考情報",
        region("relation-evidence", relation_evidence(topic, snapshot.works)),
        region("reading-notes", reading),
        "## 調査範囲と更新",
        region("survey-notes", notes),
        region(
            "navigation",
            "## 子テーマ・関連テーマ\n\n" + "\n".join(navigation) if navigation else "",
        ),
        "---\n\n原著は各文献のDOI・公開記録をご参照ください。比較表と関係図は独自の整理であり、原著の全文、Abstract、図表は再配布しません。",
    ]
    return "\n\n".join(parts) + "\n"


def index_page(snapshot: Snapshot) -> str:
    rows = []
    for key in sorted(snapshot.topics, key=lambda key: snapshot.paths[key].as_posix()):
        topic = snapshot.topics[key]
        depth, parent = 0, topic.navigation.parent
        while parent:
            depth += 1
            parent = snapshot.topics[parent].navigation.parent
        rows.append(
            "  " * depth
            + "- "
            + link(topic.title, (snapshot.paths[key] / "README.md").as_posix())
            + f"（{len(topic.entries)}件）"
        )
    return (
        "# テーマ別文献マップ\n\nテーマごとの比較表と関係図から、先行研究の違いやつながりをたどれます。\n\n"
        + region("topic-index", "\n".join(rows) or "テーマはまだありません。")
        + f"\n\n{DISCLAIMER}\n\n[原著と公開コンテンツの権利境界](COPYRIGHT.md)\n"
    )


COPYRIGHT = """# 原著と公開コンテンツの権利境界

このリポジトリには、書誌情報、原著へのリンク、独自の比較・分類・関係図を掲載します。参照先論文、Abstract、本文、図表、PDFの権利は各権利者に帰属します。

LICENSEは管理者が自ら許諾できる自作部分にのみ適用され、参照先の論文や第三者素材には適用されません。無料で読めることと、再配布・改変の許諾は別です。
"""


def rendered_files(repo: Path, snapshot: Snapshot, preserve: bool = True) -> dict[Path, str]:
    snapshot.validate()
    fresh = {
        repo / "README.md": index_page(snapshot),
        **{
            repo / snapshot.paths[key] / "README.md": topic_page(topic, snapshot)
            for key, topic in sorted(snapshot.topics.items())
        },
    }
    result = {}
    for path, text in fresh.items():
        inside(repo, path)
        existing = path.read_text(encoding="utf-8") if preserve and path.exists() else None
        result[path] = merge_page(existing, text)
    return result


def render(repo: Path, snapshot: Snapshot) -> None:
    files = rendered_files(repo, snapshot)
    copyright_path = inside(repo, repo / "COPYRIGHT.md")
    if not copyright_path.exists():
        files[copyright_path] = COPYRIGHT
    write_files(repo, files)


def check_rendered(repo: Path, snapshot: Snapshot) -> list[str]:
    issues = []
    for path, expected in rendered_files(repo, snapshot).items():
        if not path.exists():
            issues.append(f"missing generated page: {path.relative_to(repo)}")
        elif path.read_text(encoding="utf-8") != expected:
            issues.append(f"stale generated page: {path.relative_to(repo)}; run render")
    return issues
