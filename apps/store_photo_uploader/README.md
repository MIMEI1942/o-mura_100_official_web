# 店舗写真アップロードフォーム

写真と店舗名を投稿すると、

1. Google Drive の指定フォルダ配下に **店舗名のサブフォルダ** を作って写真を保存し、
2. 「リンクを知っている全員が閲覧可」の **共有リンク** を発行して、
3. スプレッドシートの **店舗名が一致する行** の指定セルにそのリンクを書き込む

までを自動で行う Streamlit アプリです。

リポジトリのルートにある 100 周年サイト（`app.py`）とは独立していて、依存関係も別管理です。

## セットアップ

### 1. Google Cloud 側の準備

1. Google Cloud プロジェクトで **Google Drive API** と **Google Sheets API** を有効化する。
2. **サービスアカウント** を作成し、JSON 形式の鍵をダウンロードする。
3. 保存先の Drive フォルダを開き、サービスアカウントのメールアドレス
   (`...@....iam.gserviceaccount.com`) を **編集者** として共有する。
4. 書き込み先のスプレッドシートも同じアドレスに **編集者** として共有する。

> **共有ドライブの利用を推奨します。**
> マイドライブに保存する場合、ファイルの所有者がサービスアカウントになり、
> サービスアカウント自身のストレージ容量を消費します。共有ドライブに保存すれば
> 容量は組織側で管理され、人間のメンバーからもファイルが見えます。
> （サービスアカウントを共有ドライブのメンバーに追加してください。）

### 2. 設定ファイル

```bash
cd apps/store_photo_uploader
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# secrets.toml を編集して値を埋める
```

`secrets.toml` は `.gitignore` 済みです。コミットしないでください。

| 設定 | 説明 | 既定値 |
| --- | --- | --- |
| `DRIVE_FOLDER_ID` | 保存先フォルダの ID（必須） | - |
| `SPREADSHEET_ID` | 書き込み先スプレッドシートの ID（必須） | - |
| `SHEET_NAME` | 対象シート名 | `シート1` |
| `STORE_NAME_COLUMN` | 店舗名が入っている列 | `A` |
| `LINK_COLUMN` | 共有リンクを書き込む列 | `B` |
| `FIRST_DATA_ROW` | データが始まる行 | `2` |
| `LINK_TARGET` | `folder` / `file` | `folder` |
| `MAX_FILES` | 一度に投稿できる枚数 | `10` |
| `MAX_FILE_MB` | 1 枚あたりの上限 | `20` |

すべて **環境変数でも指定できます**（環境変数が優先）。サービスアカウントの鍵は
`GOOGLE_SERVICE_ACCOUNT_JSON`（JSON 文字列）または `GOOGLE_APPLICATION_CREDENTIALS`
（ファイルパス）でも渡せるので、Streamlit Community Cloud などにデプロイする際は
そちらを使ってください。

### 3. 起動

```bash
cd apps/store_photo_uploader
pip install -r requirements.txt
streamlit run app.py
```

## 動作

- 店舗名は、スプレッドシートの `STORE_NAME_COLUMN` から読み込んだ一覧から選べます
  （一覧にない場合は手入力に切り替えられます）。
- ファイル名は `YYYYMMDD-HHMMSS_01_元のファイル名`（日本時間）で保存されるため、
  同じ店舗に何度投稿しても上書きされません。
- 店舗フォルダは同名のものがあれば再利用されるので、共有リンクは店舗ごとに一定です。
- 店舗名の照合は表記ゆれを吸収します（全角/半角、空白、大文字小文字を無視）。
- 一致する行が見つからない場合、Drive への保存は成功したうえで警告を表示し、
  シートへの書き込みだけをスキップします。
- 一致する行が複数ある場合は、そのすべてに書き込んだうえで対象行を表示します。

## テスト

店舗名の照合ロジックには単体テストがあります（Google API に接続しません）。

```bash
python -m pytest apps/store_photo_uploader/tests
```

## 構成

| ファイル | 役割 |
| --- | --- |
| `app.py` | Streamlit の画面と投稿フロー |
| `config.py` | 環境変数 / secrets からの設定読み込み |
| `google_services.py` | 認証と API クライアントの生成 |
| `drive_uploader.py` | Drive へのフォルダ作成・アップロード・共有 |
| `sheet_writer.py` | 店舗名の照合とセルへの書き込み |
