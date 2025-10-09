import logging
from playwright.sync_api import sync_playwright
import time
import subprocess

PROFILE_DIR = "db/playwright_profile"

def save_auth_state():
    """VNC経由で手動ログインし、認証プロファイルを永続化するタスク"""
    logging.info("認証状態の保存タスクを開始します。")
    logging.info("VNCクライアントで localhost:5900 に接続してください。")
    logging.info("ログインが完了すると、このタスクは自動で終了します。")

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                headless=False,
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
                env={"DISPLAY": ":0"}, # 仮想ディスプレイを指定
            )
            page = context.new_page()
            page.goto("https://room.rakuten.co.jp/", wait_until="domcontentloaded", timeout=60000)
            
            logging.info("ブラウザを起動しました。ログイン操作を行ってください。")
            
            # ログインが完了するまで待機（myroomページにリダイレクトされるか、myroomへのリンクが表示されるのを待つ）
            page.wait_for_url("https://room.rakuten.co.jp/myroom", timeout=300000) # 5分間待機

            logging.info("ログインが確認できました。認証プロファイルを保存して終了します。")
            context.close()
    except Exception as e:
        logging.error(f"認証状態の保存中にエラーが発生しました: {e}")