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

def get_recent_activities_from_log(limit=5, max_lines=1000):
    """
    ログファイルを末尾から読み込み、直近の「成功」または「エラー」アクティビティを指定された件数まで返す。
    """
    activities = []
    processed_actions = {} # 重複排除用: {action_name: timestamp}
    try:
        if not os.path.exists(LOG_FILE):
            return []

        # ログ名とUI表示名をマッピング
        log_name_to_ui_name = {
            "投稿": "記事投稿",
            "いいね": "いいね活動",
            "フォロー": "フォロー活動",
            "商品調達": "商品調達",
        }

        # 正規表現パターン
        summary_pattern = re.compile(r"\[Action Summary\]\s*name=(?P<name>[^,]+)(?:,\s*count=(?P<count>\d+))?(?:,\s*message='(?P<message>[^']*)')?")
        error_pattern = re.compile(r"「(?P<name>[^」]+)」(?:アクション中に|実行中に|が失敗しました)")
        timestamp_pattern = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}|\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
            for line in reversed(lines[-max_lines:]):
                if len(activities) >= limit:
                    break

                ts_match = timestamp_pattern.match(line)
                if not ts_match:
                    continue
                
                timestamp_str = ts_match.group('ts')
                try:
                    if ',' in timestamp_str:
                        dt_obj = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S,%f')
                    else:
                        dt_obj = datetime.strptime(timestamp_str, '%m-%d %H:%M:%S').replace(year=datetime.now().year)
                    timestamp_iso = dt_obj.isoformat()
                except ValueError:
                    continue

                summary_match = summary_pattern.search(line)
                if summary_match:
                    data = summary_match.groupdict()
                    log_name = data['name'].strip()
                    ui_name = log_name_to_ui_name.get(log_name, log_name)

                    # 重複チェック: 1分以内に同じアクションが処理済みならスキップ
                    if ui_name in processed_actions and (processed_actions[ui_name] - dt_obj).total_seconds() < 60:
                        continue

                    count_str = data.get('count')
                    message = data.get('message')

                    if message:
                        activities.append({"name": ui_name, "timestamp": timestamp_iso, "status": "success", "message": message})
                    elif count_str:
                        activities.append({"name": ui_name, "timestamp": timestamp_iso, "status": "success", "message": f"{int(count_str)}件 完了"})
                    processed_actions[ui_name] = dt_obj # 処理済みアクションとして記録
                    continue # この行でアクティビティを見つけたら次の行へ

                if "ERROR" in line:
                    error_match = error_pattern.search(line)
                    if error_match:
                        action_name = error_match.group('name').strip()
                        # 重複チェック: 1分以内に同じアクションが処理済みならスキップ
                        if action_name in processed_actions and (processed_actions[action_name] - dt_obj).total_seconds() < 60:
                            continue
                        simple_action_name = action_name.split('(')[0].strip()
                        activities.append({"name": simple_action_name, "timestamp": timestamp_iso, "status": "error", "message": f"処理中にエラー発生"})
                        processed_actions[action_name] = dt_obj # 処理済みアクションとして記録
        return activities
    except Exception as e:
        logger.error(f"直近のアクティビティログ解析中にエラー: {e}", exc_info=True)
        return []

