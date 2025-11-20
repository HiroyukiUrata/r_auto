import logging
import time
from playwright.sync_api import TimeoutError, Error as PlaywrightError
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
        max_retries = 3
        for attempt in range(max_retries):
            try:
                page.goto("https://room.rakuten.co.jp/items", wait_until="domcontentloaded")
        
                # 設定が有効な場合のみ、ログイン状態確認の初期ページを撮影
                config = get_config()
                if config.get("debug_screenshot_enabled", False):
                    self._take_screenshot_on_error(prefix="login_check_initial_page")
        
                logging.debug("「my ROOM」リンクをクリックします。")
                my_room_link_locator = page.locator('a:has-text("my ROOM")')
                my_room_link_locator.wait_for(state='visible', timeout=10000)
                my_room_link_locator.click()
        
                # ページの遷移を待つ
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                current_url = page.url
        
                profile_indicator = "[1]" if self.current_profile_dir == PRIMARY_PROFILE_DIR else "[2]"
        
                if "https://room.rakuten.co.jp/" in current_url and "https://login.account.rakuten.com/" not in current_url:
                    logging.info(f"ログイン状態は正常です。 {profile_indicator}")
                    return True

                # リダイレクトや予期せぬページ遷移はリトライ不要なため、ループの外で判定
                break

            except LoginRedirectError:
                # LoginRedirectErrorはリトライせずに即座に例外を再送出し、プロファイル切り替えロジックに移行させる
                raise
            except TimeoutError:
                if attempt < max_retries - 1:
                    logging.warning(f"「my ROOM」リンクが見つかりませんでした。ページをリロードして再試行します... ({attempt + 1}/{max_retries})")
                    try:
                        page.reload(wait_until="domcontentloaded")
                        time.sleep(3) # リロード後の描画を待つ
                    except PlaywrightError as reload_error:
                        logging.error(f"ページのリロード中にエラーが発生しました: {reload_error}")
                        # リロードに失敗した場合は、これ以上リトライしても無駄なのでループを抜ける
                        break
                else:
                    # 最終試行でも失敗した場合
                    self._take_screenshot_on_error(prefix="login_check_link_not_found")
                    raise LoginRedirectError(f"プロファイル '{self.current_profile_dir}' で「my ROOM」リンクが見つかりませんでした。ログインしていない可能性があります。")

        # ループを抜けた後、最終的なURLを再チェック
        current_url = page.url
        if "https://login.account.rakuten.com/" in current_url:
            self._take_screenshot_on_error(prefix="login_check_redirect")
            raise LoginRedirectError(f"プロファイル '{self.current_profile_dir}' でログインページにリダイレクトされました。")
        elif "https://room.rakuten.co.jp/" not in current_url:
            self._take_screenshot_on_error(prefix="login_check_unexpected_page")
            raise LoginRedirectError(f"プロファイル '{self.current_profile_dir}' で予期しないページに遷移しました。 (URL: {current_url})")
        else:
            # ループが正常に完了しなかった場合（リロードエラーなどでbreakした場合）
            raise LoginRedirectError(f"プロファイル '{self.current_profile_dir}' でのログイン状態確認に失敗しました。")


def run_check_login_status(): # Function name is already correct
    """ラッパー関数"""
    task = CheckLoginStatusTask() # Use the correct class name
    return task.run()