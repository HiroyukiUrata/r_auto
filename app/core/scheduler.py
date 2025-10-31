import schedule
import time
import logging
import json
import os

# タスク定義を一元的にインポート
from app.core.task_definitions import TASK_DEFINITIONS
from app.core.scheduler_utils import run_threaded, run_task_with_random_delay

SCHEDULE_FILE = "db/schedules.json"

def _save_schedules_to_file(schedules_to_save):
    """
    与えられたスケジュールデータをファイルに保存する内部関数。
    データ形式:
    {
        "task-tag": {
            "enabled": true,
            "times": [
                {"time": "HH:MM", "count": 10},
                ...
            ]
        },
        ...
    }
    """
    try:
        with open(SCHEDULE_FILE, "w") as f:
            json.dump(schedules_to_save, f, indent=4, sort_keys=True)
        logging.debug(f"スケジュールを {SCHEDULE_FILE} に保存しました。")
    except IOError as e:
        logging.error(f"スケジュールファイルの保存に失敗しました: {e}")

def load_schedules_from_file():
    """ファイルからスケジュールを読み込み、ジョブを登録する"""
    if not os.path.exists(SCHEDULE_FILE):
        logging.info(f"{SCHEDULE_FILE} が見つかりません。デフォルトスケジュールを使用します。")
        return False

    try:
        with open(SCHEDULE_FILE, "r") as f:
            schedules = json.load(f)
        
        from app.web.api import _run_task_internal # フロー実行のためにインポート
        for tag, schedule_data in schedules.items():
            definition = TASK_DEFINITIONS.get(tag)
            if definition:
                # 新旧フォーマットに対応
                if isinstance(schedule_data, list): # 旧フォーマット
                    task_enabled = True
                    times = schedule_data
                else: # 新フォーマット (辞書)
                    task_enabled = schedule_data.get("enabled", True)
                    times = schedule_data.get("times", [])

                if not task_enabled:
                    logging.debug(f"タスク '{tag}' は無効化されているため、すべてのスケジュールをスキップします。")
                    continue

                # timesは {"time": "HH:MM", "count": N} のリスト
                for entry in times:
                    # タスク定義からのデフォルト引数を取得し、スケジュール固有の引数で上書き
                    job_kwargs = definition.get("default_kwargs", {}).copy()
                    job_kwargs['count'] = entry.get('count', 1)
                    logging.debug(f"  [Scheduler] Preparing job for '{tag}' at {entry['time']} with kwargs: {job_kwargs}")

                    task_func = definition.get("function")
                    if task_func:
                        if tag == "backup-database":
                            # バックアップタスクは引数を取らないので、直接呼び出す
                            schedule.every().day.at(entry['time']).do(run_threaded, task_func).tag(tag)
                            logging.debug(f"    -> Registered backup task.")
                        else:
                            # その他の通常のタスクの場合
                            job_kwargs['task_to_run'] = task_func
                            schedule.every().day.at(entry['time']).do(run_threaded, run_task_with_random_delay, **job_kwargs).tag(tag)
                    elif "flow" in definition:
                        # フロータスクの場合
                        # _run_task_internal を直接呼び出す
                        # is_part_of_flow=False を明示的に渡す
                        schedule.every().day.at(entry['time']).do(run_threaded, _run_task_internal, tag=tag, is_part_of_flow=False, **job_kwargs).tag(tag)
                        logging.debug(f"    -> Registered flow task '{tag}' with kwargs: {job_kwargs}")
                    else:
                        logging.warning(f"タスク '{tag}' には実行可能な関数またはフローが定義されていません。")

        logging.debug(f"{SCHEDULE_FILE} からスケジュールを読み込みました。")
        return True
    except (IOError, json.JSONDecodeError) as e:
        logging.error(f"{SCHEDULE_FILE} の読み込みに失敗しました: {e}")
        return False

def reload_schedules():
    """現在のスケジュールをすべてクリアし、ファイルから再読み込みする"""
    logging.debug("スケジュールの再読み込みを要求されました。")
    schedule.clear()
    load_schedules_from_file()
    logging.info(f"スケジュールが再読み込みされました。")
    #logging.info(f"スケジュールが再読み込みされました: {schedule.get_jobs()}")

def save_and_reload_schedules(schedules_to_save):
    """スケジュールをファイルに保存し、スケジューラをリロードする"""
    _save_schedules_to_file(schedules_to_save)
    reload_schedules()


def start_scheduler():
    """スケジューラを起動し、定義されたジョブを実行する"""
    logging.debug("スケジューラを起動します。")

    # ファイルからスケジュールを読み込む。失敗した場合はデフォルト設定を使用。
    if not load_schedules_from_file():
        logging.warning("デフォルトのスケジュールは設定されていません。UIから設定してください。")

    #logging.info(f"スケジュールが設定されました: {schedule.get_jobs()}")

    logging.debug(f"スケジュールが設定されました。")

    while True:
        schedule.run_pending()
        time.sleep(1)