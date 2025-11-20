import logging
import time
import random
from playwright.sync_api import Page, Error as PlaywrightError
import re
from app.tasks.scraping_commons.user_page_like import UserPageLiker
from app.core.base_task import BaseTask
from app.core.database import get_user_details_for_like_back, update_engagement_error, commit_user_actions, update_like_back_status

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
        # UserPageLikerはURLを必要とするため、pageオブジェクトから現在のURLを取得
        target_url = page.url
        liker = UserPageLiker(
            task_instance=self,
            page=page,
            target_url=target_url,
            target_count=self.like_count
        )
        liked_count, error_count = liker.execute()
        # 1件でも成功していればTrueを返す（ドライラン時も同様）
        return liked_count, error_count

    def _execute_main_logic(self):
        users_details = get_user_details_for_like_back(self.user_ids)

        if not users_details:
            logger.warning("いいね返し対象のユーザー情報がDBから取得できませんでした。")
            logger.warning(f"フロントエンドから渡されたID(URL): {self.user_ids}")
            return True # エラーではないため正常終了とする
        
        like_back_processed_count = 0
        like_back_error_count = 0

        for user in users_details:
            page = self.context.new_page()
            try:
                page.goto(user['user_page_url'], wait_until="domcontentloaded")
                liked_this_user, errors_this_user = self._execute_like_action(page, user['user_id'], user['user_name'])
                if liked_this_user > 0 or self.dry_run:
                    like_back_processed_count += liked_this_user if not self.dry_run else 1
                    # いいね返しが成功したら、DBのステータスを更新する
                    self._execute_side_effect(
                        update_like_back_status,
                        user_page_url=user['user_page_url'],
                        like_count=self.like_count
                    )
                if errors_this_user > 0:
                    like_back_error_count += errors_this_user
            finally:
                page.close()

        # --- 最終サマリーログの出力 ---
        if like_back_processed_count > 0 or like_back_error_count > 0:
            logger.info(f"[Action Summary] name=いいね返し, count={like_back_processed_count}, errors={like_back_error_count}")

        # 成功件数とエラー件数をタプルで返す
        return like_back_processed_count, like_back_error_count

def run_like_back(user_ids: list[str], like_count: int, dry_run: bool = False):
    """LikeBackTaskのラッパー関数"""
    task = LikeBackTask(user_ids=user_ids, like_count=like_count, dry_run=dry_run)
    result = task.run()
    return result if isinstance(result, tuple) else (0, 0)