import logging
from playwright.sync_api import Page, TimeoutError

logger = logging.getLogger(__name__)

def generate_errors(page: Page):
    """
    意図的にPlaywrightのタイムアウトエラーとPythonの一般的な例外を発生させるテスト関数。
    """
    logger.info("--- エラー発生テストを開始します ---")

    # --- 1. PlaywrightのTimeoutErrorを発生させる ---
    # 存在しない要素を短いタイムアウトで待機することで、Call logを含むエラーを発生させる
    logger.info("1. PlaywrightのTimeoutErrorを発生させます...")
    try:
        # 存在しないであろう複雑なセレクタを指定
        non_existent_selector = "div#a.b_c[data-test-id='non-existent-element-for-testing']"
        page.locator(non_existent_selector).wait_for(timeout=1000)
    except TimeoutError as e:
        # exc_info=True を指定して、トレースバックがログシステムに渡されるようにする
        logger.error(f"Playwrightのタイムアウトエラーを捕捉しました: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"予期せぬエラーが発生しました: {e}", exc_info=True)

    logger.info("---")

    # --- 2. Pythonの一般的な例外 (ZeroDivisionError) を発生させる ---
    # Tracebackを発生させる
    logger.info("2. Pythonの一般的な例外（ZeroDivisionError）を発生させます...")
    try:
        result = 1 / 0
    except ZeroDivisionError as e:
        logger.error(f"ゼロ除算エラーを捕捉しました: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"予期せぬエラーが発生しました: {e}", exc_info=True)

    logger.info("--- エラー発生テストを完了しました ---")

# manual-testタスクから実行されるためのエントリーポイント
if 'page' in locals() or 'page' in globals():
    generate_errors(page)