"""Command-line entry point. External research is an explicit, bounded operation."""

import argparse
import sys
from datetime import date
from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import ImportPacket, Topic, Work
from .operations import (
    add_seeds,
    commit,
    discover,
    export_snapshot,
    import_packet,
    new_topic,
    public_snapshot,
    refresh,
    research_handoff,
)
from .providers import Crossref, Settings, settings
from .render import render, rendered_files
from .storage import (
    MapError,
    inside,
    json_text,
    load,
    private_directory,
    publication_files,
    publication_issues,
    read_yaml,
    write_files,
    yaml_text,
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="研究の概観と文献一覧のHTMLサイトを生成します。")
    root.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="公開する文献マップのリポジトリ（既定: 現在のディレクトリ）",
    )
    root.add_argument("--private-dir", type=Path, help="repo外の非公開作業ディレクトリ")
    commands = root.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="空の文献マップを作成")
    init.add_argument("--license", type=Path, help="管理者が選んだライセンス文書")
    survey = commands.add_parser("survey", help="テーマの草稿と調査用の補助ファイルを作成")
    survey.add_argument("theme")
    survey.add_argument("--id")
    survey.add_argument("--parent")
    survey.add_argument(
        "--seed",
        action="append",
        default=[],
        help="DOI、doi.org URL、BibTeX/RIS/Markdown/PDFのファイル",
    )
    survey.add_argument(
        "--query", action="append", default=[], help="検索語（英語等）。複数回指定可能"
    )
    survey.add_argument("--offline", action="store_true", help="通信せず調査依頼を作成")
    add = commands.add_parser("add", help="種文献を同定しテーマに追加")
    add.add_argument("topic_id")
    add.add_argument("seeds", nargs="+")
    update = commands.add_parser("update", help="既存書誌の更新と新規候補の探索")
    update.add_argument("topic_id")
    update.add_argument("--query", action="append", default=[])
    update.add_argument(
        "--since", type=date.fromisoformat, help="新規候補の出版日フィルタ YYYY-MM-DD"
    )
    ingest = commands.add_parser("import", help="文献・テーマのデータを取り込み")
    ingest.add_argument("packet", type=Path)
    ingest.add_argument("--path", help="新規テーマの配置先（例: topics/dust/charging）")
    commands.add_parser("render", help="通信なしで正本から_site/のHTMLを再生成")
    check = commands.add_parser("check", help="データ形式と参照を検証")
    check.add_argument(
        "--public", action="store_true", help="公開対象フィールドと生成内容の漏えい検査も行う"
    )
    export = commands.add_parser(
        "export", help="許可したフィールドだけを新しい公開スナップショットへ出力"
    )
    export.add_argument("destination", type=Path)
    schema = commands.add_parser("schema", help="JSON Schemaを出力")
    schema.add_argument("--output", type=Path, default=Path("schemas"))
    config = commands.add_parser("config", help="一度設定した探索上限をrepo外に保存")
    config.add_argument("--max-candidates", type=int)
    config.add_argument("--max-search-calls", type=int)
    config.add_argument("--timeout-seconds", type=int)
    config.add_argument("--mailto", help="Crossref polite pool用連絡先（非公開設定）")
    return root


