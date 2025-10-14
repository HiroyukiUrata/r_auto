import logging
from app.core.database import add_product_if_not_exists

def process_and_import_products(products_data: list[dict]) -> tuple[int, int]:
    """
    商品データのリストを受け取り、1件ずつDBに登録を試みる。
    URLが重複しているデータはスキップされる。
    :param products_data: 商品データの辞書のリスト
    :return: (新規追加された件数, スキップされた件数) のタプル
    """
    added_count = 0
    skipped_count = 0
    for product in products_data:
        if add_product_if_not_exists(
            name=product.get("item_description"),
            url=product.get("page_url"),
            image_url=product.get("image_url"),
            procurement_keyword=product.get("procurement_keyword")
        ):
            added_count += 1
        else:
            skipped_count += 1
    return added_count, skipped_count