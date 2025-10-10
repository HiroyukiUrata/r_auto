import logging
import json
import os
from playwright.sync_api import sync_playwright
from app.core.database import import_products

KEYWORDS_FILE = "db/keywords.json"

def get_keywords_from_file():
    """キーワードファイルを読み込んで返す"""
    if not os.path.exists(KEYWORDS_FILE):
        return {"include_keywords": [], "exclude_keywords": []}
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        logging.error(f"キーワードファイルの読み込みに失敗しました: {e}")
        return {"include_keywords": [], "exclude_keywords": []}

def procure_products():
    """
    キーワード管理で登録されたキーワードを元に、商品を検索・調達してDBに保存する。
    """
    logging.info("商品調達タスクを開始します。")

    keywords_data = get_keywords_from_file()
    include_keywords = keywords_data.get("include_keywords", [])
    exclude_keywords = keywords_data.get("exclude_keywords", [])

    if not include_keywords:
        logging.warning("「含めるキーワード」が登録されていません。商品調達をスキップします。")
        return

    # 除外キーワードを検索クエリ用に整形（例: " -除外1 -除外2"）
    exclude_query_part = " ".join([f"-{kw}" for kw in exclude_keywords])

    all_new_products = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for keyword in include_keywords:
            try:
                search_query = f"{keyword} {exclude_query_part}".strip()
                logging.info(f"キーワード「{search_query}」で商品を検索します。")
                
                # ここに、指定したキーワードで楽天市場などを検索し、
                # 商品名、URL、画像URLをスクレイピングするロジックを実装します。
                # 以下はダミーの処理です。
                # new_products = scrape_rakuten(page, search_query)
                # all_new_products.extend(new_products)

            except Exception as e:
                logging.error(f"キーワード「{keyword}」の処理中にエラーが発生しました: {e}")
        
        browser.close()

    if all_new_products:
        inserted_count = import_products(all_new_products)
        logging.info(f"{len(all_new_products)}件の商品を調達し、{inserted_count}件を新規にDBへ保存しました。")
    else:
        logging.info("調達対象の新しい商品はありませんでした。")

    logging.info("商品調達タスクを終了します。")