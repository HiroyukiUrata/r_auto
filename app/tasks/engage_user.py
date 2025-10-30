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
        for _ in range(20): # 最大20回スクロールして探す
            if liked_count >= target_like_count:
                break

            # ユーザーページの「未いいね」ボタンを探す
            # 動的クラス名に対応するため、安定した部分クラス名で検索
            image_icon_selector = convert_to_robust_selector("button.image-icon--2vI3U")
            outline_icon_selector = convert_to_robust_selector("div.rex-favorite-outline--n4SWN")
            like_buttons = page.locator(f"{image_icon_selector}:has({outline_icon_selector}):visible").all()

            if not like_buttons:
                logger.debug("  -> いいね可能なボタンが見つかりません。ページをスクロールします...")
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
                    item_container = button.locator('xpath=ancestor::div[contains(@class, "collect--")]')
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
        try:
            # ページを一番上までスクロール
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(1)

            # 最初の投稿のコメントアイコンをクリック
            first_comment_icon = page.locator("a.icon-comment").first
            first_comment_icon.wait_for(state='visible', timeout=10000)
            first_comment_icon.click()

            # コメント入力欄と投稿ボタンを待機
            comment_textarea = page.locator("textarea[ng-model='comment.comment']")
            comment_textarea.wait_for(state='visible', timeout=10000)

            # コメントを入力
            comment_textarea.fill(comment_text)
            time.sleep(random.uniform(0.5, 1))

            # 投稿ボタンをクリック
            post_button = page.get_by_role("button", name="投稿する")
            post_button.click()

            # 投稿完了を待機（ここでは簡易的に固定時間待機）
            time.sleep(2)
            logger.debug("  -> コメント投稿が完了しました。")

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

                # 状況確認のために少し待機
                logger.debug("  -> 状況確認のため5秒間待機します...")
                time.sleep(25)

                # 2. コメント投稿
                # self._post_comment(page, user_id, user.get("comment_text"))

                # 3. アクションのコミット
                logger.debug(f"  -> アクションをコミットします。（現在はログ出力のみ）")
                # commit_user_actions(user_ids=[user_id], is_comment_posted=True)
                
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