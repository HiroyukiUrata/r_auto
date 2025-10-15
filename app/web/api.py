from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import schedule
import re
import logging
import os
import json
from pydantic import BaseModel

# タスク定義を一元的にインポート
from app.core.task_definitions import TASK_DEFINITIONS
from app.core.database import get_all_inventory_products, update_product_status, delete_all_products, init_db, delete_product, update_status_for_multiple_products, delete_multiple_products, get_product_count_by_status, get_error_products_in_last_24h
from app.tasks.posting import run_posting
from app.tasks.get_post_url import run_get_post_url
from app.tasks.import_products import process_and_import_products
from app.core.config_manager import get_config, save_config
from app.core.scheduler_utils import run_threaded, run_task_with_random_delay
from datetime import date, timedelta

# --- FastAPI App Setup ---
app = FastAPI(
    title="R-Auto Control Panel",
    description="システムの稼働状況やスケジュールを管理するWeb UI",
)

KEYWORDS_FILE = "db/keywords.json"
SCHEDULE_FILE = "db/schedules.json"
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

class ConfigUpdateRequest(BaseModel):
    # すべてのフィールドをオプショナル（任意）に変更
    max_delay_minutes: int | None = None
    playwright_headless: bool | None = None
    procurement_method: str | None = None

class JsonImportRequest(BaseModel):
    products: list[dict]

class BulkUpdateRequest(BaseModel):
    product_ids: list[int]

class BulkStatusUpdateRequest(BaseModel):
    product_ids: list[int]
    status: str

class KeywordsUpdateRequest(BaseModel):
    keywords_a: list[str]
    keywords_b: list[str]


