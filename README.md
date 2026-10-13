# テーマ別文献マップ

テーマごとに文献と要点を整理し、一覧や概説の引用から参照できる文献マップです。月の科学・探査と、関連するプラズマ・ダストの基礎、計算手法、工学応用をまとめています。

公開先は [GitHub Pages](https://nkzono99.github.io/literature-graph-map/) です。収録した全文献は[全文献索引](https://nkzono99.github.io/literature-graph-map/works/)から第一著者＋年の順にたどれます。

## 収録テーマ

次の一覧は `uv run lgm readme` が正本から生成します。手で編集せず、テーマを変えたら再生成してください。

<!-- lgm:topics https://nkzono99.github.io/literature-graph-map/ -->
- [宇宙機・プラズマ応用](https://nkzono99.github.io/literature-graph-map/topics/applications/)
  - [電子反射法による天体の磁場・電位・大気推定](https://nkzono99.github.io/literature-graph-map/topics/electron-reflectometry/)
  - [プラズマ加工・微細構造の帯電](https://nkzono99.github.io/literature-graph-map/topics/plasma-processing/)
  - [宇宙機・計測器とプラズマの相互作用](https://nkzono99.github.io/literature-graph-map/topics/spacecraft-plasma/)
- [ダストの基礎](https://nkzono99.github.io/literature-graph-map/topics/dust-physics/)
  - [ダストの付着・接触・離脱](https://nkzono99.github.io/literature-graph-map/topics/dust-adhesion/)
  - [ダスト帯電の理論と粒子実験](https://nkzono99.github.io/literature-graph-map/topics/dust-charging/)
- [月の科学・探査](https://nkzono99.github.io/literature-graph-map/topics/lunar-environment/)
  - [かぐや（SELENE）の観測と研究](https://nkzono99.github.io/literature-graph-map/topics/kaguya/)
  - [月面帯電](https://nkzono99.github.io/literature-graph-map/topics/lunar-charging/)
    - [月ダストの帯電・付着・静電輸送](https://nkzono99.github.io/literature-graph-map/topics/lunar-charging/dust/)
    - [月探査の帯電リスク・除塵技術](https://nkzono99.github.io/literature-graph-map/topics/lunar-charging/engineering/)
    - [月面帯電の観測・宇宙環境](https://nkzono99.github.io/literature-graph-map/topics/lunar-charging/observations/)
    - [月面の電流収支・光電子シース](https://nkzono99.github.io/literature-graph-map/topics/lunar-charging/sheath/)
    - [月の極域・クレーター・空洞の帯電](https://nkzono99.github.io/literature-graph-map/topics/lunar-charging/topography/)
  - [月の地形・地質・内部構造](https://nkzono99.github.io/literature-graph-map/topics/lunar-geology/)
    - [月の衝突クレーター・年代学](https://nkzono99.github.io/literature-graph-map/topics/lunar-craters/)
    - [月の地形計測・重力・内部構造](https://nkzono99.github.io/literature-graph-map/topics/lunar-geodesy-interior/)
    - [月の鉱物・元素組成](https://nkzono99.github.io/literature-graph-map/topics/lunar-mineralogy/)
    - [月の縦孔・地下構造・空洞](https://nkzono99.github.io/literature-graph-map/topics/lunar-subsurface/)
    - [月の火山活動と年代](https://nkzono99.github.io/literature-graph-map/topics/lunar-volcanism/)
  - [月の磁気異常と太陽風相互作用](https://nkzono99.github.io/literature-graph-map/topics/lunar-magnetic-anomalies/)
  - [月面の水・揮発性物質](https://nkzono99.github.io/literature-graph-map/topics/lunar-water/)
- [数値計算手法](https://nkzono99.github.io/literature-graph-map/topics/numerical-methods/)
  - [PIC法・プラズマ粒子シミュレーション](https://nkzono99.github.io/literature-graph-map/topics/pic/)
    - [ハイブリッドPIC法・粒子と流体の結合](https://nkzono99.github.io/literature-graph-map/topics/pic/hybrid-pic/)
  - [Poisson方程式・場の解法](https://nkzono99.github.io/literature-graph-map/topics/poisson-solvers/)
- [プラズマの基礎過程](https://nkzono99.github.io/literature-graph-map/topics/plasma-processes/)
  - [磁気流体力学（MHD）](https://nkzono99.github.io/literature-graph-map/topics/mhd/)
  - [空洞・微細構造へのプラズマ流入](https://nkzono99.github.io/literature-graph-map/topics/plasma-cavities/)
  - [プラズマ膨張・ウェイク](https://nkzono99.github.io/literature-graph-map/topics/plasma-expansion/)
  - [シース・表面帯電の基礎](https://nkzono99.github.io/literature-graph-map/topics/plasma-sheaths/)
  - [二次電子放出](https://nkzono99.github.io/literature-graph-map/topics/secondary-electron-emission/)
<!-- /lgm:topics -->

文献を持たない親テーマは分類の入口で、子テーマの一覧を表示します。同じ論文を複数のテーマから参照でき、分野をまたぐ移動には関連テーマのリンクを使えます。

各テーマの「研究の系譜」には、転機となる論文と研究の変化を短くまとめています。論文ブロックから文献一覧へ移動し、一覧の「系譜の節目」から戻れます。

## 編集とプレビュー

共通書誌と要点の既定値は `data/works.jsonl`、テーマごとの分類・概説・系譜は `topics/**/topic.yaml`、テーマ一覧の概観は `overview.yaml` が正本です。同じ論文を複数テーマに載せても要点は一か所に書き、テーマ固有の言い換えが必要なときだけ `topic.yaml` 側で上書きします。HTMLを生成して表示します。

概観の本文の `[@topic:テーマID]` はテーマ名の引用リンクになり、テーマの概説の `[@P000001]` は第一著者＋年の引用リンクになります。

```powershell
uv sync
uv run lgm lint
uv run lgm render
uv run python -m http.server 8000 --bind 127.0.0.1 --directory _site
```

ブラウザで `http://127.0.0.1:8000/` を開きます。`_site/` は生成専用で、Gitには含めません。テーマ別Markdownの生成は行いません。

`lgm lint` は概観の引用漏れ、文献の問い・方法・判明点が未記入または準備中の箇所、そして本文に平文で書かれた「著者（年）」を検出します。著者名は `[@P000001]` の引用で表示名に変わるため、本文に著者名を重ねて書きません。テーマIDの指定やJSON出力も使えます。

調査にはAI、検索、外部プラグインなど、テーマに合う方法を使えます。要点と概説の文章は生成AIを使って作成しており、誤りや不足は気づいた時点で直していきます。

## ライセンス

コード、ドキュメント、独自の概説・要点・比較・分類には、管理者・寄稿者が保有し許諾できる権利の範囲で [MITライセンス](LICENSE) を適用します。参照先の論文や第三者資料は対象外です。AI生成を利用した文章の扱いと適用範囲は [COPYRIGHT.md](COPYRIGHT.md) に記載しています。

[編集・公開の手順](docs/USAGE.md) ／ [仕様](THEME_LITERATURE_MAP_SPEC.md) ／ [HTMLテンプレート](src/literature_graph_map/web/topic.html) ／ [著作権について](COPYRIGHT.md)
