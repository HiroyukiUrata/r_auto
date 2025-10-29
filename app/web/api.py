from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import schedule
import re
import logging
import os
import json
from pydantic import BaseModel
from pathlib import Path

# タスク定義を一元的にインポート
from app.core.task_definitions import TASK_DEFINITIONS
from app.core.database import (get_all_inventory_products, update_product_status, delete_all_products, init_db, 
                               delete_product, update_status_for_multiple_products, delete_multiple_products, get_product_count_by_status, 
                               get_error_products_in_last_24h, update_product_priority, update_product_order, bulk_update_products_from_data, commit_user_actions,
                               get_users_for_commenting)
from app.tasks.posting import run_posting
from app.tasks.get_post_url import run_get_post_url
from app.tasks.import_products import process_and_import_products
from app.core.logging_config import LOG_FILE # ログファイルのパスをインポート
from app.core.config_manager import get_config, save_config, SCREENSHOT_DIR, clear_config_cache
from app.core.scheduler_utils import run_threaded, run_task_with_random_delay, get_log_summary
from datetime import date, timedelta


KEYWORDS_FILE = "db/keywords.json"
SCHEDULE_FILE = "db/schedules.json"
RECENT_KEYWORDS_FILE = "db/recent_keywords.json"
SCHEDULE_PROFILES_DIR = "db/schedule_profiles"
KEYWORD_PROFILES_DIR = "db/keyword_profiles"

class TimeEntry(BaseModel):
    time: str
    count: int

# --- Pydantic Models ---
class ScheduleUpdateRequest(BaseModel):
    tag: str
    enabled: bool
    times: list[TimeEntry]

class ProfileNameRequest(BaseModel):
    profile_name: str

class PriorityUpdateRequest(BaseModel):
    priority: int

class ConfigUpdateRequest(BaseModel):
    # すべてのフィールドをオプショナル（任意）に変更
    max_delay_minutes: int | None = None
    playwright_headless: bool | None = None
    procurement_method: str | None = None
    caption_creation_method: str | None = None

class JsonImportRequest(BaseModel):
    products: list[dict]

class BulkUpdateRequest(BaseModel):
    product_ids: list[int]

class UserIdsRequest(BaseModel):
    user_ids: list[str]

class BulkStatusUpdateRequest(BaseModel):
    product_ids: list[int]
    status: str

class KeywordsUpdateRequest(BaseModel):
    keywords_a: list[str]
    keywords_b: list[str]


# --- HTML Routes ---
router = APIRouter()

@router.get("/", response_class=RedirectResponse)
async def redirect_to_dashboard():
    """ルートURLからダッシュボードへリダイレクトする"""
    return RedirectResponse(url="/dashboard")

@router.get("/schedules", response_class=HTMLResponse)
async def read_schedules_page(request: Request):
    """
    スケジュール設定ページを表示し、現在のスケジュール一覧を渡す
    """
    return request.app.state.templates.TemplateResponse("schedules.html", {"request": request})

@router.get("/logs", response_class=HTMLResponse)
async def read_logs(request: Request):
    """ログ確認ページを表示する"""
    return request.app.state.templates.TemplateResponse("logs.html", {"request": request})

@router.get("/chat", response_class=HTMLResponse)
async def read_chat(request: Request):
    """AIチャットページを表示する"""
    return request.app.state.templates.TemplateResponse("chat.html", {"request": request})

@router.get("/system-config", response_class=HTMLResponse)
async def read_system_config(request: Request):
    """システムコンフィグページを表示する"""
    return request.app.state.templates.TemplateResponse("config.html", {"request": request})

@router.get("/inventory", response_class=HTMLResponse)
async def read_inventory(request: Request):
    """在庫確認ページを表示する"""
    return request.app.state.templates.TemplateResponse("inventory.html", {"request": request})

@router.get("/keywords", response_class=HTMLResponse)
async def read_keywords_page(request: Request):
    """キーワード管理ページを表示する"""
    return request.app.state.templates.TemplateResponse("keywords.html", {"request": request})

@router.get("/dashboard", response_class=HTMLResponse)
async def read_dashboard(request: Request):
    """ダッシュボードページを表示する"""
    return request.app.state.templates.TemplateResponse("dashboard.html", {"request": request})

@router.get("/comment-management", response_class=HTMLResponse)
async def read_comment_management(request: Request):
    """コメント投稿管理ページを表示する"""
    return request.app.state.templates.TemplateResponse("comment_management.html", {"request": request})

