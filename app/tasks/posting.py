import logging
from playwright.sync_api import sync_playwright
import os
from app.core.database import get_unposted_products, update_product_status

from app import locators
PROFILE_DIR = "db/playwright_profile"

def post_article():
    """保存された認証プロファイルを使ってROOMへ商品情報を自動投稿する"""
    logging.info("自動投稿タスクを開始します。")

    product = get_unposted_products()
    if not product:
        logging.info("投稿対象の商品がありませんでした。")
        return

    if not os.path.exists(PROFILE_DIR):
        logging.error(f"認証プロファイル {PROFILE_DIR} が見つかりません。先に「認証状態の保存」タスクを実行してください。")
        return

    post_url = product['url']
    # 投稿文は将来的にAIで生成するか、DBに保存されたものを使用することを想定
    caption = f"「{product['name']}」おすすめです！ #楽天ROOM"

    logging.info(f"商品「{product['name']}」をURL: {post_url} で投稿します。")

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                headless=True,
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
            )

            # トレースを開始
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            
            page = context.new_page()

            logging.info(f"投稿ページにアクセスします: {post_url}")
            page.goto(post_url, wait_until="domcontentloaded", timeout=60000)

            textarea_locator = page.locator(locators.POST_TEXTAREA)
            textarea_locator.wait_for(timeout=20000)
            
            logging.info(f"キャプションを入力します: {caption[:30]}...")
            textarea_locator.fill(caption)

            is_debug = False # ここではFalseに固定
            if not is_debug:
                submit_button_locator = page.locator(locators.SUBMIT_BUTTON)
                submit_button_locator.wait_for(timeout=10000)
                submit_button_locator.click()
                logging.info("投稿ボタンをクリックしました。")
                page.wait_for_timeout(15000) # 投稿完了を待つ
            else:
                logging.info("デバッグモードのため、投稿ボタンのクリックをスキップしました。")

            # 処理終了後にトレースを停止し、ファイルを保存
            context.tracing.stop(path = "db/trace.zip")
            context.close()

        update_product_status(product['id'], '済')

    except Exception as e:
        logging.error(f"投稿処理中にエラーが発生しました: {e}")
        # エラー時にもトレースを保存
        if 'context' in locals():
            try:
                context.tracing.stop(path = "db/error_trace.zip")
            except Exception as trace_e:
                logging.error(f"トレースの保存中にエラーが発生しました: {trace_e}")
        # エラー発生時にスクリーンショットを保存
        if 'page' in locals() and not page.is_closed():
            page.screenshot(path="db/error_screenshot.png")
        update_product_status(product['id'], 'エラー')