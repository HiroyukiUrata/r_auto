import logging
from playwright.sync_api import sync_playwright
import os

PROFILE_DIR = "db/playwright_profile"

def save_auth_state():
    """VNC経由で手動ログインし、認証プロファイルを永続化するタスク"""
    logging.info("認証状態の保存タスクを開始します。")
    logging.info("VNCクライアントで localhost:5900 に接続してください。")

    # プロファイルロックファイルを削除して、多重起動エラーを防ぐ
    lockfile_path = os.path.join(PROFILE_DIR, "SingletonLock")
    if os.path.exists(lockfile_path):
        logging.warning(f"古いロックファイル {lockfile_path} が見つかったため、削除します。")
        os.remove(lockfile_path)

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
            page.goto("https://room.rakuten.co.jp/myroom", wait_until="networkidle", timeout=60000)
            logging.info("ブラウザを起動しました。ログイン操作を行ってください。")
            input("VNCでログイン操作が完了したら、このコンソールでEnterキーを押してください...")
            context.close()
            logging.info(f"認証状態を {PROFILE_DIR} に保存しました。")
            return True
    except Exception as e:
        logging.error(f"認証状態の保存中にエラーが発生しました: {e}")
        return False