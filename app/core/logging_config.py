import logging
import os

class EndpointFilter(logging.Filter):
    """特定のパスへのアクセスログをフィルタリングするクラス"""
    def __init__(self, path: str):
        super().__init__()
        self._path = path

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicornのアクセスログは 'uvicorn.access' という名前で記録される
        # ログメッセージに指定されたパスが含まれていない場合にTrueを返す
        return self._path not in record.getMessage()

# ログファイルのパスをモジュールレベルで定義
LOG_DIR = "db/logs"
LOG_FILE = os.path.join(LOG_DIR, "app.log")


def setup_logging():
    """
    アプリケーションのロギングを設定します。
    - 環境変数 LOG_LEVEL からログレベルを決定します (デフォルト: INFO)。
    - 標準出力へのストリームハンドラ
    - ローテーション機能付きのファイルハンドラ
    """
    # 環境変数からログレベルを取得
    log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    # 環境変数からログフォーマットタイプを取得 (detailed / simple)
    log_format_type = os.getenv('LOG_FORMAT', 'detailed').lower()

    os.makedirs(LOG_DIR, exist_ok=True)

    # ルートロガーを取得し、レベルを設定
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # 既存のハンドラをクリアして重複を防ぐ
    if logger.hasHandlers():
        logger.handlers.clear()

    # 環境変数に応じてログのフォーマットを切り替える
    if log_format_type == 'simple':
        # 本番環境向けのシンプルなフォーマット
        log_formatter = logging.Formatter(
            '%(asctime)s [%(levelname).1s] %(message)s',
            datefmt='%m-%d %H:%M:%S'
        )
    else: # 'detailed' またはその他の場合
        # 開発環境向けの詳細なフォーマット
        log_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s'
        )

    # 1. 標準出力へのハンドラ
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(log_formatter)
    stream_handler.addFilter(EndpointFilter(path="/api/logs")) # ログ表示API自体のログは除外
    logger.addHandler(stream_handler)

    # 2. ファイル出力へのハンドラ (ローテーション付き)
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8'
    )
    file_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)

    # uvicornのアクセスログにフィルタを追加して、/api/logsへのログを非表示にする
    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    uvicorn_access_logger.addFilter(EndpointFilter(path="/api/logs"))

    logging.debug(f"ロギング設定が完了しました。ログレベル: {log_level_str}, フォーマット: {log_format_type}")