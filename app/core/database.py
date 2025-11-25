import sqlite3
import logging
import os
import math
from urllib.parse import urlparse, parse_qs
import json
from datetime import datetime, timezone, timedelta, time

DB_FILE = "db/products.db"
KEYWORDS_FILE = "db/keywords.json"


def get_db_connection():
    """データベース接続を取得する"""
    # データベースファイルが格納されるディレクトリの存在を確認し、なければ作成する
    db_dir = os.path.dirname(DB_FILE)
    os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """データベースを初期化し、テーブルを作成する"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 最初にproductsテーブルが存在しない場合を作成する
        # これにより、DBファイルがなくても後続のPRAGMA文でエラーが発生しなくなる
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, -- 商品キャプション
                url TEXT NOT NULL, -- UNIQUE制約は後で確認・適用する
                image_url TEXT,
                post_url TEXT,
                room_url TEXT,
                shop_name TEXT,
                procurement_keyword TEXT, -- どこから調達したかを示すキーワード
                ai_caption TEXT,
                status TEXT NOT NULL DEFAULT '生情報取得', -- 生情報取得, URL取得済, 投稿文作成済, 投稿準備完了, 投稿済, エラー
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                post_url_updated_at TIMESTAMP,
                ai_caption_created_at TIMESTAMP,
                posted_at TIMESTAMP
            )
        ''')

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
            logging.debug("既存のテーブルを 'products_old' にリネームしました。")
            cursor.execute('''CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE, image_url TEXT, post_url TEXT, room_url TEXT, shop_name TEXT, ai_caption TEXT, procurement_keyword TEXT, status TEXT NOT NULL DEFAULT '生情報取得', error_message TEXT, created_at TIMESTAMP, post_url_updated_at TIMESTAMP, ai_caption_created_at TIMESTAMP, posted_at TIMESTAMP)''')
            logging.debug("新しい 'products' テーブルを作成しました。")
            # 古いテーブルから新しいテーブルへデータをコピー（重複URLは無視される）
            cursor.execute("INSERT OR IGNORE INTO products(id, name, url, image_url, post_url, room_url, ai_caption, procurement_keyword, status, error_message, created_at, post_url_updated_at, ai_caption_created_at, posted_at) SELECT id, name, url, image_url, post_url, NULL, ai_caption, procurement_keyword, status, error_message, created_at, post_url_updated_at, ai_caption_created_at, posted_at FROM products_old")
            logging.debug("データを新しいテーブルにコピーしました。")
            cursor.execute("DROP TABLE products_old")
            logging.debug("'products_old' テーブルを削除しました。")

        # --- カラム存在チェックと追加（マイグレーション処理） ---
        # 他の処理よりも先に実行することで、古いDBスキーマでもエラーなく動作するようにする
        def add_column_if_not_exists(cursor, column_name, column_type, update_query=None):
            cursor.execute("PRAGMA table_info(products)")
            columns = [row['name'] for row in cursor.fetchall()]
            if column_name not in columns:
                try:
                    cursor.execute(f"ALTER TABLE products ADD COLUMN {column_name} {column_type}")
                    if update_query:
                        cursor.execute(update_query)
                    logging.debug(f"productsテーブルに '{column_name}' カラムを追加しました。")
                except sqlite3.Error as e:
                    logging.error(f"'{column_name}' カラムの追加に失敗しました: {e}")

        # --- user_engagementテーブルのマイグレーション ---
        def add_column_to_engagement_if_not_exists(cursor, column_name, column_type):
            cursor.execute("PRAGMA table_info(user_engagement)")
            columns = [row['name'] for row in cursor.fetchall()]
            if column_name not in columns:
                try:
                    cursor.execute(f"ALTER TABLE user_engagement ADD COLUMN {column_name} {column_type}")
                    logging.debug(f"user_engagementテーブルに '{column_name}' カラムを追加しました。")
                except sqlite3.Error as e:
                    logging.error(f"'{column_name}' カラムの追加に失敗しました: {e}")

        # タイプミスを修正し、重複していた行を削除
        add_column_if_not_exists(cursor, 'post_url', 'TEXT')

        add_column_if_not_exists(cursor, 'image_url', 'TEXT')
        add_column_if_not_exists(cursor, 'created_at', 'TIMESTAMP', 
                                 "UPDATE products SET created_at = COALESCE(post_url_updated_at, ai_caption_created_at, posted_at, CURRENT_TIMESTAMP) WHERE created_at IS NULL")
        add_column_if_not_exists(cursor, 'post_url_updated_at', 'TIMESTAMP', 
                                 "UPDATE products SET post_url_updated_at = COALESCE(ai_caption_created_at, posted_at) WHERE post_url_updated_at IS NULL AND post_url IS NOT NULL")
        add_column_if_not_exists(cursor, 'ai_caption', 'TEXT')
        add_column_if_not_exists(cursor, 'ai_caption_created_at', 'TIMESTAMP', 
                                 "UPDATE products SET ai_caption_created_at = posted_at WHERE ai_caption_created_at IS NULL AND ai_caption IS NOT NULL")
        add_column_if_not_exists(cursor, 'posted_at', 'TIMESTAMP')
        add_column_if_not_exists(cursor, 'procurement_keyword', 'TEXT')
        add_column_if_not_exists(cursor, 'error_message', 'TEXT')

        # 優先度カラムを追加
        add_column_if_not_exists(cursor, 'priority', 'INTEGER', "UPDATE products SET priority = 0")
        add_column_if_not_exists(cursor, 'shop_name', 'TEXT')
        add_column_if_not_exists(cursor, 'room_url', 'TEXT')
        # `proNOWucts` のタイプミスがあった行は削除

        # --- user_engagement テーブルの作成 ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_engagement (
                id TEXT PRIMARY KEY,
                name TEXT,
                profile_page_url TEXT,
                profile_image_url TEXT,
                like_count INTEGER DEFAULT 0, -- 過去累計
                collect_count INTEGER DEFAULT 0, -- 過去累計
                comment_count INTEGER DEFAULT 0, -- 過去累計
                follow_count INTEGER DEFAULT 0, -- 過去累計
                is_following INTEGER, -- 0:未, 1:フォロー中
                latest_action_timestamp TEXT, -- 過去最新アクション日時
                recent_like_count INTEGER DEFAULT 0, -- 今セッション
                recent_collect_count INTEGER DEFAULT 0, -- 今セッション
                recent_comment_count INTEGER DEFAULT 0, -- 今セッション
                recent_follow_count INTEGER DEFAULT 0, -- 今セッション
                recent_action_timestamp TEXT, -- 今セッションの最新アクション日時
                comment_text TEXT,
                last_commented_at TEXT,
                ai_prompt_message TEXT,
                ai_prompt_updated_at TEXT,
                comment_generated_at TEXT,
                last_commented_post_url TEXT
            )
        ''')
        add_column_to_engagement_if_not_exists(cursor, 'last_engagement_error', 'TEXT')
        logging.debug("user_engagementテーブルが正常に初期化されました。")

        add_column_to_engagement_if_not_exists(cursor, 'ai_prompt_updated_at', 'TEXT')
        add_column_to_engagement_if_not_exists(cursor, 'comment_generated_at', 'TEXT')
        add_column_to_engagement_if_not_exists(cursor, 'recent_follow_count', 'INTEGER')
        add_column_to_engagement_if_not_exists(cursor, 'last_commented_post_url', 'TEXT')

        def add_column_to_my_post_comments_if_not_exists(cursor, column_name, column_type):
            cursor.execute("PRAGMA table_info(my_post_comments)")
            columns = [row['name'] for row in cursor.fetchall()]
            if column_name not in columns:
                try:
                    cursor.execute(f"ALTER TABLE my_post_comments ADD COLUMN {column_name} {column_type}")
                    logging.debug(f"my_post_commentsテーブルに '{column_name}' カラムを追加しました。")
                except sqlite3.Error as e:
                    logging.error(f"'{column_name}' カラムの追加に失敗しました: {e}")

        # --- my_post_comments テーブルの作成 ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS my_post_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_detail_url TEXT NOT NULL,
                user_page_url TEXT,
                user_name TEXT,
                user_image_url TEXT,
                comment_text TEXT,
                post_timestamp TEXT NOT NULL,
                reply_text TEXT,
                reply_generated_at TIMESTAMP,
                reply_posted_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                like_back_count INTEGER,
                last_like_back_at TIMESTAMP,
                UNIQUE (user_image_url, post_timestamp)
            )
        ''')
        logging.debug("my_post_commentsテーブルが正常に初期化されました。")

        # --- my_post_comments テーブルのマイグレーション ---
        # 過去のバージョンでDBが作成された場合でも、カラムがなければ追加する
        add_column_to_my_post_comments_if_not_exists(cursor, 'user_page_url', 'TEXT')
        add_column_to_my_post_comments_if_not_exists(cursor, 'user_image_url', 'TEXT')
        add_column_to_my_post_comments_if_not_exists(cursor, 'reply_generated_at', 'TIMESTAMP')
        add_column_to_my_post_comments_if_not_exists(cursor, 'reply_posted_at', 'TIMESTAMP')
        add_column_to_my_post_comments_if_not_exists(cursor, 'like_back_count', 'INTEGER')
        add_column_to_my_post_comments_if_not_exists(cursor, 'last_like_back_at', 'TIMESTAMP')

        # --- 既存タイムスタンプのフォーマットをISO 8601に統一するマイグレーション処理 ---
        # この処理は一度実行されると、次回以降は更新対象がなくなる
        timestamp_columns = ['created_at', 'post_url_updated_at', 'ai_caption_created_at', 'posted_at']
        for col in timestamp_columns:
            # 'YYYY-MM-DD HH:MM:SS' 形式のレコードを探す
            cursor.execute(f"SELECT id, {col} FROM products WHERE {col} LIKE '____-__-__ __:__:__'")
            records_to_update = cursor.fetchall()
            if records_to_update:
                logging.debug(f"'{col}' カラムの古いタイムスタンプ形式をISO 8601に変換します... (対象: {len(records_to_update)}件)")
                updates = []
                for row in records_to_update:
                    try:
                        # 文字列をdatetimeオブジェクトに変換し、ISO形式の文字列に再変換
                        dt_obj = datetime.strptime(row[col], '%Y-%m-%d %H:%M:%S')
                        updates.append((dt_obj.isoformat(), row['id']))
                    except (ValueError, TypeError):
                        continue # 不正な形式のデータはスキップ
                if updates:
                    cursor.executemany(f"UPDATE products SET {col} = ? WHERE id = ?", updates)


        conn.commit()
        conn.close()
        logging.debug("データベースが正常に初期化されました。")
    except sqlite3.Error as e:
        logging.error(f"データベース初期化エラー: {e}")
def get_all_error_products():
    """ステータスが「エラー」の商品をすべて取得する"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # ステータスが'エラー'のものをすべて取得し、作成日が新しい順にソート
    query = "SELECT * FROM products WHERE status = 'エラー' ORDER BY created_at DESC"
    cur.execute(query)
    products = [dict(row) for row in cur.fetchall()]
    conn.close()
    return products

