# 文献マップの編集とCLI

GitHub PagesでHTMLの文献マップを公開します。CLIは、文献データから研究の概観・文献一覧・索引を生成する補助ツールです。調査方法は自由で、AIの知識や推論、検索、外部プラグイン、手作業などを使えます。

マップには誤りや抜けが含まれる可能性があります。指摘や新しい情報を反映しながら更新します。

## 基本の編集

```powershell
uv sync
uv run lgm survey "研究テーマ" --id my-topic --offline
```

正本は3種類です。

| ファイル | 内容 |
|---|---|
| `data/works.jsonl` | 共通書誌と、文献ごとの要点（問い・方法・判明点）、項目別出典、確認状況の既定値 |
| `topics/<テーマ>/topic.yaml` | テーマの問い、分類、全体像と論点別の概説、比較表、系譜、収録文献と役割。必要な文献だけ要点を上書き |
| `overview.yaml` | テーマ一覧の概観 |

これらを編集した後、ページを生成します。

```powershell
uv run lgm render
uv run lgm check
uv run lgm lint
```

`check` は入力形式と参照IDを確認します。研究内容の正しさや調査の網羅性を判定するものではありません。

## 引用漏れ・要点漏れ・平文の著者名を確認する

```powershell
uv run lgm lint
uv run lgm lint lunar-charging-dust
uv run lgm lint --json
```

`lint` は `topics/**/topic.yaml` と `data/works.jsonl` を読み、三つの検査を行います。テーマIDを省略すると非公開テーマも含めて全件と `overview.yaml` を検査します。

1. **引用漏れ**：論点別の概観（`review`）本文の `[@P000001]` と文献一覧を照合し、未引用の文献を報告します。全体像（`synopsis`）の引用は数えません。同じ文献を複数のテーマに収録した場合は、テーマごとに引用が必要です。子テーマの文献は、その子テーマで検査します。
2. **要点漏れ**：文献ごとに表示される要点（`works.jsonl` の既定値か、`topic.yaml` 側の上書き）を調べ、`summary.question`（問い）、`summary.method`（方法）、`summary.contribution`（判明点）の未記入と仮置き文言を項目ごとに報告します。編集先として `data/works.jsonl` か `topics/.../topic.yaml` を表示します。「準備中」「準備中です」「要点は準備中です」「未記入」「未確認」「未作成」「TODO」「TBD」だけの項目を仮置きとして検出し、前後の空白、末尾の「。」「.」、英字の大小は無視します。
3. **平文の著者名**：全体像・概説・比較表と概観の本文で、「Stubbs et al. (2014)」「Pacaudら（2025）」「Furman・Pivi（2002）」のように著者名と年を平文で書いた箇所を報告します。引用記法 `[@P000038]` は表示時に第一著者＋年のリンクへ変わるので、本文では `[@P000038]は…` のように引用に名前を担わせ、文末にIDだけを添えて件数を満たす書き方を避けます。装置名や「2014年」のような年の表記は対象になりません。

`--json` では `topics_checked`、`missing_count`、`missing_citations`、`missing_summaries`、`plain_author_names` を出力します。`missing_summaries` は不足した要点1項目につき1件で、`field` に項目名、`reason` に `missing`（未記入）または `placeholder`（仮置き）を返します。`plain_author_names` は検出した文字列 `text` と節の見出し `heading` を返します。`missing_count` は三つの件数の合計です。いずれかがあれば終了コード1、なければ0です。通信やファイルの更新は行いません。

`summary` を書く場合、3項目は入力形式上の必須項目です。項目の欠落や空文字・空白だけの値、参照IDなどの形式エラーは、通常の入力検証で終了コード1となり、詳細を標準エラーへ出します。この場合はJSONの検査結果を出力しません。

文献を持つテーマで概観がない場合は全件が未引用になります。文献を持たない分類ページには引用を要求しません。全体像、見出し、比較表、系譜、補足、文献一覧への掲載は、概観本文での引用には数えません。

未引用が見つかったら、文献の要点・出典と概観の論点を照合し、対応する段落へ加筆するか節の構成を見直します。共通する主張や方法はまとめて引用し、節目や条件の違いは個別に説明します。要点漏れは文献を読んで補い、出典と確認範囲も記録します。主張と引用の対応や、要点の内容の正しさは編集時に判断します。

