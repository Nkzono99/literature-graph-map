# 文献マップの編集とCLI

このリポジトリ自体を文献マップとして公開します。CLIは、文献データから比較表・Mermaidの関係図・索引を生成する補助ツールです。調査方法は自由で、AIの知識や推論、検索、外部プラグイン、手作業などを使えます。

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

`check` は入力形式、参照ID、生成ページとの一致を確認します。研究内容の正しさや調査の網羅性を判定するものではありません。

READMEの `BEGIN GENERATED` / `END GENERATED` 内は、再生成時に正本の内容で置き換わります。領域外の文章は維持されます。ハッシュによる編集保護はありません。残したい訂正は正本へ反映してください。

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

参考情報として参照する文献は、比較表に載せず共通台帳にだけ登録することもできます。

関係にはID、両端の文献ID、種類、比較軸（`aspect`）、理由（`reason`）を記録します。`basis` は既定で `comparison`、`state` は既定で `candidate` です。出典、確認日、確認主体、条件差は分かる範囲で追加できます。

| 関係の状態 | ページでの表示 |
|---|---|
| `candidate` | 「仮」を付けて掲載 |
| `checked` | 通常の関係として掲載 |
| `recheck` | 「見直し予定」を付けて掲載 |
| `rejected` | データに残し、図と一覧には表示しない |

`checked` は整理上の状態です。人間の確認や原著の精読を保証しません。記録していない確認主体・確認日を自動で補うこともありません。

詳細は [入力例](../examples/demo.packet.yaml) を参照できます。`uv run lgm schema --output schemas` でJSON Schemaを出力できます。

## コマンド一覧

`--repo`（既定は現在のディレクトリ）と `--private-dir` はコマンド名より前に指定します。

| 操作 | 用途 |
|---|---|
| `init [--license FILE]` | 空の台帳・索引を作る。ライセンス文書の配置は任意 |
| `survey THEME [--id ID] [--parent ID] [--offline]` | テーマのひな形を作る |
| `survey THEME --query QUERY [--seed SEED]` | Crossrefで候補を探し、指定した種文献の書誌を追加する |
| `add TOPIC_ID SEED [SEED ...]` | 種文献のDOIを同定して追加する |
| `update TOPIC_ID [--query QUERY] [--since YYYY-MM-DD]` | Crossrefの書誌を再取得し、候補を探す |
| `import PACKET [--path PATH]` | 文献・テーマのデータを取り込む |
| `render` | 通信せずに正本からページを再生成する |
| `check [--public]` | データとページの整合性を確認する |
| `export DIRECTORY` | マップを別の新規ディレクトリに書き出す |
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

このリポジトリをそのまま公開できます。マップだけを切り出す場合は `export` を使えます。既存の `LICENSE` があれば一緒に出力されます。CLIはGitへのコミットやpushを行いません。

## 開発

```powershell
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run lgm --repo examples/library check
```
