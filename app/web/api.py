from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, FileResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates 
import schedule
import re
import logging
import os
import json
from pydantic import BaseModel
from typing import Optional, List
from pathlib import Path
from fastapi import BackgroundTasks
import random
import string
import threading

# タスク定義を一元的にインポート
from app.core.task_manager import TaskManager
from app.core.task_definitions import TASK_DEFINITIONS
from app.core.database import (get_all_inventory_products, update_product_status, delete_all_products, init_db, get_product_by_id,
                               delete_product, update_status_for_multiple_products, delete_multiple_products, get_product_count_by_status, get_reusable_products, recollect_product, bulk_recollect_products, update_product_post_url, update_product_room_url, get_all_error_products,
                               get_posted_products, get_posted_product_shop_summary, update_product_priority, update_product_order, bulk_update_products_from_data, commit_user_actions, get_all_user_engagements, get_users_for_commenting,
                               update_user_comment, get_generated_replies, update_reply_text, ignore_reply, get_commenting_users_summary,
                               get_table_names, export_tables_as_sql, execute_sql_script)
from app.tasks.posting import run_posting
from app.tasks.get_post_url import run_get_post_url
from app.tasks.delete_room_post import run_delete_room_post
from app.core.logging_config import LOG_FILE # ログファイルのパスをインポート


from app.core.config_manager import get_config, save_config, SCREENSHOT_DIR, clear_config_cache

from app.tasks.prompt_test_task import PromptTestTask
from app.core.scheduler_utils import run_threaded, run_task_with_random_delay, get_log_summary
from datetime import date, timedelta, datetime

# --- 実行中フローの追跡用 ---
RUNNING_FLOWS = set()
_flow_lock = threading.Lock()
# --------------------------


KEYWORDS_FILE = "db/keywords.json"
SCHEDULE_FILE = "db/schedules.json"
SOURCE_URLS_FILE = "db/source_urls.json"
LAST_USED_URL_INDEX_FILE = "db/last_used_url_index.json"
RECENT_KEYWORDS_FILE = "db/recent_keywords.json"
SCHEDULE_PROFILES_DIR = "db/schedule_profiles"
KEYWORD_PROFILES_DIR = "db/keyword_profiles"
PROMPT_PROFILES_DIR = "db/prompt_profiles"

PROMPTS_DIR = "app/prompts"
class TimeEntry(BaseModel):
    time: str
    count: int

# --- Prompt Pydantic Models ---
class Prompt(BaseModel):
    filename: str
    content: str
    name_ja: str
    description: str

class PromptUpdateRequest(BaseModel):
    content: str

class PromptTestRequest(BaseModel):
    prompt_key: str
    prompt_content: str
    test_data: list[dict]

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
    debug_screenshot_enabled: bool | None = None
    preferred_profile: str | None = None # 優先プロファイル設定を追加

class JsonImportRequest(BaseModel):
    products: list[dict]

class BulkUpdateRequest(BaseModel):
    product_ids: list[int]

class UserIdsRequest(BaseModel):
    user_ids: list[str]

class BulkEngageRequest(BaseModel):
    users: list[dict]
    dry_run: bool = False
    engage_mode: str = 'all'
    like_count: int | None = None

class UserBulkLikeBack(BaseModel):
    user_ids: list[str]
    like_count: int
    dry_run: bool = False

class BulkStatusUpdateRequest(BaseModel):
    product_ids: list[int]
    status: str

class KeywordsUpdateRequest(BaseModel):
    keywords_a: list[str]
    keywords_b: list[str]
    source_urls: Optional[list[str]] = None

class CommentUpdateRequest(BaseModel):
    user_id: str
    comment_text: str

class ReplyUpdateRequest(BaseModel):
    reply_text: str

class BulkPostRepliesRequest(BaseModel):
    replies: list[dict]
    dry_run: bool = False

class DbExportRequest(BaseModel):
    table_names: list[str]
    include_delete: bool = False

class PostUrlUpdateRequest(BaseModel):
    post_url: str

class RoomUrlUpdateRequest(BaseModel):
    room_url: str

class AiCaptionUpdateRequest(BaseModel):
    ai_caption: str

class DbImportRequest(BaseModel):
    sql_script: str



# --- HTML Routes ---
router = APIRouter()

# ★★★ デバッグ用ログ ★★★
logging.warning("--- api.py is being loaded by the application. ---")

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

@router.get("/posted-products", response_class=HTMLResponse)
async def read_posted_products_page(request: Request):
    """投稿済商品一覧ページを表示する"""
    return request.app.state.templates.TemplateResponse("posted_products.html", {"request": request})

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
    # 例: error_post_comment_user123_20231027-103000.png
    # 例: dry_run_engage-user_user123_20231027-103000.png
    # 例: login_check_redirect_ログイン状態チェック_20251109-075422.png
    # グループ: 1:type, 2:action, 3:details, 4:timestamp
    # 新しいファイル形式 `login_check_redirect_...` にも対応できるよう正規表現を修正
    # `type` と `action` をまとめて `prefix` としてキャプチャし、後から判定する
    filename_pattern = re.compile(r'^(?P<prefix>[a-zA-Z0-9_-]+)_(?P<details>.+?)_(?P<timestamp>\d{4,8}-\d{6})\.png$')

    all_files = []
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
                all_files.append(filename)
                
                action_name = "不明なアクション"
                timestamp_display = "不明な日時"
                details_display = ""
                file_type = "unknown"

                match = filename_pattern.match(filename)
                if match:
                    parsed_data = match.groupdict()
                    prefix = parsed_data.get('prefix', '')
                    details_display = parsed_data.get('details', '')

                    # prefixからtypeとactionを判定
                    if prefix.startswith('dry_run'):
                        file_type = 'dry_run'
                        action_tag = prefix.replace('dry_run_', '')
                        # タスク定義から日本語名を取得しようと試み、見つからなければタグをそのまま表示
                        definition = TASK_DEFINITIONS.get(action_tag)
                        action_name = definition.get('name_ja') if definition else action_tag

                    elif prefix.startswith('login_check_redirect'):
                        file_type = 'error'
                        action_name = "ログイン失敗" # 専用の分かりやすい名前を付ける
                    else: # 'error_...' やその他の形式
                        file_type = 'error'
                        action_tag = prefix.replace('error_', '')
                        action_name = TASK_DEFINITIONS.get(action_tag, {}).get('name_ja', action_tag)

                    raw_timestamp = parsed_data['timestamp']
                    try:
                        dt_obj = datetime.strptime(raw_timestamp, '%Y%m%d-%H%M%S')
                        timestamp_display = dt_obj.strftime('%Y-%m-%d %H:%M')
                    except ValueError:
                        timestamp_display = f"不正な日時 ({raw_timestamp})"

                file_details[filename] = {'action_name': action_name, 'timestamp': timestamp_display, 'type': file_type, 'details': details_display}

    return request.app.state.templates.TemplateResponse("error_management.html", {"request": request, "files": all_files, "file_details": file_details})

@router.get("/prompts", response_class=HTMLResponse)
async def prompts_editor(request: Request):
    """プロンプト編集ページを表示する"""
    return request.app.state.templates.TemplateResponse("prompts.html", {"request": request})

@router.get("/generated-replies", response_class=HTMLResponse)
async def read_generated_replies(request: Request):
    """生成済みコメント確認ページを表示する"""
    return request.app.state.templates.TemplateResponse("generated_replies.html", {"request": request})

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

            all_tasks[tag] = {
                "tag": tag, 
                "name_ja": definition["name_ja"], 
                "enabled": True, 
                "times": [], 
                "next_run": None,
                "show_count_in_schedule": definition.get("show_count_in_schedule", True) # ★この行を追加
            }

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

