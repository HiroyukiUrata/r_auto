import threading
import uvicorn
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.core.scheduler import start_scheduler
from app.web.api import router as api_router
from app.core.database import init_db
from app.core.logging_config import setup_logging

# アプリケーション起動時にロギングを設定
setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリケーションのライフサイクル（起動・終了時）を管理します。"""

    # データベースを初期化
    init_db()

    # スケジューラをバックグラウンドスレッドで実行
    scheduler_thread = threading.Thread(target=start_scheduler, daemon=True)
    scheduler_thread.start()
    
    yield
    
    # --- 終了時の処理（もし将来的に必要ならここに書く） ---

app = FastAPI(
    title="R-Auto Control Panel",
    description="システムの稼働状況やスケジュールを管理するWeb UI",
    lifespan=lifespan
)

# 静的ファイル（CSS, JS, faviconなど）を配信するためのマウント
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# --- テンプレート設定 ---
templates = Jinja2Templates(directory="web/templates")
# テンプレート内で環境変数を読めるようにする
templates.env.globals['getenv'] = os.getenv
app.state.templates = templates

# APIルーターを登録
app.include_router(api_router)
