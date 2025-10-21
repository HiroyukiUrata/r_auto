import json
import logging
import os

CONFIG_FILE = "db/config.json"
SCREENSHOT_DIR = "db/screenshots"
# デフォルト設定に playwright_headless を追加
DEFAULT_CONFIG = {
    "max_delay_minutes": 5,
    "playwright_headless": True,  # デフォルトはヘッドレスON
    "procurement_method": "rakuten_search", # デフォルトは 'rakuten_search' (楽天市場検索)
    "caption_creation_method": "api" # デフォルトは 'api' (Gemini API)
}

_config_cache = None

def clear_config_cache():
    """設定のキャッシュをクリアする"""
    global _config_cache
    _config_cache = None
    logging.debug("設定キャッシュをクリアしました。")

def get_config():
    """設定をJSONファイルから読み込む。ファイルがなければデフォルト設定を返す。"""
    global _config_cache
    if _config_cache is not None:
        logging.debug("設定キャッシュから設定を読み込みました。")
        return _config_cache

    if not os.path.exists(CONFIG_FILE):
        logging.info(f"{CONFIG_FILE} が見つからないため、デフォルト設定を使用します。")
        _config_cache = DEFAULT_CONFIG.copy()
        logging.debug(f"キャッシュにデフォルト設定を保存しました: {_config_cache}")
        return _config_cache
    try:
        logging.debug(f"{CONFIG_FILE} から設定を読み込みます。")
        with open(CONFIG_FILE, "r") as f:
            config_from_file = json.load(f)
            # デフォルトにないキーがファイルにあれば無視し、ファイルにないキーはデフォルト値で補う
            config = DEFAULT_CONFIG.copy()
            config.update({k: v for k, v in config_from_file.items() if k in config})
            _config_cache = config
            logging.debug(f"キャッシュにファイルから読み込んだ設定を保存しました: {_config_cache}")
            return _config_cache
    except (IOError, json.JSONDecodeError) as e:
        logging.error(f"{CONFIG_FILE} の読み込みに失敗しました: {e}")
        _config_cache = DEFAULT_CONFIG.copy()
        return _config_cache

def save_config(config_data):
    """設定をJSONファイルに保存する。"""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config_data, f, indent=4)
        logging.info(f"設定を {CONFIG_FILE} に保存しました: {config_data}")
    except IOError as e:
        logging.error(f"設定ファイル {CONFIG_FILE} の保存に失敗しました: {e}")

def is_headless():
    """ヘッドレスモードが有効かどうかを返すヘルパー関数"""
    return get_config().get("playwright_headless", True)