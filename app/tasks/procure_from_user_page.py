import logging
import json
import os
import random
from app.core.database import product_exists_by_url
from app.core.base_task import BaseTask
from app.tasks.import_products import process_and_import_products
from app.utils.selector_utils import convert_to_robust_selector

SOURCE_URLS_FILE = "db/source_urls.json"
LAST_USED_URL_INDEX_FILE = "db/last_used_url_index.json"

def get_next_source_url():
    """
    調達元のURLリストを読み込み、前回使用した次のURLを返す（ローテーション）。
    """
    if not os.path.exists(SOURCE_URLS_FILE):
        logging.warning(f"URLリストファイルが見つかりません: {SOURCE_URLS_FILE}")
        return None

    try:
        with open(SOURCE_URLS_FILE, "r", encoding="utf-8") as f:
            urls = json.load(f)
        if not urls:
            logging.warning("URLリストが空です。")
            return None

        last_index = -1
        if os.path.exists(LAST_USED_URL_INDEX_FILE):
            with open(LAST_USED_URL_INDEX_FILE, "r") as f:
                last_index = json.load(f).get("last_index", -1)

        next_index = (last_index + 1) % len(urls)

        with open(LAST_USED_URL_INDEX_FILE, "w") as f:
            json.dump({"last_index": next_index}, f)

        return urls[next_index]

    except (IOError, json.JSONDecodeError) as e:
        logging.error(f"URLリストファイルの読み込みまたは書き込みに失敗しました: {e}")
        return None

class ProcureFromUserPageTask(BaseTask):
    """
    指定されたユーザーページを巡回して商品を調達するタスク。
    """
    def __init__(self, count: int = 5):
        super().__init__(count=count)
        self.action_name = "ユーザーページから商品を調達"
        self.use_auth_profile = False # 認証プロファイルは不要

    def _execute_main_logic(self):
        source_url = get_next_source_url()
        if not source_url:
            logging.error("調達元のURLを取得できませんでした。タスクを中止します。")
            return

        logging.info(f"ユーザーページ「{source_url}」から商品調達を開始します。")
        logging.debug(f"商品調達の目標件数: {self.target_count}件")

        items = []
        page = self.page
        try:
            page.goto(source_url, wait_until="domcontentloaded", timeout=60000)
            page_title = page.title() # ページタイトルを取得
            logging.info(f"ページタイトルを取得しました: {page_title}")

            # ユーザーページの商品カードセレクタ
            card_selector = convert_to_robust_selector('div[class*="container--JAywt"]')
            product_cards = page.locator(card_selector)
            
            # ページ上のカードが読み込まれるのを待つ
            product_cards.first.wait_for(state="visible", timeout=30000)

            all_cards = product_cards.all()
            random.shuffle(all_cards) # 毎回同じ商品を取得しないようにシャッフル

            logging.debug(f"ページから {len(all_cards)} 件の商品が見つかりました。")

            for card in all_cards:
                if len(items) >= self.target_count:
                    break

                image_link_selector = convert_to_robust_selector("a.link-image--15_8Q")
                url_element = card.locator(image_link_selector).first
                image_element = card.locator("img").first

                if url_element.count() and image_element.count():
                    page_url = url_element.get_attribute('href')
                    if not page_url.startswith("http"):
                        page_url = f"https://room.rakuten.co.jp{page_url}"

                    if product_exists_by_url(page_url):
                        logging.debug(f"  スキップ(DB重複): この商品は既にDBに存在します。 URL: {page_url[:50]}...")
                        continue

                    item_data = {"item_description": image_element.get_attribute('alt'), "page_url": page_url, "image_url": image_element.get_attribute('src'), "procurement_keyword": f"ユーザー巡回 ({page_title})"}
                    items.append(item_data)
                    logging.debug(f"  [{len(items)}/{self.target_count}] 商品情報を収集: {item_data['item_description'][:30]}...")
                else:
                    logging.warning("  商品カードから必要な情報（URL、画像）を取得できませんでした。")

        except Exception as e:
            logging.error(f"ユーザーページのスクレイピング中にエラーが発生しました: {e}")

        if items:
            logging.debug(f"収集した {len(items)} 件の商品をデータベースに登録します。")
            added_count, skipped_count = process_and_import_products(items)
            logging.info(f"商品登録処理が完了しました。新規追加: {added_count}件, スキップ: {skipped_count}件")
            logging.info(f"[Action Summary] name=商品調達(ユーザー巡回), count={added_count}")
        else:
            logging.info("指定されたユーザーページから調達できる新しい商品がありませんでした。")

def run_procure_from_user_page(count: int = 5):
    """ラッパー関数"""
    task = ProcureFromUserPageTask(count=count)
    return task.run()