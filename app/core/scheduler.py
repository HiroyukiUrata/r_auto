import schedule
import time
import logging
import json
import os

# タスク定義を一元的にインポート
from app.core.task_definitions import TASK_DEFINITIONS
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
                    task_func = definition["function"]
                    # 'count' を含むキーワード引数をタスクに渡す
                    job_kwargs = {'task_to_run': task_func, 'count': entry.get('count', 1)}
                    schedule.every().day.at(entry['time']).do(run_threaded, run_task_with_random_delay, **job_kwargs).tag(tag)

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
        logging.info("デフォルトのスケジュールを設定します。")
        # デフォルトの件数を設定
        post_kwargs = {'task_to_run': TASK_DEFINITIONS["post-article"]["function"], 'count': 1}
        engagement_kwargs = {'task_to_run': TASK_DEFINITIONS["run-engagement-actions"]["function"], 'count': 10}

        schedule.every().day.at("13:00").do(run_threaded, run_task_with_random_delay, **post_kwargs).tag('post-article')
        schedule.every().day.at("15:00").do(run_threaded, run_task_with_random_delay, **engagement_kwargs).tag('run-engagement-actions')
        schedule.every().day.at("22:00").do(run_threaded, run_task_with_random_delay, **engagement_kwargs).tag('run-engagement-actions')

    logging.info(f"スケジュールが設定されました: {schedule.get_jobs()}")

    while True:
        schedule.run_pending()
        time.sleep(1)