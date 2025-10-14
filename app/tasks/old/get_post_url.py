import logging
import os
from playwright.sync_api import sync_playwright, TimeoutError
import traceback
from app.core.database import get_products_for_post_url_acquisition, update_post_url, update_product_status
from app.core.config_manager import is_headless

PROFILE_DIR = "db/playwright_profile"

def get_post_url():
    """
    投稿URL取得のメインロジック
    """
    products = get_products_for_post_url_acquisition()
    if not products:
        logging.info("投稿URL取得対象の商品はありません。")
        return

    if not os.path.exists(PROFILE_DIR):
        logging.error(f"認証プロファイルが見つかりません: {PROFILE_DIR}")
        return

    logging.info(f"{len(products)}件の商品を対象に投稿URL取得処理を開始します。")

    try:
        with sync_playwright() as p:
            headless_mode = is_headless()
            logging.info(f"Playwright ヘッドレスモード: {headless_mode}")
            context = p.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                headless=headless_mode,
                slow_mo=500 if not headless_mode else 0,
                env={"DISPLAY": ":0"} if not headless_mode else {}
            )

            for product in products:
                page = None
                try:
                    logging.info(f"商品ID: {product['id']} の処理を開始... URL: {product['url']}")
                    page = context.new_page()
                    page.goto(product['url'], wait_until='domcontentloaded', timeout=30000)

                    # "ROOMに投稿" のリンクを探す
                    post_link_locator = page.get_by_role("link", name="ROOMに投稿")
                    post_link_locator.wait_for(timeout=15000)
                    post_url = post_link_locator.get_attribute('href')

                    if post_url:
                        logging.info(f"  -> 投稿URL取得成功: {post_url}")
                        update_post_url(product['id'], post_url)
                    else:
                        logging.warning(f"  -> 商品ID: {product['id']} の投稿URLが見つかりませんでした。ステータスを「エラー」に更新します。")
                        update_product_status(product['id'], 'エラー')

                except Exception as e:
                    logging.error(f"  -> 商品ID: {product['id']} の処理中に予期せぬ例外が発生しました。")
                    logging.error(traceback.format_exc())
                    update_product_status(product['id'], 'エラー')
                finally:
                    if page:
                        page.close()
            context.close()
    except Exception as e:
        logging.critical(f"Playwrightの初期化中に致命的なエラーが発生しました: {e}")

    logging.info("投稿URL取得処理が完了しました。")