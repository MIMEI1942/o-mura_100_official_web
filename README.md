# 100周年特設ページ 公開用

社内向けの 100周年特設ページを `Streamlit` で公開するためのアプリです。

## 構成

- `app.py`: Streamlit 本体
- `assets/`: ロゴや画像などの公開素材
- `members.json`: プロジェクトメンバー表示用データ
- `requirements.txt`: デプロイ時に入れる Python パッケージ
- `.github/workflows/ci.yml`: GitHub Actions の最低限の構文チェック
- `.streamlit/config.toml`: 公開時の Streamlit 表示設定

## ローカル起動

```powershell
pip install -r requirements.txt
streamlit run app.py
```

または

```powershell
py app.py
```

## GitHub 運用の前提

- `storage.sqlite3` は Git 管理から除外しています
- 公開リポジトリへ内部データを直接載せない前提です
- 初回起動時は `app.py` 内のシードデータから最低限の表示が立ち上がります

## 永続DB設定

このアプリは、`CENTENNIAL_DATABASE_URL` または `DATABASE_URL` が設定されている場合、ローカルの `storage.sqlite3` ではなく外部 PostgreSQL を使います。

Streamlit Community Cloud では `App settings > Secrets` に次のように設定してください。

```toml
CENTENNIAL_DATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require"
```

- 外部DBが有効な場合、`kv_storage` テーブルを自動作成します
- ローカルの `storage.sqlite3` に既存データがある場合は、外部DBにまだ同じキーがないときだけ初回起動時に取り込みます
- 外部DB未設定時だけ、従来通りローカル `storage.sqlite3` を使います

### Supabase で始める場合

1. Supabase で `Free Plan` の organization を作る
2. `New project` で 100周年用の project を 1つだけ作る
3. project 作成後、画面上部の `Connect` から `Session pooler` の接続文字列をコピーする
4. パスワード部分を project 作成時の DB パスワードに置き換える
5. Streamlit Community Cloud の `App settings > Secrets` に [`.streamlit/secrets.example.toml`](C:/ブラウザ用アプリ/100周年特設ページ_公開用/.streamlit/secrets.example.toml) の形で貼る
6. 再デプロイする

このアプリでは、接続先として `Session pooler` を使う前提にしています。

### 無料枠を超えにくくする運用

- Supabase は `Free Plan` のまま使う
- project は 1つに絞る
- `Storage`、`Auth`、`Realtime`、`Edge Functions` はこのアプリでは使わない
- 添付ファイルは今まで通りアプリ側のデータ URL 保存なので、Supabase Storage へ上げない
- DB サイズは `500 MB` を超えないようにする
- 長期間アクセスがないと free project は pause されうるので、必要時は Dashboard から resume する

## GitHub への載せ方

この PC では現時点で `git` コマンドが使えないため、次のどちらかが必要です。

1. `Git for Windows` を入れて `git` を使えるようにする
2. `GitHub Desktop` を入れて GUI で管理する

GitHub Desktop を使う場合の流れ:

1. GitHub Desktop で `Add an Existing Repository` か `Create a New Repository` を選ぶ
2. このフォルダ `C:\Python\100周年特設ページ_公開用` を指定する
3. GitHub 上に新規リポジトリを作成して `Publish repository` する

## 公開先のおすすめ

`Streamlit Community Cloud` を使うと、GitHub リポジトリからそのまま `app.py` を指定して公開できます。

必要になる基本設定:

- Repository: このアプリの GitHub リポジトリ
- Branch: 通常は `main`
- Main file path: `app.py`

## 公開前に見直すべき点

- `members.json` に個人名を載せるかどうか
- 投稿データを公開リポジトリに含めないか
- 添付ファイルの中に社外公開不可のものがないか

## 次にやること

1. GitHub 用にリポジトリを作る
2. このフォルダを最初のコミットとして push する
3. Streamlit Community Cloud で `app.py` を指定して公開する

## Githubアップロード方法

通常手順

PowerShell で対象フォルダへ移動
cd "C:\ブラウザ用アプリ\100周年特設ページ_公開用"
変更確認
git status
必要なら構文確認
python -m py_compile app.py
変更を追加
git add .
コミット
git commit -m "変更内容を短く説明"
GitHub へ反映
git push
もし push で弾かれた場合
GitHub 側に先の更新があるので、先に取り込みます。

git pull --rebase origin main
git push
もし競合が出た場合
今回と同じで、反映したい内容を残してから続行します。

git status
git add .
git rebase --continue
git push
最初に確認しておくとよいコマンド

git remote -v
git branch
公開まで含めた流れ

GitHub に push
Streamlit Cloud を使っているなら、その後は同じリポジトリから自動で再デプロイされることが多いです
手動再起動が必要な場合は Streamlit 側で Reboot か Redeploy