@router.get("/error-management", response_class=HTMLResponse)
async def read_error_management(request: Request):
    """エラー管理ページを表示する"""
    # ファイル名を解析するための正規表現パターンを修正
    # 例: url_error_my_user_id_通知分析_20231027-103045.png
    # 末尾からタイムスタンプとアクション名を特定するように変更し、プレフィックスにアンダースコアが含まれても対応できるようにする
    # アクション名はタイムスタンプの直前にあるアンダースコアで区切られた部分と仮定
    filename_pattern = re.compile(r'^(?P<prefix>.+?)_(?P<action_name>[^_]+)_(?P<timestamp>\d{8}-\d{6})\.png$')
    
    files = []
    file_details = {}
    
    screenshot_path = Path(SCREENSHOT_DIR)
    if screenshot_path.exists():
        try:
            # ファイルを更新日時の降順（新しいものが上）でソート
            sorted_paths = sorted(
                screenshot_path.iterdir(),
                key=lambda f: f.stat().st_mtime,
                reverse=True
            )
        except FileNotFoundError:
            sorted_paths = []

        for f_path in sorted_paths:
            if f_path.is_file() and f_path.suffix.lower() == '.png':
                filename = f_path.name
                files.append(filename)
                
                action_name = "不明なアクション"
                error_timestamp_display = "不明な日時"

                match = filename_pattern.match(filename)
                if match:
                    parsed_data = match.groupdict()
                    action_name = parsed_data['action_name'].replace('_', ' ') # アンダースコアをスペースに
                    raw_timestamp = parsed_data['timestamp']
                    try:
                        from datetime import datetime
                        dt_obj = datetime.strptime(raw_timestamp, '%Y%m%d-%H%M%S')
                        error_timestamp_display = dt_obj.strftime('%Y-%m-%d %H:%M')
                    except ValueError:
                        error_timestamp_display = f"不正な日時 ({raw_timestamp})"
                
                file_details[filename] = {'action_name': action_name, 'error_timestamp': error_timestamp_display}

    # 既存のエラー商品表示機能はそのままに、スクリーンショットの情報を追加で渡す
    return request.app.state.templates.TemplateResponse("error_management.html", {"request": request, "files": files, "file_details": file_details})

# --- API Routes ---
@router.get("/api/schedules")
async def get_schedules():
    """現在のスケジュール情報をJSONで返す"""
    # 1. タスク定義を元にレスポンスの雛形を作成
    all_tasks = {}
    for tag, definition in TASK_DEFINITIONS.items():
        # スケジュールに表示する条件:
        # 1. is_debugがFalseである (通常のタスク)
        # 2. または、is_debugがTrueでも、show_in_scheduleが明示的にTrueである (デバッグタスクだがスケジュールも許可)
        is_schedulable = not definition.get("is_debug", False) or definition.get("show_in_schedule", False)
        if is_schedulable and definition.get("show_in_schedule", True):

            all_tasks[tag] = {"tag": tag, "name_ja": definition["name_ja"], "enabled": True, "times": [], "next_run": None}

    # 2. ファイルから保存されたスケジュール情報（enabledフラグ含む）を読み込んでマージ
    saved_schedules = _load_schedules_from_file()
    for tag, data in saved_schedules.items():
        if tag in all_tasks:
            if isinstance(data, dict): # 新フォーマット
                all_tasks[tag]["enabled"] = data.get("enabled", True)
                all_tasks[tag]["times"] = data.get("times", [])
            elif isinstance(data, list): # 旧フォーマット
                all_tasks[tag]["times"] = data

    # 3. 現在アクティブなジョブの情報を雛形にマージする
    for job in schedule.get_jobs():
        if not job.tags:
            continue
        tag = list(job.tags)[0]
        if tag in all_tasks:
            # 最も近い次の実行時刻を更新
            current_next_run = all_tasks[tag].get("next_run")
            # 日付オブジェクトで比較するために、文字列から変換
            if isinstance(current_next_run, str):
                from datetime import datetime
                current_next_run = datetime.strptime(current_next_run, "%Y-%m-%d %H:%M:%S")

            if not current_next_run or job.next_run < current_next_run:
                 all_tasks[tag]["next_run"] = job.next_run

    # next_runを文字列に変換し、時刻をソート
    for task in all_tasks.values():
        if task["next_run"] and not isinstance(task["next_run"], str):
            next_run_datetime = task["next_run"]
            today = date.today()
            
            day_prefix = ""
            if next_run_datetime.date() == today:
                day_prefix = "今日"
            elif next_run_datetime.date() == today + timedelta(days=1):
                day_prefix = "明日"
            else:
                day_prefix = next_run_datetime.strftime('%m/%d')
            task["next_run"] = f"({day_prefix}) {next_run_datetime.strftime('%H:%M')}"
        task["times"].sort(key=lambda x: x['time'])

    return JSONResponse(content=list(all_tasks.values()))

def _load_schedules_from_file():
    """スケジュールファイルを読み込む内部関数"""
    if not os.path.exists(SCHEDULE_FILE): return {}
    try:
        with open(SCHEDULE_FILE, "r") as f: return json.load(f)
    except (IOError, json.JSONDecodeError): return {}

@router.get("/api/schedule-profiles")
async def get_schedule_profiles():
    """保存されているスケジュールプロファイルの一覧を返す"""
    os.makedirs(SCHEDULE_PROFILES_DIR, exist_ok=True)
    profiles = []
    for filename in os.listdir(SCHEDULE_PROFILES_DIR):
        if filename.endswith(".json"):
            profiles.append(os.path.splitext(filename)[0])
    return JSONResponse(content=sorted(profiles))