## ページをプレビューする

公開ページはHTMLのみです。`render` は `_site/` を作り直すため、本文の訂正は正本へ、レイアウトの変更は `src/literature_graph_map/web/` へ反映します。`_site/` は生成専用で、Git管理外です。

```powershell
uv run python -m http.server 8000 --bind 127.0.0.1 --directory _site
```

ブラウザで `http://127.0.0.1:8000/` を開きます。生成サイトは外部スクリプトを読み込まず、オフラインでも閲覧・検索できます。見出し用の明朝体だけはGoogle Fontsから読み込み、未接続のときはOSの明朝体で表示します。

概観の引用リンクをクリックすると、同じページの文献一覧へ移動します。検索や分類で隠れている文献も表示されます。Tabキーでリンクを選び、Enterキーでも移動できます。

文献一覧では、このページのタイトル・著者・キーワードで検索し、分類で絞り込めます。「分類内の並び順」で古い年順・新しい年順を切り替えられます。リセットすると全件を古い年順に戻します。

子テーマのあるページでは、このページの選定文献数と、子テーマを含むテーマ全体の文献数を表示します。全体の件数は同じ文献を重複して数えません。検索の対象はこのページの一覧で、子テーマの文献は各ページで検索します。同じ文献を扱う別のテーマには、文献カードのリンクから移動できます。

ヘッダーの「全文献索引」（`works/`）は、公開テーマに収録した全文献を第一著者＋年の順に並べ、著者・タイトル・掲載誌・テーマ名で検索できます。各文献から、それを扱うテーマページの該当箇所へ移動します。要点と出典はテーマページで表示します。

「研究の系譜」では、節目となる論文と、その前後で何が変わったかをたどれます。各ブロックから文献一覧へ移動し、一覧の「系譜の節目」から戻れます。

検索経路、検索語、作業ログはページへ出力しません。`survey` は編集用の記録として利用できます。公開リポジトリではYAMLやコメントも閲覧できるため、非公開メモはリポジトリ外へ保存してください。

## 文献追加時のPaperpile登録

文献を追加する際は、Bukanを使ってPaperpileの **My Library** にも登録します。これは文献追加を担当するエージェントの標準手順です。`lgm` コマンドやPagesのビルドからは実行しません。

1. マップに追加する文献を決め、代表版のDOIまたは公開URLをそろえます。同じ文献を複数テーマに追加する場合は1件にまとめます。必要に応じてBibTeX・RISも使えます。
2. Bukanの `bukan-paperpile` スキルを読み、`paperpile_browser_status` で専用ブラウザのログイン状態を確認します。
3. `paperpile_import_references` に対象文献を小分けで渡します。通常は `format: identifiers` でDOI・URLを1行ずつ指定します。重複スキップを有効にしたまま、未登録分だけを取り込みます。BibTeX・RISでは `expectedCount` に文献数を指定します。
4. 戻り値で登録結果を確認し、作業報告に追加済み・既存・未完了の件数を記載します。`present_in_browser` / `already_present` はブラウザ上での存在確認です。サーバー同期やPDF取得の完了とは分けて扱います。

文献追加の依頼には、この登録作業も含みます。都度の承認は求めません。調査中の候補は、追加する文献に選んだ段階で対象にします。出版版とプレプリントの両方がある場合は代表版を使い、既存の別版にも注意して同じ研究の重複登録を避けます。

重複はPaperpileの取り込み画面で確認します。BukanのPDF検索に見つからなくても、書誌だけ登録されている場合があるため、未登録とは判断しません。

ツールが使えない、ログインが必要、結果が `unknown` などの場合は、未完了の文献と理由を報告し、マップの編集・公開は進めます。再試行時も重複チェックを使います。登録状況やアカウント情報などの作業メモはリポジトリ外に置き、公開ページへは出しません。

## テーマ一覧の概観を編集する

リポジトリ直下の `overview.yaml` に、テーマ同士のつながりを説明する文章を記録します。テーマページと同じ `review`・`heading`・`paragraphs` の構成です。本文の `[@topic:テーマID]` は、該当するテーマの現在の名前とURLを使った引用リンクになります。

```yaml
review:
  - heading: 観測と計算を結び付ける
    paragraphs:
      - 月面の電位を観測と計算で調べる（[@topic:lunar-charging]）。粒子と場の結合を扱うPIC法が、その計算の基礎になる（[@topic:pic]）。
```

