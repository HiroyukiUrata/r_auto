import logging
from playwright.sync_api import TimeoutError
from app.core.base_task import BaseTask # Import from core

class CheckLoginStatusTask(BaseTask): # Class name is already correct
    """
    保存された認証プロファイルを使ってログイン状態を確認するタスク
    """
    def __init__(self):
        # このタスクは件数を指定しない
        super().__init__(count=None)
        self.action_name = "ログイン状態チェック" # Remove "【検証用】"

    def _execute_main_logic(self):
        page = self.page
        page.goto("https://room.rakuten.co.jp/items", wait_until="domcontentloaded")

        try:
            logging.debug("「my ROOM」リンクをクリックします。")
            my_room_link_locator = page.locator('a:has-text("my ROOM")')
            my_room_link_locator.wait_for(state='visible', timeout=10000)
            my_room_link_locator.click()

            # ページの遷移を待つ
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            current_url = page.url

            if "https://room.rakuten.co.jp/" in current_url and "https://login.account.rakuten.com/" not in current_url:
                logging.info(f"ログイン状態は正常です。")
                #logging.info(f"成功: my ROOMページに遷移しました。ログイン状態は正常です。 (URL: {current_url})")
                return True
            elif "https://login.account.rakuten.com/" in current_url:
                # 失敗パターン1: ログインページへのリダイレクト
                logging.error(f"失敗: ログインページにリダイレクトされました。 (URL: {current_url})")
                self._take_screenshot_on_error(prefix="login_check_redirect")
                return False
            else:
                # 失敗パターン2: 予期しないページへの遷移
                logging.error(f"失敗: 予期しないページに遷移しました。 (URL: {current_url})")
                self._take_screenshot_on_error(prefix="login_check_unexpected_page")
                return False
        except TimeoutError:
            # 失敗パターン3: 「my ROOM」リンクが見つからない
            logging.error("失敗: 「my ROOM」リンクが見つかりませんでした。ログインしていない可能性があります。")
            self._take_screenshot_on_error(prefix="login_check_link_not_found")
            return False

def run_check_login_status(): # Function name is already correct
    """ラッパー関数"""
    task = CheckLoginStatusTask() # Use the correct class name
    return task.run()