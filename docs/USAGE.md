# 文献マップの編集とCLI

GitHub PagesでHTMLの文献マップを公開します。CLIは、文献データから文献一覧・Mermaidの関係図・索引を生成する補助ツールです。調査方法は自由で、AIの知識や推論、検索、外部プラグイン、手作業などを使えます。

マップには誤りや抜けが含まれる可能性があります。指摘や新しい情報を反映しながら更新します。

## 基本の編集

```powershell
uv sync
uv run lgm survey "研究テーマ" --id my-topic --offline
```

共通書誌は `data/works.jsonl`、テーマごとの要点・分類・関係は `topics/<テーマ>/topic.yaml` に記録します。これらを編集した後、ページを生成します。

```powershell
uv run lgm render
uv run lgm check
```

`check` は入力形式と参照IDを確認します。研究内容の正しさや調査の網羅性を判定するものではありません。

公開ページはHTMLのみです。`render` は `_site/` を作り直すため、本文の訂正は正本へ、レイアウトの変更は `src/literature_graph_map/web/` へ反映します。`_site/` は生成専用で、Git管理外です。

```powershell
uv run python -m http.server 8000 --bind 127.0.0.1 --directory _site
```

ブラウザで `http://127.0.0.1:8000/` を開きます。関係図の描画にはMermaidのCDN接続を使います。研究の概観・文献一覧・出典はオフラインでも読めます。

関係図の文献ノードをクリックすると、同じページの文献一覧へ移動します。検索や分類で隠れている文献も表示されます。Tabキーでノードを選び、Enterキーでも移動できます。

検索経路、検索語、作業ログはページへ出力しません。`survey` は編集用の記録として利用できます。公開リポジトリではYAMLやコメントも閲覧できるため、非公開メモはリポジトリ外へ保存してください。

## データの入力例

正本の直接編集に加えて、文献とテーマをまとめたYAMLを `import` で取り込めます。以下は形式を示す架空の例です。

```yaml
works:
  - paper_id: P000001
    title: 架空の研究
    authors: [Example Author]
    record_url: https://example.org/paper
    representative_version_id: V1
    versions:
      - version_id: V1
        year: 2026
topic:
  topic_id: my-topic
  title: 研究テーマ
  question: どのような手法があるか
  review:
    - heading: 基準モデルから研究をたどる
      paragraphs:
        - このテーマでは、まず[@P000001]のモデルを出発点にする。
  entries:
    - paper_id: P000001
      group: general
      role: 基準モデル
      summary:
        question: モデル間で予測はどう異なるか。
        method: 同じ条件でモデルを比較する。
        contribution: 条件による予測の違いを整理する。
```

```powershell
uv run lgm import packet.yaml
```

`import` は指定テーマの内容を置き換え、書誌は既存の台帳と統合します。既存テーマへ文献を追加する場合は、残したい行や関係も取り込みデータに含めてください。新規テーマの配置先は `--path topics/parent/child` で指定できます。

要点には `question`・`method`・`contribution` の3項目を記録します。要点自体は省略できます。項目別出典の `evidence_by_item`、確認状況の `inspection`、書誌取得元の `metadata_sources` は任意です。未記録でも掲載できます。

`review` は文献一覧より上に置く概説です。節ごとに `heading` と `paragraphs` を書き、本文中の `[@P000001]` で同じテーマの文献を引用します。表示時には著者＋年のリンクに変わり、クリックすると該当文献へ移動します。引用以外はプレーンテキストです。分量は3〜5節、1,000〜2,000字程度を目安に調整できます。省略時は概説の欄を表示しません。

画面では第一著者＋年で文献を呼びます。同じ組み合わせには `-1`、`-2` を付けます。複合姓などは共通書誌の `citation_author: Pagán Muñoz` で表示名の著者部分を指定できます。内部の `paper_id` は参照用として維持します。

参考情報として参照する文献は、文献一覧に載せず共通台帳にだけ登録することもできます。

関係にはID、両端の文献ID、種類、比較軸（`aspect`）、理由（`reason`）を記録します。`basis` は既定で `comparison`、`state` は既定で `candidate` です。図の辺には任意の `graph_label` で関係を短く説明できます（例：`graph_label: 空洞寸法とシース厚へ拡張`）。省略時は比較軸＋種類を使います。出典、確認日、確認主体、条件差は分かる範囲で追加できます。