引用先は存在する公開テーマに限ります。存在しないIDや非公開テーマへの引用は入力検証でエラーになります。引用以外はプレーンテキストとして表示します。ファイルを省略するか `review: []` にすると概観を表示しません。`render` と `export` はこの正本を反映し、`check --public` はYAMLのコメントも含めて公開用の検査を行います。

概観にはテーマ間のつながりを書き、個別文献の数値・判明点・著者名は書きません。それらは該当テーマの概説に置きます。`lint` は概観の平文の著者名も報告します。

## テーマの階層

`navigation.parent` に親テーマのIDを指定すると、索引・サイドバー・パンくずに反映されます。ディレクトリを移動する必要はなく、既存のURLを保ったまま階層を変えられます。分野をまたぐつながりは `navigation.related` に記録します。

親には、そのテーマの対象を含む分類を選びます。例えば、粒子帯電の一般理論は「ダストの基礎」、月ダストの帯電・輸送は「月面帯電」の下に置き、両者を関連テーマで結びます。PICを使う研究は対象分野に置き、数値計算法としてのPICを扱う研究は「数値計算手法」に置きます。子テーマの名前は、関連リンクから開いたときにも対象が分かるように付けます。

文献を持たず、公開の子テーマを持つページは分類の入口になります。文献一覧を置かず、子テーマの説明とリンクを表示します。月面帯電のように文献と子テーマを両方持つページは、概観・文献一覧と子テーマを併載します。トップページの件数には分類の入口を含めません。

テーマを追加・移動・改名したら、READMEの収録テーマ一覧を再生成します。

```powershell
uv run lgm readme
uv run lgm readme --check
```

READMEの `<!-- lgm:topics https://公開URL/ -->` と `<!-- /lgm:topics -->` の間を、公開テーマの階層一覧で置き換えます。マーカーに書いたURLがリンクの基準になります。`--check` は書き換えずに一覧が最新かどうかを返し、CIでも実行します。

## 研究の系譜を編集する

`topic.yaml` の `lineage` に研究の流れを記録します。各テーマで2〜6件ほどの節目を目安に選び、問いや手法が分かれる場合は経路を分けます。

```yaml
lineage:
  - title: モデルから観測へ
    steps:
      - paper_id: P000001
        title: 基準モデルを作る
        significance: 現象を説明する条件と、観測で確かめる予測を示した。
      - paper_id: P000002
        title: 予測を観測と照合
        significance: 観測結果から、モデルが使える条件を絞った。
        connection: 予測を測定と比較
```

`paper_id` はそのテーマの `entries` に含め、各論文は系譜内に一度置きます。`title` は節目の短い見出し、`significance` は研究上の変化、`connection` は前の論文からのつながりです。最初の論文には `connection` を付けず、2件目以降に付けます。経路が独立していれば、1件だけでも構いません。

系譜は編集者が選んだ研究の流れです。年代だけで継承関係を作らず、理論の拡張、観測による制約、方法の比較など、つながりの内容を書き分けます。教科書や総説への入口は概観に残せます。`lineage` の省略時は系譜の節を表示しません。

## 正本の書き方

`data/works.jsonl` は1行1文献のJSONです。書誌に加えて、要点・項目別出典・確認状況の既定値をここに書きます。以下は形式を示す架空の例です（実際は1行）。

```json
{"paper_id": "P000001", "title": "架空の研究", "authors": ["Example Author"],
 "representative_version_id": "V1", "versions": [{"version_id": "V1", "year": 2026}],
 "record_url": "https://example.org/paper",
 "summary": {"question": "モデル間で予測はどう異なるか。", "method": "同じ条件でモデルを比較する。", "contribution": "条件による予測の違いを整理する。"},
 "evidence_by_item": {"contribution": [{"paper_id": "P000001", "version_id": "V1", "url": "https://example.org/paper", "source_type": "abstract", "locator": "要旨"}]},
 "inspection": {"level": "abstract", "version_id": "V1", "checked_by": "ai", "checked_at": "2026-10-13"}}
```

`topics/<テーマ>/topic.yaml` には、テーマの問い、分類、概説、系譜と、収録文献の役割を書きます。文献の `entries` は通常、文献ID・分類・役割だけです。

