import logging
import shutil
import os
import time
from playwright.sync_api import sync_playwright
from app.core.base_task import PRIMARY_PROFILE_DIR, BACKUP_PROFILE_DIR

class SaveAuthStateTask:
    """
    VNC経由で手動ログインし、認証プロファイルを永続化するタスク
    """
    def __init__(self):
        self.action_name = "認証状態の保存"

    def run(self):
        logging.info(f"「{self.action_name}」タスクを開始します。")
        logging.debug("VNCクライアントで localhost:5900 に接続してください。")
        logging.debug("ログインが完了すると、このタスクは自動で終了します。")

        lockfile_path = os.path.join(PRIMARY_PROFILE_DIR, "SingletonLock")
        if os.path.exists(lockfile_path):
            logging.warning(f"古いロックファイル {lockfile_path} が見つかったため、削除します。")
            os.remove(lockfile_path)
        
        # プロファイルディレクトリが存在しない場合は作成する
        os.makedirs(PRIMARY_PROFILE_DIR, exist_ok=True)

        try:
            with sync_playwright() as p:
                with p.chromium.launch_persistent_context(
                    user_data_dir=PRIMARY_PROFILE_DIR,
                    headless=False,
                    locale="ja-JP",
                    timezone_id="Asia/Tokyo",
                    env={"DISPLAY": ":0"},
                ) as context:
                    page = context.pages[0] if context.pages else context.new_page()
                    page.goto("https://room.rakuten.co.jp/items", wait_until="domcontentloaded", timeout=60000)
                    
                    logging.debug("ブラウザを起動しました。ログイン操作を行い、完了したらブラウザを閉じてください。")
                    logging.debug("ブラウザが閉じられるのを待機しています...")
                    # ユーザーがブラウザを閉じるまで無期限に待機する
                    context.wait_for_event("close", timeout=0)
                    logging.debug("ブラウザが閉じられたため、処理を続行します。")

                    try:
                        logging.debug("認証プロファイルのバックアップを作成します...")
                        if os.path.exists(BACKUP_PROFILE_DIR):
                            shutil.rmtree(BACKUP_PROFILE_DIR)
                        ignore_patterns = shutil.ignore_patterns('Singleton*', '*.lock', '*Cache*')
                        shutil.copytree(PRIMARY_PROFILE_DIR, BACKUP_PROFILE_DIR, ignore=ignore_patterns)
                        logging.debug(f"プロファイルのバックアップを {BACKUP_PROFILE_DIR} に作成しました。")
                    except Exception as e:
                        logging.error(f"プロファイルのバックアップ作成中にエラーが発生しました: {e}")
                    
                    logging.info("認証状態の保存タスク成功。")
                    return True
        except Exception as e:
            logging.error(f"認証状態の保存中にエラーが発生しました: {e}")
            logging.error("認証状態の保存タスク失敗。Falseを返します。")
            return False

def run_save_auth_state():
    """ラッパー関数"""
    task = SaveAuthStateTask()
    return task.run()