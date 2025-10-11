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
from app.tasks.posting import post_article
from app.tasks.get_post_url import get_post_url
from app.tasks.import_products import process_and_import_products
from app.core.config_manager import get_config, save_config
from app.core.scheduler_utils import run_threaded, run_task_with_random_delay
from datetime import date, timedelta

# --- FastAPI App Setup ---
app = FastAPI(
    title="R-Auto Control Panel",
    description="システムの稼働状況やスケジュールを管理するWeb UI",
)

# Jinja2テンプレートを設定
templates = Jinja2Templates(directory="web/templates")

KEYWORDS_FILE = "db/keywords.json"
SCHEDULE_FILE = "db/schedules.json"

def save_schedules_to_file():
    """現在のスケジュールをJSONファイルに保存する"""
    schedules_to_save = {}
    # タグをキーとして実行時刻のリストを作成
    for tag in TASK_DEFINITIONS:
        schedules_to_save[tag] = []

    for job in schedule.get_jobs():
        if not job.tags:
            continue
        tag = list(job.tags)[0]
        if tag in schedules_to_save and job.at_time:
            time_str = job.at_time.strftime('%H:%M')
            # ジョブの引数から 'count' を取得。見つからなければデフォルト1。
            count = job.job_func.keywords.get('count', 1)
            schedules_to_save[tag].append({"time": time_str, "count": count})

    try:
        with open(SCHEDULE_FILE, "w") as f:
            json.dump(schedules_to_save, f, indent=4, sort_keys=True)
        logging.info(f"スケジュールを {SCHEDULE_FILE} に保存しました。")
    except IOError as e:
        logging.error(f"スケジュールファイルの保存に失敗しました: {e}")

class TimeEntry(BaseModel):
    time: str
    count: int

# --- Pydantic Models ---
class ScheduleUpdateRequest(BaseModel):
    tag: str
    times: list[TimeEntry]

class ConfigUpdateRequest(BaseModel):
    max_delay_minutes: int

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
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/logs", response_class=HTMLResponse)
async def read_logs(request: Request):
    """ログ確認ページを表示する"""
    return templates.TemplateResponse("logs.html", {"request": request})

@app.get("/chat", response_class=HTMLResponse)
async def read_chat(request: Request):
    """AIチャットページを表示する"""
    return templates.TemplateResponse("chat.html", {"request": request})

@app.get("/system-config", response_class=HTMLResponse)
async def read_system_config(request: Request):
    """システムコンフィグページを表示する"""
    return templates.TemplateResponse("config.html", {"request": request})

@app.get("/inventory", response_class=HTMLResponse)
async def read_inventory(request: Request):
    """在庫確認ページを表示する"""
    return templates.TemplateResponse("inventory.html", {"request": request})

@app.get("/keywords", response_class=HTMLResponse)
async def read_keywords_page(request: Request):
    """キーワード管理ページを表示する"""
    return templates.TemplateResponse("keywords.html", {"request": request})

@app.get("/error-management", response_class=HTMLResponse)
async def read_error_management(request: Request):
    """エラー管理ページを表示する"""
    return templates.TemplateResponse("error_management.html", {"request": request})

