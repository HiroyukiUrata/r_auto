import logging
from app.core.playwright_manager import PlaywrightManager
from app.core.database import recollect_product, delete_product

def run_delete_room_post(product_id: int, room_url: str, action: str):
    """
    Playwrightを使用してROOMの投稿を削除し、その後DB操作を行うタスク。
    :param product_id: 対象のプロダクトID
    :param room_url: 削除対象のROOM投稿URL
    :param action: 'recollect' または 'delete'
    """
    if not room_url:
        logging.warning(f"商品ID: {product_id} にはroom_urlがありません。ブラウザ操作をスキップします。")
        # URLがない場合でもDB操作は実行する
        _perform_db_action(product_id, action)
        return

    pw_manager = PlaywrightManager()
    try:
        page = pw_manager.get_page()
        logging.info(f"ROOM投稿の削除を開始します: {room_url}")
        page.goto(room_url, wait_until='domcontentloaded')

        # ページ右上の「...」ボタンをクリック
        page.locator('button[aria-label="その他"]').click()

        # 「削除」ボタンをクリック
        page.get_by_role('button', name='削除').click()

        # 確認ダイアログの「削除」ボタンをクリック
        page.get_by_role('button', name='削除する').click()
        
        logging.info(f"ROOM投稿の削除に成功しました: {room_url}")

    except Exception as e:
        logging.error(f"ROOM投稿の削除中にエラーが発生しました: {room_url} - {e}")
        pw_manager.save_screenshot("error_delete_room_post")
    finally:
        # DB操作はブラウザ操作の成否に関わらず実行する
        _perform_db_action(product_id, action)
        pw_manager.close()

def _perform_db_action(product_id: int, action: str):
    if action == 'recollect':
        recollect_product(product_id)
    elif action == 'delete':
        delete_product(product_id)