```yaml
topic_id: my-topic
title: 研究テーマ
question: どのような手法があるか
synopsis:
  - 手法は基準モデル（[@P000001]）を出発点に、条件を変えた比較へ進んだ。
review:
  - heading: 基準モデルから研究をたどる
    paragraphs:
      - このテーマでは、まず[@P000001]のモデルを出発点にする。[@P000002]は同じ条件で予測を比較した。
comparisons:
  - id: conditions
    title: 計算条件の比較
    axes:
      - id: model
        title: モデル
      - id: validation
        title: 検証
    rows:
      - paper_id: P000001
        cells:
          model: 基準モデル
          validation: 解析解と比較
      - paper_id: P000002
        cells:
          model: 条件を変えた比較
groups:
  - id: general
    title: 先行研究
entries:
  - paper_id: P000001
    group: general
    role: 基準モデル
  - paper_id: P000002
    group: general
    role: このテーマに合わせた読み方
    summary:
      question: このテーマ固有の問い。
      method: 共通の方法。
      contribution: このテーマで参照する判明点。
```

`entries` の `summary`・`evidence_by_item`・`inspection` は、そのテーマだけ違う読み方をしたい場合の上書きです。書いた項目だけが置き換わり、書かない項目は `works.jsonl` の既定値を表示します。要点の訂正は原則として `works.jsonl` 側で行い、すべてのテーマに反映させます。

要点には `question`・`method`・`contribution` の3項目を記録します。要点自体は省略できます。項目別出典の `evidence_by_item`、確認状況の `inspection`、書誌取得元の `metadata_sources` は任意です。未記録でも掲載できます。

要点のある文献には「出典・確認状況」を表示します。要旨や本文を未確認の場合も、その状態が分かります。出典には参照版を表示し、参照版とリンク先の版が異なる場合は、ページ・図番号とリンク先を分けて示します。他の文献による紹介を使った場合は、紹介元の文献名を表示します。

概説は文献一覧より上に、二層で置きます。`synopsis`（研究の全体像）は段落の一覧で、主要な問い、明らかになったこと、見解の違い、未解決問題を代表文献だけを引用して300〜600字程度で示します。`review`（論点別の概観）は節ごとに `heading` と `paragraphs` を書き、各論点を支える研究、異なる結果、手法の発展を説明しながら収録文献をすべて引用します。文献数に応じて長くなって構いません。どちらも本文中の `[@P000001]` で同じテーマの文献を引用し、表示時には著者＋年のリンクに変わります。本文に著者名と年を平文で書かず、引用に名前を担わせます。引用以外はプレーンテキストです。`synopsis` があるページでは、見出しが「研究の全体像」と「論点別の概観」になります。概観の省略はデータ形式上は可能ですが、文献を持つテーマは `lint` で全件が未引用として報告されます。

`comparisons` は、テーマで重要な比較軸に沿って文献の条件を並べる表です。表ごとに `id`、`title`、任意の `note`、3〜6本程度の `axes`（`id` と `title`）、`rows`（`paper_id` と軸IDをキーにした `cells`）を書きます。行の文献は同じテーマの文献一覧に含め、セルには要点・出典で裏づけられる内容だけを書き、記載のない項目は省略すると空欄として表示されます。全テーマ共通の属性体系は作らず、比較が意味を持つテーマにだけ置きます。

画面では第一著者＋年で文献を呼びます。同じ組み合わせには `-1`、`-2` を付けます。複合姓などは共通書誌の `citation_author: Pagán Muñoz` で表示名の著者部分を指定できます。内部の `paper_id` は参照用として維持します。

参考情報として参照する文献は、文献一覧に載せず共通台帳にだけ登録することもできます。出典から参照している文献は公開対象に含まれます。

研究同士の関係は概観の文章と系譜で説明します。関係データや関係図は持ちません。

`uv run lgm schema --output schemas` でJSON Schemaを出力できます。

## コマンド一覧

`--repo`（既定は現在のディレクトリ）と `--private-dir` はコマンド名より前に指定します。

