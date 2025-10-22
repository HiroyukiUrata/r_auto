import threading
import logging
import time
import random
import re
import os
from datetime import datetime, timedelta, timezone
from app.core.logging_config import LOG_FILE
from app.core.task_definitions import TASK_DEFINITIONS

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
    logging.debug(f"遅延実行のための設定を読み込みました: {config}")
    max_delay_minutes = config.get('max_delay_minutes', 0)
    
    if max_delay_minutes > 0:
        delay_seconds = random.randint(0, max_delay_minutes * 60)
        logger.info(f"スケジュールされたタスクの実行を {delay_seconds // 60}分{delay_seconds % 60}秒 遅延させます。")
        time.sleep(delay_seconds)
    
    task_to_run(**kwargs)

def get_last_activity_from_log(max_lines=500):
    """
    ログファイルを末尾から読み込み、直近の「成功」または「エラー」アクティビティを返す。
    """
    try:
        if not os.path.exists(LOG_FILE):
            return None

        # ログ名とUI表示名をマッピング
        log_name_to_ui_name = {
            "投稿": "記事投稿",
            "いいね": "いいね活動",
            "フォロー": "フォロー活動",
            "商品調達": "商品調達",
        }

        # 正規表現パターン
        summary_pattern = re.compile(r"\[Action Summary\]\s*name=(?P<name>[^,]+),\s*count=(?P<count>\d+)")
        error_pattern = re.compile(r"「(?P<name>[^」]+)」(?:アクション中に|実行中に|が失敗しました)")
        timestamp_pattern = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}|\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

        with open(LOG_FILE, "r", encoding="utf-8") as f:
            # ファイルの末尾から効率的に読み込む（ただし、ここでは可読性のため単純な方法を採る）
            lines = f.readlines()
            
            for line in reversed(lines[-max_lines:]):
                ts_match = timestamp_pattern.match(line)
                if not ts_match:
                    continue
                
                timestamp_str = ts_match.group('ts')
                try:
                    # タイムスタンプの形式に応じてパース
                    if ',' in timestamp_str:
                        dt_obj = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S,%f')
                    else:
                        dt_obj = datetime.strptime(timestamp_str, '%m-%d %H:%M:%S').replace(year=datetime.now().year)
                    timestamp_iso = dt_obj.isoformat()
                except ValueError:
                    continue

                # 成功ログのチェック
                summary_match = summary_pattern.search(line)
                if summary_match:
                    data = summary_match.groupdict()
                    log_name = data['name'].strip()
                    ui_name = log_name_to_ui_name.get(log_name, log_name)
                    count = int(data['count'])
                    return {
                        "name": ui_name,
                        "timestamp": timestamp_iso,
                        "status": "success",
                        "message": f"{count}件の処理が完了しました。"
                    }

                # エラーログのチェック
                if "ERROR" in line:
                    error_match = error_pattern.search(line)
                    if error_match:
                        action_name = error_match.group('name').strip()
                        # "投稿文作成 (Gemini)" -> "投稿文作成"
                        simple_action_name = action_name.split('(')[0].strip()
                        return {
                            "name": simple_action_name,
                            "timestamp": timestamp_iso,
                            "status": "error",
                            "message": f"処理中にエラーが発生しました。"
                        }
        return None # 該当ログが見つからなかった場合
    except Exception as e:
        logger.error(f"直近のアクティビティログ解析中にエラー: {e}", exc_info=True)
        return None

