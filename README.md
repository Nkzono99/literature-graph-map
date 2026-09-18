# テーマ別文献マップ

テーマごとに文献と要点を整理し、一覧や概説の引用から参照できる文献マップです。月面のプラズマ環境を中心に、基礎過程・計算手法・関連する応用をまとめています。

公開先は [GitHub Pages](https://nkzono99.github.io/literature-graph-map/) です。

## 収録テーマ

- 計算手法：[PIC法](https://nkzono99.github.io/literature-graph-map/topics/pic/) ／ [Poisson方程式・場の解法](https://nkzono99.github.io/literature-graph-map/topics/poisson-solvers/)
- 基礎過程：[シース・表面帯電](https://nkzono99.github.io/literature-graph-map/topics/plasma-sheaths/) ／ [二次電子放出](https://nkzono99.github.io/literature-graph-map/topics/secondary-electron-emission/) ／ [プラズマ膨張・ウェイク](https://nkzono99.github.io/literature-graph-map/topics/plasma-expansion/)
- 月の環境：[月面帯電](https://nkzono99.github.io/literature-graph-map/topics/lunar-charging/) ／ [磁気異常と太陽風](https://nkzono99.github.io/literature-graph-map/topics/lunar-magnetic-anomalies/) ／ [水・揮発性物質](https://nkzono99.github.io/literature-graph-map/topics/lunar-water/)
- 応用：[宇宙機・計測器とプラズマ](https://nkzono99.github.io/literature-graph-map/topics/spacecraft-plasma/) ／ [プラズマ加工・微細構造の帯電](https://nkzono99.github.io/literature-graph-map/topics/plasma-processing/)

月面帯電には、電流収支・観測・地形・ダスト・工学の子テーマもあります。同じ論文を複数のテーマから参照でき、テーマ間の移動には各ページの関連リンクを使えます。

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
