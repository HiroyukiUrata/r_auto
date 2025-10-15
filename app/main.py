import threading
import uvicorn
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
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
    # --- 起動時の処理 ---
    # アプリケーション全体で共有するテンプレート設定をapp.stateに格納
    app.state.templates = Jinja2Templates(directory="web/templates")

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

# APIルーターを登録
app.include_router(api_router)