| 関係の状態 | ページでの表示 |
|---|---|
| `candidate` | 図に「仮」を付けて掲載 |
| `checked` | 図で通常表示 |
| `recheck` | 図に「見直し予定」を付けて掲載 |
| `rejected` | データに残し、図には表示しない |

`checked` は整理上の状態です。人間の確認や原著の精読を保証しません。記録していない確認主体・確認日を自動で補うこともありません。

詳細は [入力例](../examples/demo.packet.yaml) を参照できます。`uv run lgm schema --output schemas` でJSON Schemaを出力できます。

## コマンド一覧

`--repo`（既定は現在のディレクトリ）と `--private-dir` はコマンド名より前に指定します。

| 操作 | 用途 |
|---|---|
| `init [--license FILE]` | 空の台帳を作る。ライセンス文書の配置は任意 |
| `survey THEME [--id ID] [--parent ID] [--offline]` | テーマのひな形を作る |
| `survey THEME --query QUERY [--seed SEED]` | Crossrefで候補を探し、指定した種文献の書誌を追加する |
| `add TOPIC_ID SEED [SEED ...]` | 種文献のDOIを同定して追加する |
| `update TOPIC_ID [--query QUERY] [--since YYYY-MM-DD]` | Crossrefの書誌を再取得し、候補を探す |
| `import PACKET [--path PATH]` | 文献・テーマのデータを取り込む |
| `render` | 通信せずに正本から `_site/` のHTMLサイトを再生成する |
| `check [--public]` | 正本の形式・参照を確認する |
| `export DIRECTORY` | 正本と生成HTMLを別の新規ディレクトリに書き出す |
| `config` | CLIの候補検索に使う上限・連絡先を保存する |
| `schema --output DIRECTORY` | 入力形式をJSON Schemaで出力する |

種文献にはDOI、doi.orgのURL、DOIを含む `.bib` / `.ris` / `.md` / `.txt` / `.pdf` を指定できます。画像だけのPDFはOCRしません。タイトル検索には `--query` を使います。DOIがない文献は正本の編集か `import` で登録できます。

CLIの候補検索はCrossrefを利用します。要点や関係を自動生成する機能はありません。検索コマンドや調査メモを経由せず、別の方法で調べた情報を反映しても構いません。

## 更新と補助ファイル

同じ論文は複数テーマで共通の文献IDを使います。出版版やプレプリントは `versions` に追加でき、版同士の対応を記録する `version_links` は任意です。新しい版を取り込むと、既存の参照版を維持しつつ関係に「見直し予定」が付きます。掲載は継続します。

取り込みで上書きしたくない項目には、任意で `locked_fields` を指定できます。競合は `import-report.json` に記録されます。固定する必要がなければ指定しません。

テーマのディレクトリを移動して `render` を実行すると、親・子・関連テーマへのリンクも更新されます。

CLIの検索候補・API応答・調査メモはリポジトリ外の作業領域に保存されます。Windowsでは `%LOCALAPPDATA%/literature-graph-map/<識別子>/`、他の環境では `~/.local/share/literature-graph-map/<識別子>/` です。`--private-dir` で別の場所を指定できます。

`packet.generated.yaml` は正本のコピー、`packet.yaml` は編集用コピーです。再実行しても既存の編集用コピーは維持されます。`review-packet.yaml` は取り込み時の控えで、正本とは独立しています。

```powershell
uv run lgm config --max-candidates 30 --max-search-calls 8 --timeout-seconds 20
```

この上限はCLIのCrossref検索に適用されます。外部のAIやプラグインの調査方法には影響しません。

## リポジトリへの掲載

テーマは既定で `public: true` です。`public: false` のデータを取り込む場合は、リポジトリ外へ草稿として保存します。仮の関係は公開テーマのYAMLとページに残ります。

`check --public` では、掲載対象の整合性に加え、秘密情報やローカルパス、データ用ディレクトリへの意図しないファイル混入を確認します。出典の有無や調査の完成度によって掲載を止めません。

正本とHTMLサイトを別の場所へ保存する場合は `export` を使えます。スナップショットにはYAMLの編集記録も含まれます。Pagesへの公開対象は `_site/` だけです。既存の `LICENSE` があれば一緒に出力されます。CLIはGitへのコミットやpushを行いません。

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
```