def get_log_summary(period='24h', max_lines_to_scan=20000):
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
        '返信コメント生成': {'count': 0, 'errors': 0},
        'いいね返し': {'count': 0, 'errors': 0},
        'コメント返し': {'count': 0, 'errors': 0},
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
    summary_pattern = re.compile(r"(?:\[I\]|INFO).*\[Action Summary\]\s*name=(?P<name>[^,]+),\s*count=(?P<count>\d+)(?:,\s*errors=(?P<errors>\d+))?")
    # [E] または ERROR の両方に対応
    # TimeoutErrorを含む、より広範なエラーパターンを追加
    generic_error_pattern = re.compile(r"(?:\[E\]|ERROR|\[W\]|WARNING).*「(?P<name>[^」]+)」(?:アクション中に|クリック中に|実行中に|が失敗しました|タスクの実行中にエラーが発生しました).*")

    # タイムスタンプをキャプチャするためのより一般的な正規表現
    # 詳細形式: YYYY-MM-DD HH:MM:SS,ms
    # 簡易形式: MM-DD HH:MM:SS
    timestamp_capture_pattern = re.compile(r"^(?P<ts_detailed>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})|"
                                           r"^(?P<ts_simple>\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

    now = datetime.now(timezone.utc)
    today_start_local = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if period == 'yesterday':
        start_time = (today_start_local - timedelta(days=1)).astimezone(timezone.utc)
        end_time = today_start_local.astimezone(timezone.utc)
    elif period == 'day_before_yesterday':
        start_time = (today_start_local - timedelta(days=2)).astimezone(timezone.utc)
        end_time = (today_start_local - timedelta(days=1)).astimezone(timezone.utc)
    elif period == 'today':
        start_time = today_start_local.astimezone(timezone.utc)
        end_time = None # 終わりは無制限
    else: # '24h' or default
        start_time = now - timedelta(hours=24)
        end_time = None # 終わりは無制限

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            # ファイルの末尾から最大N行を読み込むことでパフォーマンスを改善
            lines = f.readlines()
            for line in reversed(lines[-max_lines_to_scan:]):
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
                        # 期間外のログはスキップ
                        if log_time < start_time:
                            # ファイルを逆順に読んでいるので、期間より古くなったらループを抜ける
                            break
                        if end_time and log_time >= end_time:
                            continue # 期間の終わりより新しいログはスキップ
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
                    errors = int(data.get('errors') or 0)
                    
                    # まずマッピングを試す
                    ui_name = log_name_to_ui_name.get(log_name)
                    if ui_name and ui_name in actions:
                        actions[ui_name]["count"] += count
                        actions[ui_name]["errors"] += errors
                    # マッピングにないが、actionsのキーと直接一致する場合
                    elif log_name in actions:
                        actions[log_name]["count"] += count
                        actions[log_name]["errors"] += errors
                    continue

                # エラーの集計
                error_match = generic_error_pattern.search(line)
                if error_match:
                    action_name_from_log = error_match.group('name').strip()
                    # "投稿文作成 (Gemini)" のような詳細名を "投稿文作成" に丸める
                    simple_action_name = action_name_from_log.split('(')[0].strip()
                    
                    # マッピングを元にUI表示名を取得
                    ui_name = log_name_to_ui_name.get(simple_action_name)
                    if ui_name and ui_name in actions:
                        actions[ui_name]["errors"] += 1
                    # 「返信コメント生成」フローに含まれるタスクのエラーを集約
                    elif simple_action_name in ["通知分析", "AIコメント作成"] and "返信コメント生成" in actions:
                        actions["返信コメント生成"]["errors"] += 1
                    elif simple_action_name in actions: # マッピングにないが直接一致する場合
                        actions[ui_name]["errors"] += 1
                    elif simple_action_name in actions: # マッピングにないが直接一致する場合
                        actions[simple_action_name]["errors"] += 1
                # 「投稿処理中にエラー」は「記事投稿」のエラーとしてカウント
                elif "投稿処理中にエラー" in line and "記事投稿" in actions:
                    actions["記事投稿"]["errors"] += 1
                # 「投稿URL取得」中のエラーは「商品調達」のエラーとしてカウント
                elif "の処理中に予期せぬ例外が発生しました" in line and "商品調達" in actions:
                    actions["商品調達"]["errors"] += 1

    except FileNotFoundError:
        logger.warning(f"ログファイルが見つかりません: {LOG_FILE}")
    except Exception as e:
        logger.error(f"ログサマリーの取得中にエラーが発生しました: {e}", exc_info=True)

    # 集計結果が0件のアクションは除外する
    final_actions = {name: data for name, data in actions.items() if data["count"] > 0 or data["errors"] > 0}

    return {"actions": final_actions}