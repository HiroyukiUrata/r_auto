import logging
import time
import re
import random
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, expect
from app.core.database import mark_replies_as_posted
from app.core.base_task import BaseTask
from app.utils.selector_utils import convert_to_robust_selector 

logger = logging.getLogger(__name__)
def reply_to_comments(replies: list[dict], dry_run: bool = False):
    """
    指定された投稿のコメントに返信するPlaywrightタスク。

    :param replies: 返信情報のリスト。各要素は以下のキーを持つ辞書。
                    - 'postUrl': 返信先の投稿URL
                    - 'replyText': 返信コメントのテキスト
                    - 'users': 返信対象のユーザー名リスト
    :param dry_run: Trueの場合、実際の投稿は行わずスクリーンショットを撮るだけ。
    """
    task = ReplyToCommentsTask(replies=replies, dry_run=dry_run)
    result = task.run()
    return result if isinstance(result, tuple) else (0, 0)

class ReplyToCommentsTask(BaseTask):
    def __init__(self, replies: list[dict], dry_run: bool = False):
        super().__init__(dry_run=dry_run)
        self.replies = replies
        self.action_name = f"マイコメへの返信投稿 ({len(replies)}件)"
        self.needs_browser = True
        self.use_auth_profile = True

    def _execute_main_logic(self):
        page = self.page
        total_replies = len(self.replies)
        logger.debug(f"コメント返信タスクを開始します。対象: {total_replies}件, Dry Run: {self.dry_run}")

        success_count = 0
        error_count = 0

        for i, reply_info in enumerate(self.replies):
            post_url = reply_info.get('postUrl')
            reply_text = reply_info.get('replyText')
            target_users = reply_info.get('users', [])
            comment_ids = reply_info.get('commentIds', [])

            if not post_url or not reply_text:
                logger.warning(f"[{i+1}/{total_replies}] 投稿URLまたは返信テキストが不足しているためスキップします。")
                continue

            logger.debug(f"[{i+1}/{total_replies}] 投稿ページに移動します: {post_url}")
            page.goto(post_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(random.uniform(3, 5))

            try:
                # --- コメントボタンをクリック ---
                logger.debug(f"  -> コメントボタンをクリックしてコメント画面を開きます")
                comment_button_selector = convert_to_robust_selector('div.pointer--3rZ2h:has-text("コメント")')
                page.locator(comment_button_selector).click()
                time.sleep(3)#ページ読み込みをしっかり待つ

                # --- コメントを入力 ---
                logger.debug(f"  -> コメント入力欄にコメントを挿入します")
                comment_textarea = page.locator('textarea[placeholder="コメントを書いてください"]')
                comment_textarea.wait_for(state="visible", timeout=15000)
                comment_textarea.fill(reply_text)
                time.sleep(3)#ページ読み込みをしっかり待つ
                #time.sleep(random.uniform(0.5, 1))


                # --- 送信ボタンをクリック ---
                logger.debug(f"  -> 送信ボタンをクリックします")
                send_button = page.get_by_role("button", name="送信")
                self._execute_action(send_button, "click", action_name=f"reply_to_{'_'.join(target_users)}")

                # ドライランでない場合のみ、投稿完了の待機とログ出力を行う
                if not self.dry_run:
                    # 投稿完了を待機
                    time.sleep(3)
                    #logger.info(f"  -> コメント返しが完了しました。投稿URL: {page.url}")
                    logger.debug(f"  -> コメントの投稿が完了しました。")
                    
                    # DBの投稿日時を更新
                    if comment_ids:
                        self._execute_side_effect(
                            mark_replies_as_posted,
                            comment_ids=comment_ids
                        )
                
                success_count += 1

            except PlaywrightTimeoutError as e:
                logger.error(f"コメント投稿処理中にタイムアウトエラーが発生しました: {post_url}", exc_info=True)
                self._take_screenshot_on_error(prefix=f"error_timeout_for_{'_'.join(target_users)}")
                error_count += 1
                continue # 次の返信へ
            except Exception as e:
                logger.error(f"コメント投稿処理中に予期せぬエラーが発生しました: {post_url}", exc_info=True)
                self._take_screenshot_on_error(prefix=f"error_unexpected_for_{'_'.join(target_users)}")
                error_count += 1
                continue # 次の返信へ

        logger.debug("すべてのコメント返信タスクが完了しました。")

        # --- 最終サマリーログの出力 ---
        if success_count > 0 or error_count > 0:
            logger.info(f"[Action Summary] name=マイコメ返信, count={success_count}, errors={error_count}")

        # 処理結果のサマリーをログに出力
        return success_count, error_count

if __name__ == '__main__':
    # テスト用の設定
    from app.core.logging_config import setup_logging
    setup_logging()

    # クラスベースになったため、直接のテスト実行はrun()を呼び出す形に変更
    # reply_to_comments(test_replies, dry_run=True)