import threading
import logging
import time
import random
import os
import re
from datetime import datetime, timedelta
from app.core.logging_config import LOG_FILE

logger = logging.getLogger(__name__)

def run_threaded(job_func, *args, **kwargs):
    """
    ジョブを別スレッドで実行するためのラッパー関数。
    結果を格納するためのコンテナを返す。
    """
    result_container = {}
    def wrapper():
        try:
            result = job_func(*args, **kwargs)
            result_container['result'] = result
        except Exception as e:
            logger.error(f"スレッド実行中にエラーが発生: {e}", exc_info=True)
            result_container['result'] = e
            result_container['error'] = True

    job_thread = threading.Thread(target=wrapper)
    job_thread.start()
    return job_thread, result_container

def run_task_with_random_delay(task_to_run, **kwargs):
    """
    タスクを実行する前にランダムな遅延を追加する。
    """
    from app.core.config_manager import get_config
    config = get_config()
    max_delay_minutes = config.get('max_delay_minutes', 0)
    
    if max_delay_minutes > 0:
        delay_seconds = random.randint(0, max_delay_minutes * 60)
        logger.info(f"スケジュールされたタスクの実行を {delay_seconds // 60}分{delay_seconds % 60}秒 遅延させます。")
        time.sleep(delay_seconds)
    
    task_to_run(**kwargs)

def get_log_summary(period='24h'):
    """過去指定期間内のログを解析してサマリーを返す"""
    summary = {
        'actions': {
            '商品調達': {'count': 0, 'errors': 0},
            '投稿': {'count': 0, 'errors': 0},
            'いいね': {'count': 0, 'errors': 0},
            'フォロー': {'count': 0, 'errors': 0}
        }
    }
    if not os.path.exists(LOG_FILE):
        return summary

    if period == 'today':
        cutoff_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    else: # デフォルトは '24h'
        try:
            # '24h' のような形式を想定
            hours = int(re.sub(r'\D', '', period))
            cutoff_time = datetime.now() - timedelta(hours=hours)
        except (ValueError, TypeError):
            cutoff_time = datetime.now() - timedelta(hours=24) # 不正な値の場合は24時間
    action_summary_pattern = re.compile(r"\[Action Summary\] name=([^,]+), count=(\d+)")
    error_pattern = re.compile(r"ERROR")
    timestamp_pattern = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

    with open(LOG_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            ts_match = timestamp_pattern.match(line)
            if not ts_match:
                continue
            
            try:
                log_time = datetime.strptime(ts_match.group(0), "%Y-%m-%d %H:%M:%S")
                if log_time < cutoff_time:
                    continue
            except ValueError:
                continue

            # アクション成功件数の集計
            match = action_summary_pattern.search(line)
            if match:
                action_name, count_str = match.groups()
                if action_name in summary['actions']:
                    summary['actions'][action_name]['count'] += int(count_str)
            
            # エラー件数の集計
            if error_pattern.search(line):
                # エラーログからアクション名を特定する（簡易版）
                if 'いいね' in line:
                    summary['actions']['いいね']['errors'] += 1
                elif 'フォロー' in line:
                    summary['actions']['フォロー']['errors'] += 1
                elif '投稿' in line:
                    summary['actions']['投稿']['errors'] += 1
                elif '調達' in line or 'procure' in line:
                    summary['actions']['商品調達']['errors'] += 1
    
    return summary