@router.post("/api/schedule-profiles")
async def save_schedule_profile(request: ProfileNameRequest):
    """現在のスケジュールを新しいプロファイルとして保存する"""
    profile_name = request.profile_name
    if not re.match(r'^[a-zA-Z0-9_.\-ぁ-んァ-ヶー一-龠々 ]+$', profile_name):
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "プロファイル名に使用できない文字が含まれています。"}
        )
    
    profile_path = os.path.join(SCHEDULE_PROFILES_DIR, f"{profile_name}.json")
    
    try:
        current_schedules = _load_schedules_from_file()
        # `_save_schedules_to_file` は scheduler.py に移動したため、直接書き込む
        with open(profile_path, "w") as f:
            json.dump(current_schedules, f, indent=4, sort_keys=True)

        return JSONResponse(content={"status": "success", "message": f"プロファイル「{profile_name}」を保存しました。"})
    except Exception as e:
        logging.error(f"プロファイル '{profile_name}' の保存中にエラー: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "プロファイルの保存に失敗しました。"})

@router.put("/api/schedule-profiles/{profile_name}")
async def load_schedule_profile(profile_name: str):
    """指定されたプロファイルを現在のスケジュールとして読み込む"""
    profile_path = os.path.join(SCHEDULE_PROFILES_DIR, f"{profile_name}.json")
    if not os.path.exists(profile_path):
        return JSONResponse(status_code=404, content={"status": "error", "message": "プロファイルが見つかりません。"})

    try:
        with open(profile_path, "r") as f:
            profile_data = json.load(f)
        
        # `_save_schedules_to_file` と `reload_schedules` は scheduler.py 側で処理
        from app.core.scheduler import save_and_reload_schedules
        save_and_reload_schedules(profile_data)
        
        return JSONResponse(content={"status": "success", "message": f"プロファイル「{profile_name}」を読み込みました。"})
    except Exception as e:
        logging.error(f"プロファイル '{profile_name}' の読み込み中にエラー: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "プロファイルの読み込みに失敗しました。"})

@router.delete("/api/schedule-profiles/{profile_name}")
async def delete_schedule_profile(profile_name: str):
    """指定されたプロファイルを削除する"""
    profile_path = os.path.join(SCHEDULE_PROFILES_DIR, f"{profile_name}.json")
    if not os.path.exists(profile_path):
        return JSONResponse(status_code=404, content={"status": "error", "message": "プロファイルが見つかりません。"})
    try:
        os.remove(profile_path)
        return JSONResponse(content={"status": "success", "message": f"プロファイル「{profile_name}」を削除しました。"})
    except Exception as e:
        logging.error(f"プロファイル '{profile_name}' の削除中にエラー: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "プロファイルの削除に失敗しました。"})

@router.get("/api/keyword-profiles")
async def get_keyword_profiles():
    """保存されているキーワードプロファイルの一覧を返す"""
    os.makedirs(KEYWORD_PROFILES_DIR, exist_ok=True)
    profiles = [os.path.splitext(f)[0] for f in os.listdir(KEYWORD_PROFILES_DIR) if f.endswith(".json")]
    return JSONResponse(content=sorted(profiles))

@router.post("/api/keyword-profiles")
async def save_keyword_profile(request: ProfileNameRequest):
    """現在のキーワードを新しいプロファイルとして保存する"""
    profile_name = request.profile_name.strip()
    if not profile_name or not re.match(r'^[a-zA-Z0-9_.\-ぁ-んァ-ヶ一-龠々ー ]+$', profile_name) or "/" in profile_name or "\\" in profile_name:
        return JSONResponse(status_code=400, content={"status": "error", "message": "プロファイル名に使用できない文字が含まれています。"})

    profile_path = os.path.join(KEYWORD_PROFILES_DIR, f"{profile_name}.json")
    try:
        if os.path.exists(KEYWORDS_FILE):
            with open(KEYWORDS_FILE, "r") as f_src, open(profile_path, "w") as f_dst:
                f_dst.write(f_src.read())
            return JSONResponse(content={"status": "success", "message": f"プロファイル「{profile_name}」を保存しました。"})
        else:
            return JSONResponse(status_code=404, content={"status": "error", "message": "保存するキーワードファイルが見つかりません。"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"プロファイルの保存に失敗しました: {e}"})

@router.put("/api/keyword-profiles/{profile_name}")
async def load_keyword_profile(profile_name: str):
    """指定されたプロファイルを現在のキーワードとして読み込む"""
    profile_path = os.path.join(KEYWORD_PROFILES_DIR, f"{profile_name}.json")
    if not os.path.exists(profile_path):
        return JSONResponse(status_code=404, content={"status": "error", "message": "プロファイルが見つかりません。"})

    try:
        with open(profile_path, "r") as f_src, open(KEYWORDS_FILE, "w") as f_dst:
            f_dst.write(f_src.read())
        return JSONResponse(content={"status": "success", "message": f"プロファイル「{profile_name}」を読み込みました。"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"プロファイルの読み込みに失敗しました: {e}"})

@router.delete("/api/keyword-profiles/{profile_name}")
async def delete_keyword_profile(profile_name: str):
    """指定されたキーワードプロファイルを削除する"""
    profile_path = os.path.join(KEYWORD_PROFILES_DIR, f"{profile_name}.json")
    if not os.path.exists(profile_path):
        return JSONResponse(status_code=404, content={"status": "error", "message": "プロファイルが見つかりません。"})
    try:
        os.remove(profile_path)
        return JSONResponse(content={"status": "success", "message": f"プロファイル「{profile_name}」を削除しました。"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"プロファイルの削除に失敗しました: {e}"})

@router.get("/api/config-tasks")
async def get_config_tasks():
    """システムコンフィグ用のタスクリストをJSONで返す"""
    debug_tasks = []
    for tag, definition in TASK_DEFINITIONS.items():
        if definition.get("is_debug", True):
            debug_tasks.append({
                "tag": tag, 
                "name_ja": definition["name_ja"],
                "description": definition.get("description", ""),
                "order": definition.get("order", 999)
            })
    
    return JSONResponse(content=sorted(debug_tasks, key=lambda x: x["order"]))

@router.get("/api/config")
async def read_config():
    """現在の設定をJSONで返す"""
    return JSONResponse(content=get_config())

@router.get("/api/inventory")
async def get_inventory():
    """在庫商品（「投稿済」以外）のリストをJSONで返す"""
    products = get_all_inventory_products()
    # sqlite3.Rowは直接JSONシリアライズできないため、辞書のリストに変換
    products_list = [dict(product) for product in products]
    return JSONResponse(content=products_list)

@router.get("/api/errors")
async def get_error_products():
    """エラー商品（過去24時間）のリストをJSONで返す"""
    products = get_error_products_in_last_24h()
    # get_error_products_in_last_24h は既に辞書のリストを返す
    return JSONResponse(content=products)

@router.get("/api/inventory/summary")
async def get_inventory_summary():
    """在庫商品のステータスごとの件数を返す"""
    try:
        summary = get_product_count_by_status()
        return JSONResponse(content=summary)
    except Exception as e:
        logging.error(f"在庫サマリーの取得中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "サマリーの取得に失敗しました。"})

@router.get("/api/dashboard/summary")
async def get_dashboard_summary(request: Request):
    """ダッシュボード用のサマリーデータを返す"""
    # logging.debug("[DASHBOARD_API] /api/dashboard/summary の処理を開始します。")
    try:
        period = request.query_params.get('period', '24h') # クエリパラメータから期間を取得
        log_summary = get_log_summary(period=period)

        # 次のスケジュール情報を最大3件取得
        all_jobs = schedule.get_jobs()
        # 実行予定時刻があるジョブのみを抽出し、時刻順にソート
        scheduled_jobs = sorted([job for job in all_jobs if job.next_run], key=lambda j: j.next_run)
        
        next_schedules_info = []
        # ソート済みのジョブから先頭3件を取得
        for next_job in scheduled_jobs[:3]:
            if next_job and next_job.tags:
                tag = list(next_job.tags)[0]
                definition = TASK_DEFINITIONS.get(tag, {})
                
                job_kwargs = {}
                # scheduleライブラリが引数を保持する複数のパターンに対応
                if hasattr(next_job.job_func, 'keywords'):
                    job_kwargs = next_job.job_func.keywords
                elif hasattr(next_job, 'kwargs') and next_job.kwargs:
                    job_kwargs = next_job.kwargs
                
                # 実行日を判定
                today = date.today()
                next_run_date = next_job.next_run.date()
                day_prefix = ""
                if next_run_date == today:
                    day_prefix = "今日"
                elif next_run_date == today + timedelta(days=1):
                    day_prefix = "明日"
                else:
                    day_prefix = next_job.next_run.strftime('%m/%d')

                schedule_info = {
                    "name": definition.get("name_ja", "不明なタスク"),
                    "time": next_job.next_run.strftime('%H:%M'),
                    "date_prefix": day_prefix,
                    "count": job_kwargs.get('count', 0)
                }
                next_schedules_info.append(schedule_info)

        # レスポンスのキーを複数形に変更
        summary = {**log_summary, "next_schedules": next_schedules_info}
        # logging.debug(f"[DASHBOARD_API] 処理成功。フロントエンドに返すデータ: {summary}")
        return JSONResponse(content=summary)
    except Exception as e:
        # エラー発生時に詳細なトレースバックをログに出力
        logging.error(f"ダッシュボードサマリーの取得中に予期せぬエラーが発生しました。", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": "サマリーデータの取得に失敗しました。"})

@router.get("/api/dashboard/recent-keywords")
async def get_recent_keywords():
    """最近使ったキーワードを返す"""
    try:
        if os.path.exists(RECENT_KEYWORDS_FILE):
            with open(RECENT_KEYWORDS_FILE, "r", encoding="utf-8") as f:
                keywords = json.load(f)
            return JSONResponse(content=keywords)
        return JSONResponse(content=[])
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"キーワードの読み込みに失敗しました: {e}"})

@router.get("/api/dashboard/recent-activities")
async def get_recent_activities(request: Request):
    """直前に実行されたアクティビティをn件取得する"""
    try:
        limit_str = request.query_params.get('limit', '5') # デフォルトは5件
        try:
            limit = int(limit_str)
            if limit <= 0:
                limit = 5
        except ValueError:
            limit = 5
        
        # ログファイルを解析して直近のアクティビティを取得する関数を呼び出す
        from app.core.scheduler_utils import get_recent_activities_from_log
        activities = get_recent_activities_from_log(limit=limit)

        #logging.debug(f"取得した直近のアクティビティ ({len(activities)}件): {activities}")

        if activities:
            return JSONResponse(content=activities)
        else:
            # ログが1件も存在しない場合は、空のリストを返します。
            return JSONResponse(content=[])
    except Exception as e:
        logging.error(f"直前のアクティビティ取得中にエラー: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": "直前のアクティビティの取得に失敗しました。"})

@router.post("/api/inventory/{product_id}/complete")
async def complete_inventory_item(product_id: int):
    """指定された在庫商品を「投稿済」ステータスに更新する"""
    try:
        # データベースのステータスを更新
        update_product_status(product_id, '投稿済')
        return JSONResponse(content={"status": "success", "message": f"商品ID: {product_id} を「投稿済」に更新しました。"})
    except Exception as e:
        logging.error(f"商品ID: {product_id} のステータス更新中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "ステータスの更新に失敗しました。"})

@router.delete("/api/inventory/{product_id}")
async def delete_inventory_item(product_id: int):
    """指定された在庫商品を削除する"""
    try:
        if delete_product(product_id):
            return JSONResponse(content={"status": "success", "message": f"商品ID: {product_id} を削除しました。"})
        else:
            return JSONResponse(status_code=404, content={"status": "error", "message": "指定された商品が見つかりませんでした。"})
    except Exception as e:
        logging.error(f"商品ID: {product_id} の削除中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "サーバーエラーにより削除に失敗しました。"})

@router.post("/api/inventory/{product_id}/post")
async def post_inventory_item(product_id: int):
    """指定された在庫商品を1件だけ投稿する"""
    try:
        # post_articleタスクを引数count=1, product_id=product_idで実行
        run_threaded(run_posting, count=1, product_id=product_id)
        return JSONResponse(content={"status": "success", "message": f"商品ID: {product_id} の投稿処理を開始しました。"})
    except Exception as e:
        logging.error(f"商品ID: {product_id} の投稿処理開始中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "投稿処理の開始に失敗しました。"})

@router.post("/api/inventory/{product_id}/priority")
async def update_priority(product_id: int, request: PriorityUpdateRequest):
    """指定された商品の優先度を更新する"""
    try:
        update_product_priority(product_id, request.priority)
        # 成功時はメッセージなしで200 OKを返す
        return JSONResponse(content={"status": "success"})
    except Exception as e:
        logging.error(f"商品ID {product_id} の優先度更新中にエラー: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "優先度の更新に失敗しました。"})

@router.post("/api/inventory/update-order")
async def update_inventory_order(request: BulkUpdateRequest):
    """在庫商品の表示順（優先度）を一括で更新する"""
    try:
        update_product_order(request.product_ids)
        return JSONResponse(content={"status": "success", "message": "商品の順序を更新しました。"})
    except Exception as e:
        logging.error(f"商品順序の一括更新中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "順序の更新に失敗しました。"})


@router.post("/api/inventory/bulk-complete")
async def bulk_complete_inventory_items(request: BulkUpdateRequest):
    """複数の在庫商品を一括で「投稿済」ステータスに更新する"""
    try:
        updated_count = update_status_for_multiple_products(request.product_ids, '投稿済')
        return JSONResponse(content={"status": "success", "message": f"{updated_count}件の商品を「投稿済」に更新しました。"})
    except Exception as e:
        logging.error(f"商品の一括ステータス更新中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "一括更新に失敗しました。"})

@router.get("/api/screenshots/{filename}")
async def get_screenshot_file(filename: str):
    """スクリーンショット画像ファイルを返す"""
    # ファイル名の安全性を確認（ディレクトリトラバーサル攻撃を防ぐ）
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="不正なファイル名です。")
    
    file_path = Path(SCREENSHOT_DIR) / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="ファイルが見つかりません。")
    return FileResponse(path=file_path, media_type="image/png")

@router.delete("/api/screenshots/{filename}")
async def delete_screenshot_file(filename: str):
    """指定されたスクリーンショットファイルを削除する"""
    # ファイル名の安全性を確認（ディレクトリトラバーサル攻撃を防ぐ）
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="不正なファイル名です。")
    
    file_path = Path(SCREENSHOT_DIR) / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="ファイルが見つかりません。")
    
    os.remove(file_path)
    logging.info(f"スクリーンショットを削除しました: {file_path}")
    return JSONResponse(content={"status": "success", "message": "ファイルを削除しました。"})

@router.post("/api/inventory/bulk-delete")
async def bulk_delete_inventory_items(request: BulkUpdateRequest):
    """複数の在庫商品を一括で削除する"""
    try:
        deleted_count = delete_multiple_products(request.product_ids)
        return JSONResponse(content={"status": "success", "message": f"{deleted_count}件の商品を削除しました。"})
    except Exception as e:
        logging.error(f"商品の一括削除中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "一括削除に失敗しました。"})

@router.post("/api/products/bulk-status-update")
async def bulk_status_update_products(request: BulkStatusUpdateRequest):
    """複数の商品を一括で指定のステータスに更新する"""
    try:
        updated_count = update_status_for_multiple_products(request.product_ids, request.status)
        return JSONResponse(content={"status": "success", "message": f"{updated_count}件の商品を「{request.status}」に更新しました。"})
    except Exception as e:
        logging.error(f"商品の一括ステータス更新中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "一括更新に失敗しました。"})

@router.get("/api/comment-targets")
async def get_comment_targets():
    """コメント投稿対象のユーザーリストを返す"""
    try:
        # データベースからコメント対象のユーザーを取得 (上限50件)
        users = get_users_for_commenting(limit=50)
        return JSONResponse(content=users)
    except Exception as e:
        logging.error(f"コメント対象ユーザーの取得中にエラーが発生しました: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": "ユーザーリストの取得に失敗しました。"})

@router.post("/api/users/bulk-skip")
async def bulk_skip_users(request: UserIdsRequest):
    """
    複数のユーザーのアクションをコミットし、コメント対象から除外（スキップ）する。
    コメントは投稿しないため、last_commented_at は更新しない。
    """
    user_ids = request.user_ids
    if not user_ids:
        raise HTTPException(status_code=400, detail="ユーザーIDが指定されていません。")

    try:
        # is_comment_posted=False で呼び出し、アクションのコミットのみ行う
        updated_count = commit_user_actions(user_ids, is_comment_posted=False)
        return JSONResponse(content={"message": f"{updated_count}件のユーザーをスキップしました。", "count": updated_count})
    except Exception as e:
        logging.error(f"ユーザーの一括スキップ処理中にエラーが発生しました: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="サーバーエラーが発生しました。")


@router.post("/api/products/bulk-update-from-json")
async def bulk_update_from_json(request: JsonImportRequest):
    """
    JSONデータに基づいて複数の商品を一括で更新する。
    主にエラー管理画面からのデータ復旧に使用する。
    """
    try:
        products_to_update = request.products
        if not products_to_update:
            raise HTTPException(status_code=400, detail="更新する商品データがありません。")
        
        updated_count, failed_count = bulk_update_products_from_data(products_to_update)
        return JSONResponse(content={"status": "success", "message": f"{updated_count}件の商品情報を更新しました。(ID不明などで失敗: {failed_count}件)"})
    except Exception as e:
        logging.error(f"JSONからの商品一括更新中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "サーバーエラーにより更新に失敗しました。"})

@router.get("/api/keywords")
async def get_keywords():
    """キーワードをJSONファイルから読み込んで返す"""
    try:
        if os.path.exists(KEYWORDS_FILE):
            with open(KEYWORDS_FILE, "r") as f:
                keywords = json.load(f)
            return JSONResponse(content=keywords)
        else:
            return JSONResponse(content={"keywords_a": [], "keywords_b": []})
    except Exception as e:
        logging.error(f"キーワードファイルの読み込みに失敗しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "キーワードの読み込みに失敗しました。"})

@router.post("/api/keywords")
async def save_keywords(request: KeywordsUpdateRequest):
    """キーワードをJSONファイルに保存する"""
    try:
        with open(KEYWORDS_FILE, "w") as f:
            json.dump(request.dict(), f, indent=4, ensure_ascii=False)
        return JSONResponse(content={"status": "success", "message": "キーワードを保存しました。"})
    except Exception as e:
        logging.error(f"キーワードファイルの保存に失敗しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "キーワードの保存に失敗しました。"})


@router.post("/api/import/json")
async def import_from_json(request: JsonImportRequest):
    """ブラウザから送信されたJSONデータを使って商品をインポートする"""
    try:
        items_to_import = request.products
        if not items_to_import:
            return JSONResponse(status_code=400, content={"status": "error", "message": "インポートする商品がありません。"})
        
        # 共通のインポート処理関数を呼び出す
        added_count, skipped_count = process_and_import_products(items_to_import)

        # フローの起点となるタスクを実行
        _run_task_internal("json-import-flow", is_part_of_flow=False)

        return JSONResponse(content={"status": "success", "message": f"{len(items_to_import)}件中、{added_count}件の新規商品をインポートしました。\n続けてバックグラウンドで後続タスク（投稿URL取得など）を開始します。"})
    except Exception as e:
        logging.error(f"JSONからのインポート処理中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "インポート処理中にサーバーエラーが発生しました。"})

@router.post("/api/products/delete-all")
async def delete_all_products_endpoint():
    """すべての商品データを削除する"""
    try:
        delete_all_products()
        init_db() # テーブルをクリアした後、サンプルデータを再挿入するために呼び出す
        return JSONResponse(content={"status": "success", "message": "すべての商品データを削除し、サンプルデータを再挿入しました。"})
    except Exception as e:
        logging.error(f"全商品データの削除中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "サーバーエラーにより削除に失敗しました。"})

@router.post("/api/config")
async def update_config(config_request: ConfigUpdateRequest):
    """設定を更新する"""
    logging.debug(f"設定更新リクエストを受け取りました: {config_request.dict()}")
    current_config = get_config()
    # リクエストで送信された値（Noneでないもの）だけを更新する
    update_data = config_request.dict(exclude_unset=True)
    current_config.update(update_data)
    save_config(current_config)
    clear_config_cache() # 設定保存後にキャッシュをクリア
    logging.info("設定が更新され、キャッシュがクリアされました。")
    return {"status": "success", "message": "設定を更新しました。"}


@router.post("/api/schedules/update")
async def update_schedule(update_request: ScheduleUpdateRequest):
    """指定されたタグのジョブの実行時刻をすべて更新する"""
    tag = update_request.tag
    definition = TASK_DEFINITIONS.get(tag)
    if not definition:
        return JSONResponse(status_code=404, content={"status": "error", "message": f"Task definition for '{tag}' not found."})

    # そのタグを持つ既存のジョブをすべてキャンセル
    schedule.clear(tag)

    # タスクが有効な場合のみ、新しい時刻リストに基づいてジョブを再作成
    if update_request.enabled:
        for entry in update_request.times:
            if re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', entry.time):
                # タスク定義からのデフォルト引数を取得し、スケジュール固有の引数で上書き
                job_kwargs = definition.get("default_kwargs", {}).copy()
                job_kwargs['count'] = entry.count

                task_func = definition.get("function")
                if task_func:
                    # 通常のタスクの場合
                    job_kwargs['task_to_run'] = task_func
                    schedule.every().day.at(entry.time).do(run_threaded, run_task_with_random_delay, **job_kwargs).tag(tag)
                elif "flow" in definition:
                    # フロータスクの場合
                    schedule.every().day.at(entry.time).do(run_threaded, _run_task_internal, tag=tag, is_part_of_flow=False, **job_kwargs).tag(tag)
                else:
                    logging.warning(f"タスク '{tag}' には実行可能な関数またはフローが定義されていません。")

    # --- スケジュールファイルの保存ロジックを修正 ---
    # 既存のスケジュールを読み込み、今回の更新対象タグのデータだけを差し替える
    all_schedules = _load_schedules_from_file()

    # 新しい形式で保存: {"enabled": bool, "times": [...]}
    all_schedules[tag] = {
        "enabled": update_request.enabled,
        "times": [t.dict() for t in update_request.times]
    }

    # `_save_schedules_to_file` は scheduler.py 側で処理
    from app.core.scheduler import save_and_reload_schedules
    save_and_reload_schedules(all_schedules)

    return {"status": "success", "message": f"Task '{tag}' schedule updated."}

@router.post("/api/tasks/{tag}/run")
async def run_task_now(tag: str):
    """
    指定されたタスクを即時実行する。
    フローの起点となるタスクとして実行される。
    """
    return _run_task_internal(tag, is_part_of_flow=False)

@router.get("/api/logs", response_class=PlainTextResponse)
async def get_logs():
    """ログファイルの内容をテキスト形式で返します。"""
    try:
        if not os.path.exists(LOG_FILE):
            return "ログファイルはまだ作成されていません。"
        
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            # ファイルの末尾から最大1000行を読み込む
            lines = f.readlines()
            return "".join(lines[-1000:])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ログの読み込みに失敗しました: {str(e)}")


def _run_task_internal(tag: str, is_part_of_flow: bool, **kwargs):
    """
    タスクを実行する内部関数。フローの一部かどうかもハンドリングする。
    :param tag: 実行するタスクのタグ
    :param is_part_of_flow: この実行がフローの一部であるか
    :param kwargs: タスクに渡される追加の引数（例: count）
    """
    # スケジュールライブラリが内部的に渡す可能性のある引数を除外
    flow_run_kwargs = {k: v for k, v in kwargs.items() if k != 'job_func'}

    logging.debug(f"[_run_task_internal] tag={tag}, is_part_of_flow={is_part_of_flow}, kwargs={flow_run_kwargs}")

    definition = TASK_DEFINITIONS.get(tag)

    # --- 商品調達フローの動的切り替え ---
    if tag == "_procure-wrapper": # ラッパータスクが呼び出されたら差し替え
        config = get_config()
        method = config.get("procurement_method", "rakuten_search") # デフォルトは楽天検索
        if method == "rakuten_api":
            actual_tag = "rakuten-api-procure"
        else: # rakuten_search
            actual_tag = "search-and-procure-from-rakuten"
        logging.info(f"商品調達メソッド: {method} を使用します。実行タスク: {actual_tag}")
        definition = TASK_DEFINITIONS.get(actual_tag)

    # --- 投稿文作成フローの動的切り替え ---
    if tag == "create-caption-flow":
        config = get_config()
        method = config.get("caption_creation_method", "api") # デフォルトはAPI方式
        if method == "browser":
            actual_tag = "create-caption-browser"
        else: # api
            actual_tag = "create-caption-gemini"
        logging.info(f"投稿文作成メソッド: {method} を使用します。実行タスク: {actual_tag}")
        definition = TASK_DEFINITIONS.get(actual_tag)

    if not definition:
        return JSONResponse(status_code=404, content={"status": "error", "message": f"Task '{tag}' not found."})

    # 新しい "flow" キーを優先的にチェック
    flow_definition = definition.get("flow")
    if flow_definition and not is_part_of_flow:
        # 1. デフォルト引数をコピー
        flow_kwargs = definition.get("default_kwargs", {}).copy()
        # 2. スケジュール実行などから渡された引数で上書き
        flow_kwargs.update(flow_run_kwargs)

        logging.debug(f"--- 新フロー実行: 「{definition['name_ja']}」を開始します。 ---")

        def run_flow():
            import inspect
            # flow_definitionが文字列かリストか判定
            if isinstance(flow_definition, str):
                tasks_in_flow = [(task.strip(), {}) for task in flow_definition.split('|')]
            else: # リスト形式の場合
                tasks_in_flow = flow_definition

            for i, (sub_task_id, sub_task_args) in enumerate(tasks_in_flow):
                if sub_task_id in TASK_DEFINITIONS:
                    # --- フロー内の動的切り替えロジック ---
                    if sub_task_id == "_procure-wrapper":
                        config = get_config()
                        method = config.get("procurement_method", "rakuten_search")
                        if method == "rakuten_api":
                            sub_task_id = "rakuten-api-procure"
                        else: # rakuten_search
                            sub_task_id = "search-and-procure-from-rakuten"
                        logging.info(f"フロー内タスクを動的に解決: {sub_task_id}")
                    
                    if sub_task_id == "create-caption-flow":
                        config = get_config()
                        method = config.get("caption_creation_method", "api")
                        if method == "browser":
                            sub_task_id = "create-caption-browser"
                        else: # api
                            sub_task_id = "create-caption-gemini"
                        logging.info(f"フロー内タスクを動的に解決: {sub_task_id}")

                    sub_task_def = TASK_DEFINITIONS[sub_task_id]
                    logging.debug(f"  フロー実行中 ({i+1}/{len(tasks_in_flow)}): 「{sub_task_def['name_ja']}」")
                    sub_task_func = sub_task_def["function"]
                    
                    # 引数を解決
                    final_kwargs = sub_task_def.get("default_kwargs", {}).copy()
                    for key, value in sub_task_args.items():
                        if value == "flow_count":
                            final_kwargs[key] = flow_kwargs.get('count')
                    # フロー全体に渡された引数で、個別のタスクの引数を上書きする
                    final_kwargs.update(flow_kwargs)
                    
                    try:
                        # タスク関数が実際に受け取れる引数のみを渡す
                        sig = inspect.signature(sub_task_func)
                        valid_args = {
                            k: v for k, v in final_kwargs.items() 
                            if k in sig.parameters
                        }
                        task_result = sub_task_func(**valid_args)
                        if task_result is False: # 明示的にFalseの場合のみ失敗とみなす
                            logging.error(f"フロー内のタスク「{sub_task_def['name_ja']}」が失敗しました。フローを中断します。")
                            break
                    except Exception as e:
                        # 本番環境(simple)ではトレースバックを抑制し、開発環境(detailed)では表示する
                        is_detailed_log = os.getenv('LOG_FORMAT', 'detailed').lower() == 'detailed'
                        logging.error(f"フロー内のタスク「{sub_task_def['name_ja']}」実行中に予期せぬエラーが発生しました: {e}", exc_info=is_detailed_log)
                        logging.error("フローの実行を中断します。")
                        break
                else:
                    logging.error(f"フロー内のタスク「{sub_task_id}」が見つかりません。フローを中断します。")
                    break
            else: # ループが正常に完了した場合
                logging.debug(f"--- 新フロー実行: 「{definition['name_ja']}」が正常に完了しました。 ---")
        
        run_threaded(run_flow)
        return {"status": "success", "message": f"タスクフロー「{definition['name_ja']}」(件数: {flow_kwargs.get('count')})の実行を開始しました。"}

    def task_wrapper(**kwargs):
        """タスク実行後に後続タスクを呼び出すラッパー関数"""
        task_func = definition["function"]
        # タスクを実行し、その戻り値を取得
        result = task_func(**kwargs)
        # 従来の "on_success" フロー (resultがTrueの場合のみ実行)
        if not is_part_of_flow and "on_success" in definition and result is True:
            next_task_tag = definition["on_success"]
            logging.debug(f"--- 従来フロー実行: 「{definition['name_ja']}」が完了。次のタスク「{TASK_DEFINITIONS[next_task_tag]['name_ja']}」を実行します。 ---")
            _run_task_internal(next_task_tag, is_part_of_flow=True, **kwargs) # 引数を引き継ぐ
        return result

    # 結果を待って返すタイプのタスク
    if tag in ["check-login-status", "save-auth-state", "restore-auth-state"]:
        # save-auth-stateは手動操作のため、タイムアウトを長めに設定
        timeout = 310 if "save-auth-state" in tag else 60

        # task_wrapperは後続タスクを呼び出す可能性があるため、直接タスク関数を呼び出す
        task_func = definition["function"]
        job_thread, result_container = run_threaded(task_func, **kwargs)
        job_thread.join(timeout=timeout) # タスクに応じた時間待つ
        if job_thread.is_alive():
            return JSONResponse(status_code=500, content={"status": "error", "message": "タスクがタイムアウトしました。"})
        
        result = result_container.get('result')
        logging.debug(f"スレッドから受け取った結果 (タスク: {tag}): {result} (型: {type(result)})")
        if "check-login-status" in tag:
            message = "成功: ログイン状態が維持されています。" if result else "失敗: ログイン状態が確認できませんでした。"
        elif "save-auth-state" in tag:
            message = "成功: 認証状態を保存しました。" if result else "失敗: 認証状態の保存に失敗しました。詳細はログを確認してください。"
        elif "restore-auth-state" in tag:
            message = "成功: 認証プロファイルを復元しました。" if result else "失敗: 認証プロファイルの復元に失敗しました。詳細はログを確認してください。"
        else:
            message = "タスクが完了しました。" # フォールバックメッセージ
        
        logging.debug(f"APIレスポンス (タスク: {tag}): {message}")

        return JSONResponse(content={"status": "success" if result else "error", "message": message})

    # 上記以外のバックグラウンドで実行するタスク
    # 1. デフォルト引数を取得, 2. 実行時引数で上書き
    final_kwargs = definition.get("default_kwargs", {}).copy() 
    final_kwargs.update(kwargs)
    job_thread, result_container = run_threaded(task_wrapper, **final_kwargs) 

    message = f"タスク「{definition['name_ja']}」の実行を開始しました。"
    logging.debug(f"APIレスポンス (タスク: {tag}): {message}")
    return {"status": "success", "message": message}