import sqlite3
import logging

DB_FILE = "db/products.db"

def get_db_connection():
    """データベース接続を取得する"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """データベースを初期化し、テーブルを作成する"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # productsテーブルが存在しない場合のみ作成
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT '未' -- '未' or '済'
            )
        ''')
        # テーブルが空の場合のみサンプルデータを挿入
        cursor.execute("SELECT COUNT(*) FROM products")
        if cursor.fetchone()[0] == 0:
            logging.info("サンプルデータを挿入します。")
            # ↓↓↓ このURLを実際の楽天ROOMの商品コレ！ページのURLに書き換えてください
            # cursor.execute("INSERT INTO products (name, url, status) VALUES (?, ?, ?)",
            #                ('【プレステラプレミアム75  スリット鉢 くすみカラー', 'https://room.rakuten.co.jp/mix?itemcode=kaju%3A10002307&scid=we_room_upc60', '未'))
            # cursor.execute("INSERT INTO products (name, url, status) VALUES (?, ?, ?)",
            #                ('👦「あ、またこの植木鉢トレーだ！本当に人気なんだね！キャスターがついてるのが魅力的だなぁ！」', 'https://room.rakuten.co.jp/mix?itemcode=roughral%3A10004105&scid=we_room_upc60', '未'))
            cursor.execute("INSERT INTO products (name, url, status) VALUES (?, ?, ?)",
                           ('【新規追加】おしゃれな照明器具', 'https://room.rakuten.co.jp/mix?itemcode=kaju%3A10002307&scid=we_room_upc60L', '未'))
        conn.commit()
        conn.close()
        logging.info("データベースが正常に初期化されました。")
    except sqlite3.Error as e:
        logging.error(f"データベース初期化エラー: {e}")

def get_unposted_products():
    """ステータスが「未」の商品を1件取得する"""
    conn = get_db_connection()
    product = conn.execute("SELECT * FROM products WHERE status = '未' LIMIT 1").fetchone()
    conn.close()
    return product

def update_product_status(product_id, status):
    """商品のステータスを更新する"""
    conn = get_db_connection()
    conn.execute("UPDATE products SET status = ? WHERE id = ?", (status, product_id))
    conn.commit()
    conn.close()
    logging.info(f"商品ID: {product_id} のステータスを「{status}」に更新しました。")