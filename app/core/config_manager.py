import json
import logging
import os

CONFIG_FILE = "db/config.json"
SCREENSHOT_DIR = "db/screenshots"
# デフォルト設定に playwright_headless を追加
DEFAULT_CONFIG = {
    "max_delay_minutes": 5,
    "playwright_headless": True,  # デフォルトはヘッドレスON
    "procurement_method": "search" # デフォルトは 'search' (楽天市場検索)
}

def get_config():
    """設定をJSONファイルから読み込む。ファイルがなければデフォルト設定を返す。"""
    if not os.path.exists(CONFIG_FILE):
        logging.info(f"{CONFIG_FILE} が見つからないため、デフォルト設定を使用します。")
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r") as f:
            config_from_file = json.load(f)
            # デフォルトにないキーがファイルにあれば無視し、ファイルにないキーはデフォルト値で補う
            config = DEFAULT_CONFIG.copy()
            config.update({k: v for k, v in config_from_file.items() if k in config})
            return config
    except (IOError, json.JSONDecodeError) as e:
        logging.error(f"{CONFIG_FILE} の読み込みに失敗しました: {e}")
        return DEFAULT_CONFIG.copy()

def save_config(config_data):
    """設定をJSONファイルに保存する。"""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config_data, f, indent=4)
        logging.debug(f"設定を {CONFIG_FILE} に保存しました。")
    except IOError as e:
        logging.error(f"設定ファイル {CONFIG_FILE} の保存に失敗しました: {e}")

def is_headless():
    """ヘッドレスモードが有効かどうかを返すヘルパー関数"""
    return get_config().get("playwright_headless", True)