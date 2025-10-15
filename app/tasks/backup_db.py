import logging
import os
import shutil
from datetime import datetime

DB_FILE = "db/products.db"
BACKUP_DIR = "db/backup"
MAX_BACKUPS = 5 # 保持するバックアップの最大数

class BackupDatabaseTask:
    """
    データベースファイルをバックアップするタスク。
    """
    def __init__(self):
        self.action_name = "データベースバックアップ"

    def run(self):
        logging.info(f"「{self.action_name}」タスクを開始します。")
        try:
            # 1. バックアップを作成
            os.makedirs(BACKUP_DIR, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_filename = f"products_{timestamp}.db"
            backup_filepath = os.path.join(BACKUP_DIR, backup_filename)
            
            if not os.path.exists(DB_FILE):
                logging.warning(f"バックアップ対象のデータベースファイルが見つかりません: {DB_FILE}")
                return False

            shutil.copy2(DB_FILE, backup_filepath)
            
            logging.info(f"データベースのバックアップを作成しました: {backup_filepath}")

            # 2. 古いバックアップを削除
            self._cleanup_old_backups()

            return True
        except Exception as e:
            logging.error(f"データベースのバックアップ中にエラーが発生しました: {e}", exc_info=True)
            return False

    def _cleanup_old_backups(self):
        """古いバックアップファイルを削除して、最大保持数を超えないようにする"""
        logging.info(f"古いバックアップのクリーンアップ処理を開始します（最大保持数: {MAX_BACKUPS}件）。")
        try:
            backup_files = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith("products_") and f.endswith(".db")])

            if len(backup_files) > MAX_BACKUPS:
                files_to_delete = backup_files[:-MAX_BACKUPS]
                logging.info(f"保持数を超えたため、{len(files_to_delete)}件の古いバックアップを削除します。")
                for filename in files_to_delete:
                    filepath = os.path.join(BACKUP_DIR, filename)
                    os.remove(filepath)
                    logging.info(f"  - 削除しました: {filepath}")
        except Exception as e:
            logging.error(f"古いバックアップの削除中にエラーが発生しました: {e}", exc_info=True)

def run_backup_database(**kwargs):
    """ラッパー関数。スケジューラから渡される可能性のある不要な引数を受け取れるようにする。"""
    logging.debug(f"バックアップタスクが引数 {kwargs} で呼び出されましたが、引数は無視されます。")
    task = BackupDatabaseTask()
    return task.run()