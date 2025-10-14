import logging
import time
from app.test_x.tasks.base_task import BaseTask

class SampleErrorLogTask(BaseTask):
    """
    意図的にエラーを発生させるタスクの実装例。
    """
    def __init__(self):
        super().__init__(count=1)
        self.action_name = "サンプル・エラーログ"
        self.needs_browser = False # ブラウザは不要

    def _execute_main_logic(self):
        logging.info("エラー発生タスクを開始します。3秒後にエラーが発生します。")
        time.sleep(3)
        raise RuntimeError("これは動作確認のための意図的なランタイムエラーです。")

def run_sample_error_log_task():
    task = SampleErrorLogTask()
    return task.run()