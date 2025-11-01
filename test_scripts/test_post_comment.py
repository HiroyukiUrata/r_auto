import logging
import time
import os
from playwright.sync_api import Page, Error as PlaywrightError, expect

# 必要なユーティリティをインポートします
from app.utils.selector_utils import convert_to_robust_selector

# manual-testタスクから page と context オブジェクトが自動的に渡されます。

# --- ★★★ 設定項目 ★★★ ---
# テスト対象のユーザーのROOM URL
TARGET_USER_URL = "https://room.rakuten.co.jp/room_57b00b8c27/items"
# 投稿するコメント（テスト用に長めの文字列も試せます）
COMMENT_TEXT = "素敵な投稿ですね！"
# --------------------------

logger = logging.getLogger(__name__)


def run_test(page: Page):
    """
    指定されたユーザーページにアクセスし、コメント投稿処理をテストします。
    """
    logger.info(f"--- コメント投稿テストを開始します ---")
    logger.info(f"対象ユーザーURL: {TARGET_USER_URL}")

    # 1. 対象ユーザーのページにアクセス
    page.goto(TARGET_USER_URL, wait_until="domcontentloaded")
    logger.debug(f"  -> プロフィールページにアクセスしました。")

    # 2. コメント投稿処理を実行
    try:
        post_comment(page, COMMENT_TEXT)
    except Exception as e:
        logger.error(f"テスト実行中にエラーが発生しました: {e}", exc_info=True)
        page.screenshot(path="error_screenshot_comment_test.png")
        logger.error("エラーが発生したため、'error_screenshot_comment_test.png' にスクリーンショットを保存しました。")


def post_comment(page: Page, comment_text: str):
    """コメント投稿のメインロジック"""
    if not comment_text:
        logger.debug("投稿するコメントがないため、スキップします。")
        return False

    logger.debug(f"  -> 最新投稿にコメントします。")
    # engage_user.pyの実装に合わせ、ページ読み込みをしっかり待つ
    logger.debug("  -> ページ全体の動的コンテンツが読み込まれるのを20秒間待ちます。")
    time.sleep(20)

    try:
        # --- 1. コメント対象の投稿を探す ---
        logger.debug("  -> 投稿カードが表示されるのを待ちます。")
        post_card_selector = convert_to_robust_selector("div.container--JAywt")
        post_cards_locator = page.locator(post_card_selector)
        post_cards_locator.first.wait_for(state="visible", timeout=15000)
        
        all_posts = post_cards_locator.all()
        if not all_posts:
            logger.error("  -> コメント対象の投稿が見つかりませんでした。")
            return False

        max_comments = -1
        target_post_card = all_posts[0] # フォールバックとして最初の投稿を保持

        comment_icon_selector = convert_to_robust_selector("div.rex-comment-outline--2vaPK")
        logger.debug("  -> コメント数が最も多い投稿を探します...")
        for post_card in all_posts:
            try:
                comment_icon = post_card.locator(comment_icon_selector)
                if comment_icon.count() > 0:
                    comment_count_element = comment_icon.locator("xpath=./following-sibling::div[1]")
                    comment_count = int(comment_count_element.inner_text())
                    if comment_count > max_comments:
                        max_comments = comment_count
                        target_post_card = post_card
            except (ValueError, PlaywrightError):
                continue
        
        if max_comments < 1:
            logger.debug("  -> コメントが1件以上の投稿が見つからなかったため、最初の投稿を対象とします。")
        else:
            logger.debug(f"  -> コメント数が最も多い投稿が見つかりました (コメント数: {max_comments})。")

        # --- 2. 投稿の詳細ページに遷移 ---
        image_link_selector = convert_to_robust_selector("a.link-image--15_8Q")
        # クリック前に要素が画面内に表示されるようにスクロールする
        target_post_card.scroll_into_view_if_needed()
        time.sleep(0.5) # スクロール後の描画を少し待つ
        target_post_card.locator(image_link_selector).click()
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        logger.debug(f"  -> 投稿詳細ページに遷移しました: {page.url}")

        # --- 3. コメントボタンをクリック ---
        logger.debug(f"  -> コメントボタンをクリックしてコメント画面を開きます")
        comment_button_selector = convert_to_robust_selector('div.pointer--3rZ2h:has-text("コメント")')
        page.locator(comment_button_selector).click()
        time.sleep(3)

        # --- 4. コメントを入力 ---
        logger.debug(f"  -> コメント入力欄にコメントを挿入します")
        comment_textarea = page.locator('textarea[placeholder="コメントを書いてください"]')
        comment_textarea.wait_for(state="visible", timeout=15000)
        comment_textarea.fill(comment_text)
        time.sleep(3)

        # --- 5. 送信ボタンをクリック ---
        logger.debug(f"  -> 送信ボタンのクリックをスキップし、スクリーンショットを撮影します。")
        
        # スクリーンショット保存用ディレクトリを作成
        screenshot_dir = "test_scripts/screenshot"
        os.makedirs(screenshot_dir, exist_ok=True)
        screenshot_path = os.path.join(screenshot_dir, "before_sending_comment.png")
        page.screenshot(path=screenshot_path)
        logger.info(f"送信直前のスクリーンショットを保存しました: {screenshot_path}")

        if False: # テストのため、実際の送信は行わない
            page.get_by_role("button", name="送信").click()
            # 投稿完了を待機
            time.sleep(3)
            logger.info(f"  -> コメント投稿が完了しました。投稿URL: {page.url}")
        
        return True

    except PlaywrightError as e:
        logger.error(f"コメント投稿中にエラーが発生しました: {e}")
        raise  # エラーを再送出して、呼び出し元でハンドルできるようにする


# --- スクリプトのエントリーポイント ---
# manual-testタスクは、スクリプトファイル内で 'page' と 'context' という名前の
# グローバル変数にアクセスできる状態でコードを実行します。

if 'page' in locals() or 'page' in globals():
    run_test(page)
else:
    logger.warning("このスクリプトは 'run_task.py manual-test' からの実行を想定しています。")