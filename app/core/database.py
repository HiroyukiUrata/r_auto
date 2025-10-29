import sqlite3
import logging
import os
import json
from datetime import datetime, timezone, timedelta

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
                    logging.info(f"productsテーブルに '{column_name}' カラムを追加しました。")
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
                recent_action_timestamp TEXT, -- 今セッションの最新アクション日時
                comment_text TEXT,
                last_commented_at TEXT,
                ai_prompt_message TEXT,
                ai_prompt_updated_at TEXT,
                comment_generated_at TEXT
            )
        ''')
        logging.info("user_engagementテーブルが正常に初期化されました。")

        # --- user_engagementテーブルのマイグレーション ---
        def add_column_to_engagement_if_not_exists(cursor, column_name, column_type):
            cursor.execute("PRAGMA table_info(user_engagement)")
            columns = [row['name'] for row in cursor.fetchall()]
            if column_name not in columns:
                try:
                    cursor.execute(f"ALTER TABLE user_engagement ADD COLUMN {column_name} {column_type}")
                    logging.info(f"user_engagementテーブルに '{column_name}' カラムを追加しました。")
                except sqlite3.Error as e:
                    logging.error(f"'{column_name}' カラムの追加に失敗しました: {e}")

        add_column_to_engagement_if_not_exists(cursor, 'ai_prompt_updated_at', 'TEXT')
        add_column_to_engagement_if_not_exists(cursor, 'comment_generated_at', 'TEXT')

        # --- 既存タイムスタンプのフォーマットをISO 8601に統一するマイグレーション処理 ---
        # この処理は一度実行されると、次回以降は更新対象がなくなる
        timestamp_columns = ['created_at', 'post_url_updated_at', 'ai_caption_created_at', 'posted_at']
        for col in timestamp_columns:
            # 'YYYY-MM-DD HH:MM:SS' 形式のレコードを探す
            cursor.execute(f"SELECT id, {col} FROM products WHERE {col} LIKE '____-__-__ __:__:__'")
            records_to_update = cursor.fetchall()
            if records_to_update:
                logging.info(f"'{col}' カラムの古いタイムスタンプ形式をISO 8601に変換します... (対象: {len(records_to_update)}件)")
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
        logging.info("データベースが正常に初期化されました。")
    except sqlite3.Error as e:
        logging.error(f"データベース初期化エラー: {e}")
def get_error_products_in_last_24h():
    """過去24時間以内に作成され、かつステータスが「エラー」の商品を取得する"""
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

def update_post_url(product_id, post_url):
    """指定された商品の投稿URLと更新日時を更新し、ステータスを「URL取得済」に変更する"""
    conn = get_db_connection()
    try:
        # JSTのタイムゾーンを定義
        jst = timezone(timedelta(hours=9))
        now_jst_iso = datetime.now(jst).isoformat()
        conn.execute("UPDATE products SET post_url = ?, post_url_updated_at = ?, status = 'URL取得済' WHERE id = ?", (post_url, now_jst_iso, product_id))
        conn.commit()
        logging.debug(f"商品ID: {product_id} の投稿URLを更新し、ステータスを「URL取得済」に変更しました。")
    finally:
        conn.close()

def update_ai_caption(product_id, caption):
    """指定された商品のAI投稿文と更新日時を更新し、ステータスを「投稿準備完了」に変更する"""
    conn = get_db_connection()
    try:
        # JSTのタイムゾーンを定義
        jst = timezone(timedelta(hours=9))
        now_jst_iso = datetime.now(jst).isoformat()
        conn.execute("UPDATE products SET ai_caption = ?, ai_caption_created_at = ?, status = '投稿準備完了' WHERE id = ?", (caption, now_jst_iso, product_id))
        conn.commit()
        logging.debug(f"商品ID: {product_id} のAI投稿文を更新し、ステータスを「投稿準備完了」に変更しました。")
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

def import_products(products_data: list[dict]):
    """
    複数の商品データを一括でデータベースにインポートする。
    URLが重複しているデータは無視される。
    """
    if not products_data:
        return 0

    # JSTのタイムゾーンを定義
    jst = timezone(timedelta(hours=9))
    # JSTの現在時刻をISO 8601形式の文字列で取得
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
        logging.info(f"{len(product_ids)}件の商品を削除しました。")
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
            d.get('recent_like_count', 0), d.get('recent_collect_count', 0), d.get('recent_comment_count', 0),
            d.get('recent_action_timestamp'),
            d.get('ai_prompt_message'), d.get('ai_prompt_updated_at')
        ) for d in users_data
    ]

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # 存在しない場合はINSERT、存在する場合は指定したカラムのみをUPDATE
        cursor.executemany("""
            INSERT INTO user_engagement (id, name, profile_page_url, profile_image_url, latest_action_timestamp, is_following, recent_like_count, recent_collect_count, recent_comment_count, recent_action_timestamp, ai_prompt_message, ai_prompt_updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                profile_page_url = COALESCE(excluded.profile_page_url, profile_page_url),
                profile_image_url = excluded.profile_image_url,
                -- 常に新しいタイムスタンプで上書きする
                latest_action_timestamp = CASE
                    WHEN excluded.latest_action_timestamp > latest_action_timestamp THEN excluded.latest_action_timestamp
                    ELSE latest_action_timestamp
                END,
                is_following = excluded.is_following,
                recent_like_count = recent_like_count + excluded.recent_like_count,
                recent_collect_count = recent_collect_count + excluded.recent_collect_count,
                recent_comment_count = recent_comment_count + excluded.recent_comment_count,
                ai_prompt_message = excluded.ai_prompt_message,
                ai_prompt_updated_at = excluded.ai_prompt_updated_at
        """, records_to_upsert)
        conn.commit()
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

def commit_user_actions(user_ids: list[str], is_comment_posted: bool):
    """
    指定されたユーザーのrecentアクションを累計に加算し、recentをリセットする。
    コメントが投稿された場合はlast_commented_atも更新する。
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
                recent_like_count = 0,
                recent_collect_count = 0,
                recent_comment_count = 0,
                last_commented_at = CASE WHEN ? THEN ? ELSE last_commented_at END
            WHERE id IN ({placeholders})
        """
        params = [is_comment_posted, datetime.now().isoformat()] + user_ids
        cursor.execute(update_query, params)
        conn.commit()
        logging.info(f"{cursor.rowcount}件のユーザーアクションをコミットしました。")
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
                AND (recent_like_count > 0 OR recent_collect_count > 0 OR recent_comment_count > 0)
        """
        cursor.execute(query, (threshold_time,))
        user_ids = [row['id'] for row in cursor.fetchall()]
        return user_ids
    finally:
        conn.close()

def get_users_for_commenting(limit: int = 10) -> list[dict]:
    """
    コメント投稿対象のユーザーを優先度順に取得する。

    - 基本: 24時間以内のアクションがあり、未コメントのユーザー
    - 例外: 最終コメントから3日以上経過し、かつ今セッションで5件以上のいいねがあるユーザー

    :param limit: 取得するユーザーの最大数
    :return: ユーザーデータの辞書のリスト
    """
    three_days_ago = (datetime.now() - timedelta(days=3)).isoformat()
    twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).isoformat()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = f"""
            SELECT * FROM user_engagement
            WHERE
                -- 必須項目のチェック
                (recent_like_count > 0 OR recent_collect_count > 0 OR recent_comment_count > 0) AND
                profile_page_url IS NOT NULL AND profile_page_url != '' AND profile_page_url != '取得失敗' AND
                comment_text IS NOT NULL AND comment_text != '' AND
                recent_action_timestamp IS NOT NULL
                AND (
                    -- 基本条件: 24時間以内のアクションがあり、未コメント
                    (last_commented_at IS NULL AND recent_action_timestamp >= '{twenty_four_hours_ago}')
                    OR
                    -- 例外条件: 3日以上経過し、今セッションでいいね5件以上
                    (last_commented_at IS NOT NULL AND last_commented_at < '{three_days_ago}' AND recent_like_count >= 5)
                )
            ORDER BY
                CASE
                    WHEN recent_like_count >= 5 AND ai_prompt_message LIKE '%過去にも%' THEN 0 -- 最優先: 今回5いいね以上 & 過去にもアクションあり
                    WHEN ai_prompt_message LIKE '%新規にフォローしてくれました%' AND ai_prompt_message LIKE '%いいね%' THEN 1
                    WHEN ai_prompt_message LIKE '%新規にフォローしてくれました%' THEN 2
                    WHEN ai_prompt_message LIKE '%常連の方です%' THEN 3
                    WHEN ai_prompt_message LIKE '%過去にも「いいね」をしてくれたことがあります%' THEN 4
                    WHEN ai_prompt_message LIKE '%今回も%' THEN 5
                    ELSE 6
                END,
                like_count DESC
            LIMIT ?
        """
        cursor.execute(query, (limit,))
        users = [dict(row) for row in cursor.fetchall()]
        return users
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
                ai_prompt_message IS NOT NULL AND ai_prompt_message != '' AND (
                    -- 条件1: 新規フォロワーは常に対象
                    ai_prompt_message LIKE '%新規にフォロー%'
                    OR
                    -- 条件2: いいねのみの場合は3件以上
                    (ai_prompt_message NOT LIKE '%新規にフォロー%' AND recent_like_count >= 3)
                ) AND (
                    -- 生成済みコメントのチェック
                    comment_generated_at IS NULL OR
                    ai_prompt_updated_at > comment_generated_at
                )
            ORDER BY latest_action_timestamp DESC
        """
        cursor.execute(query)

        users = [dict(row) for row in cursor.fetchall()]
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