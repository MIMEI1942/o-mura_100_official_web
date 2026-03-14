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