def get_all_ready_to_post_products(limit=None):
    """ステータスが「投稿準備完了」の商品をすべて、または指定された件数だけ取得する"""
    # 投稿に必要な情報が確実に存在するもののみを対象とする
    query = """
        SELECT * FROM products WHERE status = '投稿準備完了' AND post_url IS NOT NULL AND ai_caption IS NOT NULL ORDER BY priority DESC, created_at
    """
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

def get_product_by_id(product_id: int):
    """指定されたIDの商品を1件取得する"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product = cursor.fetchone()
    conn.close()
    return dict(product) if product else None

def get_all_inventory_products():
    """在庫確認ページ用に、「投稿済」「エラー」「対象外」以外の商品をすべて取得する"""
    # 投稿準備が完了していない商品も在庫として表示するため、以前の絞り込みを解除
    query = """
        SELECT * FROM products WHERE status NOT IN ('投稿済', 'エラー', '対象外') ORDER BY priority DESC, created_at ASC
    """
    conn = get_db_connection()
    products = conn.execute(query).fetchall()
    conn.close()
    return products

def get_posted_products(page: int = 1, per_page: int = 30, search_term: str = None, start_date: datetime.date = None, end_date: datetime.date = None, room_url_unlinked: bool = False, shop_name: str = None):
    """
    投稿済の商品をページネーションと検索機能付きで取得する。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    where_clauses = ["status = '投稿済'"]
    params = []
    
    if search_term:
        where_clauses.append("(name LIKE ? OR ai_caption LIKE ?)")
        params.extend([f"%{search_term}%", f"%{search_term}%"])

    if start_date:
        where_clauses.append("posted_at >= ?")
        params.append(start_date)

    if end_date:
        # 終了日はその日の終わりまで含めるため、翌日の0時より前でフィルタリング
        end_datetime = datetime.combine(end_date, time(23, 59, 59, 999999))
        where_clauses.append("posted_at <= ?")
        params.append(end_datetime)

    if room_url_unlinked:
        where_clauses.append("(room_url IS NULL OR room_url = '')")

    if shop_name:
        where_clauses.append("shop_name = ?")
        params.append(shop_name)

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)
    
    # 総件数を取得
    count_query = f"SELECT COUNT(*) FROM products {where_sql}"
    cursor.execute(count_query, params)
    total_items = cursor.fetchone()[0]
    total_pages = math.ceil(total_items / per_page) if total_items > 0 else 1
    
    # データを取得
    offset = (page - 1) * per_page
    data_query = f"SELECT * FROM products {where_sql} ORDER BY posted_at DESC LIMIT ? OFFSET ?"
    data_params = params + [per_page, offset]
    
    cursor.execute(data_query, data_params)
    products = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return products, total_pages, total_items

def get_posted_product_shop_summary() -> list[dict]:
    """
    投稿済商品からショップごとの商品数を取得する。
    商品数が多い順にソートして返す。
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT shop_name, COUNT(*) as product_count 
            FROM products 
            WHERE status = '投稿済' AND shop_name IS NOT NULL AND shop_name != '' 
            GROUP BY shop_name 
            ORDER BY product_count DESC, shop_name ASC
        """)
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"ショップ別商品数の取得中にエラー: {e}")
        return []
    finally:
        conn.close()

def get_reusable_products():
    """
    再利用可能な商品をすべて取得する。
    対象:
    1. procurement_keyword が '再コレ再利用' の商品
    2. post_url があり、room_url がない商品 (投稿失敗の救済)
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""SELECT * FROM products WHERE procurement_keyword = '再コレ再利用'
           AND post_url IS NOT NULL AND post_url != '' AND (room_url IS NULL OR room_url = '')""")
        # sqlite3.Rowオブジェクトのリストを返す
        products = cursor.fetchall()
        return products
    finally:
        conn.close()


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
    """ステータスごとの商品数を取得する（「対象外」は除く）"""
    query = "SELECT status, COUNT(*) as count FROM products WHERE status != '対象外' GROUP BY status"
    conn = get_db_connection()
    counts = conn.execute(query).fetchall()
    conn.close()
    # sqlite3.Rowを辞書に変換
    return {row['status']: row['count'] for row in counts}

def update_product_status(product_id, status, error_message=None):
    """商品のステータスを更新する。エラーの場合はエラーメッセージも保存する。"""
    conn = get_db_connection()
    try:
        # JSTのタイムゾーンを定義
        jst = timezone(timedelta(hours=9))
        now_jst_iso = datetime.now(jst).isoformat()
        if status == '投稿済':
            # 投稿済みにする際は、投稿完了日時も記録する
            conn.execute("UPDATE products SET status = ?, posted_at = ?, error_message = NULL WHERE id = ?", (status, now_jst_iso, product_id))
        elif status == 'エラー':
            conn.execute("UPDATE products SET status = ?, error_message = ? WHERE id = ?", (status, str(error_message), product_id))
        else:
            # エラーから復帰させる場合などはエラーメッセージをクリアする
            conn.execute("UPDATE products SET status = ?, error_message = NULL WHERE id = ?", (status, product_id))
        conn.commit()
        if status == 'エラー':
            logging.info(f"商品ID: {product_id} のステータスを「{status}」に更新しました。")
        else:
            logging.debug(f"商品ID: {product_id} のステータスを「{status}」に更新しました。")
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
        # JSTのタイムゾーンを定義
        jst = timezone(timedelta(hours=9))
        now_jst_iso = datetime.now(jst).isoformat()
        if status == '投稿済':
            query = f"UPDATE products SET status = ?, posted_at = ?, error_message = NULL WHERE id IN ({placeholders})"
            params = [status, now_jst_iso] + product_ids
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