# --- API Routes ---
@app.get("/api/schedules")
async def get_schedules():
    """現在のスケジュール情報をJSONで返す"""
    # 1. タスク定義を元にレスポンスの雛形を作成
    all_tasks = {}
    for tag, definition in TASK_DEFINITIONS.items():
        # デバッグタスクはスケジュール対象外
        # is_debugがFalseで、show_in_scheduleが明示的にFalseでないタスクのみ表示
        if not definition.get("is_debug", False) and definition.get("show_in_schedule", True):
            all_tasks[tag] = {
                "tag": tag, "name_ja": definition["name_ja"], "times": [], "next_run": None
            }

    # 2. 現在スケジュールされているジョブの情報を雛形にマージする
    for job in schedule.get_jobs():
        if not job.tags:
            continue
        tag = list(job.tags)[0]

        if tag in all_tasks:
            # 実行時刻を追加
            if job.at_time:
                time_str = job.at_time.strftime('%H:%M')
                count = job.job_func.keywords.get('count', 1)
                time_entry = {"time": time_str, "count": count}
                if time_entry not in all_tasks[tag]["times"]:
                    all_tasks[tag]["times"].append(time_entry)

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
        run_threaded(post_article, count=1, product_id=product_id)
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
        if not isinstance(items_to_import, list):
            return JSONResponse(status_code=400, content={"status": "error", "message": "JSONのルートは配列である必要があります。"})
        inserted_count = process_and_import_products(items_to_import)
        
        # インポート成功後、バックグラウンドで投稿URL取得タスクを実行
        run_threaded(get_post_url)

        return JSONResponse(content={"status": "success", "message": f"{len(items_to_import)}件中、{inserted_count}件の新規商品をインポートしました。\n続けてバックグラウンドで投稿URLの取得を開始します。"})
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
    current_config["max_delay_minutes"] = config_request.max_delay_minutes
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

    # 新しい時刻リストに基づいてジョブを再作成
    for entry in update_request.times:
        if re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', entry.time):
            task_func = definition["function"]

            # タスク定義からのデフォルト引数を取得し、スケジュール固有の引数で上書き
            job_kwargs = definition.get("default_kwargs", {}).copy()
            job_kwargs['task_to_run'] = task_func
            job_kwargs['count'] = entry.count

            # スケジュールを登録
            schedule.every().day.at(entry.time).do(run_threaded, run_task_with_random_delay, **job_kwargs).tag(tag)

    # ファイルに現在のスケジュール状態を保存
    save_schedules_to_file()

    return {"status": "success", "message": f"Task '{tag}' schedule updated."}

@app.post("/api/tasks/{tag}/run")
async def run_task_now(tag: str):
    """指定されたタスクを即時実行する"""
    definition = TASK_DEFINITIONS.get(tag)
    if not definition:
        return JSONResponse(status_code=404, content={"status": "error", "message": f"Task '{tag}' not found."})

    task_func = definition["function"]
    # タスクをバックグラウンドスレッドで実行
    kwargs = definition.get("default_kwargs", {}).copy()
    # 即時実行の場合、記事投稿は10件に設定
    if tag == "post-article":
        kwargs['count'] = 10
    elif tag in ["run-like-action", "run-follow-action"]:
        kwargs['count'] = 10

    job_thread, result_container = run_threaded(task_func, **kwargs)

    # 結果を待って返すタイプのタスク
    if tag in ["check-login-status", "save-auth-state"]:
        # save-auth-stateは手動操作のため、タイムアウトを長めに設定(5分+α)
        timeout = 310 if tag == "save-auth-state" else 60

        job_thread.join(timeout=timeout) # タスクに応じた時間待つ
        if job_thread.is_alive():
            return JSONResponse(status_code=500, content={"status": "error", "message": "タスクがタイムアウトしました。"})
        
        result = result_container.get('result')
        if tag == "check-login-status":
            message = "成功: ログイン状態が維持されています。" if result else "失敗: ログイン状態が確認できませんでした。"
        elif tag == "save-auth-state":
            message = "成功: 認証状態を保存しました。" if result else "失敗: 認証状態の保存に失敗しました。詳細はログを確認してください。"
        
        # APIレスポンスとして返すメッセージをログに出力
        logging.info(f"APIレスポンス (タスク: {tag}): {message}")

        if result is True:
            return JSONResponse(content={"status": "success", "message": message})
        else:
            return JSONResponse(status_code=400, content={"status": "error", "message": message})
    else:
        message = f"タスク「{definition['name_ja']}」の実行を開始しました。"
        logging.info(f"APIレスポンス (タスク: {tag}): {message}")
        return {"status": "success", "message": message}