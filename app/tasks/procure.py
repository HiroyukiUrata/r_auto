import logging
import json
from urllib.parse import urlparse, parse_qs
from app.core.database import add_product_if_not_exists
from app.tasks.get_post_url import get_post_url

# 仮JSONの属性とDBカラム名のマッピング
TEMP_JSON_TO_DB_MAP = {
    'item_description': 'name',      # 商品説明 -> name
    'page_url': 'url',               # 商品ページURL -> url
    'image_url': 'image_url',        # 画像URL -> image_url
}

def procure_products():
    """
    商品情報を取得し、在庫（データベース）に保存する。
    現在は暫定的にJSONデータをソースとしているが、将来的には楽天APIからの取得を想定。
    """
    logging.info("商品調達タスクを開始します。")

    # 楽天APIからのレスポンスを想定した仮のJSONデータ
    temp_json_data = """
    [
      {
        "item_description": "【全品対象クーポン配布中】 壁紙の上に塗れるペンキ イマジン ウォール ペイント 4L (水性塗料) 道具セット SHE くすみカラー 塗装 壁・天井・屋内木部用 約24〜28平米 ※サンプル確認必須 ※メーカー直送商品",
        "image_url": "https://tshop.r10s.jp/kabegamiyahonpo/cabinet/paint2/rkpk-tn-she-40s-sh.jpg?fitin=275:275",
        "page_url": "https://search.rakuten.co.jp/rat-redirect?dest=https%3A%2F%2Fitem.rakuten.co.jp%2Fkabegamiyahonpo%2Frkpk-tn-shep-40s%2F"
      },
      {
        "item_description": "【本日クーポン5%引】 くすみカラーにRENEW コンパクト ソファー 2人掛け 2way ソファ 2Pソファ 2Pソファーリビングソファー コンパクトソファー コンパクトソファ 省スペース シンプル おしゃれ かわいい 二人掛け 一人暮らし グレー ベージュ ブラウン",
        "image_url": "https://tshop.r10s.jp/tansu/cabinet/sofa7/31200014_10w.jpg?fitin=275:275",
        "page_url": "https://search.rakuten.co.jp/rat-redirect?dest=https%3A%2F%2Fitem.rakuten.co.jp%2Ftansu%2F31200014%2F"
      }
    ]
    """

    try:
        items = json.loads(temp_json_data)
    except json.JSONDecodeError as e:
        logging.error(f"商品データのJSON解析に失敗しました: {e}")
        return

    added_count = 0
    for item in items:
        product_data = {}
        for json_key, db_column in TEMP_JSON_TO_DB_MAP.items():
            value = item.get(json_key)
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
            logging.info(f"  -> 追加: {product_data.get('name', 'N/A')[:40]}...")
            added_count += 1

    logging.info(f"商品調達タスクを終了します。新規追加: {added_count}件")

    if added_count > 0:
        logging.info("--- 商品調達が完了。続けて投稿URL取得を開始します ---")
        get_post_url()
        logging.info("--- 投稿URL取得が完了しました ---")