# --- HTML Routes ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """
    トップページを表示し、現在のスケジュール一覧を渡す
    """
    return request.app.state.templates.TemplateResponse("index.html", {"request": request})

@app.get("/logs", response_class=HTMLResponse)
async def read_logs(request: Request):
    """ログ確認ページを表示する"""
    return request.app.state.templates.TemplateResponse("logs.html", {"request": request})

@app.get("/chat", response_class=HTMLResponse)
async def read_chat(request: Request):
    """AIチャットページを表示する"""
    return request.app.state.templates.TemplateResponse("chat.html", {"request": request})

@app.get("/system-config", response_class=HTMLResponse)
async def read_system_config(request: Request):
    """システムコンフィグページを表示する"""
    return request.app.state.templates.TemplateResponse("config.html", {"request": request})

@app.get("/inventory", response_class=HTMLResponse)
async def read_inventory(request: Request):
    """在庫確認ページを表示する"""
    return request.app.state.templates.TemplateResponse("inventory.html", {"request": request})

@app.get("/keywords", response_class=HTMLResponse)
async def read_keywords_page(request: Request):
    """キーワード管理ページを表示する"""
    return request.app.state.templates.TemplateResponse("keywords.html", {"request": request})

@app.get("/error-management", response_class=HTMLResponse)
async def read_error_management(request: Request):
    """エラー管理ページを表示する"""
    return request.app.state.templates.TemplateResponse("error_management.html", {"request": request})

# --- API Routes ---
@app.get("/api/schedules")
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

@app.get("/api/schedule-profiles")
async def get_schedule_profiles():
    """保存されているスケジュールプロファイルの一覧を返す"""
    os.makedirs(SCHEDULE_PROFILES_DIR, exist_ok=True)
    profiles = []
    for filename in os.listdir(SCHEDULE_PROFILES_DIR):
        if filename.endswith(".json"):
            profiles.append(os.path.splitext(filename)[0])
    return JSONResponse(content=sorted(profiles))

@app.post("/api/schedule-profiles")
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

@app.put("/api/schedule-profiles/{profile_name}")
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

@app.delete("/api/schedule-profiles/{profile_name}")
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

@app.get("/api/keyword-profiles")
async def get_keyword_profiles():
    """保存されているキーワードプロファイルの一覧を返す"""
    os.makedirs(KEYWORD_PROFILES_DIR, exist_ok=True)
    profiles = [os.path.splitext(f)[0] for f in os.listdir(KEYWORD_PROFILES_DIR) if f.endswith(".json")]
    return JSONResponse(content=sorted(profiles))

@app.post("/api/keyword-profiles")
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

@app.put("/api/keyword-profiles/{profile_name}")
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

@app.delete("/api/keyword-profiles/{profile_name}")
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

@app.get("/api/config-tasks")
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

@app.get("/api/config")
async def read_config():
    """現在の設定をJSONで返す"""
    return JSONResponse(content=get_config())

@app.get("/api/inventory")
async def get_inventory():
    """在庫商品（「投稿済」以外）のリストをJSONで返す"""
    products = get_all_inventory_products()
    # sqlite3.Rowは直接JSONシリアライズできないため、辞書のリストに変換
    products_list = [dict(product) for product in products]
    return JSONResponse(content=products_list)

@app.get("/api/errors")
async def get_error_products():
    """エラー商品（過去24時間）のリストをJSONで返す"""
    products = get_error_products_in_last_24h()
    # get_error_products_in_last_24h は既に辞書のリストを返す
    return JSONResponse(content=products)

@app.get("/api/inventory/summary")
async def get_inventory_summary():
    """在庫商品のステータスごとの件数を返す"""
    try:
        summary = get_product_count_by_status()
        return JSONResponse(content=summary)
    except Exception as e:
        logging.error(f"在庫サマリーの取得中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "サマリーの取得に失敗しました。"})

@app.post("/api/inventory/{product_id}/complete")
async def complete_inventory_item(product_id: int):
    """指定された在庫商品を「投稿済」ステータスに更新する"""
    try:
        # データベースのステータスを更新
        update_product_status(product_id, '投稿済')
        return JSONResponse(content={"status": "success", "message": f"商品ID: {product_id} を「投稿済」に更新しました。"})
    except Exception as e:
        logging.error(f"商品ID: {product_id} のステータス更新中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "ステータスの更新に失敗しました。"})

@app.delete("/api/inventory/{product_id}")
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

@app.post("/api/inventory/{product_id}/post")
async def post_inventory_item(product_id: int):
    """指定された在庫商品を1件だけ投稿する"""
    try:
        # post_articleタスクを引数count=1, product_id=product_idで実行
        run_threaded(run_posting, count=1, product_id=product_id)
        return JSONResponse(content={"status": "success", "message": f"商品ID: {product_id} の投稿処理を開始しました。"})
    except Exception as e:
        logging.error(f"商品ID: {product_id} の投稿処理開始中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "投稿処理の開始に失敗しました。"})

@app.post("/api/inventory/bulk-complete")
async def bulk_complete_inventory_items(request: BulkUpdateRequest):
    """複数の在庫商品を一括で「投稿済」ステータスに更新する"""
    try:
        updated_count = update_status_for_multiple_products(request.product_ids, '投稿済')
        return JSONResponse(content={"status": "success", "message": f"{updated_count}件の商品を「投稿済」に更新しました。"})
    except Exception as e:
        logging.error(f"商品の一括ステータス更新中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "一括更新に失敗しました。"})

@app.post("/api/inventory/bulk-delete")
async def bulk_delete_inventory_items(request: BulkUpdateRequest):
    """複数の在庫商品を一括で削除する"""
    try:
        deleted_count = delete_multiple_products(request.product_ids)
        return JSONResponse(content={"status": "success", "message": f"{deleted_count}件の商品を削除しました。"})
    except Exception as e:
        logging.error(f"商品の一括削除中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "一括削除に失敗しました。"})

@app.post("/api/products/bulk-status-update")
async def bulk_status_update_products(request: BulkStatusUpdateRequest):
    """複数の商品を一括で指定のステータスに更新する"""
    try:
        updated_count = update_status_for_multiple_products(request.product_ids, request.status)
        return JSONResponse(content={"status": "success", "message": f"{updated_count}件の商品を「{request.status}」に更新しました。"})
    except Exception as e:
        logging.error(f"商品の一括ステータス更新中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "一括更新に失敗しました。"})

@app.get("/api/keywords")
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

@app.post("/api/keywords")
async def save_keywords(request: KeywordsUpdateRequest):
    """キーワードをJSONファイルに保存する"""
    try:
        with open(KEYWORDS_FILE, "w") as f:
            json.dump(request.dict(), f, indent=4, ensure_ascii=False)
        return JSONResponse(content={"status": "success", "message": "キーワードを保存しました。"})
    except Exception as e:
        logging.error(f"キーワードファイルの保存に失敗しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "キーワードの保存に失敗しました。"})


@app.post("/api/import/json")
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

@app.post("/api/products/delete-all")
async def delete_all_products_endpoint():
    """すべての商品データを削除する"""
    try:
        delete_all_products()
        init_db() # テーブルをクリアした後、サンプルデータを再挿入するために呼び出す
        return JSONResponse(content={"status": "success", "message": "すべての商品データを削除し、サンプルデータを再挿入しました。"})
    except Exception as e:
        logging.error(f"全商品データの削除中にエラーが発生しました: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "サーバーエラーにより削除に失敗しました。"})

@app.post("/api/config")
async def update_config(config_request: ConfigUpdateRequest):
    """設定を更新する"""
    current_config = get_config()
    # リクエストで送信された値（Noneでないもの）だけを更新する
    update_data = config_request.dict(exclude_unset=True)
    current_config.update(update_data)
    save_config(current_config)
    return {"status": "success", "message": "設定を更新しました。"}


@app.post("/api/schedules/update")
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

@app.post("/api/tasks/{tag}/run")
async def run_task_now(tag: str):
    """
    指定されたタスクを即時実行する。
    フローの起点となるタスクとして実行される。
    """
    return _run_task_internal(tag, is_part_of_flow=False)

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
    if not definition:
        return JSONResponse(status_code=404, content={"status": "error", "message": f"Task '{tag}' not found."})

    # 新しい "flow" キーを優先的にチェック
    flow_definition = definition.get("flow")
    if flow_definition and not is_part_of_flow:
        # 1. デフォルト引数をコピー
        flow_kwargs = definition.get("default_kwargs", {}).copy()
        # 2. スケジュール実行などから渡された引数で上書き
        flow_kwargs.update(flow_run_kwargs)

        logging.info(f"--- 新フロー実行: 「{definition['name_ja']}」を開始します。 ---")

        def run_flow():
            # flow_definitionが文字列かリストか判定
            if isinstance(flow_definition, str):
                tasks_in_flow = [(task.strip(), {}) for task in flow_definition.split('|')]
            else: # リスト形式の場合
                tasks_in_flow = flow_definition

            for i, (sub_task_id, sub_task_args) in enumerate(tasks_in_flow):
                if sub_task_id in TASK_DEFINITIONS:
                    sub_task_def = TASK_DEFINITIONS[sub_task_id]
                    logging.info(f"  フロー実行中 ({i+1}/{len(tasks_in_flow)}): 「{sub_task_def['name_ja']}」")
                    sub_task_func = sub_task_def["function"]
                    
                    # 引数を解決
                    final_kwargs = sub_task_def.get("default_kwargs", {}).copy()
                    for key, value in sub_task_args.items():
                        if value == "flow_count":
                            final_kwargs[key] = flow_kwargs.get('count')
                    
                    try:
                        task_result = sub_task_func(**final_kwargs)
                        if task_result is False: # 明示的にFalseの場合のみ失敗とみなす
                            logging.error(f"フロー内のタスク「{sub_task_def['name_ja']}」が失敗しました。フローを中断します。")
                            break
                    except Exception as e:
                        logging.error(f"フロー内のタスク「{sub_task_def['name_ja']}」実行中に予期せぬエラーが発生しました: {e}", exc_info=True)
                        logging.error("フローの実行を中断します。")
                        break
                else:
                    logging.error(f"フロー内のタスク「{sub_task_id}」が見つかりません。フローを中断します。")
                    break
            else: # ループが正常に完了した場合
                logging.info(f"--- 新フロー実行: 「{definition['name_ja']}」が正常に完了しました。 ---")
        
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
            logging.info(f"--- 従来フロー実行: 「{definition['name_ja']}」が完了。次のタスク「{TASK_DEFINITIONS[next_task_tag]['name_ja']}」を実行します。 ---")
            _run_task_internal(next_task_tag, is_part_of_flow=True, **kwargs) # 引数を引き継ぐ
        return result

    # 結果を待って返すタイプのタスク
    if tag in ["check-login-status", "save-auth-state", "test-check-login-status", "test-save-auth-state"]:
        # save-auth-stateは手動操作のため、タイムアウトを長めに設定(5分+α)
        timeout = 310 if "save-auth-state" in tag else 60

        job_thread, result_container = run_threaded(task_wrapper, **kwargs)
        job_thread.join(timeout=timeout) # タスクに応じた時間待つ
        if job_thread.is_alive():
            return JSONResponse(status_code=500, content={"status": "error", "message": "タスクがタイムアウトしました。"})
        
        result = result_container.get('result')
        logging.info(f"スレッドから受け取った結果 (タスク: {tag}): {result} (型: {type(result)})")
        
        if "check-login-status" in tag:
            message = "成功: ログイン状態が維持されています。" if result else "失敗: ログイン状態が確認できませんでした。"
        elif "save-auth-state" in tag:
            message = "成功: 認証状態を保存しました。" if result else "失敗: 認証状態の保存に失敗しました。詳細はログを確認してください。"
        else:
            message = "タスクが完了しました。" # フォールバックメッセージ
        
        logging.info(f"APIレスポンス (タスク: {tag}): {message}")

        return JSONResponse(content={"status": "success" if result else "error", "message": message})

    # 上記以外のバックグラウンドで実行するタスク
    # 1. デフォルト引数を取得, 2. 実行時引数で上書き
    final_kwargs = definition.get("default_kwargs", {}).copy() 
    final_kwargs.update(kwargs)
    job_thread, result_container = run_threaded(task_wrapper, **final_kwargs) 

    message = f"タスク「{definition['name_ja']}」の実行を開始しました。"
    logging.info(f"APIレスポンス (タスク: {tag}): {message}")
    return {"status": "success", "message": message}