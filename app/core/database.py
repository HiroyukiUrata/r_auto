import sqlite3
import logging
import os
import json

DB_FILE = "db/products.db"
KEYWORDS_FILE = "db/keywords.json"


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
            cursor.execute('''CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE, image_url TEXT, post_url TEXT, ai_caption TEXT, procurement_keyword TEXT, status TEXT NOT NULL DEFAULT '生情報取得', error_message TEXT, created_at TIMESTAMP, post_url_updated_at TIMESTAMP, ai_caption_created_at TIMESTAMP, posted_at TIMESTAMP)''')
            logging.info("新しい 'products' テーブルを作成しました。")
            # 古いテーブルから新しいテーブルへデータをコピー（重複URLは無視される）
            cursor.execute("INSERT OR IGNORE INTO products(id, name, url, image_url, post_url, ai_caption, procurement_keyword, status, created_at, post_url_updated_at, ai_caption_created_at, posted_at) SELECT id, name, url, image_url, post_url, ai_caption, NULL, status, created_at, post_url_updated_at, ai_caption_created_at, posted_at FROM products_old")
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
                procurement_keyword TEXT,
                ai_caption TEXT,
                status TEXT NOT NULL DEFAULT '生情報取得', -- 生情報取得, URL取得済, 投稿文作成済, 投稿準備完了, 投稿済, エラー
                error_message TEXT,
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
            # 既存のレコードには、他のタイムスタンプから推測できる最も古い日時を設定
            cursor.execute("UPDATE products SET created_at = COALESCE(post_url_updated_at, ai_caption_created_at, posted_at, CURRENT_TIMESTAMP) WHERE created_at IS NULL")
        if 'post_url' not in columns:
            cursor.execute("ALTER TABLE products ADD COLUMN post_url TEXT")
            logging.info("productsテーブルに 'post_url' カラムを追加しました。")
        if 'post_url_updated_at' not in columns:
            cursor.execute("ALTER TABLE products ADD COLUMN post_url_updated_at TIMESTAMP")
            cursor.execute("UPDATE products SET post_url_updated_at = COALESCE(ai_caption_created_at, posted_at) WHERE post_url_updated_at IS NULL AND post_url IS NOT NULL")
            logging.info("productsテーブルに 'post_url_updated_at' カラムを追加しました。")
        if 'ai_caption' not in columns:
            cursor.execute("ALTER TABLE products ADD COLUMN ai_caption TEXT")
            logging.info("productsテーブルに 'ai_caption' カラムを追加しました。")
        if 'ai_caption_created_at' not in columns:
            cursor.execute("ALTER TABLE products ADD COLUMN ai_caption_created_at TIMESTAMP")
            cursor.execute("UPDATE products SET ai_caption_created_at = posted_at WHERE ai_caption_created_at IS NULL AND ai_caption IS NOT NULL")
            logging.info("productsテーブルに 'ai_caption_created_at' カラムを追加しました。")
        if 'posted_at' not in columns:
            cursor.execute("ALTER TABLE products ADD COLUMN posted_at TIMESTAMP")
            logging.info("productsテーブルに 'posted_at' カラムを追加しました。")
        if 'procurement_keyword' not in columns:
            cursor.execute("ALTER TABLE products ADD COLUMN procurement_keyword TEXT")
            logging.info("productsテーブルに 'procurement_keyword' カラムを追加しました。")
        if 'error_message' not in columns:
            cursor.execute("ALTER TABLE products ADD COLUMN error_message TEXT")
            logging.info("productsテーブルに 'error_message' カラムを追加しました。")

        conn.commit()
        conn.close()
        logging.info("データベースが正常に初期化されました。")
    except sqlite3.Error as e:
        logging.error(f"データベース初期化エラー: {e}")

def get_error_products_in_last_24h():
    """過去24時間以内に作成され、かつステータスが「エラー」の商品を取得する"""
    from datetime import datetime, timedelta
    conn = get_db_connection()
    cur = conn.cursor()
    # created_atが24時間前より新しい、かつstatusが'エラー'のものを取得
    twenty_four_hours_ago = datetime.now() - timedelta(hours=24)

    query = "SELECT * FROM products WHERE status = 'エラー' AND created_at >= ? ORDER BY created_at DESC"
    params = (twenty_four_hours_ago,)

    # logging.info(f"エラー商品取得クエリ実行: query='{query}', params={params}")

    cur.execute(query, params)
    products = [dict(row) for row in cur.fetchall()]
    conn.close()
    # logging.info(f"クエリ結果: {len(products)}件のエラー商品を取得しました。")
    return products

def get_all_ready_to_post_products(limit=None):
    """ステータスが「投稿準備完了」の商品をすべて、または指定された件数だけ取得する"""
    query = "SELECT * FROM products WHERE status = '投稿準備完了' ORDER BY created_at"
    if limit:
        query += f" LIMIT {int(limit)}"
    conn = get_db_connection()
    products = conn.execute(query).fetchall()
    conn.close()
    return products

def get_product_by_id(product_id):
    """指定されたIDの商品を1件取得する"""
    query = "SELECT * FROM products WHERE id = ?"
    conn = get_db_connection()
    product = conn.execute(query, (product_id,)).fetchone()
    conn.close()
    return dict(product) if product else None

