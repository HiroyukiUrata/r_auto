import logging
from playwright.sync_api import sync_playwright
import os
from app.core.database import get_all_ready_to_post_products, update_product_status

from app import locators
PROFILE_DIR = "db/playwright_profile"

def post_article(count: int = 1):
    """
    保存された認証プロファイルを使ってROOMへ商品情報を自動投稿する。
    :param count: 投稿する件数
    """
    logging.info(f"自動投稿タスクを開始します。目標件数: {count}件")

    # --- デバッグフラグ ---
    # Trueにすると、ブラウザが表示され(headless=False)、投稿ボタンのクリックがスキップされます。
    # 通常実行時はFalseにしてください。
    is_debug =False

    products = get_all_ready_to_post_products(limit=count)
    if not products:
        logging.info("投稿対象の商品がありませんでした。")
        return

    if not os.path.exists(PROFILE_DIR):
        logging.error(f"認証プロファイル {PROFILE_DIR} が見つかりません。先に「認証状態の保存」タスクを実行してください。")
        return

    posted_count = 0
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                headless=not is_debug,
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
                env={"DISPLAY": ":0"} if not is_debug else {}
            )

            for product in products:
                page = None
                try:
                    logging.info(f"--- {posted_count + 1}/{len(products)} 件目の処理を開始 ---")
                    # 投稿には商品ページのURLではなく、投稿用URL(post_url)を使用する
                    post_url = product['post_url']
                    if not post_url:
                        logging.warning(f"商品ID {product['id']} の投稿URLがありません。スキップします。")
                        continue

                    caption = product.get('ai_caption') or f"「{product['name']}」おすすめです！ #楽天ROOM"

                    logging.info(f"商品「{product['name']}」をURL: {post_url} で投稿します。")
                    page = context.new_page()
                    page.context.tracing.start(screenshots=True, snapshots=True, sources=True)

                    logging.info(f"投稿ページにアクセスします: {post_url}")
                    page.goto(post_url, wait_until="networkidle", timeout=60000)

                    textarea_locator = page.locator(locators.POST_TEXTAREA)
                    textarea_locator.fill(caption)

                    if not is_debug:
                        page.locator(locators.SUBMIT_BUTTON).first.click(timeout=10000)
                        logging.info("投稿ボタンをクリックしました。")
                        page.wait_for_timeout(15000) # 投稿完了を待つ

                    page.context.tracing.stop(path=f"db/trace_{product['id']}.zip")
                    update_product_status(product['id'], '投稿済')
                    posted_count += 1

                except Exception as e:
                    logging.error(f"商品ID {product['id']} の投稿処理中にエラーが発生しました: {e}")
                    if page and not page.is_closed():
                        page.context.tracing.stop(path=f"db/error_trace_{product['id']}.zip")
                        page.screenshot(path=f"db/error_screenshot_{product['id']}.png")
                    update_product_status(product['id'], 'エラー') # エラーが発生した商品のみステータスを更新
                finally:
                    if page:
                        page.close()
            
            context.close()

    except Exception as e:
        logging.critical(f"Playwrightの初期化中に致命的なエラーが発生しました: {e}")
    
    logging.info(f"自動投稿タスクを終了します。処理済み: {posted_count}件")