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

        # --- URLにUNIQUE制約があるか確認し、なければテーブルを再構築する ---
        is_url_unique = False
        # PRAGMA index_listはテーブルのインデックス情報を返す
        # UNIQUE制約は自動的にユニークインデックスを作成する
        cursor.execute("PRAGMA index_list(products)")
        for index in cursor.fetchall():
            if index['unique']:
                # そのユニークインデックスがどのカラムに対するものか確認
                cursor.execute(f"PRAGMA index_info({index['name']})")
                for col in cursor.fetchall():
                    if col['name'] == 'url':
                        is_url_unique = True
                        break
            if is_url_unique:
                break
        
        if not is_url_unique:
            logging.warning("productsテーブルのurlカラムにUNIQUE制約がありません。テーブルを再構築します。")
            cursor.execute("ALTER TABLE products RENAME TO products_old")
            logging.info("既存のテーブルを 'products_old' にリネームしました。")
            # 新しいテーブルを作成（init_dbの後半で再度実行されるが、ここで定義が必要）
            cursor.execute('''CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE, image_url TEXT, post_url TEXT, ai_caption TEXT, status TEXT NOT NULL DEFAULT '生情報取得', created_at TIMESTAMP, post_url_updated_at TIMESTAMP, ai_caption_created_at TIMESTAMP, posted_at TIMESTAMP)''')
            logging.info("新しい 'products' テーブルを作成しました。")
            # 古いテーブルから新しいテーブルへデータをコピー（重複URLは無視される）
            cursor.execute("INSERT OR IGNORE INTO products(id, name, url, image_url, post_url, ai_caption, status, created_at, post_url_updated_at, ai_caption_created_at, posted_at) SELECT id, name, url, image_url, post_url, ai_caption, status, created_at, post_url_updated_at, ai_caption_created_at, posted_at FROM products_old")
            logging.info("データを新しいテーブルにコピーしました。")
            cursor.execute("DROP TABLE products_old")
            logging.info("'products_old' テーブルを削除しました。")

        # productsテーブルが存在しない場合のみ作成
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, -- 商品キャプション
                url TEXT NOT NULL UNIQUE,
                image_url TEXT,
                post_url TEXT,
                ai_caption TEXT,
                status TEXT NOT NULL DEFAULT '生情報取得', -- 生情報取得, URL取得済, 投稿文作成済, 投稿準備完了, 投稿済, エラー
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                post_url_updated_at TIMESTAMP,
                ai_caption_created_at TIMESTAMP,
                posted_at TIMESTAMP
            )
        ''')

        # --- カラム存在チェックと追加（マイグレーション処理） ---
        # 他の処理よりも先に実行することで、古いDBスキーマでもエラーなく動作するようにする
        cursor.execute("PRAGMA table_info(products)")
        columns = [row['name'] for row in cursor.fetchall()]
        if 'image_url' not in columns:
            cursor.execute("ALTER TABLE products ADD COLUMN image_url TEXT")
        if 'created_at' not in columns:
            # SQLiteの古いバージョンはALTER TABLEでの動的デフォルト値をサポートしないため、2段階で追加
            cursor.execute("ALTER TABLE products ADD COLUMN created_at TIMESTAMP")
            cursor.execute("UPDATE products SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
        if 'post_url' not in columns:
            cursor.execute("ALTER TABLE products ADD COLUMN post_url TEXT")
            logging.info("productsテーブルに 'post_url' カラムを追加しました。")
        if 'post_url_updated_at' not in columns:
            cursor.execute("ALTER TABLE products ADD COLUMN post_url_updated_at TIMESTAMP")
            logging.info("productsテーブルに 'post_url_updated_at' カラムを追加しました。")
        if 'ai_caption' not in columns:
            cursor.execute("ALTER TABLE products ADD COLUMN ai_caption TEXT")
            logging.info("productsテーブルに 'ai_caption' カラムを追加しました。")
        if 'ai_caption_created_at' not in columns:
            cursor.execute("ALTER TABLE products ADD COLUMN ai_caption_created_at TIMESTAMP")
            logging.info("productsテーブルに 'ai_caption_created_at' カラムを追加しました。")
        if 'posted_at' not in columns:
            cursor.execute("ALTER TABLE products ADD COLUMN posted_at TIMESTAMP")
            logging.info("productsテーブルに 'posted_at' カラムを追加しました。")

        conn.commit()
        conn.close()
        logging.info("データベースが正常に初期化されました。")
    except sqlite3.Error as e:
        logging.error(f"データベース初期化エラー: {e}")

def get_all_ready_to_post_products(limit=None):
    """ステータスが「投稿準備完了」の商品をすべて、または指定された件数だけ取得する"""
    query = "SELECT * FROM products WHERE status = '投稿準備完了' ORDER BY created_at"
    if limit:
        query += f" LIMIT {int(limit)}"
    conn = get_db_connection()
    products = conn.execute(query).fetchall()
    conn.close()
    return products

def get_all_inventory_products():
    """在庫確認ページ用に、「投稿済」以外の商品をすべて取得する"""
    query = "SELECT * FROM products WHERE status != '投稿済' ORDER BY created_at DESC"
    conn = get_db_connection()
    products = conn.execute(query).fetchall()
    conn.close()
    return products

def get_products_for_post_url_acquisition(limit=None):
    """投稿URL取得対象（ステータスが「生情報取得」）の商品を取得する"""
    query = "SELECT * FROM products WHERE status = '生情報取得' AND (post_url IS NULL OR post_url = '') ORDER BY created_at"
    if limit:
        query += f" LIMIT {int(limit)}"
    conn = get_db_connection()
    products = conn.execute(query).fetchall()
    conn.close()
    return products

def get_products_for_caption_creation(limit=None):
    """投稿文作成対象（ステータスが「URL取得済」）の商品を取得する"""
    query = "SELECT * FROM products WHERE status = 'URL取得済' ORDER BY created_at"
    if limit:
        query += f" LIMIT {int(limit)}"
    conn = get_db_connection()
    products = conn.execute(query).fetchall()
    conn.close()
    return products

def get_products_count_for_caption_creation():
    """投稿文作成対象（ステータスが「URL取得済」）の商品件数を取得する"""
    query = "SELECT COUNT(*) FROM products WHERE status = 'URL取得済'"
    conn = get_db_connection()
    count = conn.execute(query).fetchone()[0]
    conn.close()
    return count

def update_product_status(product_id, status):
    """商品のステータスを更新する"""
    conn = get_db_connection()
    try:
        if status == '投稿済':
            # 投稿済みにする際は、投稿完了日時も記録する
            conn.execute("UPDATE products SET status = ?, posted_at = CURRENT_TIMESTAMP WHERE id = ?", (status, product_id))
        else:
            conn.execute("UPDATE products SET status = ? WHERE id = ?", (status, product_id))
        conn.commit()
        logging.info(f"商品ID: {product_id} のステータスを「{status}」に更新しました。")
    except sqlite3.Error as e:
        logging.error(f"商品ID: {product_id} のステータス更新中にエラーが発生しました: {e}")
    finally:
        conn.close()

def update_post_url(product_id, post_url):
    """指定された商品の投稿URLと更新日時を更新し、ステータスを「URL取得済」に変更する"""
    conn = get_db_connection()
    try:
        conn.execute("UPDATE products SET post_url = ?, post_url_updated_at = CURRENT_TIMESTAMP, status = 'URL取得済' WHERE id = ?", (post_url, product_id))
        conn.commit()
        logging.info(f"商品ID: {product_id} の投稿URLを更新し、ステータスを「URL取得済」に変更しました。")
    finally:
        conn.close()

def update_ai_caption(product_id, caption):
    """指定された商品のAI投稿文と更新日時を更新し、ステータスを「投稿準備完了」に変更する"""
    conn = get_db_connection()
    try:
        conn.execute("UPDATE products SET ai_caption = ?, ai_caption_created_at = CURRENT_TIMESTAMP, status = '投稿準備完了' WHERE id = ?", (caption, product_id))
        conn.commit()
        logging.info(f"商品ID: {product_id} のAI投稿文を更新し、ステータスを「投稿準備完了」に変更しました。")
    finally:
        conn.close()

def add_product_if_not_exists(name=None, url=None, image_url=None):
    """同じURLの商品が存在しない場合のみ、新しい商品をDBに追加する"""
    if not name or not url:
        logging.warning("商品名またはURLが不足しているため、DBに追加できません。")
        return False

    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO products (name, url, image_url, status) VALUES (?, ?, ?, '生情報取得')",
                       (name, url, image_url))
        conn.commit()
        return True # 新規追加成功
    except sqlite3.IntegrityError:
        logging.debug(f"URLが重複しているため、商品は追加されませんでした: {url}")
        return False  # 既に存在する
    finally:
        conn.close()

def import_products(products_data: list[dict]):
    """
    複数の商品データを一括でデータベースにインポートする。
    URLが重複しているデータは無視される。
    """
    if not products_data:
        return 0

    # executemany用に、辞書のリストをタプルのリストに変換
    records_to_insert = [
        (p.get('name'), p.get('url'), p.get('image_url')) for p in products_data
    ]

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.executemany("INSERT OR IGNORE INTO products (name, url, image_url, status) VALUES (?, ?, ?, '生情報取得')", records_to_insert)
        conn.commit()
        return cursor.rowcount # 実際に挿入された行数を返す
    finally:
        conn.close()

def delete_all_products():
    """
    productsテーブルからすべてのレコードを削除する。
    :return: 削除された行数
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM products")
        conn.commit()
        logging.info("すべての商品レコードが削除されました。")
        return cursor.rowcount
    finally:
        conn.close()

def delete_product(product_id: int):
    """指定されたIDの商品を削除する"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
        conn.commit()
        logging.info(f"商品ID: {product_id} を削除しました。")
        return cursor.rowcount > 0
    finally:
        conn.close()