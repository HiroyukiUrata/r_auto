import logging
from playwright.sync_api import sync_playwright, TimeoutError
import os
from app import locators

from app.core.config_manager import is_headless
PROFILE_DIR = "db/playwright_profile"

def check_login_status():
    """保存された認証プロファイルを使ってログイン状態を確認するタスク"""
    logging.info("ログイン状態チェックタスクを開始します。")

    if not os.path.exists(PROFILE_DIR):
        logging.error(f"認証プロファイル {PROFILE_DIR} が見つかりません。「認証状態の保存」を先に実行してください。")
        return False

    # プロファイルロックファイルを削除して、多重起動エラーを防ぐ
    lockfile_path = os.path.join(PROFILE_DIR, "SingletonLock")
    if os.path.exists(lockfile_path):
        logging.warning(f"古いロックファイル {lockfile_path} が見つかったため、削除します。")
        os.remove(lockfile_path)

    try:
        with sync_playwright() as p:
            headless_mode = is_headless()
            logging.info(f"Playwright ヘッドレスモード: {headless_mode}")
            context = p.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                headless=headless_mode,
                env={"DISPLAY": ":0"} if not headless_mode else {}
            )
            page = context.new_page()
            page.goto("https://room.rakuten.co.jp/items", wait_until="domcontentloaded")

            try:
                logging.info("「my ROOM」リンクをクリックします。")
                my_room_link_locator = page.locator(locators.MY_ROOM_LINK)
                my_room_link_locator.wait_for(state='visible', timeout=10000)
                my_room_link_locator.click()

                # ページの遷移を待つ
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                current_url = page.url

                if "https://room.rakuten.co.jp/" in current_url:
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
    except Exception as e:
        logging.error(f"失敗: ログイン状態が確認できませんでした。: {e}")
        return False