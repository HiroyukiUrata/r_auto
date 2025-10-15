import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "app.log")

def setup_logging(log_level=logging.INFO):
    """
    アプリケーションのロギングを設定します。
    - 標準出力へのストリームハンドラ
    - ローテーション機能付きのファイルハンドラ
    """
    # logsディレクトリが存在しない場合は作成
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    # ルートロガーを取得し、レベルを設定
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # 既存のハンドラをすべて削除（重複設定を防ぐため）
    if logger.hasHandlers():
        logger.handlers.clear()

    # ログのフォーマットを定義
    log_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 1. 標準出力へのハンドラ
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(log_formatter)
    logger.addHandler(stream_handler)

    # 2. ファイル出力へのハンドラ (ローテーション付き)
    # 1ファイル10MB、バックアップは5ファイルまで
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=1024 * 1024 * 10, backupCount=5, encoding='utf-8'
    )
    file_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)

    logging.info("ロギング設定が完了しました。")