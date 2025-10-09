import logging
from playwright.sync_api import sync_playwright
import time
import os
from app import locators

PROFILE_DIR = "db/playwright_profile"

def save_auth_state():
    """VNC経由で手動ログインし、認証プロファイルを永続化するタスク"""
    logging.info("認証状態の保存タスクを開始します。")
    logging.info("VNCクライアントで localhost:5900 に接続してください。")
    logging.info("ログインが完了すると、このタスクは自動で終了します。")

    # プロファイルロックファイルを削除して、多重起動エラーを防ぐ
    lockfile_path = os.path.join(PROFILE_DIR, "SingletonLock")
    if os.path.exists(lockfile_path):
        logging.warning(f"古いロックファイル {lockfile_path} が見つかったため、削除します。")
        os.remove(lockfile_path)

    try:
        with sync_playwright() as p:
            with p.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                headless=False,
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
                env={"DISPLAY": ":0"}, # 仮想ディスプレイを指定
            ) as context:
                page = context.pages[0] if context.pages else context.new_page()
                # 指定されたURLにアクセス
                page.goto("https://room.rakuten.co.jp/items", wait_until="domcontentloaded", timeout=60000)
                
                logging.info("ブラウザを起動しました。ログイン操作を行ってください。")
 
                # ログイン後に表示される「my ROOM」リンクが表示されるまで最大5分間待機します
                logging.info("ログイン完了を待機しています... (最大5分)")
                my_room_link_locator = page.locator(locators.MY_ROOM_LINK)
                my_room_link_locator.wait_for(state='visible', timeout=300000)
 
                logging.info("ログインが確認できました。3秒後にブラウザを閉じます。")
                time.sleep(3)
 
                return True
    except Exception as e:
        logging.error(f"認証状態の保存中にエラーが発生しました: {e}")
        return False