import logging
import os
from playwright.sync_api import Page, Error
from app.core.database import get_db_connection

# --- 設定 ---
# 確認したい日付 (YYYY-MM-DD形式)
TARGET_DATE_STR = "2025-11-17"

logger = logging.getLogger(__name__)

def get_posted_products_by_date(target_date: str) -> list[dict]:
    """
    指定された日付に投稿された商品情報をDBから取得する。
    :param target_date: 'YYYY-MM-DD' 形式の日付文字列
    :return: 商品情報の辞書のリスト
    """
    logger.debug(f"DBから '{target_date}' に投稿された商品を取得します。")
    conn = get_db_connection()
    # `row_factory` を設定して、結果を辞書形式で受け取れるようにする
    conn.row_factory = lambda cursor, row: {col[0]: row[idx] for idx, col in enumerate(cursor.description)}
    cursor = conn.cursor()
    
    # `posted_at` はDATETIME型なので、date()関数で日付部分のみを比較する
    cursor.execute(
        "SELECT id, url, name FROM products WHERE status = '投稿済' AND date(posted_at) = ?",
        (target_date,)
    )
    products = cursor.fetchall()
    conn.close()
    logger.debug(f"{len(products)}件の対象商品が見つかりました。")
    return products


def run_test(page: Page):
    """
    指定された日付に投稿された商品詳細ページを開き、削除ボタンの有無を確認するテスト。
    このテストは、自分の投稿を確認することを想定しているため、認証済みのブラウザで実行する必要があります。
    """
    logger.info(f"--- 投稿済み商品の削除ボタン存在確認テストを開始します ---")
    logger.info(f"対象日付: {TARGET_DATE_STR}")

    # 1. DBから対象商品を取得
    products_to_check = get_posted_products_by_date(TARGET_DATE_STR)

    if not products_to_check:
        logger.info("確認対象の商品はありませんでした。")
        return

    total_count = len(products_to_check)
    found_count = 0
    not_found_count = 0

    # 2. 各商品をループして確認
    for i, product in enumerate(products_to_check):
        product_url = product.get("url")
        product_name = product.get("name", "名前不明")
        display_name = (product_name[:40] + '...') if len(product_name) > 40 else product_name

        logger.info(f"[{i+1}/{total_count}] 確認中: {display_name}")

        if not product_url:
            logger.warning("  -> URLがありません。スキップします。")
            not_found_count += 1
            continue
        
        try:
            page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
            
            # 削除ボタンのセレクタ (「削除する」というテキストを持つボタンを想定)
            delete_button_selector = 'button:has-text("削除する")'
            
            if page.locator(delete_button_selector).count() > 0:
                logger.info("  -> ✅ 削除ボタンを発見しました。")
                found_count += 1
            else:
                logger.warning("  -> ❌ 削除ボタンが見つかりませんでした。")
                not_found_count += 1

        except Error as e:
            logger.error(f"  -> ページの処理中にエラーが発生しました: {e}")
            not_found_count += 1

    logger.info(f"--- テスト完了 ---")
    logger.info(f"結果: 削除ボタン発見 {found_count}件, 見つからず/エラー {not_found_count}件 (合計: {total_count}件)")


# --- スクリプトのエントリーポイント ---
if 'page' in locals() or 'page' in globals():
    run_test(page)
else:
    logger.warning("このスクリプトは 'run_task.py manual-test' からの実行を想定しています。")