def get_log_summary(period='24h'):
    """
    ログファイルからアクションサマリーを抽出し、集計して返す。
    """
    # アクション名を定義から取得
    # UIに表示したいシンプルな名称を直接定義する
    actions = {
        '商品調達': {'count': 0, 'errors': 0},
        '記事投稿': {'count': 0, 'errors': 0},
        'いいね活動': {'count': 0, 'errors': 0},
        'フォロー活動': {'count': 0, 'errors': 0},
    }
    
    # ログ名とUI表示名をマッピング
    log_name_to_ui_name = {
        "投稿": "記事投稿",
        "いいね": "いいね活動",
        "フォロー": "フォロー活動",
        "商品調達": "商品調達",
    }

    # ログから情報を抽出する正規表現パターン
    # [I] または INFO の両方に対応
    summary_pattern = re.compile(r"(?:\[I\]|INFO).*\[Action Summary\]\s*name=(?P<name>[^,]+),\s*count=(?P<count>\d+)")
    # [E] または ERROR の両方に対応
    std_error_pattern = re.compile(r"(?:\[E\]|ERROR).*「(?P<name>[^」]+)」アクション中に予期せぬエラーが発生しました")
    post_error_pattern = re.compile(r"(?:\[E\]|ERROR).*商品ID \d+ の投稿処理中にエラーが発生しました")
    # タイムスタンプをキャプチャするためのより一般的な正規表現
    # 詳細形式: YYYY-MM-DD HH:MM:SS,ms
    # 簡易形式: MM-DD HH:MM:SS
    timestamp_capture_pattern = re.compile(r"^(?P<ts_detailed>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})|"
                                           r"^(?P<ts_simple>\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

    now = datetime.now(timezone.utc)
    if period == 'today':
        start_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    else: # '24h'
        start_time = now - timedelta(hours=24)

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                log_time = None
                try:
                    ts_match = timestamp_capture_pattern.match(line)
                    if ts_match:
                        groups = ts_match.groupdict()
                        if groups['ts_detailed']:
                            # 開発環境形式: YYYY-MM-DD HH:MM:SS,ms
                            log_time = datetime.strptime(groups['ts_detailed'], '%Y-%m-%d %H:%M:%S,%f')
                        elif groups['ts_simple']:
                            # 本番環境形式: MM-DD HH:MM:SS
                            log_time = datetime.strptime(groups['ts_simple'], '%m-%d %H:%M:%S').replace(year=now.year)
                            # 年をまたぐログ（例: 12月末に実行し、1月1日にログを見る）を考慮
                            if log_time.astimezone(timezone.utc) > now:
                                log_time = log_time.replace(year=now.year - 1)

                    if log_time:
                        log_time = log_time.astimezone().astimezone(timezone.utc)
                        if log_time < start_time:
                            continue
                    else:
                        # タイムスタンプに一致しない行はスキップ
                        continue
                except (ValueError, IndexError) as e:
                    logger.debug(f"ログ行のタイムスタンプ解析に失敗: {line.strip()} - {e}")
                    continue

                # タイムスタンプのチェックを通過した行に対してのみ、サマリーとエラーを集計する
                summary_match = summary_pattern.search(line)
                if summary_match:
                    data = summary_match.groupdict()
                    log_name = data['name'].strip()
                    count = int(data['count'])
                    
                    ui_name = log_name_to_ui_name.get(log_name)
                    if ui_name and ui_name in actions:
                        actions[ui_name]["count"] += count
                    continue

                # エラーの集計
                std_error_match = std_error_pattern.search(line)
                post_error_match = post_error_pattern.search(line)

                if std_error_match:
                    action_name = std_error_match.group('name').strip()
                    # "投稿文作成 (Gemini)" のような詳細名を "投稿文作成" に丸める
                    simple_action_name = action_name.split('(')[0].strip()
                    
                    if simple_action_name in actions:
                        actions[simple_action_name]["errors"] += 1
                        continue # この行の処理は完了

                    # エラー名が内部タスク名の場合、親フローを探して加算
                    for flow_def in TASK_DEFINITIONS.values():
                        flow_content = flow_def.get("flow")
                        if not flow_content: continue
                        
                        flow_tasks = [t.strip() for t in flow_content.split('|')] if isinstance(flow_content, str) else [t[0] for t in flow_content]
                        if any(TASK_DEFINITIONS.get(t, {}).get("name_ja") == simple_action_name for t in flow_tasks):
                            parent_flow_name = flow_def.get("name_ja")
                            if parent_flow_name and parent_flow_name in actions:
                                actions[parent_flow_name]["errors"] += 1
                                break
                elif post_error_match:
                    if "記事投稿" in actions:
                        actions["記事投稿"]["errors"] += 1

    except FileNotFoundError:
        logger.warning(f"ログファイルが見つかりません: {LOG_FILE}")
    except Exception as e:
        logger.error(f"ログサマリーの取得中にエラーが発生しました: {e}", exc_info=True)

    # 集計結果が0件のアクションは除外する
    final_actions = {name: data for name, data in actions.items() if data["count"] > 0 or data["errors"] > 0}

    return {"actions": final_actions}