def recollect_product(product_id: int):
    """指定された商品を「投稿準備完了」ステータスに戻し、room_urlとposted_atをNULLにする"""
    conn = get_db_connection()
    try:
        conn.execute("UPDATE products SET status = '投稿準備完了', room_url = NULL, posted_at = NULL, error_message = NULL, priority = NULL WHERE id = ?", (product_id,))
        conn.commit()
        logging.info(f"商品ID: {product_id} を「再コレ」として更新しました。")
        return True
    except sqlite3.Error as e:
        logging.error(f"商品ID: {product_id} の再コレ処理中にエラーが発生しました: {e}")
        return False
    finally:
        conn.close()

def bulk_recollect_products(product_ids: list[int]):
    """複数の商品を一括で「投稿準備完了」ステータスに戻し、room_urlとposted_atをNULLにする"""
    if not product_ids:
        return 0
    conn = get_db_connection()
    try:
        placeholders = ','.join('?' for _ in product_ids)
        query = f"UPDATE products SET status = '投稿準備完了', room_url = NULL, posted_at = NULL, error_message = NULL, priority = NULL WHERE id IN ({placeholders})"
        cursor = conn.cursor()
        cursor.execute(query, product_ids)
        conn.commit()
        logging.debug(f"{len(product_ids)}件の商品を「再コレ」として一括更新しました。")
        return cursor.rowcount
    except sqlite3.Error as e:
        logging.error(f"商品の一括再コレ処理中にエラーが発生しました: {e}")
        return 0
    finally:
        conn.close()

def update_product_priority(product_id: int, priority: int):
    """商品の優先度を更新する"""
    conn = get_db_connection()
    conn.execute("UPDATE products SET priority = ? WHERE id = ?", (priority, product_id))
    conn.commit()
    conn.close()
    logging.debug(f"商品ID: {product_id} の優先度を {priority} に更新しました。")

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

def update_post_url(product_id, post_url, shop_name=None, new_main_url=None):
    """指定された商品の情報を更新し、ステータスを「URL取得済」に変更する"""
    conn = get_db_connection()
    try:
        jst = timezone(timedelta(hours=9))
        now_jst_iso = datetime.now(jst).isoformat()

        # 基本のUPDATE文
        query = "UPDATE products SET post_url = ?, shop_name = ?, post_url_updated_at = ?, status = 'URL取得済'"
        params = [post_url, shop_name, now_jst_iso]

        if new_main_url:
            query += ", url = ?"
            params.append(new_main_url)
        
        query += " WHERE id = ?"
        params.append(product_id)

        conn.execute(query, tuple(params))
        conn.commit()
        logging.debug(f"商品ID: {product_id} の投稿URLを更新し、ステータスを「URL取得済」に変更しました。")
    finally:
        conn.close()

def update_product_post_url(product_id: int, post_url: str):
    """
    指定された商品のpost_urlとroom_urlを更新する。
    フロントエンドからはpost_urlとして渡されるが、post_urlカラムのみを更新する。
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # post_urlカラムのみを更新する
        cursor.execute("UPDATE products SET post_url = ? WHERE id = ?", (post_url, product_id))
        conn.commit()
        logging.info(f"商品ID: {product_id} の投稿URLを更新しました。 URL: {post_url}")
        return cursor.rowcount
    except sqlite3.Error as e:
        logging.error(f"商品ID: {product_id} のpost_url更新中にエラー: {e}")
        return 0
    finally:
        conn.close()

def update_product_room_url(product_id: int, room_url: str):
    """
    指定された商品のroom_urlを更新する。
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE products SET room_url = ? WHERE id = ?", (room_url, product_id))
        conn.commit()
        logging.debug(f"商品ID: {product_id} のROOM URLを更新しました。 URL: {room_url}")
        return cursor.rowcount
    except sqlite3.Error as e:
        logging.error(f"商品ID: {product_id} のroom_url更新中にエラー: {e}")
        return 0
    finally:
        conn.close()

def update_room_url_by_rakuten_url(rakuten_url: str, room_url: str):
    """楽天市場のURLをキーに、ROOMの個別商品ページURLを更新する"""
    if not rakuten_url or not room_url:
        return
    
    # パターン1: URLを正規化して完全一致で検索
    normalized_url = _normalize_rakuten_url(rakuten_url)

    # パターン2: エンコードされたままのpc=パラメータで部分一致検索
    encoded_pc_param = None
    if "hb.afl.rakuten.co.jp" in rakuten_url and "?pc=" in rakuten_url:
        encoded_pc_param = rakuten_url.split('?pc=')[1]

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # まず正規化URLで検索・更新を試みる
        cursor.execute("UPDATE products SET room_url = ? WHERE url = ?", (room_url, normalized_url))
        
        if cursor.rowcount > 0:
            logging.debug(f"  -> {cursor.rowcount}件のレコードのroom_urlを更新しました。(正規化URL: {normalized_url})")
            conn.commit()
            return

        # パターン1で更新されなかった場合、パターン2（部分一致）を試す
        if encoded_pc_param:
            like_pattern = f"%{encoded_pc_param}%"
            logging.debug(f"正規化URLでの更新に失敗したため、部分一致検索を試みます。パターン: {like_pattern}")
            
            # 更新前に、対象が1件に絞れるか確認（意図しない複数更新を防ぐため）
            cursor.execute("SELECT id FROM products WHERE url LIKE ?", (like_pattern,))
            found_products = cursor.fetchall()

            if len(found_products) == 1:
                product_id_to_update = found_products[0]['id']
                cursor.execute("UPDATE products SET room_url = ? WHERE id = ?", (room_url, product_id_to_update))
                if cursor.rowcount > 0:
                    logging.debug(f"  -> 1件のレコードのroom_urlを更新しました。(部分一致パターン)")
            elif len(found_products) > 1:
                logging.warning(f"  -> 部分一致で複数の更新対象が見つかったため、更新をスキップします。({len(found_products)}件)")
            else:
                logging.warning(f"  -> room_urlの更新対象レコードが見つかりませんでした。(URL: {normalized_url})")
        else:
            logging.warning(f"  -> room_urlの更新対象レコードが見つかりませんでした。(URL: {normalized_url})")
        
        conn.commit()
    finally:
        conn.close()

def update_ai_caption(product_id: int, caption: str) -> int:
    """指定された商品のAI投稿文と更新日時を更新し、ステータスを「投稿準備完了」に変更する"""
    conn = get_db_connection()
    try:
        # JSTのタイムゾーンを定義
        jst = timezone(timedelta(hours=9))
        now_jst_iso = datetime.now(jst).isoformat()
        cursor = conn.cursor()
        cursor.execute("UPDATE products SET ai_caption = ?, ai_caption_created_at = ?, status = '投稿準備完了' WHERE id = ?", (caption, now_jst_iso, product_id))
        conn.commit()
        logging.debug(f"商品ID: {product_id} のAI投稿文を更新し、ステータスを「投稿準備完了」に変更しました。")
        return cursor.rowcount
    finally:
        conn.close()

def _normalize_rakuten_url(url: str) -> str:
    """
    楽天ROOMのアフィリエイトURLから実際の楽天商品URLを抽出する。
    それ以外のURLはそのまま返す。
    """
    if "hb.afl.rakuten.co.jp" in url:
        try:
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            pc_url = query_params.get('pc', [None])[0]
            if pc_url:
                # pc_url自体もクエリパラメータを持つ可能性があるので、それも除去
                url = pc_url.split('?')[0]
        except Exception:
            pass # パースに失敗した場合は元のURLを返す

    # アフィリエイトリンク以外、またはpcパラメータの抽出後、
    # ? 以降のクエリパラメータを削除してURLを正規化する
    base_url = url.split('?')[0]

    # プロトコルを https に統一
    if base_url.startswith("http://"):
        base_url = base_url.replace("http://", "https://", 1)

    return base_url

