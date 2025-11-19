import logging
from app.core.base_task import BaseTask
from app.core.database import recollect_product, delete_product
from playwright.sync_api import Error

class DeleteRoomPostTask(BaseTask):
    """
    Playwrightを使用してROOMの投稿を削除するタスク。
    """
    def __init__(self, product_id: int, room_url: str, action: str):
        super().__init__()
        self.product_id = product_id
        self.room_url = room_url
        self.action = action
        self.action_name = f"ROOM投稿削除({action})"

    def _execute_main_logic(self):
        if not self.room_url:
            logging.warning(f"商品ID: {self.product_id} にはroom_urlがありません。ブラウザ操作をスキップします。")
            # DB操作は finally ブロックで実行される
            return True

        page = self.page
        logging.info(f"ROOM投稿の削除を開始します: {self.room_url}")
        page.goto(self.room_url, wait_until='domcontentloaded')

        # エラーページに遷移した場合、投稿は既に存在しないと判断
        if "room.rakuten.co.jp/common/error" in page.url:
            logging.warning(f"エラーページに遷移しました。商品ID: {self.product_id} の投稿は既に削除されている可能性があります。")
            return True # 処理は成功とみなし、DB操作に進む

        try:
            # ページ右上の「...」ボタンをクリック
            page.locator('button[aria-label="その他"]').click()

            # 「削除」ボタンをクリック
            page.get_by_role('button', name='削除').click()

            # 確認ダイアログの「削除する」ボタンをクリック
            page.get_by_role('button', name='削除する').click()
            
            page.wait_for_load_state("domcontentloaded", timeout=20000)
            logging.info(f"ROOM投稿の削除に成功しました: {self.room_url}")
            return True
        except Error as e:
            logging.error(f"ROOM投稿の削除中にエラーが発生しました: {self.room_url} - {e}")
            self._take_screenshot_on_error(prefix="error_delete_room_post")
            return False # 失敗としてマークするが、DB操作は finally で実行される

def run_delete_room_post(product_id: int, room_url: str, action: str):
    task = DeleteRoomPostTask(product_id, room_url, action)
    # task.run() は成功時に True、失敗時に False を返す
    success = task.run()
    
    # Playwrightタスクが成功した場合のみDB操作を実行
    if success:
        logging.info(f"Playwrightでの削除タスクが成功したため、DB操作を実行します。Action: {action}, Product ID: {product_id}")
        if action == 'recollect':
            recollect_product(product_id)
        elif action == 'delete':
            delete_product(product_id)
    else:
        logging.warning(f"Playwrightでの削除タスクが失敗したため、DB操作はスキップされました。Action: {action}, Product ID: {product_id}")