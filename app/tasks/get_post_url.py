import logging
import traceback
from playwright.sync_api import TimeoutError
from app.core.base_task import BaseTask
from app.core.database import get_products_for_post_url_acquisition, update_post_url, update_product_status

class GetPostUrlTask(BaseTask):
    """
    商品の投稿用URLを取得するタスク。
    """
    def __init__(self):
        # このタスクはDBから全件取得するため、countは不要
        super().__init__(count=None)
        self.action_name = "投稿URL取得"

    def _execute_main_logic(self):
        products = get_products_for_post_url_acquisition()
        if not products:
            logging.info("投稿URL取得対象の商品はありません。")
            return

        total_count = len(products)
        logging.info(f"{total_count}件の商品を対象に投稿URL取得処理を開始します。")

        success_count = 0
        error_count = 0
        for product in products:
            # BaseTaskが起動したブラウザコンテキスト内で、商品ごとに新しいページを作成
            page = self.context.new_page()
            try:
                logging.debug(f"商品ID: {product['id']} の処理を開始... URL: {product['url']}")
                page.goto(product['url'], wait_until='domcontentloaded', timeout=30000)

                # "ROOMに投稿" のリンクを探す
                post_link_locator = page.get_by_role("link", name="ROOMに投稿")
                post_link_locator.wait_for(timeout=15000)
                post_url = post_link_locator.get_attribute('href')

                if post_url:
                    logging.debug(f"  -> 投稿URL取得成功: {post_url}")
                    update_post_url(product['id'], post_url)
                    success_count += 1
                else:
                    logging.warning(f"  -> 商品ID: {product['id']} の投稿URLが見つかりませんでした。ステータスを「エラー」に更新します。")
                    update_product_status(product['id'], 'エラー')
                    error_count += 1

            except Exception as e:
                logging.error(f"  -> 商品ID: {product['id']} の処理中に予期せぬ例外が発生しました。")
                logging.error(traceback.format_exc())
                update_product_status(product['id'], 'エラー')
                error_count += 1
            finally:
                # 1商品ごとの処理が終わったら、必ずページを閉じる
                if page and not page.is_closed():
                    page.close()
        
        logging.info(f"投稿URL取得処理が完了しました。成功: {success_count}件, 失敗: {error_count}件 (対象: {total_count}件)")

def run_get_post_url():
    """ラッパー関数"""
    task = GetPostUrlTask()
    return task.run()