def add_recollection_product(name=None, url=None, image_url=None, shop_name=None, procurement_keyword=None):
    """
    【再収集タスク専用】URLを正規化し、重複があれば更新、なければ新規追加する (UPSERT)。
    重複判定は前方一致で行う。
    """
    if not name or not url: # shop_nameは必須ではないのでチェックに含めない
        logging.warning("商品名またはURLが不足しているため、DBに追加できません。")
        return False

    # URLを正規化（アフィリエイトリンクから実際の楽天商品URLを抽出）
    unique_url = _normalize_rakuten_url(url)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 1. 前方一致で既存レコードを検索 (http/httpsの違いを吸収)
        # `https://` または `http://` を除いた部分で検索する
        url_part = unique_url.split("://", 1)[-1]
        
        # DBに保存されているURLも `://` 以降の部分で比較する
        # これにより、DBにhttpで保存されていても、httpsで検索した際に見つけられる
        # 前方一致検索も同時に行う
        like_pattern = f"{url_part}%"
        cursor.execute("""
            SELECT id FROM products WHERE SUBSTR(url, INSTR(url, '://') + 3) LIKE ? LIMIT 1
        """, (like_pattern,))
        existing_product = cursor.fetchone()

        # 2. 既存レコードがあればUPDATE、なければINSERT
        if existing_product:
            # 既存レコードを更新
            product_id = existing_product['id']
            logging.info(f"URLが前方一致で重複したため、既存の商品(ID: {product_id})を更新します。")
            cursor.execute("""
                UPDATE products SET
                    url = ?,
                    name = ?,
                    image_url = ?,
                    shop_name = ?,
                    procurement_keyword = ?,
                    status = '投稿準備完了',
                    posted_at = NULL,
                    error_message = NULL
                WHERE id = ?
            """, (unique_url, name, image_url, shop_name, procurement_keyword, product_id))
            conn.commit()
            return False # 更新なので 'was_inserted' は False
        else:
            # 新規レコードを挿入
            logging.debug(f"新規商品としてDBに登録します: {name[:30]}...")
            cursor.execute("""
                INSERT INTO products (name, url, image_url, shop_name, procurement_keyword, status, created_at)
                VALUES (?, ?, ?, ?, ?, '生情報取得', ?)
            """, (name, unique_url, image_url, shop_name, procurement_keyword, datetime.now(timezone(timedelta(hours=9))).isoformat()))
            conn.commit()
            return True # 新規挿入なので True
    finally:
        conn.close()

def add_product_if_not_exists(name=None, url=None, image_url=None, procurement_keyword=None):
    """同じURLの商品が存在しない場合のみ、新しい商品をDBに追加する。調達キーワードも保存する。"""
    if not name or not url:
        logging.warning("商品名またはURLが不足しているため、DBに追加できません。")
        return False

    # JSTのタイムゾーンを定義
    jst = timezone(timedelta(hours=9))
    # JSTの現在時刻をISO 8601形式の文字列で取得
    created_at_jst = datetime.now(jst).isoformat()

    conn = get_db_connection()
    try:
        # created_atも明示的にJSTで指定する
        conn.execute("INSERT INTO products (name, url, image_url, procurement_keyword, status, created_at) VALUES (?, ?, ?, ?, '生情報取得', ?)",
                       (name, url, image_url, procurement_keyword, created_at_jst))
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

def product_exists_by_post_url(post_url: str) -> bool:
    """指定されたpost_urlを持つ商品がデータベースに存在するかどうかをチェックする。"""
    if not post_url:
        return False
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # post_urlがNULLでないレコードも考慮
        cursor.execute("SELECT 1 FROM products WHERE post_url = ? AND post_url IS NOT NULL LIMIT 1", (post_url,))
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

    jst = timezone(timedelta(hours=9))
    created_at_jst = datetime.now(jst).isoformat()

    # executemany用に、辞書のリストをタプルのリストに変換
    records_to_insert = [
        (p.get('name'), p.get('url'), p.get('image_url'), p.get('procurement_keyword'), created_at_jst) for p in products_data if p.get('name') and p.get('url')
    ]

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.executemany("INSERT OR IGNORE INTO products (name, url, image_url, procurement_keyword, status, created_at) VALUES (?, ?, ?, ?, '生情報取得', ?)", records_to_insert)
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
        logging.debug(f"{len(product_ids)}件の商品を削除しました。")
        return cursor.rowcount
    finally:
        conn.close()

def update_product_order(product_ids: list[int]):
    """商品のリスト順に基づいてpriorityを更新する"""
    if not product_ids:
        return

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # リストの先頭が高い優先度になるように、priorityを降順で設定
        max_priority = len(product_ids)
        for i, product_id in enumerate(product_ids):
            cursor.execute("UPDATE products SET priority = ? WHERE id = ?", (max_priority - i, product_id))
        conn.commit()
        logging.debug(f"{len(product_ids)}件の商品の順序を更新しました。")
    finally:
        conn.close()

def bulk_update_products_from_data(products_data: list[dict]):
    """
    辞書のリストから複数の商品を一括で更新する。
    ステータスとタイムスタンプも条件に応じて更新する。
    """
    if not products_data:
        return 0, 0

    conn = get_db_connection()
    updated_count = 0
    failed_count = 0
    jst = timezone(timedelta(hours=9))

    try:
        with conn:  # トランザクションを開始
            for product_data in products_data:
                product_id = product_data.get('id')
                if not product_id:
                    failed_count += 1
                    continue

                # 更新対象のフィールドを抽出
                post_url = product_data.get('post_url')
                ai_caption = product_data.get('ai_caption')

                # ステータスとタイムスタンプのロジック
                now_jst_iso = datetime.now(jst).isoformat()
                status_update_sql = ""
                params = []

                if post_url and ai_caption:
                    status_update_sql = ", status = '投稿準備完了', post_url_updated_at = COALESCE(post_url_updated_at, ?), ai_caption_created_at = COALESCE(ai_caption_created_at, ?)"
                    params.extend([now_jst_iso, now_jst_iso])
                elif post_url:
                    status_update_sql = ", status = 'URL取得済', post_url_updated_at = COALESCE(post_url_updated_at, ?)"
                    params.append(now_jst_iso)

                # 基本のUPDATE文
                query = f"UPDATE products SET post_url = ?, ai_caption = ?, error_message = NULL {status_update_sql} WHERE id = ?"
                final_params = [post_url, ai_caption] + params + [product_id]

                cursor = conn.cursor()
                cursor.execute(query, final_params)
                if cursor.rowcount > 0:
                    updated_count += 1

    except sqlite3.Error as e:
        logging.error(f"商品の一括データ更新中にエラーが発生しました: {e}")
        raise  # エラーを呼び出し元に伝播させる
    finally:
        conn.close()

    return updated_count, failed_count

def bulk_insert_my_post_comments(comments_data: list[dict]) -> int | None:
    """
    収集した自分の投稿へのコメントデータを一括でDBに保存する。
    (user_image_url, post_timestamp) の組み合わせで重複をチェックし、重複データは無視される。
    :param comments_data: スクレイピングしたコメントデータのリスト
    :return: 新規に挿入された行数
    """
    if not comments_data:
        return 0

    # 最初のデータからカラム名を取得し、created_atを追加
    columns = list(comments_data[0].keys())
    if 'created_at' not in columns:
        columns.append('created_at')
    
    col_str = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))

    # 挿入用データを作成（created_atを追加）
    created_at_jst = datetime.now(timezone(timedelta(hours=9))).isoformat()
    data_to_insert = [tuple(d.get(col, created_at_jst) for col in columns) for d in comments_data]

    sql = f"INSERT OR IGNORE INTO my_post_comments ({col_str}) VALUES ({placeholders})"

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.executemany(sql, data_to_insert)
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()

