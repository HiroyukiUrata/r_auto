import logging
import os
import re
import time
import random
from playwright.sync_api import Error, expect
from app.core.base_task import BaseTask
from app.utils.selector_utils import convert_to_robust_selector


logger = logging.getLogger(__name__)


class FollowTask(BaseTask):
    """
    楽天ROOMフォロータスク（導線修正版）。
    - トップ→my ROOM→フォロワー一覧→ターゲットユーザーへ遷移（既存導線を維持）
    - ターゲットユーザーのフォロワーモーダルで「フォローする」を順次クリック
    - 目標数と成功数の差をエラー件数として返す
    """

    list_container_selector = "div#userList"

    def __init__(self, count: int = 10):
        super().__init__(count=count)
        self.action_name = "フォロー"
        self.state_check_timeout = 1500  # ms

    # ===== ユーティリティ =====
    def wait_cards_ready(self, page):
        """モーダル内でカードが表示されるまで待機。"""
        page.locator(self.list_container_selector).first.wait_for(state="visible", timeout=30000)
        card = page.locator(f"{self.list_container_selector} div[class*='profile-wrapper']").first
        try:
            card.wait_for(state="visible", timeout=10000)
        except Exception:
            page.wait_for_timeout(1000)

    def scroll_to_load_once(self, page, scroll_delay=1.0):
        """モーダルを一度スクロールして次のカードをロード。"""
        try:
            page.locator(self.list_container_selector).evaluate("n => n.scrollTop = n.scrollHeight")
        except Exception:
            pass
        page.wait_for_timeout(int(scroll_delay * 1000))
        try:
            page.locator("div[aria-label='loading']").first.wait_for(state="hidden", timeout=3000)
        except Exception:
            pass

    def ensure_modal_ready_for_click(self, page):
        """
        クリック前にモーダルが開いており、最低限スクロール可能な状態かを確認する。
        """
        try:
            container = page.locator(self.list_container_selector).first
        except Exception as e:
            logger.warning("モーダルコンテナ取得に失敗しました: %s", e)
            return

        try:
            if not container.is_visible():
                logger.debug("クリック前チェック: モーダルが非表示のため再オープンします。")
                page.locator('button:has-text("フォロワー")').first.click(force=True)
                self.wait_cards_ready(page)
            else:
                # 表示されている場合も、カードの準備完了を待つ
                self.wait_cards_ready(page)

            # スクロールが実行できる状態か軽く確認（失敗しても致命的ではない）
            try:
                container.evaluate("n => n.scrollHeight")
            except Exception as e:
                logger.debug("クリック前チェック: モーダルのスクロール状態確認に失敗しました: %s", e)
        except Exception as e:
            logger.warning("クリック前チェック中にエラーが発生しました: %s", e)

    def safe_find_next_candidate(self, page, processed: set[str], max_wait_seconds: int = 30):
        """
        モーダルの表示状態を確認しながら未処理の「フォローする」ボタンを探す。
        見つかれば (button, user_name, key, attempts) を返し、見つからなければ None を返す。
        """
        attempts = 0
        stagnation = 0
        last_height = None
        start_time = time.time()

        while True:
            if time.time() - start_time > max_wait_seconds:
                logger.debug("候補探索の待ち時間を超過したためタイムアウトで抜けます: %s", max_wait_seconds)
                break

            # モーダルが閉じていたら再オープン
            try:
                container = page.locator(self.list_container_selector).first
                if not container.is_visible():
                    logger.debug("モーダルが非表示のため再オープンします")
                    page.locator('button:has-text("フォロワー")').first.click(force=True)
                    self.wait_cards_ready(page)
                    start_time = time.time()
                    continue
                else:
                    # 表示されている状態でカードの準備完了を待つ
                    self.wait_cards_ready(page)
            except Exception:
                logger.debug("モーダル可視判定に失敗 -> 再オープンを試みます")
                page.locator('button:has-text("フォロワー")').first.click(force=True)
                self.wait_cards_ready(page)
                start_time = time.time()
                continue

            follow_buttons = page.locator(self.list_container_selector).get_by_role("button", name="フォローする")
            follow_count = follow_buttons.count()
            follow_now_count = page.locator(self.list_container_selector).get_by_role("button", name="フォロー中").count()
            logger.debug("未フォロー: %s / フォロー中: %s (attempt=%s)", follow_count, follow_now_count, attempts + 1)

            for idx in range(follow_count):
                btn = follow_buttons.nth(idx)
                user_row = btn.locator('xpath=ancestor::div[contains(@class, "profile-wrapper")]').first
                name_el = user_row.locator(convert_to_robust_selector("span.profile-name--2Hsi5")).first
                try:
                    user_name = name_el.inner_text().strip()
                except Exception:
                    user_name = ""
                key = user_name or f"idx-{idx}"

                if key in processed:
                    continue

                try:
                    btn.evaluate("el => el.scrollIntoView({block:'center', behavior:'instant'})")
                except Exception:
                    pass
                page.wait_for_timeout(200)
                return btn, user_name, key, attempts + 1

            attempts += 1
            try:
                current_height = page.locator(self.list_container_selector).evaluate("n => n.scrollHeight")
            except Exception:
                current_height = None

            if last_height is not None and current_height is not None and current_height <= last_height:
                stagnation += 1
            else:
                stagnation = 0
            last_height = current_height

            logger.debug(
                "新規候補なし -> スクロールして再検索 (attempt=%s, scrollHeight=%s, stagnation=%s)",
                attempts,
                current_height,
                stagnation,
            )
            self.scroll_to_load_once(page, scroll_delay=1.0)

            if attempts >= 50 or stagnation >= 3:
                logger.debug("未処理の『フォローする』ボタンが見つからず終了します (attempts=%s, stagnation=%s)", attempts, stagnation)
                break

        logger.debug("未処理の『フォローする』ボタンが見つかりませんでした")
        return None

    def find_next_candidate(self, page, processed: set[str], max_wait_seconds: int = 30):
        """
        未処理の「フォローする」ボタンを探す。
        見つかれば (button, user_name, key, attempts) を返し、見つからなければ None。
        """
        self.wait_cards_ready(page)
        attempts = 0
        stagnation = 0
        last_height = None
        start_time = time.time()

        while True:
            if time.time() - start_time > max_wait_seconds:
                logger.debug("候補探索が%ssを超過したためタイムアウトで抜けます。", max_wait_seconds)
                break

            # モーダルが閉じていたら再オープン
            try:
                if not page.locator(self.list_container_selector).first.is_visible():
                    logger.debug("モーダルが非表示のため再オープンします。")
                    page.locator('button:has-text("フォロワー")').first.click(force=True)
                    self.wait_cards_ready(page)
                    start_time = time.time()
                    continue
            except Exception:
                logger.debug("モーダル可視判定に失敗 -> 再オープンを試みます。")
                page.locator('button:has-text("フォロワー")').first.click(force=True)
                self.wait_cards_ready(page)
                start_time = time.time()
                continue

            follow_buttons = page.locator(self.list_container_selector).get_by_role("button", name="フォローする")
            follow_count = follow_buttons.count()
            follow_now_count = page.locator(self.list_container_selector).get_by_role("button", name="フォロー中").count()
            logger.debug("未フォロー: %s / フォロー中: %s (attempt=%s)", follow_count, follow_now_count, attempts + 1)

            for idx in range(follow_count):
                btn = follow_buttons.nth(idx)
                user_row = btn.locator('xpath=ancestor::div[contains(@class, "profile-wrapper")]').first
                name_el = user_row.locator(convert_to_robust_selector("span.profile-name--2Hsi5")).first
                try:
                    user_name = name_el.inner_text().strip()
                except Exception:
                    user_name = ""
                key = user_name or f"idx-{idx}"

                if key in processed:
                    continue

                try:
                    btn.evaluate("el => el.scrollIntoView({block:'center', behavior:'instant'})")
                except Exception:
                    pass
                page.wait_for_timeout(200)
                return btn, user_name, key, attempts + 1

            attempts += 1
            try:
                current_height = page.locator(self.list_container_selector).evaluate("n => n.scrollHeight")
            except Exception:
                current_height = None

            if last_height is not None and current_height is not None and current_height <= last_height:
                stagnation += 1
            else:
                stagnation = 0
            last_height = current_height

            logger.debug(
                "新規候補なし -> スクロールして再検索 (attempt=%s, scrollHeight=%s, stagnation=%s)",
                attempts,
                current_height,
                stagnation,
            )
            self.scroll_to_load_once(page, scroll_delay=1.0)

            if attempts >= 50 or stagnation >= 3:
                logger.debug("未処理の『フォローする』ボタンが見つからず終了 (attempts=%s, stagnation=%s)", attempts, stagnation)
                break

        logger.debug("未処理の『フォローする』ボタンが見つかりませんでした。")
        return None

    # ===== メインロジック =====
    def _execute_main_logic(self):
        page = self.page

        # ===================================================
        # ★★★ 導線修正: My ROOM、フォロワー一覧、ターゲットユーザーへ遷移 ★★★
        # ===================================================

        target_url = "https://room.rakuten.co.jp/items"
        logger.debug(f"トップページ「{target_url}」に移動します...")
        page.goto(target_url, wait_until="domcontentloaded")
        time.sleep(2)

        myroom_link = page.locator('a:has-text("my ROOM")').first
        logger.debug("「my ROOM」リンクをクリックし、自己ルームに遷移します。")
        myroom_link.wait_for(state="visible", timeout=10000)
        myroom_link.click()
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        my_room_url = page.url
        logger.debug(f"対象URL: 「{my_room_url}」")

        follower_button = page.get_by_text("フォロワー", exact=True).locator("xpath=ancestor::button").first
        follower_button.wait_for(timeout=30000)
        follower_button.click()

        first_user_in_modal = page.locator(self.list_container_selector).first
        first_user_in_modal.wait_for(state="visible", timeout=30000)

        first_user_profile_link = first_user_in_modal.locator(convert_to_robust_selector("a.profile-name-content--iyogY")).first
        try:
            user_name_selector = convert_to_robust_selector("span.profile-name--2Hsi5")
            user_name = first_user_profile_link.locator(user_name_selector).first.inner_text().strip()
        except Exception:
            user_name = "ユーザー名取得失敗"

        logger.debug(f"ユーザー「{user_name}」のルームに遷移します。")
        first_user_profile_link.click()
        page.wait_for_load_state("domcontentloaded", timeout=15000)

        target_follower_button = page.locator('button:has-text("フォロワー")').first
        target_follower_button.wait_for(timeout=30000)
        target_follower_button.click(force=True)

        first_button_in_list = page.locator(self.list_container_selector).get_by_role("button", name="フォローする").or_(
            page.locator(self.list_container_selector).get_by_role("button", name="フォロー中")
        ).first
        first_button_in_list.wait_for(timeout=30000)

        # ===================================================
        # フォロー実行（モーダル開閉しながら）
        # ===================================================
        followed_count = 0
        error_count = 0
        processed_keys: set[str] = set()

        while followed_count < self.target_count:
            # モーダルが開いているかも含めて安全に候補を探す
            candidate = self.safe_find_next_candidate(page, processed_keys)
            if candidate is None:
                logger.debug("新規候補が見つからず終了します。処理済み: %s", len(processed_keys))
                break

            btn, user_name, key, attempts_used = candidate
            processed_keys.add(key)
            logger.debug("フォロー候補: ユーザー名='%s' (累計処理=%s, attempts=%s)", user_name or "取得失敗", len(processed_keys), attempts_used)

            click_succeeded = False
            for click_attempt in range(2):
                try:
                    if click_attempt > 0:
                        # リトライ時はモーダル状態とスクロール状態を再確認
                        self.ensure_modal_ready_for_click(page)

                    btn.click(timeout=10000, no_wait_after=True)
                    # 状態変化チェックは緩めにし、クリック成功でカウントを進める
                    page.wait_for_timeout(500)
                    followed_count += 1
                    click_succeeded = True
                    logger.debug(
                        "フォロークリック完了: %s (%s/%s, attempt=%s)",
                        user_name or "取得失敗",
                        followed_count,
                        self.target_count,
                        click_attempt + 1,
                    )
                    # INFO ログにもフォローしたユーザー名を出す
                    logger.info(
                        "'%s' (%s/%s)",
                        user_name or "取得失敗",
                        followed_count,
                        self.target_count,
                    )
                    break
                except (Error, Exception) as e:
                    logger.warning(
                        "フォロークリックに失敗しました (attempt=%s): %s",
                        click_attempt + 1,
                        e,
                    )
                    page.wait_for_timeout(1000)

            if not click_succeeded:
                error_count += 1

            # モーダルを閉じて開き直し、ズレをリセット
            try:
                page.locator("div.close-button--2Se88").first.click()
            except Exception:
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
            page.wait_for_timeout(300)
            if followed_count < self.target_count:
                try:
                    page.locator('button:has-text("フォロワー")').first.click(force=True)
                    self.wait_cards_ready(page)
                except Exception as e:
                    logger.warning("モーダル再オープンに失敗しました: %s", e)
                    break

        # 目標数と成功数の差をエラー件数として返す
        final_error_count = self.target_count - followed_count
        return followed_count, final_error_count


def run_follow_action(count: int = 10):
    """ラッパー関数"""
    task = FollowTask(count=count)
    result = task.run()
    return result if isinstance(result, tuple) and len(result) >= 2 else (0, count)
