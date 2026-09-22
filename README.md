# テーマ別文献マップ

テーマごとに文献と要点を整理し、一覧や概説の引用から参照できる文献マップです。月の科学・探査と、関連するプラズマ・ダストの基礎、計算手法、工学応用をまとめています。

公開先は [GitHub Pages](https://nkzono99.github.io/literature-graph-map/) です。

## 収録テーマ

- [月の科学・探査](https://nkzono99.github.io/literature-graph-map/topics/lunar-environment/)：[地形・地質・内部構造](https://nkzono99.github.io/literature-graph-map/topics/lunar-geology/) ／ [月面帯電](https://nkzono99.github.io/literature-graph-map/topics/lunar-charging/) ／ [磁気異常と太陽風](https://nkzono99.github.io/literature-graph-map/topics/lunar-magnetic-anomalies/) ／ [水・揮発性物質](https://nkzono99.github.io/literature-graph-map/topics/lunar-water/) ／ [かぐや（SELENE）](https://nkzono99.github.io/literature-graph-map/topics/kaguya/)
- [プラズマの基礎過程](https://nkzono99.github.io/literature-graph-map/topics/plasma-processes/)：[シース・表面帯電](https://nkzono99.github.io/literature-graph-map/topics/plasma-sheaths/) ／ [二次電子放出](https://nkzono99.github.io/literature-graph-map/topics/secondary-electron-emission/) ／ [プラズマ膨張・ウェイク](https://nkzono99.github.io/literature-graph-map/topics/plasma-expansion/) ／ [空洞へのプラズマ流入](https://nkzono99.github.io/literature-graph-map/topics/plasma-cavities/)
- [ダストの基礎](https://nkzono99.github.io/literature-graph-map/topics/dust-physics/)：[付着・接触・離脱](https://nkzono99.github.io/literature-graph-map/topics/dust-adhesion/) ／ [帯電の理論と粒子実験](https://nkzono99.github.io/literature-graph-map/topics/dust-charging/)
- [数値計算手法](https://nkzono99.github.io/literature-graph-map/topics/numerical-methods/)：[PIC法](https://nkzono99.github.io/literature-graph-map/topics/pic/) ／ [Poisson方程式・場の解法](https://nkzono99.github.io/literature-graph-map/topics/poisson-solvers/)
- [宇宙機・プラズマ応用](https://nkzono99.github.io/literature-graph-map/topics/applications/)：[宇宙機・計測器とプラズマ](https://nkzono99.github.io/literature-graph-map/topics/spacecraft-plasma/) ／ [プラズマ加工・微細構造の帯電](https://nkzono99.github.io/literature-graph-map/topics/plasma-processing/)

「月の地形・地質・内部構造」の下には、地形計測・重力・地殻、鉱物・元素組成、火山活動、衝突クレーター、地下構造の子テーマがあります。「月面帯電」では、電流収支・観測・地形による帯電・月ダスト・探査技術へ進めます。かぐやは観測ミッションから各分野をたどる入口です。

ダストの接触・付着と粒子帯電は「ダストの基礎」にまとめ、月面での帯電・輸送は「月面帯電」の下に置いています。同じ論文を複数のテーマから参照でき、分野をまたぐ移動には関連テーマのリンクを使えます。

各テーマの「研究の系譜」には、転機となる論文と研究の変化を短くまとめています。論文ブロックから文献一覧へ移動し、一覧の「系譜の節目」から戻れます。

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
