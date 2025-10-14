import logging
import shutil
import os
import time
from playwright.sync_api import sync_playwright
from app import locators

PROFILE_DIR = "db/playwright_profile"
BACKUP_PROFILE_DIR = "db/playwright_profile_backup"

class SaveAuthStateTestTask:
    """
    【検証用】VNC経由で手動ログインし、認証プロファイルを永続化するタスク
    """
    def __init__(self):
        self.action_name = "【検証用】認証状態の保存"

    def run(self):
        logging.info(f"「{self.action_name}」タスクを開始します。")
        logging.info("VNCクライアントで localhost:5900 に接続してください。")
        logging.info("ログインが完了すると、このタスクは自動で終了します。")

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
                    env={"DISPLAY": ":0"},
                ) as context:
                    page = context.pages[0] if context.pages else context.new_page()
                    page.goto("https://room.rakuten.co.jp/items", wait_until="domcontentloaded", timeout=60000)
                    
                    logging.info("ブラウザを起動しました。ログイン操作を行ってください。")
                    logging.info("ログイン完了を待機しています... (最大5分)")
                    my_room_link_locator = page.locator(locators.MY_ROOM_LINK)
                    my_room_link_locator.wait_for(state='visible', timeout=300000)
    
                    logging.info("ログインが確認できました。3秒後にブラウザを閉じます。")
                    time.sleep(3)

                    try:
                        logging.info("認証プロファイルのバックアップを作成します...")
                        if os.path.exists(BACKUP_PROFILE_DIR):
                            shutil.rmtree(BACKUP_PROFILE_DIR)
                        ignore_patterns = shutil.ignore_patterns('Singleton*', '*.lock', '*Cache*')
                        shutil.copytree(PROFILE_DIR, BACKUP_PROFILE_DIR, ignore=ignore_patterns)
                        logging.info(f"プロファイルのバックアップを {BACKUP_PROFILE_DIR} に作成しました。")
                    except Exception as e:
                        logging.error(f"プロファイルのバックアップ作成中にエラーが発生しました: {e}")
                    
                    logging.info("認証状態の保存タスク成功。Trueを返します。")
                    return True
        except Exception as e:
            logging.error(f"認証状態の保存中にエラーが発生しました: {e}")
            logging.error("認証状態の保存タスク失敗。Falseを返します。")
            return False

def run_save_auth_state_test():
    """ラッパー関数"""
    task = SaveAuthStateTestTask()
    return task.run()