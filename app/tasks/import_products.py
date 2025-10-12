import logging
from urllib.parse import urlparse, parse_qs
from app.core.database import add_product_if_not_exists, DB_FILE
import sqlite3

def get_existing_product_urls():
    """データベースに登録されているすべての商品のURLをセットで返す。"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT url FROM products WHERE url IS NOT NULL")
            return {row[0] for row in cursor.fetchall()}
    except sqlite3.Error as e:
        logging.error(f"既存のURL取得中にDBエラーが発生しました: {e}")
        return set()
# このマップは商品データのキーとDBカラムを対応付ける
PRODUCT_DATA_MAP = {
    'item_description': 'name',
    'page_url': 'url',
    'image_url': 'image_url',
    'procurement_keyword': 'procurement_keyword',
}

def process_and_import_products(items: list) -> tuple[int, int]:
    """
    商品アイテムのリストを受け取り、DBに保存する共通処理関数。
    :param items: 商品情報の辞書のリスト
    :return: (新規追加件数, スキップ件数) のタプル
    """
    logging.info(f"商品登録処理を開始します。対象件数: {len(items)}件")
    added_count = 0
    skipped_count = 0

    for i, item in enumerate(items):
        product_name_for_log = item.get('item_description', 'N/A')[:40]
        logging.info(f"  [{i+1}/{len(items)}] 商品「{product_name_for_log}...」を処理中...")
        product_data = {}
        for json_key, db_column in PRODUCT_DATA_MAP.items():
            value = item.get(json_key)
            # 楽天の検索リダイレクトURLを実際のitem.rakuten.co.jpのURLに変換する
            if db_column == 'url' and value and 'rat-redirect' in value:
                try:
                    parsed_url = urlparse(value)
                    query_params = parse_qs(parsed_url.query)
                    product_data[db_column] = query_params.get('dest', [None])[0]
                except (IndexError, TypeError):
                    product_data[db_column] = None
            else:
                product_data[db_column] = value
        
        if add_product_if_not_exists(**product_data):
            logging.info(f"    -> [追加] 新規商品としてデータベースに登録しました。")
            added_count += 1
        else:
            logging.info(f"    -> [スキップ] この商品は既にデータベースに存在します。")
            skipped_count += 1
    
    return added_count, skipped_count