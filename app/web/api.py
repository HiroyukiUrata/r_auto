from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import schedule
import re
import logging
import json
from pydantic import BaseModel

# タスク定義を一元的にインポート
from app.core.task_definitions import TASK_DEFINITIONS
from app.core.config_manager import get_config, save_config
from app.core.scheduler_utils import run_threaded
from datetime import date, timedelta

# --- FastAPI App Setup ---
app = FastAPI(
    title="R-Auto Control Panel",
    description="システムの稼働状況やスケジュールを管理するWeb UI",
)

# Jinja2テンプレートを設定
templates = Jinja2Templates(directory="web/templates")

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
            schedules_to_save[tag].append(time_str)

    try:
        with open(SCHEDULE_FILE, "w") as f:
            json.dump(schedules_to_save, f, indent=4, sort_keys=True)
        logging.info(f"スケジュールを {SCHEDULE_FILE} に保存しました。")
    except IOError as e:
        logging.error(f"スケジュールファイルの保存に失敗しました: {e}")

# --- Pydantic Models ---
class ScheduleUpdateRequest(BaseModel):
    tag: str
    times: list[str]

class ConfigUpdateRequest(BaseModel):
    max_delay_minutes: int


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

@app.get("/debug", response_class=HTMLResponse)
async def read_debug(request: Request):
    """デバッグページを表示する"""
    return templates.TemplateResponse("debug.html", {"request": request})

# --- API Routes ---
@app.get("/api/schedules")
async def get_schedules():
    """現在のスケジュール情報をJSONで返す"""
    # 1. タスク定義を元にレスポンスの雛形を作成
    all_tasks = {}
    for tag, definition in TASK_DEFINITIONS.items():
        # デバッグタスクはスケジュール対象外
        if not definition.get("is_debug", False):
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
                if time_str not in all_tasks[tag]["times"]:
                    all_tasks[tag]["times"].append(time_str)

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
        task["times"].sort()

    return JSONResponse(content=list(all_tasks.values()))

@app.get("/api/debug-tasks")
async def get_debug_tasks():
    """デバッグ用のタスクリストをJSONで返す"""
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
    for time_str in update_request.times:
        if re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', time_str):
            task_func = definition["function"]
            schedule.every().day.at(time_str).do(run_threaded, run_task_with_random_delay, task_to_run=task_func).tag(tag)

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
    job_thread, result_container = run_threaded(task_func)

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
        if result is True:
            return JSONResponse(content={"status": "success", "message": message})
        else:
            return JSONResponse(status_code=400, content={"status": "error", "message": message})
    else:
        return {"status": "success", "message": f"タスク「{definition['name_ja']}」の実行を開始しました。"}