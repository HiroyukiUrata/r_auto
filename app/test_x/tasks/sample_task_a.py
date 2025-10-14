import logging
import time
from app.test_x.tasks.base_task import BaseTask

class SampleTaskA(BaseTask):
    """サンプルタスクA: ログを出力するだけ"""
    def __init__(self):
        super().__init__(count=1)
        self.action_name = "サンプルタスクA"
        self.needs_browser = False # ブラウザは不要

    def _execute_main_logic(self):
        logging.info("タスクAを実行しました。")
        time.sleep(1)

def run_sample_task_a():
    task = SampleTaskA()
    return task.run()