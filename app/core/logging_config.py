import logging
import os
import re

# --- TRACEログレベルの追加 ---
TRACE_LEVEL_NUM = 5
logging.addLevelName(TRACE_LEVEL_NUM, "TRACE")
def trace(self, message, *args, **kws):
    if self.isEnabledFor(TRACE_LEVEL_NUM):
        self._log(TRACE_LEVEL_NUM, message, args, **kws)
logging.Logger.trace = trace
# --- ここまで ---

class EndpointFilter(logging.Filter):
    """特定のパスへのアクセスログをフィルタリングするクラス"""
    def __init__(self, path: str):
        super().__init__()
        self._path = path

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicornのアクセスログは 'uvicorn.access' という名前で記録される
        # ログメッセージに指定されたパスが含まれていない場合にTrueを返す
        return self._path not in record.getMessage()

class PlaywrightLogFilter(logging.Filter):
    """Playwrightの冗長な 'Call log:' をログメッセージから削除するフィルタ"""
    def filter(self, record: logging.LogRecord) -> bool:
        # record.getMessage() はフォーマット前の生のログメッセージを返す
        original_message = record.getMessage()
        # メッセージに "Call log:" が含まれているか確認
        call_log_pos = original_message.find("Call log:")
        if call_log_pos != -1:
            # "Call log:" より前の部分だけをメッセージとして採用し、末尾の空白を削除
            record.msg = original_message[:call_log_pos].strip()
        return True # 常にログを通過させる

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
    # 新しく追加したTRACEレベルに対応
    if log_level_str == 'TRACE':
        log_level = TRACE_LEVEL_NUM
    else:
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

    # 本番環境(simple)の場合、Playwrightの冗長なログを抑制する
    if log_format_type == 'simple':
        playwright_logger = logging.getLogger("playwright")
        playwright_logger.setLevel(logging.WARNING)
        # ルートロガーにフィルタを追加して、すべてのログに適用
        logging.getLogger().addFilter(PlaywrightLogFilter())

    logging.debug(f"ロギング設定が完了しました。ログレベル: {log_level_str}, フォーマット: {log_format_type}")