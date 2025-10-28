import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Optional

from playwright.sync_api import sync_playwright, BrowserContext, Page
from app.core.config_manager import is_headless, SCREENSHOT_DIR

PROFILE_DIR = "db/playwright_profile"

class BaseTask(ABC):
    """
    Playwrightを使用する自動化タスクの基底クラス。
    ブラウザのセットアップ、実行、ティアダウンの共通処理を管理する。
    """
    def __init__(self, count: Optional[int] = None, max_duration_seconds: int = 600):
        self.target_count = count
        self.max_duration_seconds = max_duration_seconds
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.action_name = "アクション" # サブクラスで上書きする
        self.needs_browser = True # デフォルトではブラウザを必要とする
        self.use_auth_profile = True # デフォルトでは認証プロファイルを使用する

    def _setup_browser(self):
        """ブラウザコンテキストをセットアップする"""
        headless_mode = is_headless()
        logging.debug(f"Playwright ヘッドレスモード: {headless_mode}")

        if self.use_auth_profile:
            logging.debug(f"認証プロファイル ({PROFILE_DIR}) を使用してブラウザを起動します。")
            if not os.path.exists(PROFILE_DIR):
                raise FileNotFoundError(f"認証プロファイル {PROFILE_DIR} が見つかりません。「認証状態の保存」または「認証プロファイルの復元」タスクを実行してください。")

            lockfile_path = os.path.join(PROFILE_DIR, "SingletonLock")
            if os.path.exists(lockfile_path):
                logging.warning(f"古いロックファイル {lockfile_path} が見つかったため、削除します。")
                os.remove(lockfile_path)

            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                headless=headless_mode,
                slow_mo=500 if not headless_mode else 0,
                env={"DISPLAY": ":0"},
                args=["--disable-blink-features=AutomationControlled"] # 自動化検知を回避する引数を追加
            )
        else:
            logging.debug("新しいブラウザセッション（認証プロファイルなし）で起動します。")
            browser = self.playwright.chromium.launch(
                headless=headless_mode,
                slow_mo=500 if not headless_mode else 0,
                env={"DISPLAY": ":0"},
                args=["--disable-blink-features=AutomationControlled"] # 自動化検知を回避する引数を追加
            )
            self.context = browser.new_context(locale="ja-JP")

        self.page = self.context.new_page()
        # ビューポートサイズを固定して、ヘッドレスモードと通常モードの挙動の差をなくす
        self.page.set_viewport_size({"width": 1920, "height": 1080})

    def _teardown_browser(self):
        """ブラウザコンテキストを閉じる"""
        if self.context:
            logging.debug("ブラウザコンテキストを閉じています...")
            try:
                self.context.close()
                # close()が完了し、プロファイルがディスクに書き込まれるのを少し待つ
                time.sleep(2)
                logging.debug("ブラウザコンテキストを正常に閉じました。")
            except Exception as e:
                logging.error(f"ブラウザコンテキストのクローズ中にエラーが発生しました: {e}")

    def run(self):
        """タスクの実行フローを管理する"""
        success = False
        if self.target_count is not None:
            logging.debug(f"「{self.action_name}」アクションを開始します。目標件数: {self.target_count}")
        else:
            logging.debug(f"「{self.action_name}」アクションを開始します。")

        if self.needs_browser:
            with sync_playwright() as p:
                self.playwright = p
                try:
                    self._setup_browser()
                    # _execute_main_logic の戻り値（True/False）を success 変数に格納する
                    success = self._execute_main_logic()
                except FileNotFoundError as e:
                    logging.error(f"ファイルが見つかりません: {e}")
                except Exception as e:
                    # 本番環境(simple)ではトレースバックを抑制し、開発環境(detailed)では表示する
                    is_detailed_log = os.getenv('LOG_FORMAT', 'detailed').lower() == 'detailed'
                    logging.error(f"「{self.action_name}」アクション中に予期せぬエラーが発生しました: {e}", exc_info=is_detailed_log)
                    self._take_screenshot_on_error()
                    success = False # 例外発生時は明確に False とする
                finally:
                    self._teardown_browser()
        else:
            # ブラウザ不要のタスク
            try:
                success = self._execute_main_logic()
            except Exception as e:
                # 本番環境(simple)ではトレースバックを抑制し、開発環境(detailed)では表示する
                is_detailed_log = os.getenv('LOG_FORMAT', 'detailed').lower() == 'detailed'
                logging.error(f"「{self.action_name}」アクション中にエラーが発生しました: {e}", exc_info=is_detailed_log)
                success = False

        logging.debug(f"「{self.action_name}」アクションを終了します。")
        return success

    def _take_screenshot_on_error(self, prefix: str = "error"):
        """エラー発生時にスクリーンショットを保存する"""
        if self.page:
            try:
                os.makedirs(SCREENSHOT_DIR, exist_ok=True)
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                safe_action_name = "".join(c for c in self.action_name if c.isalnum() or c in (' ', '_')).rstrip()
                screenshot_path = os.path.join(SCREENSHOT_DIR, f"{prefix}_{safe_action_name}_{timestamp}.png")
                self.page.screenshot(path=screenshot_path)
                logging.info(f"エラー発生時のスクリーンショットを保存しました。")
                #logging.info(f"エラー発生時のスクリーンショットを {screenshot_path} に保存しました。")
            except Exception as ss_e:
                logging.error(f"スクリーンショットの保存に失敗しました: {ss_e}")

    @abstractmethod
    def _execute_main_logic(self):
        """
        タスク固有のメインロジック。
        サブクラスで必ず実装する必要がある。
        """
        pass