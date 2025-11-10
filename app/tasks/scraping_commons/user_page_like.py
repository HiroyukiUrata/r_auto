import logging
import time
import random
from playwright.sync_api import Page, Error
from app.utils.selector_utils import convert_to_robust_selector
from app.core.base_task import BaseTask

logger = logging.getLogger(__name__)

class UserPageLiker:
    """
    指定されたユーザーページを巡回し、「いいね」を順番に実行する共通クラス。
    """
    def __init__(self, task_instance: BaseTask, page: Page, target_url: str, target_count: int):
        """
        コンストラクタ
        :param task_instance: 呼び出し元のBaseTaskインスタンス
        :param page: PlaywrightのPageオブジェクト
        :param target_url: いいねを実行する対象のユーザーページURL
        :param target_count: いいねする目標件数
        """
        self.task_instance = task_instance
        self.page = page
        self.target_url = target_url
        self.target_count = target_count
        # dry_runモードは呼び出し元のタスクインスタンスから継承する
        self.dry_run = self.task_instance.dry_run

    def execute(self) -> tuple[int, int]:
        """
        いいね処理を実行し、実際にいいねした成功数とエラー数をタプルで返す。
        :return: (成功数, エラー数)
        """
        logger.info(f"--- ページ巡回いいね処理を開始します ---")
        logger.info(f"対象URL: {self.target_url}")
        logger.info(f"目標いいね数: {self.target_count}件")
        if self.dry_run:
            logger.info("DRY RUNモードで実行します。実際のアクションは行われません。")

        liked_count = 0
        error_count = 0
        scroll_count = 0
        max_scroll_attempts = 20  # 無限ループを避けるための最大スクロール回数

        try:
            self.page.goto(self.target_url.strip(), wait_until="domcontentloaded", timeout=60000)
            page_title = self.page.title()
            logger.info(f"ページにアクセスしました: {page_title}")

            # --- いいね済みカードを非表示にする ---
            all_cards_locator = self.page.locator(convert_to_robust_selector('div[class*="container--JAywt"]'))
            liked_button_selector = convert_to_robust_selector('button:has(div[class*="rex-favorite-filled--2MJip"])')
            liked_button_locator = self.page.locator(liked_button_selector)
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
            # 目標「試行回数」に達するまでループする
            while (liked_count + error_count) < self.target_count and scroll_count < max_scroll_attempts:
                logger.debug(f"--- ループ開始 (現在 {liked_count}/{self.target_count} 件) ---")

                card_selector_str = convert_to_robust_selector('div[class*="container--JAywt"]')
                unliked_icon_selector = convert_to_robust_selector("div.rex-favorite-outline--n4SWN")
                target_card = self.page.locator(f"{card_selector_str}:visible:has({unliked_icon_selector})").first

                if target_card.count() > 0:
                    logger.debug("  -> 未いいねのカードを発見しました。")
                    try:
                        target_card.evaluate("node => { node.style.border = '5px solid orange'; }")

                        description_selector = convert_to_robust_selector('div[class*="social-text-area--"]')
                        description_element = target_card.locator(description_selector).first
                        if description_element.count() > 0:
                            description_text = description_element.text_content().replace('\n', ' ').strip()
                            display_text = (description_text[:30] + '...') if len(description_text) > 30 else description_text
                            logger.info(f"  -> 商品紹介文: {display_text}")

                        unliked_button_locator = target_card.locator(f'button:has({unliked_icon_selector})')
                        unliked_button_locator.evaluate("node => { node.style.border = '3px solid limegreen'; }")

                        logger.info(f"  -> [{liked_count + 1}/{self.target_count}] いいねボタンをクリックします。")
                        
                        # BaseTaskの共通アクション実行メソッドを呼び出す
                        self.task_instance._execute_action(
                            unliked_button_locator, "click",
                            action_name=f"user_page_like_{liked_count + 1}",
                            screenshot_locator=target_card
                        )

                        liked_count += 1
                        logger.debug("  -> いいね成功。")

                        # dry_runモードでない場合のみ待機
                        if not self.dry_run:
                            time.sleep(random.uniform(3, 5))
                    except Exception as e:
                        error_message = str(e).split("Call log:")[0].strip()
                        logger.warning(f"  -> いいねクリック中にエラーが発生しました: {error_message}")
                        error_count += 1
                    finally:
                        # 成功・失敗にかかわらず、処理したカードは非表示にする
                        target_card.evaluate("node => { node.style.display = 'none'; }")

                else:
                    logger.debug("  -> 画面上に未いいねのカードがありません。新しいカードを読み込むためスクロールします。")
                    self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    scroll_count += 1
                    try:
                        spinner_selector = 'div[aria-label="loading"]'
                        self.page.locator(spinner_selector).wait_for(state="visible", timeout=3000)
                        self.page.locator(spinner_selector).wait_for(state="hidden", timeout=30000)
                        time.sleep(2)
                    except Error:
                        logger.warning("  -> スピナーが表示されませんでした。ページの終端かもしれません。")
                        time.sleep(2)

        except Exception as e:
            logger.error(f"ページ巡回いいね処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
        finally:
            logger.info(f"--- ページ巡回いいね処理を完了します ---")
            logger.info(f"結果: 成功 {liked_count}件, 失敗 {error_count}件")
            return liked_count, error_count