import logging
import time
from datetime import datetime, timedelta
import random
from typing import List
from playwright.sync_api import Page, Error as PlaywrightError
from app.utils.selector_utils import convert_to_robust_selector
from app.core.database import commit_user_actions, update_engagement_error
from app.core.base_task import BaseTask

logger = logging.getLogger(__name__)

class NewCommentBackTask(BaseTask):
    """
    【新】「コメント返し」専門タスク。
    """
    def __init__(self, users: List[dict], dry_run: bool = False):
        super().__init__(count=None, dry_run=dry_run)
        self.users = users
        self.action_name = f"コメント返し ({len(users)}人)"
        self.needs_browser = True
        self.use_auth_profile = True
        logger.debug(f"NewCommentBackTaskが初期化されました。Users: {len(users)}人, DryRun: {self.dry_run}")

    def _post_comment(self, page: Page, user_id: str, user_name: str, comment_text: str):
        """コメント返し処理（okaeshi_action.pyから移植）"""
        if not comment_text:
            logger.debug("投稿するコメントがないため、スキップします。")
            return False

        logger.info(f"「{user_name}」にコメント返しを開始します。")
        # ページを一番上までスクロール
        logger.debug(f"  -> 最新投稿にコメントします。")
        page.evaluate("window.scrollTo(0, 0)")
        
        # いいね返し処理で非表示にされたカードを再表示させるため、ページをリロードする
        logger.debug("  -> ページをリロードして全投稿を再表示します。")
        page.reload(wait_until="domcontentloaded", timeout=40000)
        time.sleep(30) # リロード後の描画を少し待つ
        # 最初の投稿カードが表示されるのを待つことで、動的な描画完了を確実にする
        post_card_selector = convert_to_robust_selector("div.container--JAywt")
        page.locator(post_card_selector).first.wait_for(state="visible", timeout=30000)

        try:
            logger.debug("  -> 投稿カードが表示されるのを待ちます。")
           # --- 1. コメント数が最も多い投稿を探す ---
            post_cards_locator = page.locator(post_card_selector)
            post_cards_locator.first.wait_for(state="visible", timeout=15000)
            
            all_posts = post_cards_locator.all()
            if not all_posts:
                logger.error("  -> コメント対象の投稿が見つかりませんでした。")
                return False

            max_comments = -1
            target_post_card = all_posts[0] # フォールバックとして最初の投稿を保持

            comment_icon_selector = convert_to_robust_selector("div.rex-comment-outline--2vaPK")
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
            target_post_card.scroll_into_view_if_needed()
            time.sleep(0.5)
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
            logger.debug(f"  -> 送信ボタンをクリックします")
            send_button = page.get_by_role("button", name="送信")
            self._execute_action(send_button, "click", action_name=f"post_comment_{user_id}")

            if not self.dry_run:
                time.sleep(3)
                logger.debug(f"  -> コメント返しが完了しました。")
            return True
        except PlaywrightError as e:
            log_message = f"「コメント返し」中にエラーが発生しました: {e}"
            logger.error(log_message, exc_info=True)
            update_engagement_error(user_id, log_message)
            self._take_screenshot_on_error(prefix=f"new_comment_error_{user_id}")
            return False

    def _execute_main_logic(self):
        processed_count = 0
        error_count = 0

        for user in self.users:
            user_id = user.get("id")
            user_name = user.get("name")
            profile_page_url = user.get("profile_page_url")
            comment_text = user.get("comment_text")
            last_commented_at_str = user.get("last_commented_at")

            if not profile_page_url or profile_page_url == '取得失敗':
                logger.warning(f"ユーザー「{user_name}」のプロフィールURLが無効なため、スキップします。")
                error_count += 1
                continue

            # コメント実行可否を判定
            can_comment = False
            if comment_text:
                # --- database.py の _add_engagement_type_to_users とロジックを完全に一致させる ---
                three_days_ago = datetime.now() - timedelta(days=3)
                last_commented_at = datetime.fromisoformat(last_commented_at_str) if last_commented_at_str else None
                
                # 1. 共通の前提条件: 3日間の再コメント期間をクリアしているか (新規ユーザーは常にTrue)
                can_comment_today = not last_commented_at or last_commented_at < three_days_ago

                if can_comment_today:
                    # 2. 個別の条件: 条件Aまたは条件Bを満たすか
                    recent_likes = user.get("recent_like_count", 0)
                    recent_follows = user.get("recent_follow_count", 0)
                    is_following = user.get("is_following", 0) == 1
                    # 条件A: いいね5件以上
                    is_like_based_target = (recent_likes >= 5)
                    # 条件B: フォロー済み & 新規フォローバック & いいね1件以上
                    is_follow_based_target = (is_following and recent_follows > 0 and recent_likes >= 1)

                    if is_like_based_target or is_follow_based_target:
                        can_comment = True
                        reason_type = "新規" if not last_commented_at else "再コメント"
                        reason_detail = f"いいね{recent_likes}件" if is_like_based_target else f"フォローバック&いいね{recent_likes}件"
                        logger.info(f"  -> {reason_type}コメント条件を満たしたため、投稿を実行します。({reason_detail})")
                    else:
                        reasons = []
                        if not is_after_3_days:
                            reasons.append("最終コメントから3日経過していない")
                        if not (is_like_based_target or is_follow_based_target):
                            reasons.append(f"いいね数またはフォロー条件未達 (いいね:{recent_likes}, フォローバック:{recent_follows})")
                        logger.info(f"  -> 再コメント条件を満たさないため、コメントはスキップします。({', '.join(reasons)})")
                else: # can_comment_today が False の場合
                    reasons = []
                    if not can_comment_today:
                        reasons.append("最終コメントから3日経過していない")
                    logger.info(f"  -> 再コメント条件を満たさないため、コメントはスキップします。({', '.join(reasons)})")
            if not can_comment:
                # can_commentがFalseになる理由は、上記のロジックで既にINFOレベルでログ出力されているため、
                # ここでの追加のログは不要。
                continue

            page = None
            try:
                page = self.context.new_page()
                page.goto(profile_page_url, wait_until="domcontentloaded")
                
                if self._post_comment(page, user_id, user_name, comment_text):
                    processed_count += 1
                    self._execute_side_effect(
                        commit_user_actions,
                        user_ids=[user_id],
                        is_comment_posted=True,
                        post_url=page.url if not self.dry_run else None,
                        action_name="commit_comment_action"
                    )
                else:
                    error_count += 1
            except Exception as e:
                logger.error(f"ユーザー「{user_name}」のコメント返し処理中にエラー: {e}", exc_info=True)
                self._take_screenshot_on_error(prefix=f"new_comment_back_error_{user_id}")
                error_count += 1
            finally:
                if page:
                    page.close()

        return processed_count, error_count

def run_new_comment_back(users: List[dict], dry_run: bool = False, **kwargs):
    """NewCommentBackTaskのラッパー関数"""
    task = NewCommentBackTask(users=users, dry_run=dry_run)
    result = task.run()
    return result if isinstance(result, tuple) else (0, 0)