import schedule
import time
import logging
import json
import os

# タスク定義を一元的にインポート
from app.core.task_definitions import TASK_DEFINITIONS
from app.web.api import _run_task_internal # フロー実行のためにインポート
from app.core.scheduler_utils import run_threaded, run_task_with_random_delay

SCHEDULE_FILE = "db/schedules.json"

def load_schedules_from_file():
    """ファイルからスケジュールを読み込み、ジョブを登録する"""
    if not os.path.exists(SCHEDULE_FILE):
        logging.info(f"{SCHEDULE_FILE} が見つかりません。デフォルトスケジュールを使用します。")
        return False

    try:
        with open(SCHEDULE_FILE, "r") as f:
            schedules = json.load(f)
        for tag, times in schedules.items():
            definition = TASK_DEFINITIONS.get(tag)
            if definition:
                # timesは {"time": "HH:MM", "count": N} のリスト
                for entry in times:
                    # タスク定義からのデフォルト引数を取得し、スケジュール固有の引数で上書き
                    job_kwargs = definition.get("default_kwargs", {}).copy()
                    job_kwargs['count'] = entry.get('count', 1)

                    task_func = definition.get("function")
                    if task_func:
                        # 通常のタスクの場合
                        job_kwargs['task_to_run'] = task_func
                        schedule.every().day.at(entry['time']).do(run_threaded, run_task_with_random_delay, **job_kwargs).tag(tag)
                    elif "flow" in definition:
                        # フロータスクの場合
                        # _run_task_internal を直接呼び出す
                        # is_part_of_flow=False を明示的に渡す
                        schedule.every().day.at(entry['time']).do(run_threaded, _run_task_internal, tag=tag, is_part_of_flow=False, **job_kwargs).tag(tag)
                    else:
                        logging.warning(f"タスク '{tag}' には実行可能な関数またはフローが定義されていません。")

        logging.info(f"{SCHEDULE_FILE} からスケジュールを読み込みました。")
        return True
    except (IOError, json.JSONDecodeError) as e:
        logging.error(f"{SCHEDULE_FILE} の読み込みに失敗しました: {e}")
        return False

def start_scheduler():
    """スケジューラを起動し、定義されたジョブを実行する"""
    logging.info("スケジューラを起動します。")

    # ファイルからスケジュールを読み込む。失敗した場合はデフォルト設定を使用。
    if not load_schedules_from_file():
        logging.info("デフォルトのスケジュールは設定されていません。UIから設定してください。")

    logging.info(f"スケジュールが設定されました: {schedule.get_jobs()}")

    while True:
        schedule.run_pending()
        time.sleep(1)