import logging
import time
import random
from playwright.sync_api import Page, Error as PlaywrightError
import re
from app.utils.selector_utils import convert_to_robust_selector
from app.core.base_task import BaseTask
from app.core.database import get_user_details_for_like_back, update_engagement_error, commit_user_actions

logger = logging.getLogger(__name__)

class LikeBackTask(BaseTask):
    """
    指定された複数のユーザーに「いいね返し」を行うタスク。
    リピーター育成画面のサマリーからの実行を想定。
    """
    def __init__(self, user_ids: list[str], like_count: int, dry_run: bool = False):
        super().__init__(count=None, dry_run=dry_run)
        self.user_ids = user_ids
        self.like_count = like_count
        self.action_name = f"いいね返し ({len(user_ids)}人)"
        self.needs_browser = True
        self.use_auth_profile = True
        logger.debug(f"LikeBackTaskが初期化されました。Users: {len(user_ids)}人, LikeCount: {self.like_count}, DryRun: {self.dry_run}")

    def _execute_like_action(self, page: Page, user_id: str, user_name: str):
        """1ユーザーに対するいいね返し処理"""
        logger.info(f"ユーザー「{user_name}」に{self.like_count}件のいいね返しを開始します。")

        # 「いいね済み」のカードを特定して非表示にする
        all_cards_locator = page.locator(convert_to_robust_selector('div[class*="container--JAywt"]'))
        liked_button_selector = convert_to_robust_selector('button:has(div[class*="rex-favorite-filled--2MJip"])') # いいね済みボタンのセレクタ
        liked_button_locator = page.locator(liked_button_selector)
        try:
            # ページ上のカードが読み込まれるのを待ちます。
            all_cards_locator.first.wait_for(state="visible", timeout=15000)
            
            # 全カードの中から、「いいね済み」ボタンを持つカードだけを絞り込みます。
            liked_cards_locator = all_cards_locator.filter(has=liked_button_locator)
            count = liked_cards_locator.count()
            logger.debug(f"{count} 件の「いいね済み」カードが見つかりました。")

            if count > 0:
                #  絞り込んだカードを一括で非表示にします。
                liked_cards_locator.evaluate_all("nodes => nodes.forEach(n => n.style.display = 'none')")
                logger.debug(f"合計 {count} 件のカードを非表示にしました。")

            time.sleep(1) # 視覚的な確認のための待機
        except Exception as e:
            logger.error(f"エラー: 「いいね済み」の処理中に問題が発生しました。タイムアウトしたか、セレクタが古い可能性があります。")
            logger.error(f"詳細: {e}") # 詳細なエラーメッセージを出力

        liked_count = 0
        try:
            for _ in range(10): # 最大10回試行
                if liked_count >= self.like_count:
                    break
                
                time.sleep(1)
                card_selector_str = convert_to_robust_selector('div[class*="container--JAywt"]')
                target_card = page.locator(f"{card_selector_str}:visible").first
                target_card.evaluate("node => { node.style.border = '5px solid orange'; }")
                
                unliked_icon_selector = convert_to_robust_selector("div.rex-favorite-outline--n4SWN")
                unliked_button_locator = target_card.locator(f'button:has({unliked_icon_selector})')
                unliked_button_locator.evaluate("node => { node.style.border = '3px solid limegreen'; }")
                
                # ファイル名として使えない文字を置換
                safe_user_id = re.sub(r'[\\/:*?"<>|]', '_', user_id)

                self._execute_action(unliked_button_locator, "click", action_name=f"like_back_{safe_user_id}_{liked_count + 1}", screenshot_locator=target_card)
                liked_count += 1
                if not self.dry_run:
                    time.sleep(random.uniform(1, 3)) # 連続クリックを避けるための短い待機
                
                target_card.evaluate("node => { node.style.display = 'none'; }")

        except Exception as e:
            error_message = str(e).split("Call log:")[0].strip()
            log_message = f"「いいね返し」中にエラーが発生しました: {error_message}"
            logger.error(log_message)
            update_engagement_error(user_id, log_message)
            return False

        logger.info(f"  -> いいね返し完了。合計{liked_count}件実行しました。")
        return True

    def _execute_main_logic(self):
        users_details = get_user_details_for_like_back(self.user_ids)

        if not users_details:
            logger.warning("いいね返し対象のユーザー情報がDBから取得できませんでした。")
            logger.warning(f"フロントエンドから渡されたID(URL): {self.user_ids}")
            return True # エラーではないため正常終了とする
        
        for user in users_details:
            page = self.context.new_page()
            try:
                page.goto(user['user_page_url'], wait_until="domcontentloaded")
                if self._execute_like_action(page, user['user_id'], user['user_name']):
                    self._execute_side_effect(commit_user_actions, user_ids=[user['user_id']], is_comment_posted=False, action_name="commit_like_back_action")
            finally:
                page.close()
        return True

def run_like_back(user_ids: list[str], like_count: int, dry_run: bool = False):
    """LikeBackTaskのラッパー関数"""
    task = LikeBackTask(user_ids=user_ids, like_count=like_count, dry_run=dry_run)
    return task.run()