import logging
import shutil
import os

from app.core.base_task import BaseTask
from app.core.base_task import PRIMARY_PROFILE_DIR, SECONDARY_PROFILE_DIR, BACKUP_PROFILE_DIR

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

        # 両方のプロファイルが使用中でないか確認
        for profile_dir in [PRIMARY_PROFILE_DIR, SECONDARY_PROFILE_DIR]:
            lockfile_path = os.path.join(profile_dir, "SingletonLock")
            if os.path.exists(lockfile_path):
                logging.error(f"プロファイルが現在使用中のようです（ロックファイルが存在します: {lockfile_path}）。")
                logging.error("実行中の他のブラウザタスクが完了してから、再度試してください。")
                return False

        try:
            # 1. プライマリとセカンダリの両方のプロファイルを削除
            for profile_dir in [PRIMARY_PROFILE_DIR, SECONDARY_PROFILE_DIR]:
                logging.debug(f"現在のプロファイルディレクトリ {profile_dir} を削除します。")
                if os.path.exists(profile_dir):
                    shutil.rmtree(profile_dir)

            # 2. バックアップからプライマリプロファイルを復元
            logging.info(f"バックアップからプライマリプロファイル ({PRIMARY_PROFILE_DIR}) を復元します...")
            shutil.copytree(BACKUP_PROFILE_DIR, PRIMARY_PROFILE_DIR)
            
            # 3. バックアップからセカンダリプロファイルを復元
            logging.info(f"バックアップからセカンダリプロファイル ({SECONDARY_PROFILE_DIR}) を復元します...")
            shutil.copytree(BACKUP_PROFILE_DIR, SECONDARY_PROFILE_DIR)

            logging.info("認証プロファイルの復元に成功しました。")
            return True

        except Exception as e:
            logging.error(f"認証プロファイルの復元中に予期せぬエラーが発生しました: {e}", exc_info=True)
            return False

def run_restore_auth_state():
    """ラッパー関数"""
    task = RestoreAuthStateTask()
    return task.run()