import logging
import time
from app.test_x.tasks.base_task import BaseTask

class SampleTaskB(BaseTask):
    """サンプルタスクB: ログを出力するだけ"""
    def __init__(self):
        super().__init__(count=1)
        self.action_name = "サンプルタスクB"
        self.needs_browser = False # ブラウザは不要

    def _execute_main_logic(self):
        logging.info("タスクBを実行しました。")
        time.sleep(1)

def run_sample_task_b():
    task = SampleTaskB()
    return task.run()