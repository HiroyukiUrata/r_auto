import logging
from playwright.sync_api import sync_playwright, TimeoutError
import os

PROFILE_DIR = "db/playwright_profile"

def check_login_status():
    """保存された認証プロファイルを使ってログイン状態を確認するタスク"""
    logging.info("ログイン状態チェックタスクを開始します。")

    if not os.path.exists(PROFILE_DIR):
        logging.error(f"認証プロファイル {PROFILE_DIR} が見つかりません。「認証状態の保存」を先に実行してください。")
        return False

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                headless=True,
            )
            page = context.new_page()
            page.goto("https://room.rakuten.co.jp/items", wait_until="domcontentloaded")

            # 「my ROOM」リンクを探す
            my_room_link_selector = 'a:has-text("my ROOM")'
            try:
                logging.info("「my ROOM」リンクをクリックします。")
                page.locator(my_room_link_selector).wait_for(state='visible', timeout=10000)
                page.click(my_room_link_selector)

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