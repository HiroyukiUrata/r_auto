import json
import logging
import os

CONFIG_FILE = "db/config.json"
DEFAULT_CONFIG = {
    "max_delay_minutes": 30
}

def get_config():
    """設定をファイルから読み込む。見つからない場合はデフォルトを返す。"""
    if not os.path.exists(CONFIG_FILE):
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        logging.error(f"{CONFIG_FILE} の読み込みに失敗しました。デフォルト設定を返します。: {e}")
        return DEFAULT_CONFIG

def save_config(config_data):
    """設定データをファイルに保存する。"""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config_data, f, indent=4)
        logging.info(f"設定を {CONFIG_FILE} に保存しました。")
    except IOError as e:
        logging.error(f"設定ファイルへの保存に失敗しました: {e}")