import logging
from playwright.sync_api import TimeoutError
from app.test_x.tasks.base_task import BaseTask
from app import locators

class CheckLoginStatusTestTask(BaseTask):
    """
    【検証用】保存された認証プロファイルを使ってログイン状態を確認するタスク
    """
    def __init__(self):
        # このタスクは件数を指定しない
        super().__init__(count=None)
        self.action_name = "【検証用】ログイン状態チェック"

    def _execute_main_logic(self):
        page = self.page
        page.goto("https://room.rakuten.co.jp/items", wait_until="domcontentloaded")

        try:
            logging.info("「my ROOM」リンクをクリックします。")
            my_room_link_locator = page.locator(locators.MY_ROOM_LINK)
            my_room_link_locator.wait_for(state='visible', timeout=10000)
            my_room_link_locator.click()

            # ページの遷移を待つ
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            current_url = page.url

            if "https://room.rakuten.co.jp/" in current_url and "https://login.account.rakuten.com/" not in current_url:
                logging.info(f"成功: my ROOMページに遷移しました。ログイン状態は正常です。 (URL: {current_url})")
                return True
            elif "https://login.account.rakuten.com/" in current_url:
                logging.error(f"失敗: ログインページにリダイレクトされました。 (URL: {current_url})")
                return False
            else:
                logging.error(f"失敗: 予期しないページに遷移しました。 (URL: {current_url})")
                return False
        except TimeoutError:
            logging.error("失敗: 「my ROOM」リンクが見つかりませんでした。ログインしていない可能性があります。")
            return False

def run_check_login_status_test():
    """ラッパー関数"""
    task = CheckLoginStatusTestTask()
    return task.run()