import logging
import shutil
import os

from app.core.base_task import BaseTask

PROFILE_DIR = "db/playwright_profile"
BACKUP_PROFILE_DIR = "db/playwright_profile_backup"

class RestoreAuthStateTask(BaseTask):
    """
    バックアップからPlaywrightの認証プロファイルを復元するタスク。
    ログインセッションが切れた際の高速な復旧を目的とする。
    """
    def __init__(self):
        super().__init__()
        self.action_name = "認証プロファイルの復元"
        self.needs_browser = False # このタスクはブラウザを起動しない

    def _execute_main_logic(self):
        logging.info(f"「{self.action_name}」タスクを開始します。")

        if not os.path.exists(BACKUP_PROFILE_DIR):
            logging.error(f"バックアップディレクトリが見つかりません: {BACKUP_PROFILE_DIR}")
            logging.error("復元に失敗しました。先に「認証状態の保存」タスクを実行してバックアップを作成してください。")
            return False

        # プロファイルが現在使用中かどうかを確認
        lockfile_path = os.path.join(PROFILE_DIR, "SingletonLock")
        if os.path.exists(lockfile_path):
            logging.error(f"プロファイルが現在使用中のようです（ロックファイルが存在します: {lockfile_path}）。")
            logging.error("実行中の他のブラウザタスクが完了してから、再度試してください。")
            return False

        try:
            logging.debug(f"現在のプロファイルディレクトリ {PROFILE_DIR} を削除します。")
            if os.path.exists(PROFILE_DIR):
                shutil.rmtree(PROFILE_DIR)

            logging.debug(f"バックアップ {BACKUP_PROFILE_DIR} からプロファイルをコピーしています...")
            shutil.copytree(BACKUP_PROFILE_DIR, PROFILE_DIR)

            logging.info("認証プロファイルの復元に成功しました。")
            return True

        except Exception as e:
            logging.error(f"認証プロファイルの復元中に予期せぬエラーが発生しました: {e}", exc_info=True)
            return False

def run_restore_auth_state():
    """ラッパー関数"""
    task = RestoreAuthStateTask()
    return task.run()