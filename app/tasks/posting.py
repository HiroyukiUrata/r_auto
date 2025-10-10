import logging
from playwright.sync_api import sync_playwright
import os
from app.core.database import get_all_unposted_products, update_product_status

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

    products = get_all_unposted_products(limit=count)
    if not products:
        logging.info("投稿対象の商品がありませんでした。")
        return

    if not os.path.exists(PROFILE_DIR):
        logging.error(f"認証プロファイル {PROFILE_DIR} が見つかりません。先に「認証状態の保存」タスクを実行してください。")
        return

    posted_count = 0
    try:
        with sync_playwright() as p:
            for product in products:
                logging.info(f"--- {posted_count + 1}/{len(products)} 件目の処理を開始 ---")
                post_url = product['url']
                # 投稿文は将来的にAIで生成するか、DBに保存されたものを使用することを想定
                caption = f"「{product['name']}」おすすめです！ #楽天ROOM"

                logging.info(f"商品「{product['name']}」をURL: {post_url} で投稿します。")

                context = None # エラーハンドリングのため
                try:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=PROFILE_DIR,
                        headless=not is_debug, # is_debugがTrueならFalse(表示)、FalseならTrue(非表示)
                        locale="ja-JP",
                        timezone_id="Asia/Tokyo",
                        # headless=Falseの場合のみ、仮想ディスプレイを指定
                        env={"DISPLAY": ":0"} if is_debug else {},
                    )
                    context.tracing.start(screenshots=True, snapshots=True, sources=True)
                    page = context.new_page()

                    logging.info(f"投稿ページにアクセスします: {post_url}")
                    page.goto(post_url, wait_until="networkidle", timeout=60000)
                    
                    textarea_locator = page.locator(locators.POST_TEXTAREA)
                    logging.info(f"キャプションを入力します: {caption[:30]}...")
                    textarea_locator.fill(caption)

                    if not is_debug:
                        page.locator(locators.SUBMIT_BUTTON).first.click(timeout=10000)
                        logging.info("投稿ボタンをクリックしました。")
                        page.wait_for_timeout(15000) # 投稿完了を待つ
                    else:
                        logging.info("デバッグモードのため、投稿ボタンのクリックをスキップしました。")

                    context.tracing.stop(path=f"db/trace_{product['id']}.zip")
                    context.close()
                    update_product_status(product['id'], '済')
                    posted_count += 1

                except Exception as e:
                    logging.error(f"商品ID {product['id']} の投稿処理中にエラーが発生しました: {e}")
                    if context:
                        try:
                            context.tracing.stop(path=f"db/error_trace_{product['id']}.zip")
                        except Exception as trace_e:
                            logging.error(f"トレースの保存中にエラーが発生しました: {trace_e}")
                    if 'page' in locals() and not page.is_closed():
                        page.screenshot(path=f"db/error_screenshot_{product['id']}.png")
                    update_product_status(product['id'], 'エラー')
                    # 1件エラーが出たら、残りは実行せずにタスクを終了する
                    logging.warning("エラーが発生したため、残りの投稿処理を中止します。")
                    break
    except Exception as e:
        logging.critical(f"Playwrightの初期化中に致命的なエラーが発生しました: {e}")
    
    logging.info(f"自動投稿タスクを終了します。処理済み: {posted_count}件")