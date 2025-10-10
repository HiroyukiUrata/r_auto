import time
import random
import threading
import logging
from app.core.config_manager import get_config

def run_task_with_random_delay(task_to_run, max_delay_minutes=None, **task_kwargs):
    """
    タスクを指定された最大遅延時間内のランダムな時間待機してから実行する。
    タスク自体に渡す引数も受け取れるようにする。
    """
    if max_delay_minutes is None:
        max_delay_minutes = get_config().get("max_delay_minutes", 30)
    delay_seconds = random.randint(0, max_delay_minutes * 60)
    logging.info(f"タスク '{task_to_run.__name__}' は {delay_seconds // 60} 分 {delay_seconds % 60} 秒後に実行されます。")
    time.sleep(delay_seconds)
    task_to_run(**task_kwargs)

def run_threaded(job_func, *args, **kwargs):
    """タスクを別スレッドで実行するためのラッパー"""
    result_container = {}
    def wrapper():
        try:
            result = job_func(*args, **kwargs)
            result_container['result'] = result
        except Exception as e:
            result_container['error'] = e
    job_thread = threading.Thread(target=wrapper)
    job_thread.start()
    return job_thread, result_container