def get_all_inventory_products():
    """在庫確認ページ用に、「投稿済」「エラー」以外の商品をすべて取得する"""
    query = "SELECT * FROM products WHERE status NOT IN ('投稿済', 'エラー') ORDER BY created_at DESC"
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

def get_product_count_by_status():
    """ステータスごとの商品数を取得する"""
    query = "SELECT status, COUNT(*) as count FROM products GROUP BY status"
    conn = get_db_connection()
    counts = conn.execute(query).fetchall()
    conn.close()
    # sqlite3.Rowを辞書に変換
    return {row['status']: row['count'] for row in counts}

def update_product_status(product_id, status, error_message=None):
    """商品のステータスを更新する。エラーの場合はエラーメッセージも保存する。"""
    conn = get_db_connection()
    try:
        if status == '投稿済':
            # 投稿済みにする際は、投稿完了日時も記録する
            conn.execute("UPDATE products SET status = ?, posted_at = CURRENT_TIMESTAMP, error_message = NULL WHERE id = ?", (status, product_id))
        elif status == 'エラー':
            conn.execute("UPDATE products SET status = ?, error_message = ? WHERE id = ?", (status, str(error_message), product_id))
        else:
            # エラーから復帰させる場合などはエラーメッセージをクリアする
            conn.execute("UPDATE products SET status = ?, error_message = NULL WHERE id = ?", (status, product_id))
        conn.commit()
        logging.info(f"商品ID: {product_id} のステータスを「{status}」に更新しました。")
    except sqlite3.Error as e:
        logging.error(f"商品ID: {product_id} のステータス更新中にエラーが発生しました: {e}")
    finally:
        conn.close()

def update_status_for_multiple_products(product_ids: list[int], status: str):
    """複数の商品のステータスを一括で更新する"""
    if not product_ids:
        return 0
    conn = get_db_connection()
    try:
        placeholders = ','.join('?' for _ in product_ids)
        if status == '投稿済':
            query = f"UPDATE products SET status = ?, posted_at = CURRENT_TIMESTAMP, error_message = NULL WHERE id IN ({placeholders})"
            params = [status] + product_ids
        else:
            query = f"UPDATE products SET status = ?, error_message = NULL WHERE id IN ({placeholders})"
            params = [status] + product_ids
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        logging.info(f"{len(product_ids)}件の商品のステータスを「{status}」に更新しました。")
        return cursor.rowcount
    finally:
        conn.close()

def get_all_keywords() -> list[dict]:
    """
    JSONファイルからすべてのキーワードを読み込み、辞書のリストとして返す。
    :return: [{'keyword': 'キーワード1'}, {'keyword': 'キーワード2'}, ...] の形式のリスト
    """
    if not os.path.exists(KEYWORDS_FILE):
        logging.warning(f"キーワードファイルが見つかりません: {KEYWORDS_FILE}")
        return []

    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        keywords_a = data.get("keywords_a", [])
        keywords_b = data.get("keywords_b", [])
        
        all_keywords = keywords_a + keywords_b
        
        # 辞書のリスト形式に変換して返す
        return [{"keyword": kw} for kw in all_keywords if kw]
    except (IOError, json.JSONDecodeError) as e:
        logging.error(f"キーワードファイルの読み込みまたは解析に失敗しました: {e}")
        return []

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

def add_product_if_not_exists(name=None, url=None, image_url=None, procurement_keyword=None):
    """同じURLの商品が存在しない場合のみ、新しい商品をDBに追加する。調達キーワードも保存する。"""
    if not name or not url:
        logging.warning("商品名またはURLが不足しているため、DBに追加できません。")
        return False

    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO products (name, url, image_url, procurement_keyword, status) VALUES (?, ?, ?, ?, '生情報取得')",
                       (name, url, image_url, procurement_keyword))
        conn.commit()
        return True # 新規追加成功
    except sqlite3.IntegrityError:
        logging.debug(f"URLが重複しているため、商品は追加されませんでした: {url}")
        return False  # 既に存在する
    finally:
        conn.close()

def product_exists_by_url(url: str) -> bool:
    """指定されたURLの商品がデータベースに存在するかどうかをチェックする。"""
    if not url:
        return False
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM products WHERE url = ? LIMIT 1", (url,))
        return cursor.fetchone() is not None
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
        (p.get('name'), p.get('url'), p.get('image_url'), p.get('procurement_keyword')) for p in products_data if p.get('name') and p.get('url')
    ]

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.executemany("INSERT OR IGNORE INTO products (name, url, image_url, procurement_keyword, status, created_at) VALUES (?, ?, ?, ?, '生情報取得', CURRENT_TIMESTAMP)", records_to_insert)
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

def delete_multiple_products(product_ids: list[int]):
    """指定されたIDの複数の商品を一括で削除する"""
    if not product_ids:
        return 0
    conn = get_db_connection()
    try:
        placeholders = ','.join('?' for _ in product_ids)
        query = f"DELETE FROM products WHERE id IN ({placeholders})"
        cursor = conn.cursor()
        cursor.execute(query, product_ids)
        conn.commit()
        logging.info(f"{len(product_ids)}件の商品を削除しました。")
        return cursor.rowcount
    finally:
        conn.close()