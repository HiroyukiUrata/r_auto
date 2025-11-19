import logging
from playwright.sync_api import TimeoutError
from app.core.base_task import BaseTask, PRIMARY_PROFILE_DIR, LoginRedirectError # Import from core

from app.core.config_manager import get_config
class CheckLoginStatusTask(BaseTask): # Class name is already correct
    """
    保存された認証プロファイルを使ってログイン状態を確認するタスク
    """
    def __init__(self):
        # このタスクは件数を指定しない
        super().__init__(count=None)
        self.action_name = "ログイン状態" # Remove "【検証用】"

    def _execute_main_logic(self):
        page = self.page
        page.goto("https://room.rakuten.co.jp/items", wait_until="domcontentloaded")

        # 設定が有効な場合のみ、ログイン状態確認の初期ページを撮影
        config = get_config()
        if config.get("debug_screenshot_enabled", False):
            self._take_screenshot_on_error(prefix="login_check_initial_page")

        try:
            logging.debug("「my ROOM」リンクをクリックします。")
            my_room_link_locator = page.locator('a:has-text("my ROOM")')
            my_room_link_locator.wait_for(state='visible', timeout=30000)
            my_room_link_locator.click()

            # ページの遷移を待つ
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            current_url = page.url

            profile_indicator = "[1]" if self.current_profile_dir == PRIMARY_PROFILE_DIR else "[2]"

            if "https://room.rakuten.co.jp/" in current_url and "https://login.account.rakuten.com/" not in current_url:
                logging.info(f"ログイン状態は正常です。 {profile_indicator}")
                #logging.info(f"成功: my ROOMページに遷移しました。ログイン状態は正常です。 (URL: {current_url})")
                return True
            elif "https://login.account.rakuten.com/" in current_url:
                # 失敗パターン1: ログインページへのリダイレクト
                self._take_screenshot_on_error(prefix="login_check_redirect")
                # プロファイル切り替えのトリガーとなる例外を送出
                raise LoginRedirectError(f"プロファイル '{self.current_profile_dir}' でログインページにリダイレクトされました。")
            else:
                # 失敗パターン2: 予期しないページへの遷移
                self._take_screenshot_on_error(prefix="login_check_unexpected_page")
                # これもログイン失敗の一種として扱う
                raise LoginRedirectError(f"プロファイル '{self.current_profile_dir}' で予期しないページに遷移しました。 (URL: {current_url})")

        except TimeoutError:
            # 失敗パターン3: 「my ROOM」リンクが見つからない
            self._take_screenshot_on_error(prefix="login_check_link_not_found")
            # これもログイン失敗として扱い、例外を送出
            raise LoginRedirectError(f"プロファイル '{self.current_profile_dir}' で「my ROOM」リンクが見つかりませんでした。ログインしていない可能性があります。")


def run_check_login_status(): # Function name is already correct
    """ラッパー関数"""
    task = CheckLoginStatusTask() # Use the correct class name
    return task.run()