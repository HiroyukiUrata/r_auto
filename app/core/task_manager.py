import logging
from app.core.task_definitions import TASK_DEFINITIONS

logger = logging.getLogger(__name__)

class TaskManager:
    """
    タスクの実行を管理するクラス。
    主にAPIから非同期でタスクを呼び出す際に使用する。
    """
    def run_task_by_tag(self, tag: str, **kwargs):
        """
        指定されたタグに対応するタスク関数を実行する。
        """
        definition = TASK_DEFINITIONS.get(tag)
        if not definition:
            logger.error(f"タスク定義が見つかりません: {tag}")
            return

        task_func = definition.get("function")
        if not task_func:
            logger.error(f"タスク '{tag}' に実行可能な関数が定義されていません。")
            return

        # タスク関数にキーワード引数を渡して実行
        task_func(**kwargs)