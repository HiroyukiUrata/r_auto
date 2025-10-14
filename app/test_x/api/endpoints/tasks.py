import logging
import time
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse
from app.core.task_definitions import TASK_DEFINITIONS

router = APIRouter()

@router.post("/run/{task_id}", status_code=202)
async def run_task(task_id: str, background_tasks: BackgroundTasks):
    """
    指定されたtask_idのタスクを実行する。
    タスク定義に 'flow' キーが存在する場合は、フローとして連続実行する。
    """
    if task_id not in TASK_DEFINITIONS:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    task_def = TASK_DEFINITIONS[task_id]
    flow_definition = task_def.get("flow")

    if flow_definition:
        # "flow" キーが存在する場合、フローとして実行
        logging.info(f"タスクフロー「{task_def['name_ja']}」を開始します。")
        task_ids_in_flow = [task.strip() for task in flow_definition.split('|')]

        def run_flow():
            """フロー内のタスクを順次実行する内部関数"""
            for i, sub_task_id in enumerate(task_ids_in_flow):
                if sub_task_id in TASK_DEFINITIONS:
                    sub_task_def = TASK_DEFINITIONS[sub_task_id]
                    logging.info(f"  フロー実行中 ({i+1}/{len(task_ids_in_flow)}): 「{sub_task_def['name_ja']}」")
                    sub_task_func = sub_task_def["function"]
                    sub_kwargs = sub_task_def.get("default_kwargs", {})
                    try:
                        # タスクを実行し、成功したかどうかを戻り値で受け取る
                        task_result = sub_task_func(**sub_kwargs)
                        if not task_result:
                            logging.error(f"フロー内のタスク「{sub_task_def['name_ja']}」が失敗しました。フローを中断します。")
                            break # タスクが失敗したらフローを停止

                        time.sleep(1) # タスク間の短い待機
                    except Exception as e:
                        logging.error(f"フロー内のタスク「{sub_task_def['name_ja']}」実行中にエラーが発生しました: {e}", exc_info=True)
                        logging.error("フローの実行を中断します。")
                        break # エラーが発生したらフローを停止
                else:
                    logging.error(f"フロー内のタスク「{sub_task_id}」が見つかりません。フローを中断します。")
                    break
            else: # ループが正常に完了した場合
                logging.info(f"タスクフロー「{task_def['name_ja']}」が正常に完了しました。")

        background_tasks.add_task(run_flow)
        return {"message": f"Task flow '{task_id}' has been started in the background."}

    # "flow" キーがない場合は、プレースホルダー関数を実行するだけ
    task_func = task_def["function"]
    kwargs = task_def.get("default_kwargs", {})
    background_tasks.add_task(task_func, **kwargs)
    logging.info(f"タスク「{task_def['name_ja']}」をバックグラウンドで実行開始しました。")
    return {"message": f"Task '{task_id}' has been started in the background."}

@router.get("/test-page", response_class=HTMLResponse)
async def show_test_page(request: Request):
    """検証用のWebページを表示する"""
    from app.main import templates  # メインのtemplatesインスタンスをインポート
    return templates.TemplateResponse("test_page.html", {"request": request})