import logging
from typing import Optional, List
from app.tasks.scraping_commons.user_page_like import UserPageLiker
from app.core.base_task import BaseTask
from app.core.database import commit_user_actions

logger = logging.getLogger(__name__)

class NewLikeBackTask(BaseTask):
    """
    【新】「いいね返し」専門タスク。
    - like_countが指定されていれば「固定数モード」
    - like_countがNoneであれば「可変（お返し）モード」
    で動作する。
    """
    def __init__(self, users: List[dict], like_count: Optional[int] = None, dry_run: bool = False):
        super().__init__(count=None, dry_run=dry_run)
        self.users = users
        self.like_count = like_count
        self.action_name = f"いいね返し ({len(users)}人)"
        self.needs_browser = True
        self.use_auth_profile = True
        logger.debug(f"NewLikeBackTaskが初期化されました。Users: {len(users)}人, LikeCount: {self.like_count}, DryRun: {self.dry_run}")

    def _execute_main_logic(self):
        total_liked_count = 0
        total_error_count = 0

        for user in self.users:
            page = None
            user_id = user.get('id')
            user_name = user.get('name')
            profile_page_url = user.get('profile_page_url')
            
            logger.info(f"ユーザー「{user_name}」へのいいね返しを開始します。")
            # 先にこのユーザーに対するいいね目標数を計算しておく
            target_like_count = 0
            if self.like_count is not None:
                target_like_count = self.like_count
            else:
                like_back_count = user.get("recent_like_count", 0)
                if like_back_count > 0:
                    target_like_count = min(like_back_count, 5)

            if not profile_page_url or profile_page_url == '取得失敗':
                logger.warning(f"ユーザー「{user_name}」のプロフィールURLが無効なため、スキップします。")
                # いいねするはずだった件数をエラーとしてカウント
                if target_like_count > 0:
                    total_error_count += target_like_count
                continue

            try:
                page = self.context.new_page()
                page.goto(profile_page_url, wait_until="domcontentloaded")

                # --- いいね件数の決定ロジック ---
                if self.like_count is not None:
                    logger.debug(f"「{user_name}」に固定数モードでいいねします: {target_like_count}件")
                else:
                    if target_like_count > 0:
                        logger.debug(f"「{user_name}」に可変モードでいいねします (通知ベース: {user.get('recent_like_count', 0)}件 -> 上限適用後: {target_like_count}件)")

                if target_like_count <= 0:
                    logger.debug(f"「{user_name}」はいいね対象外（0件）のためスキップします。")
                    continue

                # --- いいね実行 ---
                liker = UserPageLiker(
                    task_instance=self,
                    page=page,
                    target_url=profile_page_url,
                    target_count=target_like_count
                )
                liked_count, errors_this_user = liker.execute()

                # UserPageLikerからの結果を総数に加算
                total_liked_count += liked_count
                total_error_count += errors_this_user

                # 1件でも成功していれば、DBへのコミット処理を実行
                if liked_count > 0:
                    self._execute_side_effect(
                        commit_user_actions,
                        user_ids=[user_id],
                        is_comment_posted=False,
                        action_name="commit_like_back_action"
                    )

            except Exception as e:
                logger.error(f"ユーザー「{user_name}」のいいね返し処理中にエラー: {e}", exc_info=True)
                self._take_screenshot_on_error(prefix=f"new_like_back_error_{user_id}")
                # ページ遷移エラーなどの場合、目標いいね数をすべてエラーとしてカウント
                total_error_count += target_like_count
            finally:
                if page:
                    page.close()

        return total_liked_count, total_error_count

def run_new_like_back(users: List[dict], like_count: Optional[int] = None, dry_run: bool = False, **kwargs):
    """NewLikeBackTaskのラッパー関数"""
    task = NewLikeBackTask(users=users, like_count=like_count, dry_run=dry_run)
    result = task.run()
    return result if isinstance(result, tuple) else (0, 0)