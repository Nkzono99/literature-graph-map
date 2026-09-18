# このプロジェクトでの作業

このリポジトリ自体が、テーマ別の論文比較表と関係図を公開する文献マップです。文献を探し、研究の違いやつながりを把握できることを目指します。誤りや不足は、気づいた時点で修正して育てます。

調査方法はタスクに応じて選べます。AIの知識・推論、検索、外部プラグイン、手作業を利用でき、特定のモデルやAPI、調査順序には固定しません。出典や確認状況は分かる範囲で記録し、不明点が残っていても整理を進めます。

## 作業に必要な情報

- 共通書誌は `data/works.jsonl`、テーマ別の要点・関係は `topics/**/topic.yaml` が正本です。READMEの生成領域は `uv run lgm render` で更新します。
- CLIの入力形式やコマンドは [docs/USAGE.md](docs/USAGE.md)、表示とデータの仕様は [THEME_LITERATURE_MAP_SPEC.md](THEME_LITERATURE_MAP_SPEC.md) を必要に応じて参照できます。
- 調査結果は正本へ直接編集するか、任意の取り込みデータを `lgm import` で反映できます。
- Markdown内の画像は `![説明](相対パス)` で埋め込みます。標準の関係図はMermaidです。
- ローカルテストは使い捨てデータを使い、本番へのアクセスはありません。テストは `uv run pytest -q`、静的チェックは `uv run ruff check src tests` と `uv run ruff format --check src tests` です。
