# テーマ別文献マップ

テーマごとの論文比較表と関係図から、先行研究の違いやつながりをたどるためのリポジトリです。

この文献マップには誤りや抜けが含まれる可能性があります。気づいた点をご指摘いただければ、その都度修正します。

<!-- BEGIN GENERATED: topic-index -->
- [月面帯電：光電子シース・宇宙環境・地形・ダスト](<topics/lunar-charging/README.md>)（17件）
<!-- END GENERATED: topic-index -->

## マップを育てる

調査にはAI、検索、外部プラグインなど、テーマに合う方法を使えます。共通書誌は `data/works.jsonl`、要点・関係は `topics/` のテーマ別YAMLへ記録し、同梱のCLIで表と図を生成します。

```powershell
uv sync
uv run lgm render
```

テーマのひな形を作る場合は `uv run lgm survey "研究テーマ" --id my-topic --offline` を使えます。CLIによる候補検索やデータ取り込みも利用できます。

[操作方法](docs/USAGE.md) ／ [架空データによる表示例](examples/library/topics/demo/README.md) ／ [仕様](THEME_LITERATURE_MAP_SPEC.md) ／ [著作権について](COPYRIGHT.md)
