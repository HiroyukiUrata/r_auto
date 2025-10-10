import logging
import json
import os
from urllib.parse import urlparse, parse_qs
from app.core.database import import_products

IMPORT_FILE_PATH = "db/import_products.json"

# インポートするJSONのキーとDBカラム名のマッピング
JSON_TO_DB_MAP = {
    'item_description': 'name',
    'page_url': 'url',
    'image_url': 'image_url',
}

def process_and_import_products(items: list) -> int:
    """
    商品アイテムのリストを受け取り、解析してデータベースにインポートする。
    :param items: 商品情報の辞書を含むリスト
    :return: 実際にインポートされた商品の件数
    """
    products_to_import = []
    for item in items:
        product_data = {}
        for json_key, db_column in JSON_TO_DB_MAP.items():
            value = item.get(json_key)
            
            # page_urlはリダイレクト用なので、実際のリンクを抽出
            if db_column == 'url' and value and 'rat-redirect' in value:
                try:
                    parsed_url = urlparse(value)
                    query_params = parse_qs(parsed_url.query)
                    actual_url = query_params.get('dest', [None])[0]
                    product_data[db_column] = actual_url
                except Exception:
                    product_data[db_column] = None
            else:
                product_data[db_column] = value
        
        if product_data.get('name') and product_data.get('url'):
            products_to_import.append(product_data)

    if not products_to_import:
        return 0

    return import_products(products_to_import)

def import_products_from_file():
    """
    db/import_products.json ファイルから商品データを一括でインポートする。
    """
    logging.info(f"商品インポートタスクを開始します。ファイル: {IMPORT_FILE_PATH}")

    if not os.path.exists(IMPORT_FILE_PATH):
        logging.error(f"インポートファイルが見つかりません: {IMPORT_FILE_PATH}")
        return

    try:
        with open(IMPORT_FILE_PATH, "r", encoding="utf-8") as f:
            items = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logging.error(f"ファイルの読み込みまたはJSONの解析に失敗しました: {e}")
        return

    if not items:
        logging.warning("インポート対象の商品データが見つかりませんでした。")
        return

    inserted_count = process_and_import_products(items)
    logging.info(f"商品インポートタスクが完了しました。{len(items)}件中、{inserted_count}件の新規商品をインポートしました。")