| 操作 | 用途 |
|---|---|
| `init [--license FILE]` | 空の台帳を作る。ライセンス文書の配置は任意 |
| `survey THEME [--id ID] [--parent ID] [--offline]` | テーマのひな形を作る |
| `survey THEME --query QUERY [--seed SEED]` | Crossrefで候補を探し、指定した種文献の書誌を追加する |
| `add TOPIC_ID SEED [SEED ...]` | 種文献のDOIを同定して追加する |
| `update TOPIC_ID [--query QUERY] [--since YYYY-MM-DD]` | Crossrefの書誌を再取得し、候補を探す |
| `render` | 通信せずに正本から `_site/` のHTMLサイトを再生成する |
| `check [--public]` | 正本の形式・参照を確認する |
| `lint [TOPIC_ID] [--json]` | 概観本文の引用漏れ・文献の要点漏れ・平文の著者名と編集先を表示する |
| `readme [--check]` | READMEの収録テーマ一覧を正本から生成する |
| `export DIRECTORY` | 正本と生成HTMLを別の新規ディレクトリに書き出す |
| `config` | CLIの候補検索に使う上限・連絡先を保存する |
| `schema --output DIRECTORY` | 入力形式をJSON Schemaで出力する |

種文献にはDOI、doi.orgのURL、DOIを含む `.bib` / `.ris` / `.md` / `.txt` / `.pdf` を指定できます。画像だけのPDFはOCRしません。タイトル検索には `--query` を使います。DOIがない文献は正本の編集で登録できます。

CLIの候補検索はCrossrefを利用します。要点を自動生成する機能はありません。検索コマンドや調査メモを経由せず、別の方法で調べた情報を反映しても構いません。

## 更新と補助ファイル

同じ論文は複数テーマで共通の文献IDを使います。出版版やプレプリントは `versions` に追加でき、版同士の対応を記録する `version_links` は任意です。新しい版を追加したときは既存の参照版を維持し、要点を見直すまで `inspection.recheck: true` を付けると、ページに「旧版に基づく記述」と表示されます。掲載は継続します。

`update` による書誌の再取得で上書きしたくない項目には、文献の `locked_fields` を指定できます。要点・出典・確認状況と確認済みの公開先は再取得で変わりません。

テーマのディレクトリを移動して `render` を実行すると、親・子・関連テーマへのリンクも更新されます。

CLIの検索候補・API応答・調査メモはリポジトリ外の作業領域に保存されます。Windowsでは `%LOCALAPPDATA%/literature-graph-map/<識別子>/`、他の環境では `~/.local/share/literature-graph-map/<識別子>/` です。`--private-dir` で別の場所を指定できます。`survey`・`add`・`update` はそこへ `RESEARCH_REQUEST.md`（調査メモ）、`candidates.json`（検索候補）、`search-report.json`（通信の記録）を書きます。

```powershell
uv run lgm config --max-candidates 30 --max-search-calls 8 --timeout-seconds 20
```

この上限はCLIのCrossref検索に適用されます。外部のAIやプラグインの調査方法には影響しません。

## リポジトリへの掲載

テーマは既定で `public: true` です。`public: false` のテーマはページを生成せず、`check --public` で指摘されるため、公開前の草稿はリポジトリ外に置きます。

`check --public` では、掲載対象の整合性に加え、秘密情報やローカルパス、データ用ディレクトリへの意図しないファイル混入を確認します。出典の有無や調査の完成度によって掲載を止めません。

正本とHTMLサイトを別の場所へ保存する場合は `export` を使えます。スナップショットにはYAMLの編集記録も含まれます。Pagesへの公開対象は `_site/` だけです。`COPYRIGHT.md` の権利説明と既存の `LICENSE` は、HTMLサイトとエクスポート先にも反映されます。CLIはGitへのコミットやpushを行いません。

## GitHub Pagesへの公開

1. GitHubリポジトリの **Settings → Pages → Build and deployment → Source** で **GitHub Actions** を選びます。
2. 変更を `main` へpushすると、`.github/workflows/pages.yml` が検証・HTML生成・公開を実行します。Actions画面の **Publish literature map → Run workflow** からも実行できます。
3. 公開URLはPages設定画面やデプロイ結果に表示されます。このリポジトリでは `https://nkzono99.github.io/literature-graph-map/` です。

生成HTMLのコミットは不要です。公開されるファイルはHTML・CSS・JavaScriptに限定され、正本や作業ログはPagesへコピーしません。

[GitHub公式のカスタムワークフロー説明](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)

## 開発

```powershell
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run lgm --repo examples/library check
uv run lgm readme --check
```
