import logging
import random
import time
from playwright.sync_api import Page, Error as PlaywrightError
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
        """いいねバック処理"""
        # いいねのお返しは最大5件までとする
        target_like_count = min(like_back_count, 5)

        if target_like_count <= 0:
            logger.debug(f"いいねバックの対象件数が0のため、スキップします。")
            return

        logger.debug(f"ユーザー「{user_name}」に{target_like_count}件のいいねバックを開始します。")

        # ユーザーページでは、いいね済みの状態をクラスで判別できないため、クリック後に要素ごと非表示にする戦略を取る

        liked_count = 0
        for _ in range(7): # 最大20回スクロールして探す
            if liked_count >= target_like_count:
                break

            # ヘッドレスモードでの描画遅延を考慮し、ボタンを探す前に少し待機する
            time.sleep(3)

            # ユーザーページの「未いいね」ボタンを探す
            # 動的クラス名に対応するため、安定した部分クラス名で検索
            image_icon_selector = convert_to_robust_selector("button.image-icon--2vI3U")
            outline_icon_selector = convert_to_robust_selector("div.rex-favorite-outline--n4SWN")
            like_buttons = page.locator(f"{image_icon_selector}:has({outline_icon_selector}):visible").all()


            if not like_buttons:
                logger.debug(f"  -> いいね可能なボタンが見つかりません。ページをスクロールします... ")
                page.evaluate("window.scrollBy(0, 500)")
                time.sleep(2)
                continue

            # ページに表示されているボタンをシャッフルして、毎回同じものから「いいね」するのを防ぐ
            random.shuffle(like_buttons)
            for button in like_buttons[:target_like_count - liked_count]: # 残りの必要数だけ処理
                if liked_count >= target_like_count:
                    break
                # このtryブロックはボタン1回のクリック処理を囲む
                try:
                    # ボタンの祖先要素である投稿アイテム全体(カード)を探す
                    # 正しいXPathを使用して、動的クラス名を持つ祖先div要素を特定する
                    item_container = button.locator('xpath=ancestor::div[contains(@class, "vertical-space--")]')
                    button.click()
                    # 「いいね」した投稿をその場で非表示にして、次のループで見つけないようにする
                    item_container.evaluate("node => node.style.display = 'none'")
                    liked_count += 1
                    logger.debug(f"  -> いいねバック成功 ({liked_count}/{target_like_count})")
                    time.sleep(random.uniform(1.5, 2.5))
                except Exception as e:
                    logger.error(f"いいねクリック中にエラーが発生しました。このユーザーのいいねバック処理を中断します: {e}")
                    # エラーが発生したら、このユーザーのいいねバック処理を終了するために外側のループを抜ける
                    return # _like_backメソッド自体を終了させる

        logger.debug(f"  -> いいねバック完了。合計{liked_count}件実行しました。")

    def _post_comment(self, page: Page, user_id: str, comment_text: str):
        """コメント投稿処理"""
        if not comment_text:
            logger.debug("投稿するコメントがないため、スキップします。")
            return

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
                return

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
            logger.debug(f"  -> コメント投稿が完了しました。投稿URL: {page.url}")

        except PlaywrightError as e:
            logger.error(f"コメント投稿中にエラーが発生しました: {e}")
            self._take_screenshot_on_error(prefix=f"comment_error_{user_id}")

    def _execute_main_logic(self):
        total_users = len(self.users)
        processed_count = 0
        
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


                # 1. いいねバック
                self._like_back(page, user_name, user.get("recent_like_count", 0))

                # 2. コメント投稿
                comment_text = user.get("comment_text")
                self._post_comment(page, user_id, comment_text)

                # 3. アクションのコミット
                logger.debug(f"  -> アクションをコミットします。(現在はログ出力のみ)")
                commit_user_actions(user_ids=[user_id], is_comment_posted=bool(comment_text), post_url=page.url if comment_text else None)
                
                processed_count += 1
            except Exception as e:
                logger.error(f"ユーザー「{user_name}」の処理中にエラーが発生しました: {e}", exc_info=True)
                self._take_screenshot_on_error(prefix=f"engage_error_{user_id}")
            finally:
                if page:
                    page.close()

        logger.info(f"[Action Summary] name=ユーザーエンゲージメント, count={processed_count}")
        return True

def run_engage_user(users: list[dict]):
    """ラッパー関数"""
    task = EngageUserTask(users=users)
    return task.run()