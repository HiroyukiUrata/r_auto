import logging
import random
import time
from datetime import datetime, timedelta
from playwright.sync_api import Page, Error as PlaywrightError
from app.utils.selector_utils import convert_to_robust_selector 
from app.core.database import commit_user_actions, update_engagement_error
from app.core.base_task import BaseTask

logger = logging.getLogger(__name__)

class EngageUserTask(BaseTask):
    """
    指定されたユーザーに対して「いいねバック」と「コメント投稿」を行うタスク。
    """
    def __init__(self, users: list[dict], dry_run: bool = False, engage_mode: str = 'all', like_count: int = None):
        super().__init__(count=None, dry_run=dry_run)
        self.action_name = f"複数ユーザーへのエンゲージメント ({len(users)}人)"
        self.needs_browser = True
        self.use_auth_profile = True

        # タスク実行に必要な引数を設定
        self.users = users
        self.engage_mode = engage_mode # 'all', 'like_only', 'comment_only'
        self.like_count = like_count # 画面から指定されたいいね数
        logger.debug(f"EngageUserTaskが初期化されました。Mode: {self.engage_mode}, DryRun: {self.dry_run}, LikeCount: {self.like_count}")

    def _like_back(self, page: Page, user_id: str, user_name: str, like_back_count: int, profile_page_url: str):
        """いいね返し処理"""
        # APIからlike_countが指定されている場合（画面入力がある場合）は、その値を最優先する
        if self.like_count is not None and self.like_count > 0:
            target_like_count = self.like_count
            logger.debug(f"「全員表示ON」モードのため、APIから指定されたいいね数 ({self.like_count}件) を使用します。")
        # APIから指定がない場合（全員表示OFFモード）、通知から得られたいいね数（like_back_count）を元に決定する
        elif like_back_count > 0:
            target_like_count = min(like_back_count, 5)
            logger.debug(f"「全員表示OFF」モードのため、通知ベースのいいね返しを実行します (recent_like_count: {like_back_count}件)。上限5件適用後: {target_like_count}件")
        else:
            # APIからの指定もなく、通知からのいいねもない場合（新規フォロワーなど）は0件とする
            target_like_count = 0
            logger.debug(f"「全員表示OFF」モードで、いいね返し対象外のため、いいねは実行しません。")

        if target_like_count <= 0:
            logger.debug(f"いいね返しの対象件数が0のため、スキップします。")
            return True # 処理不要なので成功扱い

        from app.tasks.scraping_commons.user_page_like import UserPageLiker
        liker = UserPageLiker(
            task_instance=self,
            page=page,
            target_url=profile_page_url,
            target_count=target_like_count
        )
        liked_count, error_count = liker.execute()
        
        return liked_count > 0 or self.dry_run

    def _post_comment(self, page: Page, user_id: str, user_name: str, comment_text: str):
        """コメント返し処理"""
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
            # 参考スクリプトに合わせて、より内側のコンテナをカードとして特定する
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
            time.sleep(3)#ページ読み込みをしっかり待つ

            # --- 4. コメントを入力 ---
            logger.debug(f"  -> コメント入力欄にコメントを挿入します")
            comment_textarea = page.locator('textarea[placeholder="コメントを書いてください"]')
            comment_textarea.wait_for(state="visible", timeout=15000)
            comment_textarea.fill(comment_text)
            time.sleep(3)#ページ読み込みをしっかり待つ
            #time.sleep(random.uniform(0.5, 1))


           # --- 5. 送信ボタンをクリック ---
            logger.debug(f"  -> 送信ボタンをクリックします")
            send_button = page.get_by_role("button", name="送信")
            self._execute_action(send_button, "click", action_name=f"post_comment_{user_id}")

            # ドライランでない場合のみ、投稿完了の待機とログ出力を行う
            if not self.dry_run:
                # 投稿完了を待機
                time.sleep(3)
                #logger.info(f"  -> コメント返しが完了しました。投稿URL: {page.url}")
                logger.info(f"  -> コメント返しが完了しました。")
            return True

        except PlaywrightError as e:
            # Call Logを除いたエラーメッセージを生成
            error_message = str(e).split("Call log:")[0].strip()
            log_message = f"「コメント返し」中にエラーが発生しました: {error_message}"
            logger.error(log_message)
            update_engagement_error(user_id, log_message)
            self._take_screenshot_on_error(prefix=f"comment_error_{user_id}")
            return False

    def _execute_main_logic(self):
        total_users = len(self.users)
        like_back_processed_count = 0
        comment_processed_count = 0
        like_back_error_count = 0
        comment_error_count = 0
        
        for i, user in enumerate(self.users):
            user_id = user.get("id")
            user_name = user.get("name")
            profile_page_url = user.get("profile_page_url")
            
            # ループごとに成功フラグをリセット
            like_back_success = False
            comment_success = False

            logger.debug(f"--- {i+1}/{total_users}人目の処理開始: {user_name} ---")

            if not profile_page_url or profile_page_url == '取得失敗':
                logger.error(f"  -> プロフィールURLが無効なため、スキップします。")
                continue

            page = None
            try:
                # 新しいタブでユーザーページを開く
                page = self.context.new_page()
                page.goto(profile_page_url, wait_until="domcontentloaded")
                logger.debug(f"  -> プロフィールページにアクセスしました: {profile_page_url}")


                # 1. いいね返し
                if self.engage_mode in ['all', 'like_only']:
                    logger.debug(f"  -> Mode '{self.engage_mode}' のため、いいね返しを実行します。")
                    like_back_success = self._like_back(
                        page, user_id, user_name, 
                        user.get("recent_like_count", 0),
                        profile_page_url
                    )
                    if like_back_success:
                        like_back_processed_count += 1
                    elif user.get("recent_like_count", 0) > 0: # いいね対象があったのに失敗した場合
                        like_back_error_count += 1

                # 2. コメント返しの実行可否を判定
                comment_text = user.get("comment_text")
                last_commented_at_str = user.get("last_commented_at")

                can_comment = False
                if comment_text:
                    # パターン1: 新規コメント (last_commented_at がない)
                    if not last_commented_at_str:
                        can_comment = True
                        logger.info("  -> 新規ユーザーのため、コメント投稿を実行します。")
                    # パターン2: 再コメント
                    else:
                        # 条件1: 最終コメントから3日以上経過
                        three_days_ago = datetime.now() - timedelta(days=3)
                        last_commented_at = datetime.fromisoformat(last_commented_at_str)
                        is_after_3_days = last_commented_at < three_days_ago
                        
                        # 条件2: 今回のセッションで5件以上いいね
                        recent_likes = user.get("recent_like_count", 0)
                        is_enough_likes = recent_likes >= 5

                        if is_after_3_days and is_enough_likes:
                            can_comment = True
                            logger.info(f"  -> 再コメント条件を満たしたため、コメント投稿を実行します。(最終コメントから3日以上経過 & いいね{recent_likes}件)")
                        else:
                            reasons = []
                            if not is_after_3_days:
                                reasons.append("最終コメントから3日経過していない")
                            if not is_enough_likes:
                                reasons.append(f"いいねが5件未満({recent_likes}件)")
                            logger.info(f"  -> 再コメント条件を満たさないため、コメントはスキップします。({', '.join(reasons)})")

                if can_comment and self.engage_mode in ['all', 'comment_only']:
                    logger.debug(f"  -> Mode '{self.engage_mode}' のため、コメント返しを実行します。")
                    comment_success = self._post_comment(page, user_id, user_name, comment_text)
                    if comment_success:
                        comment_processed_count += 1
                    else:
                        comment_error_count += 1

                # 3. アクションのコミット（個別実行）
                # いいね返しが成功した場合、いいね関連のアクションのみをコミット
                if like_back_success:
                    logger.debug(f"  -> いいね返しのアクションをコミットします。")
                    self._execute_side_effect(
                        commit_user_actions,
                        user_ids=[user_id],
                        is_comment_posted=False,
                        action_name="commit_like_back_action"
                    )
                
                # コメント返しが成功した場合、コメント関連のアクションをコミット
                if comment_success:
                    logger.debug(f"  -> コメント返しのアクションをコミットします。")
                    # ドライラン時は page.url が存在しない可能性があるため、Noneを渡す
                    post_url_for_commit = page.url if not self.dry_run else None
                    self._execute_side_effect(
                        commit_user_actions,
                        user_ids=[user_id],
                        is_comment_posted=True,
                        post_url=post_url_for_commit,
                        action_name="commit_comment_action"
                    )

            except Exception as e:
                logger.error(f"ユーザー「{user_name}」の処理中にエラーが発生しました: {e}", exc_info=True)
                self._take_screenshot_on_error(prefix=f"engage_error_{user_id}")
            finally:
                if page:
                    page.close()

        if like_back_processed_count > 0 or like_back_error_count > 0:
            logger.info(f"[Action Summary] name=いいね返し, count={like_back_processed_count}, errors={like_back_error_count}")

        if comment_processed_count > 0 or comment_error_count > 0:
            logger.info(f"[Action Summary] name=コメント返し, count={comment_processed_count}, errors={comment_error_count}")

        return True

def run_engage_user(users: list[dict], dry_run: bool = False, engage_mode: str = 'all', like_count: int = None):
    """ラッパー関数"""
    task = EngageUserTask(users=users, dry_run=dry_run, engage_mode=engage_mode, like_count=like_count)
    return task.run()