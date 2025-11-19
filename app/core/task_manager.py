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

        # フロータスクか、通常のタスクかを判定
        if "flow" in definition:
            # フロータスクの場合、api.pyのフロー実行関数を呼び出す
            # 循環インポートを避けるため、ここでインポートする
            from app.web.api import _run_task_internal
            logger.debug(f"フロータスク '{tag}' を実行します。")
            _run_task_internal(tag=tag, is_part_of_flow=False, **kwargs)
        else:
            # 通常のタスクの場合
            task_func = definition.get("function")
            if not task_func:
                logger.error(f"タスク '{tag}' に実行可能な関数が定義されていません。")
                return

            # タスク関数にキーワード引数を渡して実行
            logger.debug(f"通常タスク '{tag}' を実行します。")
            task_func(**kwargs)