def run(args: argparse.Namespace) -> int:
    if args.command == "schema":
        output = args.output.resolve()
        write_files(
            output,
            {
                output / f"{name}.schema.json": json_text(model.model_json_schema())
                for name, model in (("work", Work), ("topic", Topic), ("import", ImportPacket))
            },
        )
        print(f"JSON Schemaを生成: {output}")
        return 0
    repo = args.repo.resolve()
    private = private_directory(repo, args.private_dir)
    if args.command == "config":
        data = settings(private).model_dump()
        for key in Settings.model_fields:
            value = getattr(args, key, None)
            if value is not None:
                data[key] = value
        config = Settings.model_validate(data)
        write_files(private, {private / "settings.yaml": yaml_text(config)})
        print(f"探索設定を保存: {private / 'settings.yaml'}")
        return 0
    snapshot = load(repo)
    if args.command == "init":
        license_text = args.license.read_text(encoding="utf-8-sig") if args.license else None
        if license_text is not None:
            license_path = inside(repo, repo / "LICENSE")
            if license_path.exists() and license_path.read_text(encoding="utf-8") != license_text:
                raise MapError("LICENSE already exists; edit it explicitly to change the license")
        commit(repo, snapshot)
        if license_text is not None:
            write_files(repo, {repo / "LICENSE": license_text})
        print(f"初期化: {repo / 'data/works.jsonl'}")
    elif args.command == "render":
        render(repo, snapshot)
        print(f"HTMLサイトを生成: {repo / '_site/index.html'}")
    elif args.command == "check":
        issues = []
        if args.public:
            issues.extend(publication_files(repo))
            public = public_snapshot(snapshot)
            if set(public.topics) != set(snapshot.topics):
                issues.append(
                    "private topics are present in the publication repository; move them outside it"
                )
            if set(public.works) != set(snapshot.works):
                issues.append("unreferenced works are present in the public ledger")
            files = list({**public.source_files(repo), **rendered_files(repo, public)}.items())
            # Include original YAML comments and hand-written public prose.
            paths = list((repo / "topics").rglob("README.md"))
            paths += list((repo / "topics").rglob("topic.yaml"))
            paths += [repo / "data/works.jsonl", repo / "COPYRIGHT.md", repo / "LICENSE"]
            for path in paths:
                inside(repo, path)
                if path.is_file():
                    files.append((path, path.read_text(encoding="utf-8")))
            for path, text in files:
                issues.extend(
                    f"{path.relative_to(repo)}: {issue}" for issue in publication_issues(text)
                )
        if issues:
            raise MapError("\n".join(dict.fromkeys(issues)))
        print(f"検証OK: {len(snapshot.works)}文献 / {len(snapshot.topics)}テーマ")
    elif args.command == "import":
        packet = ImportPacket.model_validate(read_yaml(args.packet))
        conflicts = import_packet(repo, snapshot, packet, private, args.path)
        print(
            f"調査データを取り込み: {packet.topic.topic_id}"
            if packet.topic.public
            else f"非公開草稿をrepo外へ保存: {private / packet.topic.topic_id / 'review-packet.yaml'}"
        )
        if conflicts:
            print(
                f"固定項目を維持しました。再確認事項{len(conflicts)}件: {private / 'import-report.json'}"
            )
    elif args.command == "export":
        count = export_snapshot(repo, snapshot, args.destination)
        print(
            f"公開用スナップショットを出力: {args.destination.resolve()}（{count}ファイル）。pushは行っていません。"
        )
    else:
        config = settings(private)
        provider = Crossref(private, config)
        try:
            if args.command == "survey":
                if args.offline and args.seed:
                    raise MapError(
                        "--offline cannot resolve new seeds; import a prepared packet instead"
                    )
                topic = new_topic(snapshot, args.theme, args.id, args.parent)
                limitations = []
                if not args.offline:
                    limitations += add_seeds(snapshot, topic, args.seed, provider, private)
                    limitations += discover(topic, provider, args.query or [args.theme])
                else:
                    limitations = ["オフライン草稿。検索・採否・内容確認は未実行。"]
            else:
                if args.topic_id not in snapshot.topics:
                    raise MapError(f"unknown topic: {args.topic_id}")
                topic = snapshot.topics[args.topic_id]
                if args.command == "add":
                    before = len(topic.entries)
                    limitations = add_seeds(snapshot, topic, args.seeds, provider, private)
                    topic.survey.changes = (
                        f"文献追加{len(topic.entries) - before}件。新規文献の内容と関係は未確認。"
                    )
                else:
                    limitations = refresh(snapshot, topic, provider)
                    limitations += discover(
                        topic,
                        provider,
                        args.query or topic.survey.queries or [topic.question],
                        str(args.since) if args.since else None,
                    )
                    topic.survey.changes = (
                        "書誌更新と候補探索。OA・新規版の確認は調査データで補完。"
                    )
            topic.survey.limitations = list(dict.fromkeys(topic.survey.limitations + limitations))
            topic.survey.publication_status = "draft"
            topic.survey.reviewed_at = None
            commit(repo, snapshot)
            request = research_handoff(private, topic, snapshot, provider.events)
            print(f"草稿: {repo / snapshot.paths[topic.topic_id] / 'topic.yaml'}")
            print(f"調査メモ: {request}")
            print(
                f"補足: {len(topic.survey.limitations)}件。正本の編集またはimportで内容を更新できます。"
            )
        finally:
            provider.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        return run(args)
    except ValidationError as exc:
        # Never print rejected field values: they can contain the secret being rejected.
        errors = "; ".join(
            ".".join(str(part) for part in e["loc"]) + ": " + e["msg"]
            for e in exc.errors(include_input=False, include_url=False)
        )
        print("検証エラー: " + errors, file=sys.stderr)
    except (MapError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
    return 1
