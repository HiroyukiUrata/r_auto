import threading
import uvicorn
import logging

from fastapi.templating import Jinja2Templates
from app.core.scheduler import start_scheduler
from app.web.api import app
from app.core.database import init_db

# --- アプリケーション全体で共有するテンプレート設定 ---
templates = Jinja2Templates(directory="web/templates")

def run_api_server():
    """FastAPIサーバーを起動する"""
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    # アプリケーション全体で利用するログ設定を一元化
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # スケジューラをバックグラウンドスレッドで実行
    # データベースを初期化
    init_db()

    scheduler_thread = threading.Thread(target=start_scheduler, daemon=True)
    scheduler_thread.start()

    # FastAPIサーバーをメインスレッドで実行
    # (uvicornはこちらで実行しないとホットリロードなどが機能しにくいため)
    run_api_server()
