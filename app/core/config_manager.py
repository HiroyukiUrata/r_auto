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
    "caption_creation_method": "api", # デフォルトは 'api' (Gemini API)
    "debug_screenshot_enabled": False, # デバッグ目的のスクリーンショット撮影を有効にするか
    "preferred_profile": "primary" # 優先プロファイルのデフォルト値を追加
}

_config_cache = None

def clear_config_cache():
    """設定のキャッシュをクリアする"""
    global _config_cache
    if _config_cache is not None:
        _config_cache = None
        #logging.info("[CACHE] 設定キャッシュをクリアしました。")
    else:
        logging.debug("[CACHE] 設定キャッシュは既に空でした。")

def get_config():
    """設定をJSONファイルから読み込む。ファイルがなければデフォルト設定を返す。"""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    if not os.path.exists(CONFIG_FILE):
        logging.info(f"{CONFIG_FILE} が見つからないため、デフォルト設定を使用します。")
        _config_cache = DEFAULT_CONFIG.copy()
        return _config_cache
    try:
        logging.debug(f"[CONFIG] {CONFIG_FILE} から設定を読み込みます。")
        with open(CONFIG_FILE, "r") as f:
            config_from_file = json.load(f)
            # デフォルト設定をベースに、ファイルから読み込んだ設定で上書きする
            # これにより、ファイルに保存されている未知のキー（例: preferred_profile）も保持される
            config = DEFAULT_CONFIG.copy()
            config.update(config_from_file)
            _config_cache = config
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
        #logging.info(f"[CONFIG] 設定を {CONFIG_FILE} に保存しました: {config_data}")
        # ファイルに保存した直後にキャッシュをクリアする
        clear_config_cache()
    except IOError as e:
        logging.error(f"設定ファイル {CONFIG_FILE} の保存に失敗しました: {e}")

def is_headless():
    """ヘッドレスモードが有効かどうかを返すヘルパー関数"""
    return get_config().get("playwright_headless", True)