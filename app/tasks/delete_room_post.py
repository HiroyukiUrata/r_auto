import logging
from app.core.base_task import BaseTask
from app.core.database import recollect_product, delete_product
from playwright.sync_api import Error

class DeleteRoomPostTask(BaseTask):
    """
    Playwrightを使用してROOMの投稿を削除するタスク。
    複数の商品を一度に処理できるように変更。
    """
    def __init__(self, products_to_process: list[dict], action: str):
        super().__init__()
        self.products_to_process = products_to_process
        self.action = action
        self.action_name = f"ROOM投稿一括削除({action}, {len(products_to_process)}件)"
        self.use_auth_profile = True # ログイン状態が必須のため、認証プロファイルを使用する

    def _execute_main_logic(self):
        if not self.products_to_process:
            logging.info("処理対象の商品がありません。")
            return [], []

        successful_ids = []
        failed_ids = []

        for product in self.products_to_process:
            product_id = product.get('id')
            room_url = product.get('room_url')

            if not room_url:
                logging.warning(f"商品ID: {product_id} にはroom_urlがありません。ブラウザ操作をスキップし、成功として扱います。")
                successful_ids.append(product_id)
                continue

            page = self.context.new_page()
            try:
                logging.debug(f"  -> 処理開始 (ID: {product_id}): {room_url}")
                # ページの動的コンテンツが完全に読み込まれるのを待つため、networkidleを使用
                page.goto(room_url, wait_until='domcontentloaded', timeout=90000)

                # エラーページに遷移した場合、投稿は既に存在しないと判断
                if "room.rakuten.co.jp/common/error" in page.url:
                    logging.warning(f"    -> エラーページに遷移しました。商品ID: {product_id} の投稿は既に削除されている可能性があります。")
                    successful_ids.append(product_id)
                    continue

                # --- 削除処理 ---
                dialog_accepted = False
                def handle_dialog(dialog):
                    nonlocal dialog_accepted
                    logging.debug(f"    -> 確認ダイアログを検出: '{dialog.message}'。承認します。")
                    dialog.accept()
                    dialog_accepted = True

                page.on("dialog", handle_dialog)
                try:
                    # 参考スクリプトに基づき、直接「削除」ボタンを探すロジックに変更
                    delete_button_locator = page.locator('button[aria-label="削除"]').first
                    
                    # ボタンが表示されるまで最大60秒待機する
                    try:
                        delete_button_locator.wait_for(state="visible", timeout=60000)
                    except Error:
                        # タイムアウトした場合、ボタンが見つからなかったと判断
                        logging.warning(f"    -> 削除ボタンが見つかりませんでした（60秒待機後）。スキップします。 (ID: {product_id})")
                        failed_ids.append(product_id) # 失敗として扱う
                        continue

                    logging.debug(f"    -> 削除ボタンをクリックします。 (ID: {product_id})")
                    delete_button_locator.click()
                finally:
                    page.remove_listener("dialog", handle_dialog)
                
                page.wait_for_load_state("domcontentloaded", timeout=20000)
                logging.debug(f"    -> 削除成功 (ID: {product_id})")
                successful_ids.append(product_id)

            except Error as e:
                logging.error(f"  -> 削除中にエラー (ID: {product_id}): {e}")
                self._take_screenshot_on_error(prefix=f"error_delete_room_post_{product_id}")
                failed_ids.append(product_id)
            finally:
                if page and not page.is_closed():
                    page.close()

        return successful_ids, failed_ids

def run_delete_room_post(products: list[dict], action: str):
    """
    複数の商品を一括で削除/再コレするタスクを実行するラッパー関数。
    :param products: 処理対象の商品の辞書のリスト。各辞書は 'id' と 'room_url' を含む。
    :param action: 'recollect' または 'delete'
    """
    task = DeleteRoomPostTask(products, action)
    # BaseTask.run()は、このタスクの場合 (successful_ids, failed_ids) というタプルを返す
    result = task.run()
    if isinstance(result, tuple) and len(result) == 2:
        successful_ids, failed_ids = result
    else:
        successful_ids, failed_ids = [], []
    
    # Playwrightタスクが完了した後、成功したIDに対してのみDB操作を実行
    if successful_ids:
        logging.debug(f"Playwrightでの処理が成功した {len(successful_ids)}件の商品についてDB操作を実行します。Action: {action}")
        if action == 'recollect':
            from app.core.database import bulk_recollect_products
            bulk_recollect_products(successful_ids)
        elif action == 'delete':
            from app.core.database import delete_multiple_products
            delete_multiple_products(successful_ids)

    if failed_ids:
        logging.warning(f"Playwrightでの処理に失敗した商品が {len(failed_ids)}件ありました。これらのDB操作はスキップされました。")

    # --- 最終サマリーログの出力 ---
    # scheduler_utils.py の集計キーに合わせて name を設定する
    summary_name = "再コレ" if action == 'recollect' else "投稿削除"
    success_count = len(successful_ids)
    error_count = len(failed_ids)
    logger.info(f"[Action Summary] name={summary_name}, count={success_count}, errors={error_count}")

    # フロー側で集計するために、成功件数と失敗件数を返す
    return len(successful_ids), len(failed_ids)