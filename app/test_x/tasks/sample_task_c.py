import logging
import time
from app.test_x.tasks.base_task import BaseTask

class SampleTaskC(BaseTask):
    """サンプルタスクC: ログを出力するだけ"""
    def __init__(self):
        super().__init__(count=1)
        self.action_name = "サンプルタスクC"
        self.needs_browser = False # ブラウザは不要

    def _execute_main_logic(self):
        logging.info("タスクCを実行しました。")
        time.sleep(1)

def run_sample_task_c():
    task = SampleTaskC()
    return task.run()