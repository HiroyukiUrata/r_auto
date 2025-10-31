import logging
import random
import time
from playwright.sync_api import Page, Error as PlaywrightError, expect
from app.utils.selector_utils import convert_to_robust_selector
from app.core.base_task import BaseTask
from app.core.database import get_product_by_id, commit_user_actions

logger = logging.getLogger(__name__)

class EngageUserTask(BaseTask):
    """
    指定されたユーザーに対して「いいねバック」と「コメント投稿」を行うタスク。
    """
    def __init__(self, users: list[dict]):
        super().__init__(count=None)
        self.action_name = f"複数ユーザーへのエンゲージメント ({len(users)}人)"
        self.needs_browser = True
        self.use_auth_profile = True

        # タスク実行に必要な引数を設定
        self.users = users

    def _like_back(self, page: Page, user_name: str, like_back_count: int):
        """いいね返し処理"""
        # いいねのお返しは最大5件までとする
        target_like_count = min(like_back_count, 5)

        if target_like_count <= 0:
            logger.debug(f"いいね返しの対象件数が0のため、スキップします。")
            return False

        logger.debug(f"ユーザー「{user_name}」に{target_like_count}件のいいね返しを開始します。")

        # 「いいね済み」のカードを特定して非表示にする

        all_cards_locator = page.locator(convert_to_robust_selector('div[class*="container--JAywt"]'))
        liked_button_selector = convert_to_robust_selector('button:has(div[class*="rex-favorite-filled--2MJip"])')
        liked_button_locator = page.locator(liked_button_selector)
        try:
            # ページ上のカードが読み込まれるのを待ちます。
            all_cards_locator.first.wait_for(state="visible", timeout=30000)
            
            # 全カードの中から、「いいね済み」ボタンを持つカードだけを絞り込みます。
            liked_cards_locator = all_cards_locator.filter(has=liked_button_locator)
            count = liked_cards_locator.count()
            print(f"{count} 件の「いいね済み」カードが見つかりました。")

            if count > 0:
                #  絞り込んだカードを一括で非表示にします。
                liked_cards_locator.evaluate_all("nodes => nodes.forEach(n => n.style.display = 'none')")
                print(f"合計 {count} 件のカードを非表示にしました。")

            time.sleep(3) # 視覚的な確認のための待機
        
        except Exception as e:
            print(f"エラー: 「いいね済み」の処理中に問題が発生しました。タイムアウトしたか、セレクタが古い可能性があります。")
            print(f"詳細: {e}") # 詳細なエラーメッセージを出力

        liked_count = 0

        try:
            for _ in range(10):
                if liked_count >= target_like_count:
                    break
                
                time.sleep(1)
                card_selector_str = convert_to_robust_selector('div[class*="container--JAywt"]')
                target_card = page.locator(f"{card_selector_str}:visible").first
                target_card.evaluate("node => { node.style.border = '5px solid orange'; }")
                
                # ハイライトしたカードの中から「未いいね」ボタンを探してハイライトする
                unliked_icon_selector = convert_to_robust_selector("div.rex-favorite-outline--n4SWN")
                unliked_button_locator = target_card.locator(f'button:has({unliked_icon_selector})')
                unliked_button_locator.evaluate("node => { node.style.border = '3px solid limegreen'; }")
                
                # 「未いいね」ボタンをクリックします。
                expect(unliked_button_locator).to_be_enabled(timeout=5000)
                unliked_button_locator.click()
                liked_count += 1

            
                time.sleep(30)#めちゃめちゃ待ったら連続クリックできるはず。たぶｎ
                target_card.evaluate("node => { node.style.display = 'none'; }")

        except Exception as e:
            logger.error(f"いいね返し中にエラーが発生しました: {e}")
            return False # _like_backメソッド自体を終了させる

        logger.debug(f"  -> いいね返し完了。合計{liked_count}件実行しました。")
        # 1件でもいいねできていれば成功とみなす
        return liked_count > 0

    def _post_comment(self, page: Page, user_id: str, comment_text: str):
        """コメント返し処理"""
        if not comment_text:
            logger.debug("投稿するコメントがないため、スキップします。")
            return False

        logger.debug(f"  -> 最新投稿にコメントします。")
        # ページを一番上までスクロール
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1)

        try:
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
            comment_button_selector = convert_to_robust_selector('div.pointer--3rZ2h:has-text("コメント")')
            page.locator(comment_button_selector).click()

            # --- 4. コメントを入力して投稿 ---
            comment_textarea = page.locator('textarea[placeholder="コメントを書いてください"]')
            comment_textarea.wait_for(state="visible", timeout=15000)
            comment_textarea.fill(comment_text)
            time.sleep(random.uniform(0.5, 1))

            page.get_by_role("button", name="送信").click()

            # 投稿完了を待機
            time.sleep(3)
            logger.debug(f"  -> コメント返しが完了しました。投稿URL: {page.url}")
            return True

        except PlaywrightError as e:
            logger.error(f"コメント返し中にエラーが発生しました: {e}")
            self._take_screenshot_on_error(prefix=f"comment_error_{user_id}")
            return False

    def _execute_main_logic(self):
        total_users = len(self.users)
        like_back_processed_count = 0
        comment_processed_count = 0
        
        for i, user in enumerate(self.users):
            user_id = user.get("id")
            user_name = user.get("name")
            profile_page_url = user.get("profile_page_url")
            
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
                like_back_success = self._like_back(page, user_name, user.get("recent_like_count", 0))
                if like_back_success:
                    like_back_processed_count += 1

                # 2. コメント返し
                comment_text = user.get("comment_text")
                comment_success = self._post_comment(page, user_id, comment_text)
                if comment_success:
                    comment_processed_count += 1

                # 3. アクションのコミット
                # いいね返しまたはコメント返しのどちらかが成功した場合にコミット
                if like_back_success or comment_success:
                    logger.debug(f"  -> アクションをコミットします。")
                    commit_user_actions(user_ids=[user_id], is_comment_posted=bool(comment_text and comment_success), post_url=page.url if (comment_text and comment_success) else None)

            except Exception as e:
                logger.error(f"ユーザー「{user_name}」の処理中にエラーが発生しました: {e}", exc_info=True)
                self._take_screenshot_on_error(prefix=f"engage_error_{user_id}")
            finally:
                if page:
                    page.close()
        
        logger.info(f"[Action Summary] name=いいね返し, count={like_back_processed_count}")
        logger.info(f"[Action Summary] name=コメント返し, count={comment_processed_count}")
        return True

def run_engage_user(users: list[dict]):
    """ラッパー関数"""
    task = EngageUserTask(users=users)
    return task.run()