def get_latest_comment_timestamps_by_post() -> dict[str, str]:
    """
    各投稿(post_detail_url)ごとに、DBに保存されている最新のコメントタイムスタンプを取得する。
    :return: { 'post_detail_url': 'latest_post_timestamp', ... } という形式の辞書
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT post_detail_url, MAX(post_timestamp) as latest_timestamp
            FROM my_post_comments
            GROUP BY post_detail_url
        """)
        return {row['post_detail_url']: row['latest_timestamp'] for row in cursor.fetchall()}
    finally:
        conn.close()

def get_latest_comment_details_by_post() -> dict[str, dict]:
    """
    各投稿(post_detail_url)ごとに、DBに保存されている最新のコメント情報を取得する。
    タイムスタンプの揺らぎによる重複収集を防ぐために使用する。
    :return: { 'post_detail_url': {'post_timestamp': '...', 'user_page_url': '...', 'comment_text': '...'}, ... }
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # 各投稿ごとに最新のタイムスタンプを持つレコードのIDを取得し、そのレコードの全情報を取得する
        # (post_detail_url, post_timestamp) の組み合わせで最新の1件を特定する
        cursor.execute("""
            SELECT c.*
            FROM my_post_comments c
            INNER JOIN (
                SELECT post_detail_url, MAX(post_timestamp) as max_ts
                FROM my_post_comments
                GROUP BY post_detail_url
            ) AS latest ON c.post_detail_url = latest.post_detail_url AND c.post_timestamp = latest.max_ts
        """)
        # 辞書に変換して返す
        return {row['post_detail_url']: dict(row) for row in cursor.fetchall()}
    finally:
        conn.close()

def get_unreplied_comments(limit: int = 20) -> list[dict]:
    """
    返信がまだ生成されていないコメントを取得する (reply_generated_at IS NULL)。
    新しいコメントから順に取得する。
    :param limit: 取得する最大件数
    :return: コメントデータの辞書のリスト
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM my_post_comments
            WHERE reply_generated_at IS NULL
            ORDER BY post_timestamp DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def get_post_urls_with_unreplied_comments() -> list[str]:
    """
    返信がまだ生成されていないコメントを持つ投稿のURLリストを、
    最新の未返信コメント日時が新しい順に取得する。
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT post_detail_url
            FROM my_post_comments
            WHERE reply_generated_at IS NULL
            GROUP BY post_detail_url
            ORDER BY MAX(post_timestamp) DESC
        """)
        return [row['post_detail_url'] for row in cursor.fetchall()]
    finally:
        conn.close()

