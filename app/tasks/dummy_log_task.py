import logging
import time
import random

def run_dummy_log_reproducer():
    """
    ダッシュボードのエラー件数問題を再現するためのログを生成するダミータスク。
    実際の処理は行わず、ログ出力のみを行う。
    """
    logging.info("--- (デバッグ用) ログ再現タスクを開始します ---")

    # --- 記事投稿フローの再現 ---
    logging.info("--- フロー実行: 「記事投稿」を開始します。 ---")
    time.sleep(1)
    logging.info("ログイン状態は正常です。 [1]")
    time.sleep(2)
    
    error_product_ids = [3570, 3587, 3606]
    for pid in error_product_ids:
        logging.error(f"商品ID {pid} の投稿処理中にエラーが発生しました: Locator.click: Timeout 10000ms exceeded.")
        time.sleep(0.1)
        logging.info(f"商品ID: {pid} のステータスを「エラー」に更新しました。")
        time.sleep(random.uniform(1, 3))
    
    logging.info("合計 5 件のカードを処理しました。")
    time.sleep(0.5)
    logging.info("--- 商品URLとROOM URLの紐付けを終了します ---")
    time.sleep(0.5)
    logging.info("--- フロー完了: 「記事投稿」が正常に完了しました。(実行時間: 9分57秒) ---")
    time.sleep(0.1)
    logging.info("[Action Summary] name=記事投稿, count=2, errors=3")
    time.sleep(2)

    # --- 商品削除フローの再現 ---
    logging.info("--- フロー実行: 「（内部処理）商品削除フロー」を開始します。 ---")
    time.sleep(1)
    logging.info("ログイン状態は正常です。 [1]")
    time.sleep(1)
    logging.info("--- フロー完了: 「（内部処理）商品削除フロー」が正常に完了しました。(実行時間: 1分9秒) ---")
    time.sleep(0.1)
    logging.info("[Action Summary] name=投稿削除, count=1, errors=0")
    time.sleep(2)

    # --- いいね活動フローの再現 ---
    logging.info("--- フロー実行: 「いいね活動」を開始します。 ---")
    time.sleep(1)
    logging.info("ログイン状態は正常です。 [1]")
    time.sleep(2)
    logging.info("--- フロー完了: 「いいね活動」が正常に完了しました。(実行時間: 9分43秒) ---")
    time.sleep(0.1)
    logging.info("[Action Summary] name=いいね活動, count=50, errors=0")
    time.sleep(2)

    logging.info("--- (デバッグ用) ログ再現タスクが完了しました ---")