@router.get("/api/schedules/next")
async def get_next_schedule():
    """直近のスケジュールを1件だけ返す"""
    all_jobs = schedule.get_jobs()
    # 実行予定時刻があり、有効なタグを持つジョブのみを抽出
    scheduled_jobs = [job for job in all_jobs if job.next_run and job.tags]
    
    if not scheduled_jobs:
        return JSONResponse(content={})

    # 最も実行時刻が近いジョブを見つける
    next_job = min(scheduled_jobs, key=lambda j: j.next_run)
    
    tag = list(next_job.tags)[0]
    definition = TASK_DEFINITIONS.get(tag, {})
    
    return JSONResponse(content={
        "name": definition.get("name_ja", "不明なタスク"),
        "next_run": next_job.next_run.isoformat() # JavaScriptで扱いやすいISO形式で返す
    })


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
    config = get_config()
    return JSONResponse(content=config)

@router.get("/api/inventory")
async def get_inventory():
    """在庫商品（「投稿済」以外）のリストをJSONで返す"""
    products = get_all_inventory_products()
    # sqlite3.Rowは直接JSONシリアライズできないため、辞書のリストに変換
    products_list = [dict(product) for product in products]
    return JSONResponse(content=products_list)

@router.get("/api/posted-products")
async def api_get_posted_products(
    page: int = 1,
    per_page: int = 30,
    search_term: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    room_url_unlinked: bool = False,
    shop_name: Optional[str] = None,
    comment_search: Optional[str] = None
):
    """投稿済商品をページネーション付きで取得する"""
    try:
        products, total_pages, total_items = get_posted_products(
            page=page,
            per_page=per_page,
            search_term=search_term,
            start_date=start_date,
            end_date=end_date,
            room_url_unlinked=room_url_unlinked,
            shop_name=shop_name,
            comment_search_text=comment_search
        )
        
        return JSONResponse(content={"products": products, "total_pages": total_pages, "current_page": page, "total_items": total_items})
    except Exception as e:
        logging.error(f"投稿済商品の取得中にエラー: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="商品の取得に失敗しました。")

@router.get("/api/posted-products/shops")
async def api_get_distinct_shop_names():
    """投稿済商品に含まれるショップ名の一覧を返す"""
    try:
        shops_summary = get_posted_product_shop_summary()
        return JSONResponse(content={"shops": shops_summary})
    except Exception as e:
        logging.error(f"ショップ名一覧の取得中にエラー: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="ショップ名一覧の取得に失敗しました。")


@router.post("/api/posted-products/{product_id}/recollect")
async def api_recollect_posted_product(product_id: int, background_tasks: BackgroundTasks):
    """指定された投稿済商品を「再コレ」するタスクを開始する"""
    product = get_product_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品が見つかりません。")

    task_manager = TaskManager()
    background_tasks.add_task(
        task_manager.run_task_by_tag,
        "recollect-product-flow",
        products=[{'id': product_id, 'room_url': product.get('room_url')}],
        action='recollect'
    )
    return JSONResponse(content={"status": "success", "message": f"商品ID: {product_id} の再コレ処理を開始しました。"})

@router.post("/api/posted-products/bulk-recollect")
async def api_bulk_recollect_posted_products(request: BulkUpdateRequest, background_tasks: BackgroundTasks):
    """複数の投稿済商品を「再コレ」するタスクを開始する"""
    if not request.product_ids:
        raise HTTPException(status_code=400, detail="商品IDが指定されていません。")
    
    products_to_process = []
    for product_id in request.product_ids:
        product = get_product_by_id(product_id)
        if product:
            products_to_process.append({'id': product_id, 'room_url': product.get('room_url')})

    task_manager = TaskManager()
    if products_to_process:
        background_tasks.add_task(task_manager.run_task_by_tag, "recollect-product-flow", products=products_to_process, action='recollect')

    return JSONResponse(content={"status": "success", "message": f"{len(request.product_ids)}件の商品の再コレ処理を開始しました。"})

@router.delete("/api/posted-products/{product_id}")
async def api_delete_posted_product(product_id: int, background_tasks: BackgroundTasks):
    """指定された投稿済商品を削除するタスクを開始する"""
    product = get_product_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品が見つかりません。")

    # 1件でもリストとして渡す
    task_manager = TaskManager()
    products_to_process = [{'id': product_id, 'room_url': product.get('room_url')}]
    background_tasks.add_task(task_manager.run_task_by_tag, "delete-product-flow", products=products_to_process, action='delete')
    return JSONResponse(content={"status": "success", "message": f"商品ID: {product_id} の削除処理を開始しました。"})

@router.post("/api/posted-products/bulk-delete") # DELETE with body is tricky, so use POST
async def api_bulk_delete_posted_products(request: BulkUpdateRequest, background_tasks: BackgroundTasks):
    """複数の投稿済商品を削除するタスクを開始する"""
    if not request.product_ids:
        raise HTTPException(status_code=400, detail="商品IDが指定されていません。")
    products_to_process = []
    for product_id in request.product_ids:
        product = get_product_by_id(product_id)
        if product:
            products_to_process.append({'id': product_id, 'room_url': product.get('room_url')})
    task_manager = TaskManager()
    if products_to_process:
        background_tasks.add_task(task_manager.run_task_by_tag, "delete-product-flow", products=products_to_process, action='delete')
    return JSONResponse(content={"status": "success", "message": f"{len(request.product_ids)}件の商品の削除処理を開始しました。"})

@router.post("/api/posted-products/{product_id}/update-url")
async def api_update_posted_product_url(product_id: int, request: PostUrlUpdateRequest):
    """指定された投稿済商品のROOM投稿URLを更新する"""
    try:
        updated_count = update_product_post_url(product_id, request.post_url)
        
        if updated_count == 0:
            raise HTTPException(status_code=404, detail="商品が見つからないか、URLの更新に失敗しました。")
        
        return JSONResponse(content={"status": "success", "message": "ROOM投稿URLを更新しました。"})
    except Exception as e:
        logging.error(f"商品ID {product_id} のURL更新中にエラー: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="サーバーエラーによりURLの更新に失敗しました。")

@router.patch("/api/posted-products/{product_id}/room-url")
async def api_update_posted_product_room_url(product_id: int, request: RoomUrlUpdateRequest):
    """指定された投稿済商品の投稿済ROOMページURL(room_url)を更新する"""
    try:
        updated_count = update_product_room_url(product_id, request.room_url)
        
        if updated_count == 0:
            raise HTTPException(status_code=404, detail="商品が見つからないか、URLの更新に失敗しました。")
        
        return JSONResponse(content={"status": "success", "message": "投稿済ROOMページのURLを更新しました。"})
    except Exception as e:
        logging.error(f"商品ID {product_id} のroom_url更新中にエラー: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="サーバーエラーによりURLの更新に失敗しました。")


# BulkUpdateRequest is already defined, no need for PostedProductBulkUpdateRequest
# class PostedProductBulkUpdateRequest(BaseModel):
#     product_ids: list[int]



@router.get("/api/errors")
async def get_error_products():
    """エラー商品（過去24時間）のリストをJSONで返す"""
    products = get_all_error_products()
    # get_error_products_in_last_24h は既に辞書のリストを返す
    return JSONResponse(content=products)

@router.get("/api/errors/summary")
async def get_errors_summary():
    """エラー商品数とスクリーンショット数の合計を返す"""
    try:
        # エラー商品数を取得
        error_products = get_all_error_products()
        error_product_count = len(error_products)

        # スクリーンショット数を取得
        screenshot_count = 0
        screenshot_path = Path(SCREENSHOT_DIR)
        if screenshot_path.exists():
            screenshot_count = len([name for name in os.listdir(screenshot_path) if os.path.isfile(os.path.join(screenshot_path, name)) and name.lower().endswith('.png')])
        
        return JSONResponse(content={
            "error_product_count": error_product_count,
            "screenshot_count": screenshot_count
        })
    except Exception as e:
        logging.error(f"エラーサマリーの取得中にエラー: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="エラーサマリーの取得に失敗しました。")

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
        period = request.query_params.get('period', 'today') # クエリパラメータから期間を取得, デフォルトを 'today' に変更
        
        # period パラメータのバリデーション
        allowed_periods = ['today', '24h', 'yesterday', 'day_before_yesterday']
        if period not in allowed_periods:
            period = 'today'
        log_summary = get_log_summary(period=period)

        # 24時間以内のエラー商品数を取得
        all_error_products = get_all_error_products()
        total_error_product_count = len(all_error_products)

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
                    "count": job_kwargs.get('count', 0),
                    "show_count": definition.get("show_count_in_dashboard", True) # ★フラグを追加
                }
                next_schedules_info.append(schedule_info)

        # レスポンスのキーを複数形に変更
        summary = {
            **log_summary,
            "next_schedules": next_schedules_info,
            "error_product_count": total_error_product_count
        }
        # logging.debug(f"[DASHBOARD_API] 処理成功。フロントエンドに返すデータ: {summary}")
        return JSONResponse(content=summary)
    except Exception as e:
        # エラー発生時に詳細なトレースバックをログに出力
        logging.error(f"ダッシュボードサマリーの取得中に予期せぬエラーが発生しました。", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": "サマリーデータの取得に失敗しました。"})

@router.get("/api/engagement-summary")
async def get_engagement_summary():
    """いいね返し・コメント返し対象のユーザー数を返す"""
    try:
        users = get_users_for_commenting(limit=100) # 十分な数を取得
        like_only_count = 0
        comment_target_count = 0
        for user in users:
            if user.get('engagement_type') == 'comment':
                comment_target_count += 1
            elif user.get('engagement_type') == 'like_only':
                like_only_count += 1
        
        return JSONResponse(content={"like_back_target_count": like_only_count, "comment_target_count": comment_target_count})
    except Exception as e:
        logging.error(f"エンゲージメントサマリーの取得中にエラー: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"like_back_target_count": 0, "comment_target_count": 0})

@router.get("/api/dashboard/recent-keywords")
async def get_recent_keywords():
    """最近使ったキーワードを返す"""
    try:
        if os.path.exists(RECENT_KEYWORDS_FILE):
            with open(RECENT_KEYWORDS_FILE, "r", encoding="utf-8") as f:
                keywords = json.load(f) # これはオブジェクトのリスト [{keyword: "...", genre_name: "...", genre_id: "..."}, ...]
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

@router.patch("/api/inventory/{product_id}/update-caption")
async def api_update_inventory_caption(product_id: int, request: AiCaptionUpdateRequest):
    """指定された在庫商品のAIキャプションを更新する"""
    try:
        # database.pyのupdate_ai_caption関数を呼び出す
        from app.core.database import update_ai_caption
        updated_count = update_ai_caption(product_id, request.ai_caption)
        
        if updated_count == 0:
            raise HTTPException(status_code=404, detail="商品が見つからないか、投稿文の更新に失敗しました。")
        
        return JSONResponse(content={"status": "success", "message": "投稿文を更新しました。"})
    except Exception as e:
        logging.error(f"商品ID {product_id} の投稿文更新中にエラー: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"サーバーエラーにより投稿文の更新に失敗しました: {str(e)}")

@router.post("/api/inventory/bulk-regenerate-caption")
async def bulk_regenerate_inventory_caption(request: BulkUpdateRequest, background_tasks: BackgroundTasks):
    """
    複数の在庫商品の投稿文を再生成するフローを開始する。
    1. DBのステータスを「URL取得済」に戻し、AIキャプション関連の情報をクリアする。
    2. 「投稿文作成」フロータスクを実行する。
    """
    product_ids = request.product_ids
    if not product_ids:
        raise HTTPException(status_code=400, detail="商品IDが指定されていません。")
    
    try:
        task_manager = TaskManager()
        # 新しく定義したフローを呼び出す。引数としてproduct_idsを渡す。
        background_tasks.add_task(
            task_manager.run_task_by_tag, "bulk-regenerate-caption-flow", product_ids=product_ids
        )
        
        return JSONResponse(content={"status": "success", "message": f"{len(product_ids)}件の商品の投稿文再生成タスクを開始しました。"})
    except Exception as e:
        logging.error(f"投稿文の一括再生成処理中にエラー: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="サーバーエラーにより処理を開始できませんでした。")

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
async def get_comment_targets(request: Request):
    """コメント投稿対象のユーザーリストを返す"""
    try:
        show_all_param = request.query_params.get('all', 'false')
        show_all = show_all_param.lower() == 'true'
        search_keyword = request.query_params.get('search', '')
        sort_by_param = request.query_params.get('sort', 'not_provided')

        logging.debug(f"[API:get_comment_targets] Request params: all='{show_all_param}', sort='{sort_by_param}', search='{search_keyword}'")
        
        if show_all:
            # 全ユーザー表示モード。ソート順をクエリパラメータから取得
            sort_by = sort_by_param if sort_by_param != 'not_provided' else 'all'
            logging.debug(f"[API:get_comment_targets] Calling get_all_user_engagements with: sort_by='{sort_by}', search='{search_keyword}'")
            users = get_all_user_engagements(sort_by=sort_by, limit=200, search_keyword=search_keyword)
            logging.debug(f"[API:get_comment_targets] get_all_user_engagements returned {len(users)} users.")
        else:
            # 通常のコメント対象ユーザー表示モード
            logging.debug("[API:get_comment_targets] Calling get_users_for_commenting.")
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
        updated_count = commit_user_actions(user_ids=user_ids, is_comment_posted=False)
        return JSONResponse(content={"message": f"{updated_count}件のユーザーをスキップしました。", "count": updated_count})
    except Exception as e:
        logging.error(f"ユーザーの一括スキップ処理中にエラーが発生しました: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="サーバーエラーが発生しました。")

@router.post("/api/users/bulk-engage", summary="選択した複数のユーザーにエンゲージメントタスクを実行")
async def engage_with_multiple_users(request: BulkEngageRequest, background_tasks: BackgroundTasks):
    """
    選択された複数のユーザーに対して、いいねバックとコメント投稿のタスクを非同期で実行する。
    """
    if not request.users:
        raise HTTPException(status_code=400, detail="対象ユーザーが指定されていません。")

    # engage_modeに応じて実行するフローのタグを決定
    if request.engage_mode == 'like_only':
        task_tag = "new-engage-flow-like-only"
    elif request.engage_mode == 'comment_only':
        task_tag = "new-engage-flow-comment-only"
    else: # 'all' または未指定の場合
        task_tag = "new-engage-flow-all"

    task_manager = TaskManager()
    background_tasks.add_task(
        task_manager.run_task_by_tag, 
        task_tag, 
        users=request.users, 
        dry_run=request.dry_run, 
        engage_mode=request.engage_mode,
        like_count=request.like_count
    )

    return {"message": f"{len(request.users)}件のユーザーへのエンゲージメントタスクを開始しました。(Mode: {request.engage_mode}, Dry Run: {request.dry_run})"}

@router.patch("/api/users/update-comment", summary="指定されたユーザーのコメントを更新")
async def patch_user_comment(request: CommentUpdateRequest):
    """
    指定されたユーザーIDのコメントテキストを更新する。
    """
    try:
        update_user_comment(
            user_id=request.user_id,
            comment_text=request.comment_text
        )
        return JSONResponse(content={"status": "success", "message": "コメントを更新しました。"})
    except Exception as e:
        logging.error(f"ユーザー(ID: {request.user_id})のコメント更新中にエラーが発生しました: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="サーバーエラーによりコメントの更新に失敗しました。")

@router.get("/api/generated-replies")
async def api_get_generated_replies(request: Request):
    """生成済みの返信コメントをグループ化して取得する"""
    try:
        hours_ago_str = request.query_params.get('hours_ago', '24')
        try:
            hours_ago = int(hours_ago_str)
        except ValueError:
            hours_ago = 24 # デフォルト値
        comments = get_generated_replies(hours_ago=hours_ago)
        
        # post_detail_url ごとにグループ化し、その中で reply_text ごとにグループ化する
        posts = {}
        for comment in comments:
            post_url = comment['post_detail_url']
            if post_url not in posts:
                posts[post_url] = {}
            
            reply_text = comment.get('reply_text', '（返信テキストなし）')
            if reply_text not in posts[post_url]:
                posts[post_url][reply_text] = []
            
            posts[post_url][reply_text].append(dict(comment))

        # 投稿ごとに最新の reply_generated_at を見つけてソートするためのリストを作成
        sorted_post_list = []
        for post_url, replies in posts.items():
            latest_ts = None
            for reply_text, comments in replies.items():
                for comment in comments:
                    if not latest_ts or comment['reply_generated_at'] > latest_ts:
                        latest_ts = comment['reply_generated_at']
            sorted_post_list.append({'post_url': post_url, 'replies': replies, 'latest_ts': latest_ts})
        
        # 最新のタイムスタンプが新しい順にソート
        sorted_post_list.sort(key=lambda x: x['latest_ts'], reverse=True)

        # ソート後のデータを再構築
        sorted_posts = {item['post_url']: item['replies'] for item in sorted_post_list}

        # コメントユーザーのサマリーを取得
        commenting_users_raw = get_commenting_users_summary(limit=100)
        # DBから取得したキー 'user_image_url' を、フロントエンドが期待する 'user_icon_url' に変更する
        commenting_users = [{**{k: v for k, v in dict(user).items() if k != 'user_image_url'}, 'user_icon_url': user['user_image_url']} for user in commenting_users_raw]

        return JSONResponse(content={
            "posts": sorted_posts,
            "commenting_users": commenting_users
        })
    except Exception as e:
        logging.error(f"生成済みコメントの取得中にエラー: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "データの取得に失敗しました。"})

@router.patch("/api/generated-replies/{representative_id}")
async def api_update_reply(comment_id: int, request: ReplyUpdateRequest):
    """特定のコメントグループの返信テキストを一括で更新する"""
    try:
        # データベース関数を正しい引数で呼び出す
        update_reply_text(comment_id=comment_id, new_text=request.reply_text)
        return JSONResponse(content={"status": "success"})
    except Exception as e:
        logging.error(f"コメントグループ(代表ID: {comment_id})の更新中にエラー: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"コメントの更新に失敗しました: {str(e)}")

@router.delete("/api/generated-replies/{comment_id}")
async def api_ignore_reply(comment_id: int):
    """特定のコメントを返信対象から除外する"""
    try:
        ignore_reply(comment_id)
        return JSONResponse(content={"status": "success"})
    except Exception as e:
        logging.error(f"コメント(ID: {comment_id})の無視処理中にエラー: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": "処理に失敗しました。"})

@router.post("/api/replies/bulk-post", summary="選択した複数のコメントに返信するタスクを実行")
async def bulk_post_replies(request: BulkPostRepliesRequest, background_tasks: BackgroundTasks):
    """
    選択された複数のコメントに対して、返信投稿タスクを非同期で実行する。
    """
    if not request.replies:
        raise HTTPException(status_code=400, detail="対象の返信が指定されていません。")

    task_manager = TaskManager()
    background_tasks.add_task(
        task_manager.run_task_by_tag,
        "reply-to-comment",
        replies=request.replies,
        dry_run=request.dry_run
    )

    mode_text = "予行投稿" if request.dry_run else "投稿"
    return {"message": f"{len(request.replies)}件のコメントへの「{mode_text}」タスクを開始しました。"}

@router.get("/api/db/tables", summary="DBのテーブル一覧を取得")
async def api_get_db_tables():
    """データベースに存在するテーブル名の一覧を返す。"""
    try:
        tables = get_table_names()
        return JSONResponse(content={"tables": tables})
    except Exception as e:
        logging.error(f"DBテーブル一覧の取得中にエラー: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="テーブル一覧の取得に失敗しました。")

@router.post("/api/db/export", summary="選択したテーブルをSQLでエクスポート")
async def api_export_db(request: DbExportRequest):
    """指定されたテーブルのデータをSQL形式でエクスポートする。"""
    try:
        sql_dump = export_tables_as_sql(request.table_names, request.include_delete)
        return PlainTextResponse(content=sql_dump)
    except Exception as e:
        logging.error(f"DBのエクスポート中にエラー: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="エクスポート処理に失敗しました。")

@router.post("/api/db/import", summary="SQLクエリを実行してDBを操作")
async def api_import_db(request: DbImportRequest):
    """
    受け取ったSQLスクリプトを実行する。
    注意: このエンドポイントは強力な権限を持つため、アクセス制御を適切に行うこと。
    """
    if not request.sql_script.strip():
        raise HTTPException(status_code=400, detail="実行するSQLクエリがありません。")
    try:
        execute_sql_script(request.sql_script)
        return JSONResponse(content={"status": "success", "message": "SQLクエリが正常に実行されました。"})
    except Exception as e:
        logging.error(f"DBのインポート(SQL実行)中にエラー: {e}", exc_info=True)
        # エラーメッセージをフロントに返す
        raise HTTPException(status_code=500, detail=f"SQLの実行に失敗しました: {str(e)}")

@router.post("/api/db/export-reusable-products", response_class=Response)
async def export_reusable_products():
    """
    procurement_keywordが「再コレ再利用」の商品を抽出し、
    SQLite用のINSERT OR REPLACEクエリを生成して返す。
    """
    try:
        # 条件に合う商品をすべて取得
        products = get_reusable_products()

        if not products:
            return Response(content="-- 対象となる「再コレ再利用」商品はありませんでした。", media_type="text/plain; charset=utf-8")

        # INSERT OR REPLACE文を生成
        sql_statements = []
        sql_statements.append("-- 「再コレ再利用」商品データのエクスポート\n")
        sql_statements.append(f"-- {len(products)}件の商品が見つかりました\n")

        # 最初のレコードからカラム名を取得
        columns = list(products[0].keys())
        
        # post_urlを主キーとして扱うため、idはエクスポート対象から外す
        if 'id' in columns:
            columns.remove('id')

        column_str = ", ".join(f'"{col}"' for col in columns)

        for product in products:
            values = []
            for col in columns:
                value = product[col]
                if value is None:
                    values.append("NULL")
                elif isinstance(value, (int, float)):
                    values.append(str(value))
                else:
                    # 文字列内のシングルクォートをエスケープ
                    escaped_value = str(value).replace("'", "''") if value else ''
                    values.append(f"'{escaped_value}'")
            
            values_str = ", ".join(values)
            sql_statements.append(f"INSERT OR REPLACE INTO products ({column_str}) VALUES ({values_str});")

        full_sql_script = "\n".join(sql_statements)
        return Response(content=full_sql_script, media_type="text/plain; charset=utf-8")

    except Exception as e:
        logging.error(f"再利用商品のエクスポート中にエラーが発生しました: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"再利用商品のエクスポート中にエラーが発生しました: {str(e)}")

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
    keywords = {"keywords_a": [], "keywords_b": []}
    source_urls = []
    try:
        # キーワードファイルの読み込み
        if os.path.exists(KEYWORDS_FILE):
            with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
                keywords = json.load(f)
        
        # URLリストファイルの読み込み
        if os.path.exists(SOURCE_URLS_FILE):
            with open(SOURCE_URLS_FILE, "r", encoding="utf-8") as f:
                source_urls = json.load(f)

        response_data = {
            "keywords_a": keywords.get("keywords_a", []),
            "keywords_b": keywords.get("keywords_b", []),
            "source_urls": source_urls
        }
        return JSONResponse(content=response_data)
    except (IOError, json.JSONDecodeError) as e:
        logging.error(f"キーワードまたはURLリストの読み込みに失敗しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "キーワードの読み込みに失敗しました。"})

@router.post("/api/keywords")
async def save_keywords(request: KeywordsUpdateRequest):
    """キーワードをJSONファイルに保存する"""
    try:
        # キーワードA群とB群を保存
        keyword_data = {"keywords_a": request.keywords_a, "keywords_b": request.keywords_b}
        with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(keyword_data, f, indent=2, ensure_ascii=False)

        # URLリストを保存
        if request.source_urls is not None:
            current_urls = []
            if os.path.exists(SOURCE_URLS_FILE):
                with open(SOURCE_URLS_FILE, "r", encoding="utf-8") as f:
                    current_urls = json.load(f)
            
            # URLリストが変更されていたら、ローテーションインデックスをリセット
            if current_urls != request.source_urls:
                logging.info("URLリストが変更されたため、巡回インデックスをリセットします。")
                with open(LAST_USED_URL_INDEX_FILE, "w", encoding="utf-8") as f:
                    json.dump({"last_index": -1}, f)

            with open(SOURCE_URLS_FILE, "w", encoding="utf-8") as f:
                json.dump(request.source_urls, f, indent=2, ensure_ascii=False)

        return JSONResponse(content={"status": "success", "message": "キーワードとURLリストを保存しました。"})
    except (IOError, json.JSONDecodeError) as e:
        logging.error(f"キーワードまたはURLリストの保存に失敗しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "キーワード等の保存に失敗しました。"})


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
    """設定を更新する。Pydanticモデルまたは生の辞書を受け入れる。"""
    try:
        # Pydanticモデルとしてパースしようと試みる
        update_data = config_request.dict(exclude_unset=True)
    except Exception:
        # ダミーのConfigUpdateRequestインスタンスからdictを取得し、実際のリクエストで更新
        update_data = config_request

    current_config = get_config()
    current_config.update(update_data)
    save_config(current_config)
    # save_config内でキャッシュクリアされるため、ここでの呼び出しは不要
    #logging.info(f"システム設定が更新されました: {update_data}")
    return {"status": "success", "message": "設定を更新しました。", "new_config": get_config()}


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
async def run_task_now(tag: str, request: Request):
    """
    指定されたタスクを即時実行する。
    フローの起点となるタスクとして実行される。
    リクエストボディで引数を渡すことができる。
    """
    try:
        # リクエストボディからJSON形式の引数を取得。ボディが空なら空の辞書。
        extra_kwargs = await request.json() if request.headers.get('content-length') != '0' else {}
    except json.JSONDecodeError:
        extra_kwargs = {} # JSONデコードに失敗した場合も空の辞書
    return _run_task_internal(tag, is_part_of_flow=False, **extra_kwargs)

def _run_task_internal(tag: str, is_part_of_flow: bool, **kwargs):
    """
    タスクを実行する内部関数。フローの一部かどうかもハンドリングする。
    :param tag: 実行するタスクのタグ
    :param is_part_of_flow: この実行がフローの一部であるか
    :param kwargs: タスクに渡される追加の引数（例: count）
    """
    # スケジュールライブラリが内部的に渡す可能性のある引数を除外
    flow_run_kwargs = {k: v for k, v in kwargs.items() if k != 'job_func'}

    definition = TASK_DEFINITIONS.get(tag)

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

        # --- フロー内容の動的書き換え ---
        if tag == "procure-products-flow":
            config = get_config()
            method = config.get("procurement_method", "rakuten_search")
            if method == "user_page_crawl":
                procure_task = "procure-from-user-page"
            elif method == "rakuten_api":
                procure_task = "rakuten-api-procure"
            else: # "rakuten_search" がデフォルト
                procure_task = "search-and-procure-from-rakuten"
            
            logging.debug(f"商品調達メソッド '{method}' を使用します。実行タスク: {procure_task}")
            # フローの先頭に、解決した調達タスクを挿入
            flow_definition.insert(0, (procure_task, {"count": "flow_count"}))

        # --- フローID生成ロジック ---
        def generate_short_flow_id():
            """HHMMxx形式の短いフローIDを生成する (例: 1504a9)"""
            timestamp_part = datetime.now().strftime("%H%M")
            random_part = ''.join(random.choices(string.ascii_lowercase + string.digits, k=2))
            return f"{timestamp_part}{random_part}"

        flow_id = f"{tag}-{generate_short_flow_id()}"

        logging.info(f"フロー実行: 「{definition['name_ja']}」を開始します。 [flow_id:{flow_id}]")

        def run_flow():
            # フローの集計方法を決定
            should_aggregate = definition.get("aggregate_results", False)
            main_success_count = 0 if should_aggregate else None
            total_error_count = 0 if should_aggregate else None
            summary_message = None if should_aggregate else None

            with _flow_lock:
                RUNNING_FLOWS.add(flow_id)

            def format_duration(seconds: float) -> str:
                """実行時間を分かりやすい形式に変換する"""
                if seconds < 60:
                    return f"{seconds:.2f}秒"
                
                seconds_int = int(seconds)
                if seconds_int < 3600:
                    minutes, remaining_seconds = divmod(seconds_int, 60)
                    return f"{minutes}分{remaining_seconds}秒"
                else:
                    hours, remainder = divmod(seconds_int, 3600)
                    minutes, _ = divmod(remainder, 60)
                    return f"{hours}時間{minutes}分"

            import time
            start_time = time.time()

            flow_succeeded = True # フローが成功したかどうかを追跡するフラグ

            import inspect
            # flow_definitionが文字列かリストか判定
            if isinstance(flow_definition, str):
                tasks_in_flow = [(task.strip(), {}) for task in flow_definition.split('|')]
            else: # リスト形式の場合
                tasks_in_flow = flow_definition

            try:
                for i, (sub_task_id, sub_task_args) in enumerate(tasks_in_flow):
                    original_sub_task_id = sub_task_id # 動的解決前のIDを保持

                    # --- create-caption-flow の動的解決 ---
                    if sub_task_id == "create-caption-flow":
                        config = get_config()
                        method = config.get("caption_creation_method", "api")
                        sub_task_id = "create-caption-browser" if method == "browser" else "create-caption-gemini"
                        logging.info(f"フロー内の 'create-caption-flow' を '{sub_task_id}' に解決しました。")
                    # -----------------------------------------

                    if sub_task_id in TASK_DEFINITIONS:
                        # --- フロー内の動的切り替えロジック ---
                        if sub_task_id == "_create-caption-wrapper":
                            config = get_config()
                            method = config.get("caption_creation_method", "api")
                            if method == "browser":
                                sub_task_id = "create-caption-browser"
                            else: # api
                                sub_task_id = "create-caption-gemini"
                            logging.debug(f"フロー内タスクを動的に解決: {sub_task_id}")
                        sub_task_def = TASK_DEFINITIONS.get(original_sub_task_id, {})
                        logging.debug(f"  フロー実行中 ({i+1}/{len(tasks_in_flow)}): 「{sub_task_def['name_ja']}」")
                        
                        # --- ネストされたフローのハンドリング ---
                        resolved_sub_task_def = TASK_DEFINITIONS.get(sub_task_id, {})
                        sub_task_func = resolved_sub_task_def.get("function")
                        is_nested_flow = "flow" in resolved_sub_task_def and sub_task_func is None

                        if not sub_task_func and not is_nested_flow:
                            logging.error(f"フロー内のタスク '{sub_task_id}' に実行可能な関数またはフローが定義されていません。")
                            flow_succeeded = False # ★★★ エラー時にフラグを立てる
                            break
                        
                        # 引数を解決
                        final_kwargs = sub_task_def.get("default_kwargs", {}).copy()
                        for key, value in sub_task_args.items():
                            if value == "flow_count":
                                final_kwargs[key] = flow_kwargs.get('count')
                            elif value == "flow_hours_ago":
                                final_kwargs[key] = flow_kwargs.get('hours_ago')
    
                        final_kwargs.update(flow_kwargs)
                        
                        try:
                            if is_nested_flow:
                                # ネストされたフローを実行
                                logging.debug(f"  -> ネストされたフロー '{sub_task_id}' を実行します。")
                                task_result = _run_task_internal(sub_task_id, is_part_of_flow=True, **final_kwargs)
                            else:
                                # 通常の関数を実行
                                sig = inspect.signature(sub_task_func)
                                valid_args = { k: v for k, v in final_kwargs.items() if k in sig.parameters }
                                task_result = sub_task_func(**valid_args)

                            # ★★★ デバッグログ追加 ★★★
                            logging.debug(f"      -> タスク '{sub_task_id}' の戻り値: {task_result} (型: {type(task_result)})")

                            if should_aggregate:
                                # --- 合算モード ---
                                if isinstance(task_result, str):
                                    summary_message = task_result
                                    logging.debug(f"      -> [集計] summary_message を設定しました: '{summary_message}'")
                                elif isinstance(task_result, int) and not isinstance(task_result, bool):
                                    if main_success_count == 0 and task_result > 0:
                                        main_success_count = task_result
                                        logging.debug(f"      -> [集計] main_success_count を {main_success_count} に設定しました。")
                                elif isinstance(task_result, tuple) and len(task_result) >= 2 and all(isinstance(n, int) for n in task_result):
                                    if main_success_count == 0 and task_result[0] > 0:
                                        main_success_count = task_result[0]
                                        logging.debug(f"      -> [集計] main_success_count を {main_success_count} に設定しました。(from tuple)")
                                    total_error_count += task_result[1]
                                    logging.debug(f"      -> [集計] total_error_count を {task_result[1]} 加算しました。 (現在値: {total_error_count})")
                            else:
                                # --- 個別報告モード ---
                                sub_summary_name = sub_task_def.get("summary_name")
                                if sub_summary_name:
                                    if isinstance(task_result, tuple) and len(task_result) >= 2:
                                        success_count, error_count = task_result[0], task_result[1]
                                        if success_count > 0 or error_count > 0:
                                            logging.info(f"[Action Summary] name={sub_summary_name}, count={success_count}, errors={error_count}")
                                    elif isinstance(task_result, str):
                                        logging.info(f"[Action Summary] name={sub_summary_name}, message='{task_result}'")

                        except Exception as e:
                            logging.error(f"フロー内のタスク「{sub_task_def['name_ja']}」実行中に予期せぬエラーが発生しました: {e}", exc_info=os.getenv('LOG_FORMAT', 'detailed').lower() == 'detailed')
                            task_result = False
    
                        if task_result is False: # タスクが明示的にFalseを返した場合
                            logging.error(f"フロー内のタスク「{sub_task_def.get('name_ja', sub_task_id)}」が失敗しました。フローを中断します。 [flow_id:{flow_id}]")
                            flow_succeeded = False
                            break
                    else:
                        logging.error(f"フロー内のタスク定義「{sub_task_id}」が見つかりません。フローを中断します。 [flow_id:{flow_id}]")
                        flow_succeeded = False
                        break
            finally:
                with _flow_lock:
                    RUNNING_FLOWS.remove(flow_id)

                # 合算モードの場合のみ、フロー全体のサマリーを出力
                if should_aggregate:
                    summary_name = definition.get("summary_name", definition['name_ja'])
                    if summary_message is not None:
                        logging.info(f"[Action Summary] name={summary_name}, message='{summary_message}' [flow_id:{flow_id}]")
                    elif main_success_count is not None and total_error_count is not None and (main_success_count > 0 or total_error_count > 0):
                        logging.info(f"[Action Summary] name={summary_name}, count={main_success_count}, errors={total_error_count} [flow_id:{flow_id}]")
                
                elapsed_time = time.time() - start_time
                duration_str = format_duration(elapsed_time)
                # フロー全体の最終結果をログに出力
                if flow_succeeded:
                    logging.info(f"フロー完了: 「{definition['name_ja']}」が正常に完了しました。(実行時間: {duration_str}) [flow_id:{flow_id}]")
                else:
                    logging.error(f"フロー中断: 「{definition['name_ja']}」は途中で失敗しました。(実行時間: {duration_str}) [flow_id:{flow_id}]")
        
        run_threaded(run_flow)
        return {"status": "success", "message": f"タスクフロー「{definition['name_ja']}」の実行を開始しました。"}

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
        # check-login-statusはプロファイル切り替えと復旧で時間がかかる可能性があるため、タイムアウトを延長
        if "save-auth-state" in tag:
            timeout = 310
        elif "check-login-status" in tag:
            timeout = 120 # 60秒から120秒に延長
        else:
            timeout = 60

        # task_wrapperは後続タスクを呼び出す可能性があるため、直接タスク関数を呼び出す
        task_func = definition["function"]
        job_thread, result_container = run_threaded(task_func, **kwargs)
        job_thread.join(timeout=timeout) # タスクに応じた時間待つ
        if job_thread.is_alive():
            return JSONResponse(status_code=500, content={"status": "error", "message": f"タスクがタイムアウトしました（{timeout}秒）。"})
        
        result = result_container.get('result')
        logging.debug(f"スレッドから受け取った結果 (タスク: {tag}): {result} (型: {type(result)})")

        # BaseTask.run()の戻り値がタプル(success, message)か、単なるboolかを判定
        success = result[0] if isinstance(result, tuple) else result
        custom_message = result[1] if isinstance(result, tuple) and len(result) > 1 else ""

        if "check-login-status" in tag:
            default_message = "成功: ログイン状態が維持されています。" if success else "失敗: ログイン状態が確認できませんでした。"
            message = f"{default_message}\n{custom_message}".strip()
        elif "save-auth-state" in tag:
            message = "成功: 認証状態を保存しました。" if success else "失敗: 認証状態の保存に失敗しました。詳細はログを確認してください。"
        elif "restore-auth-state" in tag:
            message = "成功: 認証プロファイルを復元しました。" if success else "失敗: 認証プロファイルの復元に失敗しました。詳細はログを確認してください。"
        else:
            message = "タスクが完了しました。" # フォールバックメッセージ
        
        logging.debug(f"APIレスポンス (タスク: {tag}): {message}")

        return JSONResponse(content={"status": "success" if success else "error", "message": message})

    # 上記以外のバックグラウンドで実行するタスク
    # 1. デフォルト引数を取得, 2. 実行時引数で上書き
    final_kwargs = definition.get("default_kwargs", {}).copy() 
    final_kwargs.update(kwargs)
    job_thread, result_container = run_threaded(task_wrapper, **final_kwargs) 

    message = f"タスク「{definition['name_ja']}」の実行を開始しました。"
    logging.debug(f"APIレスポンス (タスク: {tag}): {message}")
    return {"status": "success", "message": message}

class BulkDeleteRequest(BaseModel):
    """一括削除リクエストのモデル"""
    filenames: list[str]

@router.post("/api/screenshots/bulk-delete", summary="スクリーンショットの一括削除")
async def bulk_delete_screenshots(request: BulkDeleteRequest):
    """
    指定されたスクリーンショットのファイル名リストを受け取り、一括で削除します。
    処理後、削除した件数をまとめてログに出力します。
    """
    deleted_count = 0
    failed_files = []
    not_found_files = []

    for filename in request.filenames:
        # ディレクトリトラバーサル攻撃を防ぐための基本的なセキュリティチェック
        if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
            logging.warning(f"不正なファイル名のためスキップしました: {filename}")
            failed_files.append(filename)
            continue

        file_path = os.path.join(SCREENSHOT_DIR, filename)
        
        if os.path.exists(file_path) and os.path.isfile(file_path):
            try:
                os.remove(file_path)
                deleted_count += 1
            except OSError as e:
                logging.error(f"スクリーンショットの削除に失敗しました: {file_path}, エラー: {e}")
                failed_files.append(filename)
        else:
            logging.warning(f"削除対象のスクリーンショットが見つかりません: {file_path}")
            not_found_files.append(filename)

    if deleted_count > 0:
        logging.info(f"{deleted_count}件のスクリーンショットを削除しました。")

    if failed_files:
        raise HTTPException(status_code=500, detail=f"{len(failed_files)}件のファイルの削除に失敗しました: {', '.join(failed_files)}")

    message = f"{deleted_count}件のスクリーンショットを削除しました。"
    if not_found_files:
        message += f" ({len(not_found_files)}件は見つかりませんでした)"

    return {"message": message}
# --- Prompt Profile API ---

@router.get("/api/prompt-profiles/{prompt_key}")
async def get_prompt_profiles(prompt_key: str):
    """保存されているプロンプトプロファイルの一覧を返す"""
    profile_dir = os.path.join(PROMPT_PROFILES_DIR, prompt_key)
    os.makedirs(profile_dir, exist_ok=True)
    # 拡張子を.txtに変更
    profiles = [os.path.splitext(f)[0] for f in os.listdir(profile_dir) if f.endswith(".txt")]
    return JSONResponse(content=sorted(profiles))

@router.post("/api/prompt-profiles/{prompt_key}")
async def save_prompt_profile(prompt_key: str, request: ProfileNameRequest):
    """現在のプロンプトを新しいプロファイルとして保存する"""
    profile_name = request.profile_name.strip()
    if not profile_name or not re.match(r'^[a-zA-Z0-9_.\-ぁ-んァ-ヶ一-龠々ー ]+$', profile_name) or "/" in profile_name or "\\" in profile_name:
        return JSONResponse(status_code=400, content={"status": "error", "message": "プロファイル名に使用できない文字が含まれています。"})

    # prompt_keyからファイル名を取得するマッピング
    prompt_filenames = {
        "create-caption-flow": "product_caption_prompt.txt",
        "create-comment": "engagement_comment_body_prompt.txt"
    }
    source_filename = prompt_filenames.get(prompt_key)
    if not source_filename:
        return JSONResponse(status_code=400, content={"status": "error", "message": "無効なプロンプトキーです。"})

    source_path = os.path.join(PROMPTS_DIR, source_filename)
    profile_dir = os.path.join(PROMPT_PROFILES_DIR, prompt_key)
    os.makedirs(profile_dir, exist_ok=True)
    profile_path = os.path.join(profile_dir, f"{profile_name}.txt")

    try:
        with open(source_path, "r", encoding="utf-8") as f_src:
            content = f_src.read()
        with open(profile_path, "w", encoding="utf-8") as f_dst:
            f_dst.write(content)

        return JSONResponse(content={"status": "success", "message": f"プロファイル「{profile_name}」を保存しました。"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"プロファイルの保存に失敗しました: {e}"})

@router.put("/api/prompt-profiles/{prompt_key}/{profile_name}")
async def load_prompt_profile(prompt_key: str, profile_name: str):
    """指定されたプロファイルを現在のプロンプトとして読み込む"""
    profile_dir = os.path.join(PROMPT_PROFILES_DIR, prompt_key)
    profile_path = os.path.join(profile_dir, f"{profile_name}.txt")
    if not os.path.exists(profile_path):
        return JSONResponse(status_code=404, content={"status": "error", "message": "プロファイルが見つかりません。"})

    prompt_filenames = {
        "create-caption-flow": "product_caption_prompt.txt",
        "create-comment": "engagement_comment_body_prompt.txt",
        "user_comment_body_prompt": "engagement_comment_body_prompt.txt" # 念のため古いキーも残す
    }
    dest_filename = prompt_filenames.get(prompt_key)
    if not dest_filename:
        return JSONResponse(status_code=400, content={"status": "error", "message": "無効なプロンプトキーです。"})

    dest_path = os.path.join(PROMPTS_DIR, dest_filename)

    try:
        with open(profile_path, "r", encoding="utf-8") as f_src:
            content = f_src.read()
        with open(dest_path, "w", encoding="utf-8") as f_dst:
            f_dst.write(content)

        return JSONResponse(content={"status": "success", "message": f"プロファイル「{profile_name}」を読み込みました。"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"プロファイルの読み込みに失敗しました: {e}"})

@router.delete("/api/prompt-profiles/{prompt_key}/{profile_name}")
async def delete_prompt_profile(prompt_key: str, profile_name: str):
    """指定されたプロンプトプロファイルを削除する"""
    profile_dir = os.path.join(PROMPT_PROFILES_DIR, prompt_key)
    profile_path = os.path.join(profile_dir, f"{profile_name}.txt")
    if not os.path.exists(profile_path):
        return JSONResponse(status_code=404, content={"status": "error", "message": "プロファイルが見つかりません。"})
    try:
        os.remove(profile_path)
        return JSONResponse(content={"status": "success", "message": f"プロファイル「{profile_name}」を削除しました。"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"プロファイルの削除に失敗しました: {e}"})

# --- Prompt Editor API ---

@router.get('/api/prompts')
async def get_prompts():
    """
    編集可能なプロンプトファイルの一覧と内容を取得する
    """
    try:
        # 編集対象のファイルを指定
        editable_files = {
            "create-caption-flow": {
                "name_ja": "<i class='bi bi-file-post me-1'></i>投稿文生成プロンプト",
                "description": "商品情報から投稿文を生成する際の指示です。",
                "filename": "product_caption_prompt.txt"
            },
            "create-comment": {
                "name_ja": "<i class='bi bi-chat-dots me-1'></i>返信コメント生成プロンプト",
                "description": "ユーザーへの返信コメント（掛け合い形式の本文）を生成する際の指示です。",
                "filename": "engagement_comment_body_prompt.txt"
            }
        }

        prompts_data = {}
        for key, info in editable_files.items():
            filepath = os.path.join(PROMPTS_DIR, info["filename"])
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                prompts_data[key] = {**info, "content": content}
            else:
                prompts_data[key] = {**info, "content": f"エラー: ファイルが見つかりません ({filepath})", "error": True}

        return JSONResponse(content=prompts_data)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"プロンプトの読み込み中にエラーが発生しました: {str(e)}"})

@router.post("/api/prompts/test")
async def test_prompt(request: PromptTestRequest):
    """
    指定されたプロンプトとテストデータを使用してAIの生成をテストする。
    """
    try:
        logging.info(f"[/api/prompts/test] リクエスト受信: prompt_key='{request.prompt_key}', test_data件数={len(request.test_data)}")
        # タスクをインスタンス化して実行
        task = PromptTestTask(
            prompt_key=request.prompt_key,
            prompt_content=request.prompt_content,
            test_data=request.test_data,
        )
        # PromptTestTaskのrunメソッドは同期的に結果を返す
        result = task.run()
        return JSONResponse(content=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.error(f"プロンプトのテスト実行中にエラーが発生しました: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post('/api/prompts/{prompt_name}')
async def update_prompt(prompt_name: str, request: Request):
    """
    指定されたプロンプトの内容を更新する
    """
    try:
        data = await request.json()
        content = data.get('content')
        
        # このマッピングは get_prompts と同じである必要があります
        filename_map = {
            "create-caption-flow": "product_caption_prompt.txt",
            "create-comment": "engagement_comment_body_prompt.txt"
        }
        filename = filename_map.get(prompt_name)
        if not filename:
            return JSONResponse(status_code=400, content={"error": "無効なプロンプトキーです。"})

        filepath = os.path.join(PROMPTS_DIR, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return JSONResponse(content={"message": f"プロンプト「{prompt_name}」を更新しました。"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"プロンプトの更新中にエラーが発生しました: {str(e)}"})

@router.get("/api/logs", response_class=PlainTextResponse)
async def get_logs(
    start: str | None = None,
    end: str | None = None,
    level: str | None = None,
    flow_id: str | None = None, # ★フローIDでのフィルタリングを追加
):
    """
    ログファイルの内容を取得する。
    startとendクエリパラメータで期間を指定してフィルタリング可能。
    flow_idクエリパラメータで特定のフローに関連するログのみを抽出可能。
    """
    # フローIDをログメッセージから抽出するための正規表現
    flow_id_pattern = re.compile(r"\[flow_id:([^\]]+)\]")

    def get_flow_id_from_line(line: str) -> str | None:
        """ログの1行から 'flow_id' を抽出する。"""
        match = flow_id_pattern.search(line)
        return match.group(1) if match else None

    def remove_extra_from_line(line: str) -> str:
        """ログの1行から [flow_id:...] の部分を削除して返す。"""
        return flow_id_pattern.sub("", line)

    # flow_idが指定された場合、他のフィルター（期間、レベル）は無視する
    if flow_id:
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            
            filtered_lines = []
            in_flow_block = False
            for line in lines:
                line_flow_id = get_flow_id_from_line(line)

                if not in_flow_block and line_flow_id == flow_id and "フロー実行" in line:
                    # フローの開始行を見つけたら、ブロックを開始
                    in_flow_block = True
                
                if in_flow_block:
                    # ブロック内に入ったら、すべての行を追加
                    filtered_lines.append(remove_extra_from_line(line))

                if in_flow_block and line_flow_id == flow_id and ("フロー完了" in line or "フロー中断" in line):
                    # フローの完了/中断行を見つけたら、ブロックを終了
                    break # このフローIDの処理は完了なのでループを抜ける
            
            return "".join(filtered_lines)
        except Exception as e:
            logging.error(f"フローID '{flow_id}' のログフィルタリング中にエラー: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"フローログのフィルタリング中にエラーが発生しました: {e}")


    try:
        if not os.path.exists(LOG_FILE): # LOG_FILEはモジュール上部でインポート済み
            return "ログファイルが見つかりません。"

        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        if not start and not end and not level and not flow_id:
            return "".join(lines[-1000:]) # フィルターなしの場合は末尾1000行に制限

        filtered_lines = []
        start_dt = datetime.strptime(start, "%Y-%m-%dT%H:%M") if start else None
        end_dt = datetime.strptime(end, "%Y-%m-%dT%H:%M") if end else None

        for line in lines:
            try:
                # ログフォーマット(detailed/simple)の両方に対応
                if re.match(r'^\d{4}-\d{2}-\d{2}', line):
                    # detailed形式: 'YYYY-MM-DD HH:MM:SS,ms'
                    ts_str = line[:23]
                    log_dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S,%f')
                elif re.match(r'^\d{2}-\d{2}', line):
                    # simple形式: 'MM-DD HH:MM:SS' (年をまたぐ場合も考慮)
                    ts_str = line[:14].strip()
                    now = datetime.now()
                    log_dt = datetime.strptime(ts_str, '%m-%d %H:%M:%S').replace(year=now.year)
                    if log_dt > now: # ログの日時が未来になった場合、去年のログと判断
                        log_dt = log_dt.replace(year=now.year - 1)
                else:
                    continue # タイムスタンプがない行はスキップ

                if start_dt and log_dt < start_dt: continue
                if end_dt and log_dt > end_dt: continue

                # ログレベルでのフィルタリング
                if level:
                    level_upper = level.upper()
                    line_upper = line.upper()
                    # 'INFO' のようなフルネームか、'[I]' のような短縮形の両方に対応
                    short_form = f"[{level_upper[0]}]"
                    if level_upper not in line_upper and short_form not in line_upper:
                        continue
                
                # ★ extra情報を削除して表示
                filtered_lines.append(remove_extra_from_line(line))
            except (ValueError, IndexError):
                # タイムスタンプが期待する形式でない行はスキップ
                continue

        return "".join(filtered_lines)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ログの読み込み中にサーバーエラーが発生しました: {e}")

@router.get("/api/logs/flows", response_class=JSONResponse)
async def get_log_flows():
    """ログファイルを解析し、実行されたフローの履歴を返す。"""
    try:
        if not os.path.exists(LOG_FILE):
            return JSONResponse(content=[])

        # detailed形式とsimple形式の両方に対応する正規表現
        start_log_pattern = re.compile(r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}|\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?フロー実行: 「(?P<name>.*?)」を開始します。.*?\[flow_id:(?P<id>[^\]]+)\]")

        flows = []
        now = datetime.now()

        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                match = start_log_pattern.search(line)
                if match:
                    data = match.groupdict()
                    timestamp_str, flow_name, flow_id = data['timestamp'], data['name'], data['id']
                    try:
                        # タイムスタンプの形式を判定してパース
                        if re.match(r'^\d{4}-\d{2}-\d{2}', timestamp_str):
                            # detailed形式: 'YYYY-MM-DD HH:MM:SS,ms'
                            dt_obj = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S,%f')
                        else: # simple形式
                            # simple形式: 'MM-DD HH:MM:SS'
                            dt_obj = datetime.strptime(timestamp_str, '%m-%d %H:%M:%S').replace(year=now.year)
                            if dt_obj > now: # 年をまたぐ場合の補正
                                dt_obj = dt_obj.replace(year=now.year - 1)

                        formatted_ts = dt_obj.strftime('%m-%d %H:%M')
                        flows.append({
                            "id": flow_id,
                            "name": flow_name,
                            "timestamp": formatted_ts,
                            "sort_key": dt_obj
                        })
                    except (ValueError, IndexError):
                        continue

        sorted_flows = sorted(flows, key=lambda x: x['sort_key'], reverse=True)
        return JSONResponse(content=[{k: v for k, v in flow.items() if k != 'sort_key'} for flow in sorted_flows])

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"フローログの解析中にエラーが発生しました: {e}")

@router.get("/api/flows/status", response_class=JSONResponse)
async def get_running_flows_status():
    """現在実行中のフローのIDと名前のリストを返す。"""
    running_flows_details = []
    with _flow_lock:
        for flow_id in RUNNING_FLOWS:
            # flow_id (例: "run-follow-action-1020u5") からタスクタグを抽出
            # 末尾の "-HHMMxx" 形式の部分を除外する
            tag_parts = flow_id.split('-')
            tag = '-'.join(tag_parts[:-1]) if len(tag_parts) > 2 else flow_id
            
            definition = TASK_DEFINITIONS.get(tag, {})
            running_flows_details.append({
                "id": flow_id,
                "name": definition.get("name_ja", tag) # 定義から日本語名を取得
            })
            
    return JSONResponse(content={"running_flows": running_flows_details})
