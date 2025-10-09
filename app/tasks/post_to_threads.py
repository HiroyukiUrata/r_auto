import logging
from playwright.sync_api import sync_playwright
import os
import time

STATE_FILE = "db/state.json"

def post_to_threads():
    """
    保存された認証情報を使ってThreadsにログインし、
    VNC経由で投稿ボタンを押すところまでを実行するタスク。
    """
    logging.info("Threadsへの投稿タスクを開始します。")

    if not os.path.exists(STATE_FILE):
        logging.error(f"認証ファイル {STATE_FILE} が見つかりません。先に「認証状態の保存」タスクを実行してください。")
        return

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, env={"DISPLAY": ":0"})
            context = browser.new_context(storage_state=STATE_FILE, locale="ja-JP", timezone_id="Asia/Tokyo")
            page = context.new_page()

            logging.info("Threadsにアクセスします...")
            page.goto("https://www.threads.net/", wait_until="domcontentloaded")

            logging.info("新規投稿ボタンをクリックします...")
            page.locator("div[role='button'][tabindex='0']").first.click()

            logging.info("投稿文を入力します...")
            page.locator("div[aria-label='スレッドを作成']").fill(f"Playwrightからのテスト投稿です。\n現在時刻: {time.strftime('%Y-%m-%d %H:%M:%S')}")

            logging.info("「投稿する」ボタンをクリックします...")
            page.get_by_role("button", name="投稿する").click()

            logging.info("投稿が完了しました。5秒後にブラウザを閉じます。")
            time.sleep(5)
            browser.close()
    except Exception as e:
        logging.error(f"Threadsへの投稿中にエラーが発生しました: {e}")