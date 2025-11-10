import logging
import time
import random
from playwright.sync_api import Page, Error
from app.utils.selector_utils import convert_to_robust_selector

# --- 設定 ---
# いいねする目標件数
TARGET_COUNT = 2
# テスト対象のユーザーページURL
SOURCE_URL = "https://room.rakuten.co.jp/room_1c5608038c/items"

logger = logging.getLogger(__name__)

def run_test(page: Page):
    """
    指定されたユーザーページを巡回し、「いいね」を順番に実行するテスト。
    """
    logger.info(f"--- ユーザーページ巡回いいねテストを開始します ---")
    logger.info(f"対象URL: {SOURCE_URL}")
    logger.info(f"目標いいね数: {TARGET_COUNT}件")

    liked_count = 0
    scroll_count = 0
    max_scroll_attempts = 20 # 無限ループを避けるための最大スクロール回数

    try:
        page.goto(SOURCE_URL.strip(), wait_until="domcontentloaded", timeout=60000)
        page_title = page.title()
        logger.info(f"ページにアクセスしました: {page_title}")

        # --- いいね済みカードを非表示にする ---
        all_cards_locator = page.locator(convert_to_robust_selector('div[class*="container--JAywt"]'))
        liked_button_selector = convert_to_robust_selector('button:has(div[class*="rex-favorite-filled--2MJip"])')
        liked_button_locator = page.locator(liked_button_selector)
        try:
            all_cards_locator.first.wait_for(state="visible", timeout=15000)
            liked_cards_locator = all_cards_locator.filter(has=liked_button_locator)
            count = liked_cards_locator.count()
            if count > 0:
                liked_cards_locator.evaluate_all("nodes => nodes.forEach(n => n.style.display = 'none')")
                logger.debug(f"ページ読み込み時に存在した「いいね済み」カード {count} 件を非表示にしました。")
            time.sleep(2)
        except Exception as e:
            logger.warning(f"いいね済みカードの非表示処理中にエラーが発生しましたが、処理を続行します: {e}")

        # --- メインループ ---
        while liked_count < TARGET_COUNT and scroll_count < max_scroll_attempts:
            logger.debug(f"--- ループ開始 (現在 {liked_count}/{TARGET_COUNT} 件) ---")

            # 画面に表示されている「未いいね」のカードを1件取得
            card_selector_str = convert_to_robust_selector('div[class*="container--JAywt"]')
            unliked_icon_selector = convert_to_robust_selector("div.rex-favorite-outline--n4SWN")
            
            # :visibleセレクタで非表示のカードを除外し、:has()で未いいねボタンを持つカードに絞り込む
            target_card = page.locator(f"{card_selector_str}:visible:has({unliked_icon_selector})").first

            if target_card.count() > 0:
                logger.debug("  -> 未いいねのカードを発見しました。")
                target_card.evaluate("node => { node.style.border = '5px solid orange'; }")

                # --- 商品紹介文の取得とログ出力 ---
                description_selector = convert_to_robust_selector('div[class*="social-text-area--"]')
                description_element = target_card.locator(description_selector).first
                if description_element.count() > 0:
                    description_text = description_element.text_content().replace('\n', ' ').strip()
                    display_text = (description_text[:30] + '...') if len(description_text) > 30 else description_text
                    logger.info(f"  -> 商品紹介文: {display_text}")
                else:
                    logger.debug("  -> 商品紹介文が見つかりませんでした。")
                
                # カード内の「未いいね」ボタンをクリック
                unliked_button_locator = target_card.locator(f'button:has({unliked_icon_selector})')
                unliked_button_locator.evaluate("node => { node.style.border = '3px solid limegreen'; }")
                
                logger.info(f"  -> [{liked_count + 1}/{TARGET_COUNT}] いいねボタンをクリックします。")
                unliked_button_locator.click()
                liked_count += 1
                time.sleep (11)
                # 処理済みのカードは非表示にする
                target_card.evaluate("node => { node.style.display = 'none'; }")
                time.sleep(random.uniform(3, 5)) # 連続クリックを避けるための待機

            else:
                # 処理対象のカードがなければスクロール
                logger.debug("  -> 画面上に未いいねのカードがありません。新しいカードを読み込むためスクロールします。")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                scroll_count += 1
                try:
                    spinner_selector = 'div[aria-label="loading"]'
                    page.locator(spinner_selector).wait_for(state="visible", timeout=3000)
                    page.locator(spinner_selector).wait_for(state="hidden", timeout=30000)
                    time.sleep(2) # 描画を待つ
                except Error:
                    logger.warning("  -> スピナーが表示されませんでした。ページの終端かもしれません。")
                    time.sleep(2)

    except Exception as e:
        logger.error(f"テスト実行中に予期せぬエラーが発生しました: {e}", exc_info=True)
    finally:
        logger.info(f"--- テスト完了 ---")
        logger.info(f"合計 {liked_count} 件の「いいね」を実行しました。")

# --- スクリプトのエントリーポイント ---
if 'page' in locals() or 'page' in globals():
    run_test(page)
else:
    logger.warning("このスクリプトは 'run_task.py manual-test --script test_scripts/test_like_in_user_page.py' からの実行を想定しています。")