def get_unreplied_comments_for_post(post_detail_url: str) -> list[dict]:
    """指定された投稿URLについて、返信がまだ生成されていないコメントを取得する。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM my_post_comments WHERE post_detail_url = ? AND reply_generated_at IS NULL ORDER BY post_timestamp DESC", (post_detail_url,))
    comments = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return comments

def bulk_update_comment_replies(replies: list[dict]):
    """
    AIが生成した返信テキストと関連情報をDBに一括で更新する。comment_idをキーに更新する。
    :param replies: 'reply_text', 'replied_user_names', 'id' を含む辞書のリスト
    """
    if not replies:
        return 0

    now_jst_iso = datetime.now(timezone(timedelta(hours=9))).isoformat()
    
    # 更新用データのリストを作成
    update_data = []
    for reply in replies:
        comment_id = reply.get('id')
        reply_text = reply.get('reply_text')
        if comment_id and reply_text:
            update_data.append((reply_text, now_jst_iso, comment_id))

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # comment_id を使って正確に更新する
        cursor.executemany("""
            UPDATE my_post_comments SET reply_text = ?, reply_generated_at = ?
            WHERE id = ? AND reply_generated_at IS NULL
        """, update_data)
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()

def get_generated_replies(hours_ago: int = 24) -> list[dict]:
    """
    生成済みで、まだ投稿されていない返信コメントを取得する。
    (reply_text IS NOT NULL AND reply_posted_at IS NULL)
    :param hours_ago: 何時間前までに生成されたコメントを対象とするか
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        threshold_time = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()

        cursor.execute("""
            SELECT * FROM my_post_comments
            WHERE reply_text IS NOT NULL 
              AND reply_text != '[SKIPPED]' AND reply_posted_at IS NULL
              AND reply_generated_at >= ?
            ORDER BY reply_generated_at, post_timestamp DESC
        """, (threshold_time,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def update_reply_text(comment_id: int, new_text: str):
    """
    指定されたコメントIDが属するグループ全体の返信テキストを一括で更新する。
    グループは post_detail_url と元の reply_text によって定義される。
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 1. 代表コメントIDから、グループを特定するための情報を取得
        cursor.execute("SELECT post_detail_url, reply_text FROM my_post_comments WHERE id = ?", (comment_id,))
        representative_comment = cursor.fetchone()

        if not representative_comment:
            logging.warning(f"コメント(ID: {comment_id})が見つからないため、更新できませんでした。")
            return

        original_post_url = representative_comment['post_detail_url']
        original_reply_text = representative_comment['reply_text']

        # 2. 同じグループに属するすべてのコメントの返信テキストを一括で更新
        cursor.execute("""
            UPDATE my_post_comments 
            SET reply_text = ? 
            WHERE post_detail_url = ? AND reply_text = ?
        """, (new_text, original_post_url, original_reply_text))

        conn.commit()
        updated_count = cursor.rowcount
        logging.info(f"コメントグループ（代表ID: {comment_id}）の返信テキストを更新しました。対象件数: {updated_count}件")

    finally:
        conn.close()

def ignore_reply(comment_id: int):
    """
    指定されたコメントIDの返信を無視する（reply_textにスキップマーカーを設定し、処理済みとする）。
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # スキップした日時も記録することで、再生成の対象から外す
        now_jst_iso = datetime.now(timezone(timedelta(hours=9))).isoformat()
        cursor.execute("UPDATE my_post_comments SET reply_text = '[SKIPPED]', reply_generated_at = ? WHERE id = ?", (now_jst_iso, comment_id,))
        conn.commit()
        logging.debug(f"コメント(ID: {comment_id})を返信対象から除外しました。")
    finally:
        conn.close()

def mark_replies_as_posted(comment_ids: list[int]):
    """
    指定されたコメントIDのリストについて、返信が投稿されたことを記録する。
    (reply_posted_at に現在時刻を設定)
    """
    if not comment_ids:
        return 0
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        now_jst_iso = datetime.now(timezone(timedelta(hours=9))).isoformat()
        placeholders = ','.join('?' for _ in comment_ids)
        query = f"UPDATE my_post_comments SET reply_posted_at = ? WHERE id IN ({placeholders})"
        cursor.execute(query, [now_jst_iso] + comment_ids)
        conn.commit()
        logging.debug(f"{cursor.rowcount}件のコメントを「投稿済み」として日時を更新しました。")
        return cursor.rowcount
    finally:
        conn.close()

def get_commenting_users_summary(limit: int = 50) -> list[dict]:
    """
    コメントしてくれたユーザーのサマリー（合計コメント数、最新コメント日時）を取得する。
    最新コメント日時が新しい順にソートする。
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            WITH RankedUsers AS (
                SELECT
                    user_name,
                    user_page_url,
                    user_image_url,
                    post_timestamp,
                    like_back_count,
                    last_like_back_at,
                    ROW_NUMBER() OVER(PARTITION BY user_page_url ORDER BY post_timestamp DESC) as rn
                FROM my_post_comments
                WHERE user_page_url IS NOT NULL AND user_page_url != ''
            )
            SELECT
                (SELECT user_name FROM RankedUsers WHERE user_page_url = ru.user_page_url AND rn = 1) as user_name,
                ru.user_page_url,
                ru.user_page_url as user_id,
                (SELECT user_image_url FROM RankedUsers WHERE user_page_url = ru.user_page_url AND rn = 1) as user_image_url,
                COUNT(ru.user_page_url) as total_comments,
                MAX(ru.post_timestamp) as latest_comment_timestamp,
                MAX(ru.like_back_count) as like_back_count,
                MAX(ru.last_like_back_at) as last_like_back_at
            FROM my_post_comments ru
            WHERE ru.user_page_url IS NOT NULL AND ru.user_page_url != ''
            GROUP BY ru.user_page_url
            ORDER BY latest_comment_timestamp DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def get_user_details_for_like_back(user_page_urls: list[str]) -> list[dict]:
    """
    指定されたユーザーページのURLリストに基づいて、いいね返しに必要なユーザー詳細を取得する。
    my_post_commentsテーブルから情報を取得する。
    :param user_page_urls: ユーザーページのURLリスト
    :return: ユーザー詳細の辞書のリスト
    """
    if not user_page_urls:
        return []
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        placeholders = ','.join('?' for _ in user_page_urls)
        # my_post_commentsテーブルから最新の情報を取得する
        # user_idとしてuser_page_urlをエイリアスで設定し、タスク側との互換性を保つ
        query = f"""
            SELECT DISTINCT user_name, user_page_url, user_page_url as user_id
            FROM my_post_comments WHERE user_page_url IN ({placeholders})
        """
        cursor.execute(query, user_page_urls)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def update_like_back_status(user_page_url: str, like_count: int):
    """
    指定されたユーザーページのURLに紐づくすべてのコメントレコードに対して、
    いいね返しの累計数と最終実行日時を更新する。
    :param user_page_url: 更新対象のユーザーページURL
    :param like_count: 今回実行したいいね数
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # 1. 現在の累計いいね数を取得
        cursor.execute("SELECT MAX(like_back_count) FROM my_post_comments WHERE user_page_url = ?", (user_page_url,))
        current_total = cursor.fetchone()[0]
        if current_total is None:
            current_total = 0
            
        # 2. 新しい累計数を計算
        new_total = current_total + like_count
        
        # 3. 最終実行日時と新しい累計数で、該当ユーザーの全レコードを更新
        now_jst_iso = datetime.now(timezone(timedelta(hours=9))).isoformat()
        cursor.execute("""
            UPDATE my_post_comments
            SET like_back_count = ?, last_like_back_at = ?
            WHERE user_page_url = ?
        """, (new_total, now_jst_iso, user_page_url))
        conn.commit()
    finally:
        conn.close()

# --- User Engagement Table Functions ---

def get_latest_engagement_timestamp() -> datetime:
    """
    user_engagementテーブルから最も新しいlatest_action_timestampを取得する。
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(latest_action_timestamp) FROM user_engagement")
        result = cursor.fetchone()[0]
        if result:
            # ISOフォーマットの文字列からdatetimeオブジェクトに変換
            # マイクロ秒がない場合も考慮
            return datetime.fromisoformat(result)
    except (sqlite3.Error, TypeError, ValueError) as e:
        logging.warning(f"エンゲージメントの最新タイムスタンプ取得中にエラー: {e}")
    finally:
        conn.close()
    return datetime.min

def get_users_for_url_acquisition() -> list[dict]:
    """
    プロフィールページのURLがまだ取得されていないユーザーを取得する。
    - profile_page_url が NULL または空文字列
    - 取得失敗の記録がない
    - 優先度順にソート
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM user_engagement
            WHERE (profile_page_url IS NULL OR profile_page_url = '')
                AND (
                    recent_like_count >= 3
                    OR (is_following > 0 AND recent_follow_count > 0 AND recent_like_count >= 1)
                )
            ORDER BY 
                (CASE WHEN recent_follow_count > 0 THEN 1 ELSE 0 END) DESC,
                recent_like_count DESC,
                recent_collect_count DESC,
                latest_action_timestamp DESC
        """)
        users = [dict(row) for row in cursor.fetchall()]
        return users
    finally:
        conn.close()

def get_users_for_prompt_creation() -> list[dict]:
    """
    AIプロンプトメッセージを生成/更新する必要があるユーザーを取得する。
    - URLが取得済み
    - ai_prompt_updated_at が latest_action_timestamp より古い、または NULL
    - かつ、最後にコメントしてから3日以上経過している、または新規ユーザー
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        three_days_ago = (datetime.now() - timedelta(days=3)).isoformat()

        cursor.execute("""
            SELECT * FROM user_engagement
            WHERE 
                profile_page_url IS NOT NULL
                AND (
                    -- 条件1: 新規コメント対象 (フォロー済み & 新規フォロー & いいね1件以上)
                    (last_commented_at IS NULL AND is_following = 1 AND recent_follow_count > 0 AND recent_like_count >= 1)
                    OR
                    -- 条件2: 再コメント対象 (最終コメントから3日以上経過 & いいね5件以上)
                    (last_commented_at IS NOT NULL AND last_commented_at < ? AND recent_like_count >= 5)
                )
                -- 既にプロンプトが最新の場合は除外
                AND (ai_prompt_updated_at IS NULL OR ai_prompt_updated_at < latest_action_timestamp)
        """, (three_days_ago,))
        users = [dict(row) for row in cursor.fetchall()]
        return users
    finally:
        conn.close()

def update_engagement_error(user_id: str, error_message: str):
    """
    指定されたユーザーのエンゲージメントエラーを記録する。
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE user_engagement SET last_engagement_error = ? WHERE id = ?", (error_message, user_id))
        conn.commit()
        logging.warning(f"ユーザーID: {user_id} のエンゲージメントエラーを記録しました: {error_message}")
    except sqlite3.Error as e:
        logging.error(f"ユーザーID: {user_id} のエンゲージメントエラー記録中にエラー: {e}")
    finally:
        conn.close()

def get_all_user_engagements_map() -> dict:
    """
    user_engagementテーブルからすべてのユーザーデータを取得し、user_idをキーとする辞書で返す。
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_engagement")
        rows = cursor.fetchall()
        return {row['id']: dict(row) for row in rows}
    except sqlite3.Error as e:
        logging.error(f"すべてのエンゲージメントデータ取得中にエラー: {e}")
        return {}
    finally:
        conn.close()

def bulk_upsert_user_engagements(users_data: list[dict]):
    """
    複数のユーザーエンゲージメントデータを一括で挿入または更新する (UPSERT)。
    """
    if not users_data:
        return 0
    
    # UPSERT用にデータをタプルのリストに変換
    records_to_upsert = [
        (
            d.get('id'), d.get('name'), d.get('profile_page_url'), d.get('profile_image_url'), d.get('latest_action_timestamp'),
            1 if d.get('is_following') else 0,
            d.get('recent_like_count', 0), d.get('recent_collect_count', 0), d.get('recent_comment_count', 0), d.get('recent_follow_count', 0),
            d.get('recent_action_timestamp'),
            d.get('ai_prompt_message'), d.get('ai_prompt_updated_at')
        ) for d in users_data
    ]

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # 存在しない場合はINSERT、存在する場合は指定したカラムのみをUPDATE
        cursor.executemany("""
            INSERT INTO user_engagement (id, name, profile_page_url, profile_image_url, latest_action_timestamp, is_following, recent_like_count, recent_collect_count, recent_comment_count, recent_follow_count, recent_action_timestamp, ai_prompt_message, ai_prompt_updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                profile_page_url = COALESCE(excluded.profile_page_url, profile_page_url),
                profile_image_url = excluded.profile_image_url,
                -- 常に新しいタイムスタンプで上書きする (recent_action_timestamp を考慮)
                recent_action_timestamp = CASE
                    WHEN excluded.recent_action_timestamp > COALESCE(recent_action_timestamp, '') THEN excluded.recent_action_timestamp
                    ELSE COALESCE(recent_action_timestamp, excluded.recent_action_timestamp)
                END,
                -- 常に新しいタイムスタンプで上書きする (recent_action_timestamp を考慮)
                latest_action_timestamp = CASE
                    WHEN excluded.recent_action_timestamp > COALESCE(latest_action_timestamp, '') THEN excluded.recent_action_timestamp
                    ELSE COALESCE(latest_action_timestamp, excluded.recent_action_timestamp)
                END,
                is_following = excluded.is_following,
                recent_like_count = recent_like_count + excluded.recent_like_count,
                recent_collect_count = recent_collect_count + excluded.recent_collect_count,
                recent_comment_count = recent_comment_count + excluded.recent_comment_count,
                recent_follow_count = recent_follow_count + excluded.recent_follow_count,
                ai_prompt_message = excluded.ai_prompt_message,
                ai_prompt_updated_at = excluded.ai_prompt_updated_at
        """, records_to_upsert)
        conn.commit()
        logging.debug(f"{cursor.rowcount}件のユーザーエンゲージメントデータをUPSERTしました。")
        return cursor.rowcount
    finally:
        conn.close()

def bulk_update_user_profiles(users_data: list[dict]):
    """
    複数のユーザーのプロフィール情報（URLやAIプロンプト）を一括で更新する。
    この関数は recent_ カウントを加算しない。
    """
    if not users_data:
        return 0

    records_to_update = [
        (
            d.get('profile_page_url'),
            d.get('ai_prompt_message'),
            d.get('ai_prompt_updated_at'),
            d.get('id')
        ) for d in users_data
    ]

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # 存在する場合に指定したカラムのみをUPDATE
        cursor.executemany("""
            UPDATE user_engagement SET
                profile_page_url = COALESCE(?, profile_page_url),
                ai_prompt_message = COALESCE(?, ai_prompt_message),
                ai_prompt_updated_at = COALESCE(?, ai_prompt_updated_at)
            WHERE id = ?
        """, records_to_update)
        conn.commit()
        logging.debug(f"{cursor.rowcount}件のユーザープロフィール情報を更新しました。")
        return cursor.rowcount
    finally:
        conn.close()

def cleanup_old_user_engagements(days: int = 30):
    """指定した日数より古いエンゲージメントデータを削除する"""
    threshold_date = datetime.now() - timedelta(days=days)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_engagement WHERE latest_action_timestamp < ?", (threshold_date.isoformat(),))
    conn.commit()
    logging.info(f"{cursor.rowcount}件の古いエンゲージメントデータを削除しました（{days}日以上経過）。")
    conn.close()

def commit_user_actions(user_ids: list[str], is_comment_posted: bool, post_url: str | None = None):
    """
    指定されたユーザーのrecentアクションを累計に加算し、recentをリセットする。
    コメントが投稿された場合はlast_commented_atとlast_commented_post_urlも更新する。
    """
    if not user_ids:
        return 0
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        placeholders = ','.join('?' for _ in user_ids)
        
        update_query = f"""
            UPDATE user_engagement SET
                like_count = like_count + recent_like_count,
                collect_count = collect_count + recent_collect_count,
                comment_count = comment_count + recent_comment_count,
                follow_count = follow_count + recent_follow_count,
                recent_like_count = 0,
                recent_collect_count = 0,
                recent_comment_count = 0,
                recent_follow_count = 0,
                last_engagement_error = NULL
            WHERE id IN ({placeholders})
        """
        if is_comment_posted:
            update_query = update_query.replace("WHERE", ", last_commented_at = ?, last_commented_post_url = ? WHERE")
            params = [datetime.now().isoformat(), post_url] + user_ids
        else:
            params = user_ids
        cursor.execute(update_query, params)
        conn.commit()
        logging.debug(f"{cursor.rowcount}件のユーザーアクションをコミットしました。")
        return cursor.rowcount
    finally:
        conn.close()

def get_stale_user_ids_for_commit(hours: int = 24) -> list[str]:
    """
    指定された時間以上、アクションがコミットされずに放置されているユーザーのIDを取得する。
    'stale' の条件:
    - recent_action_timestamp が指定時間より前
    - かつ、未コミットのアクション (recent_like_countなど) が存在する
    """
    threshold_time = (datetime.now() - timedelta(hours=hours)).isoformat()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            SELECT id FROM user_engagement
            WHERE
                recent_action_timestamp < ?
                AND (recent_like_count > 0 OR recent_collect_count > 0 OR recent_comment_count > 0 OR recent_follow_count > 0)
        """
        cursor.execute(query, (threshold_time,))
        user_ids = [row['id'] for row in cursor.fetchall()]
        return user_ids
    finally:
        conn.close()

def _add_engagement_type_to_users(users: list[dict]) -> list[dict]:
    """ユーザーデータのリストにエンゲージメントタイプを追加するヘルパー関数"""
    three_days_ago = datetime.now() - timedelta(days=3)
    processed_users = []
    for user in users:
        user['engagement_type'] = 'none'  # デフォルト
        
        # --- 判定に必要な変数を準備 ---
        recent_likes = user.get('recent_like_count', 0)
        recent_follows = user.get('recent_follow_count', 0)
        is_following = user.get('is_following', 0) == 1
        last_commented_at_str = user.get('last_commented_at')
        last_commented_at = datetime.fromisoformat(last_commented_at_str) if last_commented_at_str else None
        has_comment_text = bool(user.get('comment_text'))

        # --- コメント対象(💬)の判定 ---
        is_comment_target = False
        # 1. 共通の前提条件: コメント本文があり、かつ3日間の再コメント期間をクリアしている
        can_comment_today = has_comment_text and (not last_commented_at or last_commented_at < three_days_ago)

        if can_comment_today:
            # 2. 個別の条件: 条件Aまたは条件Bを満たすか
            # 条件A: いいね5件以上
            is_like_based_target = (recent_likes >= 5)
            # 条件B: フォロー済み & 新規フォローバック & いいね1件以上
            is_follow_based_target = (is_following and recent_follows > 0 and recent_likes >= 1)

            if is_like_based_target or is_follow_based_target:
                is_comment_target = True

        if is_comment_target:
            user['engagement_type'] = 'comment'
        # --- いいね返しのみ対象(❤️)の判定 ---
        # コメント対象ではなく、かつ、いいねが3件以上ある場合
        elif recent_likes >= 3:
            user['engagement_type'] = 'like_only'

        # どちらかの対象であればリストに追加
        if user['engagement_type'] != 'none':
            processed_users.append(user)

    return processed_users

def get_users_for_commenting(limit: int = 10) -> list[dict]:
    """
    コメント投稿対象のユーザーをアクション日時順に取得する。

    - **コメント返信対象 (💬)**:
        - AIによるコメント本文が生成済みで、かつ最終コメントから3日以上経過（または新規）しており、
        - 以下のいずれかを満たすユーザー:
            - (A) 今セッションで **いいねを5回以上**
            - (B) こちらが **フォロー済み** で、相手から **新規フォロー** があり、かつ **いいねを1回以上**
    - **いいね返しのみ対象 (❤️)**:
        - 上記の「コメント返信対象」ではない。
        - かつ、今セッションで **いいねを3回以上** してくれたユーザー。

    :param limit: 取得するユーザーの最大数
    :return: ユーザーデータの辞書のリスト
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # コメント対象またはいいね返しの可能性があるユーザーを幅広く取得
        # - 最近のアクションがある (recent_like_count > 0)
        # - または、コメントが生成されている (comment_text IS NOT NULL)
        query = """
            SELECT * FROM user_engagement
            WHERE
                -- 条件A,B,いいね返し対象のいずれかに合致する可能性のあるユーザーを幅広く取得
                -- (フォローバック+いいね1件 or いいね3件以上)
                (is_following = 1 AND recent_follow_count > 0 AND recent_like_count >= 1)
                OR (recent_like_count >= 3)
            ORDER BY recent_action_timestamp DESC
        """
        cursor.execute(query)
        potential_users = [dict(row) for row in cursor.fetchall()]

        # ヘルパー関数で engagement_type を判定し、対象外のユーザーを除外
        target_users = _add_engagement_type_to_users(potential_users)

        return target_users[:limit]
    finally:
        conn.close()

def get_users_for_ai_comment_creation() -> list[dict]:
    """
    AIによるコメント生成対象のユーザーを取得する。
    以下のいずれかの条件に合致するユーザーを対象とする。
    1. 新規生成対象: ai_prompt_message があり、comment_generated_at が NULL
    2. 再生成対象: ai_prompt_updated_at が comment_generated_at より新しい
    """
    conn = get_db_connection()
    try:
        
        cursor = conn.cursor()
        query = """
            SELECT * FROM user_engagement
            WHERE 
                ai_prompt_message IS NOT NULL AND ai_prompt_message != ''
                AND (
                    comment_generated_at IS NULL 
                    OR ai_prompt_updated_at > comment_generated_at
                )
        """
        cursor.execute(query)

        users = [dict(row) for row in cursor.fetchall()]
        return users
    finally:
        conn.close()

def get_all_user_engagements(sort_by: str = 'recent_action', limit: int = 100, search_keyword: str = '') -> list[dict]:
    """
    user_engagementテーブルからすべてのユーザーデータを、指定された条件でソートして取得する。

    :param sort_by: ソート条件のキー。
        - 'recent_action': 最新アクション日時順（デフォルト）
        - 'commented': 投稿済ユーザー（最終コメント日時が新しい順）
        - 'like_count_desc': 累計いいね数が多い順
        - 'commented_at_desc': 最終コメント日時が新しい順
        - 'commented_at_asc': 最終コメント日時が古い順
    :param search_keyword: ユーザー名で絞り込むための検索キーワード。
    :param limit: 取得する最大件数。
    :return: ユーザーデータの辞書のリスト。
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # ソート条件に応じてORDER BY句とWHERE句を決定
        where_clauses = []
        order_by_clause = "ORDER BY latest_action_timestamp DESC" # デフォルト

        if sort_by == 'all' or sort_by == 'recent_action':
            # 全員表示の場合は絞り込みなし、デフォルトのソート順を維持
            pass
        elif sort_by == 'commented':
            where_clauses.append("last_commented_at IS NOT NULL")
            order_by_clause = "ORDER BY last_commented_at DESC"
        elif sort_by == 'like_count_desc':
            order_by_clause = "ORDER BY (like_count + recent_like_count) DESC"
        # 'commented_at_desc' と 'commented_at_asc' は 'commented' と同じ絞り込み条件
        elif sort_by == 'commented_at_desc':
            where_clauses.append("last_commented_at IS NOT NULL")
            order_by_clause = "ORDER BY last_commented_at DESC"
        elif sort_by == 'like_back_ready':
            where_clauses.append("profile_page_url IS NOT NULL AND profile_page_url != '取得失敗'")
            order_by_clause = "ORDER BY latest_action_timestamp DESC" # いいね返し対象も最新アクション順で表示
        elif sort_by == 'commented_at_asc':
            where_clauses.append("last_commented_at IS NOT NULL")
            order_by_clause = "ORDER BY last_commented_at ASC"

        # 検索キーワードがあればWHERE句に追加
        params = []
        if search_keyword:
            where_clauses.append("name LIKE ?")
            params.append(f'%{search_keyword}%')

        where_clause_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        params.append(limit)

        query = f"SELECT * FROM user_engagement {where_clause_str} {order_by_clause} LIMIT ?"
        
        logging.debug(f"[DB:get_all_user_engagements] Executing query: `{query}` with params: {params}")
        cursor.execute(query, params)
        users = [dict(row) for row in cursor.fetchall()]

        # 「全員表示」の場合は絞り込みを行わず、全ユーザーを返す
        # それ以外（コメント対象者表示など）の場合は、エンゲージメントタイプを判定して絞り込む
        # `like_back_ready` も全員表示のソートオプションなので、絞り込み対象から除外する
        if sort_by not in ['all', 'recent_action', 'like_count_desc', 'commented_at_desc', 'commented_at_asc', 'like_back_ready']:
            users = _add_engagement_type_to_users(users)

        return users
    finally:
        conn.close()


def update_user_comment(user_id: str, comment_text: str):
    """
    指定されたユーザーのcomment_textとcomment_generated_atを更新する。
    """
    now_str = datetime.now().isoformat()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE user_engagement SET comment_text = ?, comment_generated_at = ? WHERE id = ?", (comment_text, now_str, user_id))
        conn.commit()
    finally:
        conn.close()

def reset_products_for_caption_regeneration(product_ids: list[int]):
    """
    指定された複数の商品を、AI投稿文を再生成するためにリセットする。
    - ai_caption と ai_caption_created_at を NULL にする
    - status を 'URL取得済' にする
    """
    if not product_ids:
        return 0
    conn = get_db_connection()
    try:
        placeholders = ','.join('?' for _ in product_ids)
        query = f"""
            UPDATE products SET
                ai_caption = NULL,
                ai_caption_created_at = NULL,
                status = 'URL取得済'
            WHERE id IN ({placeholders})
        """
        cursor = conn.cursor()
        cursor.execute(query, product_ids)
        conn.commit()
        logging.info(f"{cursor.rowcount}件の商品を投稿文再生成のためにリセットしました。")
        return cursor.rowcount
    finally:
        conn.close()

def get_table_names() -> list[str]:
    """データベース内のすべてのテーブル名を取得する。"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        return [row['name'] for row in cursor.fetchall()]
    finally:
        conn.close()

def export_tables_as_sql(table_names: list[str], include_delete: bool) -> str:
    """
    指定されたテーブルのデータをSQL形式でエクスポートする。
    sqlite3のiterdump()を使用し、安全にSQLを生成する。
    """
    if not table_names:
        return "-- テーブルが選択されていません。"

    conn = get_db_connection()
    try:
        sql_dump = ["-- R-Auto DB Export", f"-- Generated at: {datetime.now().isoformat()}", "", "BEGIN TRANSACTION;"]
        
        # iterdump()はテーブル名がダブルクォートで囲まれるため、それに合わせる
        # 例: 'CREATE TABLE "products" ...'
        # iterdump()はテーブル定義(CREATE TABLE)とデータ(INSERT)を両方出力する
        dump_lines = list(conn.iterdump())

        for table_name in table_names:
            if include_delete:
                sql_dump.append(f"DELETE FROM {table_name};")
            
            # 指定されたテーブルに関連するINSERT文のみを抽出して追加
            for line in dump_lines:
                # INSERT文を INSERT OR IGNORE に置換して、インポート時の重複エラーを防ぐ
                if line.startswith(f'INSERT INTO "{table_name}"') or line.startswith(f'INSERT INTO {table_name}'):
                    line = line.replace("INSERT INTO", "INSERT OR IGNORE INTO", 1)
                    sql_dump.append(line)
        
        sql_dump.append("COMMIT;")
        
        return "\n".join(sql_dump)
    finally:
        conn.close()

def execute_sql_script(sql_script: str) -> bool:
    """指定されたSQLスクリプトを実行する。"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.executescript(sql_script)
        conn.commit()
        return True
    except sqlite3.IntegrityError as e:
        # 主にバックアップからの復元時に発生する重複エラーは警告としてログに記録し、処理は成功とみなす
        logging.warning(f"SQLスクリプトの実行中に重複エラーが発生しましたが、処理を続行します: {e}")
        return True
    except sqlite3.DatabaseError as e:
        logging.error(f"SQLスクリプトの実行中にエラーが発生しました: {e}")
        # 'database disk image is malformed' エラーの場合、復旧を試みる
        if "malformed" in str(e):
            logging.info("データベースが破損している可能性があるため、復旧を試みます...")
            if recover_database():
                logging.info("データベースの復旧に成功しました。再度SQLスクリプトを実行します。")
                # 復旧後、再度実行を試みる
                conn_new = get_db_connection()
                try:
                    cursor_new = conn_new.cursor()
                    cursor_new.executescript(sql_script)
                    conn_new.commit()
                    return True
                finally:
                    conn_new.close()
            else:
                logging.error("データベースの復旧に失敗しました。")
        raise e # 他のDBエラーや復旧失敗時は再度例外を発生させる
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def recover_database() -> bool:
    """破損したデータベースの復旧を試みる"""
    backup_path = DB_FILE + ".bak"
    logging.info(f"現在のDBファイルを '{backup_path}' にバックアップします。")
    if os.path.exists(DB_FILE):
        os.rename(DB_FILE, backup_path)

    logging.info("新しいDBファイルを作成し、バックアップからデータを復元します。")
    # sqlite3コマンドを使って、バックアップから新しいDBにデータをダンプする
    # .dumpは破損していても読める範囲のデータをSQLとして出力する
    # そのSQLを新しいDBで実行することでデータを復元する
    dump_command = f'sqlite3 "{backup_path}" .dump | sqlite3 "{DB_FILE}"'
    result = os.system(dump_command)

    if result == 0:
        logging.info("DBの復元が正常に完了しました。")
        # 復元後、スキーマの整合性を保つためにinit_dbを再実行
        init_db()
        return True
    else:
        logging.error(f"DBの復元に失敗しました。コマンド終了コード: {result}")
        # 失敗した場合はバックアップを元に戻す
        os.rename(backup_path, DB_FILE)
        return False
