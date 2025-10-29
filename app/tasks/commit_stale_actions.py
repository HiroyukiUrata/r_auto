import logging
from app.core.base_task import BaseTask
from app.core.database import get_stale_user_ids_for_commit, commit_user_actions

logger = logging.getLogger(__name__)

class CommitStaleActionsTask(BaseTask):
    """
    一定時間以上処理されていない（投稿もスキップもされていない）ユーザーのアクションを
    自動的に「スキップ」扱いとしてコミットするタスク。
    """
    def __init__(self, hours: int = 24):
        super().__init__()
        self.action_name = "古いアクションの自動コミット"
        self.needs_browser = False # このタスクはブラウザを必要としない
        self.hours = hours

    def _execute_main_logic(self):
        logger.debug(f"--- {self.hours}時間以上経過した未処理のアクションを検索・コミットします ---")
        try:
            stale_user_ids = get_stale_user_ids_for_commit(hours=self.hours)
            if not stale_user_ids:
                logger.debug("自動コミット対象のユーザーはいません。")
                return True
            
            logger.debug(f"{len(stale_user_ids)}人のユーザーのアクションを自動コミットします。")
            commit_user_actions(stale_user_ids, is_comment_posted=False)
            return True
        except Exception as e:
            logger.error(f"古いアクションの自動コミット中にエラーが発生しました: {e}", exc_info=True)
            return False

def run_commit_stale_actions(hours: int = 24):
    """ラッパー関数"""
    task = CommitStaleActionsTask(hours=hours)
    return task.run()