import logging
import os
from app.core.base_task import BaseTask
from app.core.database import get_all_ready_to_post_products, update_product_status, get_product_by_id

TRACE_DIR = "db/error_trace"

class PostingTask(BaseTask):
    """
    ROOMへ商品情報を自動投稿するタスク。
    """
    def __init__(self, count: int = 10, product_id: int = None):
        # BaseTaskのcountはログ表示用
        super().__init__(count=count)
        self.action_name = "記事投稿"
        self.product_id = product_id

    def _execute_main_logic(self):
        # トレース保存用ディレクトリを作成
        os.makedirs(TRACE_DIR, exist_ok=True)

        if self.product_id:
            product = get_product_by_id(self.product_id)
            if product and product['status'] == '投稿準備完了':
                products = [product]
                logging.debug(f"指定された商品ID: {self.product_id} を投稿します。")
            else:
                logging.error(f"指定された商品ID: {self.product_id} は存在しないか、投稿準備完了ではありません。")
                return
        else:
            products = get_all_ready_to_post_products(limit=self.target_count)
            if not products:
                logging.info("投稿対象の商品がありませんでした。")
                return

        posted_count = 0
        for product in products:
            page = None
            try:
                logging.debug(f"--- {posted_count + 1}/{len(products)} 件目の処理を開始 ---")
                post_url = product['post_url']
                if not post_url:
                    logging.warning(f"商品ID {product['id']} の投稿URLがありません。スキップします。")
                    continue

                caption = product['ai_caption'] or f"「{product['name']}」おすすめです！ #楽天ROOM"

                product_name = product['name']
                display_name = (product_name[:97] + '...') if len(product_name) > 100 else product_name
                logging.debug(f"商品「{display_name}」を投稿します。")
                page = self.context.new_page()
                page.context.tracing.start(screenshots=True, snapshots=True, sources=True)

                #logging.info(f"投稿ページにアクセスします: {post_url}")
                page.goto(post_url, wait_until="networkidle", timeout=60000)

                textarea_locator = page.locator("textarea[name='content']")
                textarea_locator.fill(caption)

                page.locator('button.collect-btn:has-text("完了")').first.click(timeout=10000)
                #logging.info("投稿ボタンをクリックしました。")
                page.wait_for_timeout(15000) # 投稿完了を待つ
                
                page.context.tracing.stop() # トレースを停止するが、ファイルは保存しない
                update_product_status(product['id'], '投稿済')
                posted_count += 1

            except Exception as e:
                logging.error(f"商品ID {product['id']} の投稿処理中にエラーが発生しました: {e}")
                if page and not page.is_closed():
                    page.context.tracing.stop(path=os.path.join(TRACE_DIR, f"error_trace_{product['id']}.zip"))
                    page.screenshot(path=os.path.join(TRACE_DIR, f"error_screenshot_{product['id']}.png"))
                update_product_status(product['id'], 'エラー', error_message=str(e)) # エラーメッセージも記録
            finally:
                if page and not page.is_closed():
                    page.close()
        
        logging.info(f"自動投稿タスクを終了します。処理済み: {posted_count}件")

def run_posting(count: int = 10, product_id: int = None):
    """ラッパー関数"""
    task = PostingTask(count=count, product_id=product_id)
    return task.run()