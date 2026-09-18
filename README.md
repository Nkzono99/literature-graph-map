# テーマ別文献マップ

テーマごとに文献と要点を整理し、一覧や概説の引用から参照できる文献マップです。現在は月面帯電の17文献を収録しています。

公開先は [GitHub Pages](https://nkzono99.github.io/literature-graph-map/) です。

## 編集とプレビュー

共通書誌は `data/works.jsonl`、要点・分類・関係は `topics/**/topic.yaml` が正本です。HTMLを生成して表示します。

```powershell
uv sync
uv run lgm render
uv run python -m http.server 8000 --bind 127.0.0.1 --directory _site
```

ブラウザで `http://127.0.0.1:8000/` を開きます。`_site/` は生成専用で、Gitには含めません。テーマ別Markdownの生成は行いません。

調査にはAI、検索、外部プラグインなど、テーマに合う方法を使えます。誤りや不足は気づいた時点で直していきます。

[編集・公開の手順](docs/USAGE.md) ／ [仕様](THEME_LITERATURE_MAP_SPEC.md) ／ [HTMLテンプレート](src/literature_graph_map/web/topic.html) ／ [著作権について](COPYRIGHT.md)
