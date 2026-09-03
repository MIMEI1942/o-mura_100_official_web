@echo off
rem 店舗写真アップロードフォームをローカルサーバとして起動する。
rem 同じ LAN 内の PC・スマートフォンのブラウザからアクセスできる。
rem 初回のみ: pip install -r requirements.txt

cd /d "%~dp0"

if not exist ".streamlit\secrets.toml" (
    echo [!] .streamlit\secrets.toml がありません。
    echo     .streamlit\secrets.toml.example をコピーして設定してください。
    pause
    exit /b 1
)

echo このPCのIPアドレス:
ipconfig | findstr /C:"IPv4"
echo.
echo 上記のアドレスに :8501 を付けてブラウザで開いてください。
echo 例: http://192.168.1.10:8501
echo 終了するには、このウィンドウで Ctrl + C を押してください。
echo.

streamlit run app.py --server.address 0.0.0.0 --server.port 8501
pause
