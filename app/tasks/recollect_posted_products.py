import logging
from app.core.database import get_db_connection, init_db
from app.tasks.delete_room_post import run_delete_room_post

logger = logging.getLogger(__name__)


def _fetch_recent_posted_products(limit: int):
    """
    status='投稿済' かつ room_url がある商品を「古い順」に取得する。
    ai_caption に「#オリジナル写真」を含むものは除外。
    limit <= 0 の場合は上限なし。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    base_sql = """
        SELECT id, room_url
        FROM products
        WHERE status = '投稿済'
          AND room_url IS NOT NULL
          AND TRIM(room_url) != ''
          AND (ai_caption NOT LIKE '%#オリジナル写真%' OR ai_caption IS NULL)
        ORDER BY posted_at ASC, id ASC
    """
    if limit and limit > 0:
        cursor.execute(base_sql + " LIMIT ?", (limit,))
    else:
        cursor.execute(base_sql)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def run_recollect_posted_products(count: int = 5, **kwargs):
    """
    投稿済商品のROOM投稿を再コレ（再在庫化）するタスク。
    """
    init_db()
    products = _fetch_recent_posted_products(count)
    if not products:
        logger.info("再コレ対象の商品がありません（投稿済 & room_urlあり）。")
        return 0, 0

    logger.info("再コレ対象件数: %s", len(products))
    return run_delete_room_post(products=products, action="recollect")
