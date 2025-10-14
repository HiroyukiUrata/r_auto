import logging
import random
import json
import os
from app.core.database import product_exists_by_url
from app.core.base_task import BaseTask
from app.tasks.import_products import process_and_import_products

KEYWORDS_FILE = "db/keywords.json"

def get_keywords_from_file():
    """キーワードファイルを読み込んで、AとBのリストを返す"""
    if not os.path.exists(KEYWORDS_FILE):
        logging.warning(f"キーワードファイルが見つかりません: {KEYWORDS_FILE}")
        return [], []
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("keywords_a", []), data.get("keywords_b", [])
    except (IOError, json.JSONDecodeError) as e:
        logging.error(f"キーワードファイルの読み込みに失敗しました: {e}")
        return [], []

class RakutenSearchProcureTask(BaseTask):
    """
    楽天市場を検索して商品を調達するタスク。
    ログインプロファイルは不要。
    """
    def __init__(self, count: int = 5):
        super().__init__(count=count)
        self.action_name = "楽天市場から商品を検索・調達"
        self.use_auth_profile = False # 認証プロファイルは不要

    def _execute_main_logic(self):
        keywords_a, keywords_b = get_keywords_from_file()
    
        if not keywords_a:
            logging.warning("キーワードAが設定されていません。商品調達を中止します。")
            return
        
        search_keywords = []
        if keywords_a and keywords_b:
            keyword_a = random.choice(keywords_a)
            keyword_b = random.choice(keywords_b)
            combined_keyword = f"{keyword_a} {keyword_b}"
            search_keywords.append(combined_keyword)
            logging.info(f"キーワードA「{keyword_a}」とキーワードB「{keyword_b}」を組み合わせて検索します: 「{combined_keyword}」")
        else:
            search_keywords = keywords_a
            random.shuffle(search_keywords)
            logging.info("キーワードAのみで検索します。")
        
        logging.info(f"商品調達の目標件数: {self.target_count}件")

        items = []
        # BaseTaskが管理するページオブジェクトを使用
        page = self.page
        try:
            for keyword in search_keywords:
                if len(items) >= self.target_count:
                    logging.info(f"目標件数 ({self.target_count}件) に達したため、キーワード検索を終了します。")
                    break

                page_num = 1
                MAX_PAGES_PER_KEYWORD = 5
                logging.info(f"キーワード「{keyword}」での商品検索を開始します。")

                while page_num <= MAX_PAGES_PER_KEYWORD:
                    if len(items) >= self.target_count:
                        break

                    search_url = f"https://search.rakuten.co.jp/search/mall/{keyword}/?p={page_num}"
                    logging.info(f"検索ページにアクセスします (Page {page_num}): {search_url}")
                    page.goto(search_url, wait_until="domcontentloaded", timeout=60000)

                    product_cards = page.locator("div.searchresultitem")
                    num_found_on_page = product_cards.count()
                    logging.info(f"ページ {page_num} から {num_found_on_page} 件の商品が見つかりました。")

                    if num_found_on_page == 0:
                        logging.info(f"このキーワード「{keyword}」ではこれ以上商品が見つかりませんでした。次のキーワードに進みます。")
                        break

                    for i, card in enumerate(product_cards.all()):
                        if len(items) >= self.target_count:
                            break
                        
                        url_element = card.locator("a[class*='image-link-wrapper--']").first
                        image_element = card.locator("img[class*='image--']").first

                        if url_element.count() and image_element.count():
                            page_url = url_element.get_attribute('href')
                            if product_exists_by_url(page_url):
                                logging.info(f"  スキップ(DB重複): この商品は既にDBに存在します。 URL: {page_url[:50]}...")
                                continue

                            item_data = {"item_description": image_element.get_attribute('alt'), "page_url": page_url, "image_url": image_element.get_attribute('src'), "procurement_keyword": keyword}
                            items.append(item_data)
                            logging.info(f"  [{len(items)}/{self.target_count}] 商品情報を収集: {item_data['item_description'][:30]}...")
                        else:
                            logging.warning(f"  商品カード {i+1} から必要な情報（商品名、URL、画像）を取得できませんでした。")
                    
                    page_num += 1
        except Exception as e:
            logging.error(f"楽天市場のスクレイピング中にエラーが発生しました: {e}")

        if items:
            logging.info(f"収集した {len(items)} 件の商品をデータベースに登録します。")
            added_count, skipped_count = process_and_import_products(items)
            logging.info(f"商品登録処理が完了しました。新規追加: {added_count}件, スキップ: {skipped_count}件")
        else:
            logging.info("楽天市場から調達できる商品がありませんでした。")

def search_and_procure_from_rakuten(count: int = 5):
    """ラッパー関数"""
    task = RakutenSearchProcureTask(count=count)
    return task.run()