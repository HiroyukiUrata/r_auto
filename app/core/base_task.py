import logging
import os
import time
import sys
from abc import ABC, abstractmethod
from typing import Optional
from playwright.sync_api import sync_playwright, BrowserContext, Page, Locator
from app.core.config_manager import is_headless, SCREENSHOT_DIR

PROFILE_DIR = "db/playwright_profile"

class BaseTask(ABC):
    """
    すべてのタスククラスが継承する基本クラス。
    """
    def __init__(self, count: Optional[int] = None, max_duration_seconds: int = 600, dry_run: bool = False):
        self.target_count = count
        self.max_duration_seconds = max_duration_seconds
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.action_name = "アクション"  # サブクラスで上書きする
        self.needs_browser = True # デフォルトではブラウザを必要とする
        self.use_auth_profile = True # デフォルトでは認証プロファイルを使用する
        self.dry_run = dry_run
        if self.dry_run:
            self.action_name += " (DRY RUN)"

    def _execute_action(self, locator: Locator, action: str, *args, **kwargs):
        """
        Playwrightのアクションをドライランモードを考慮して実行する汎用ヘルパー。

        使用例:
        self._execute_action(page.get_by_role("button"), "click")
        self._execute_action(page.locator("textarea"), "fill", "テキスト")
        self._execute_action(page.locator("input"), "press", "Enter", action_name="submit_form")

        :param locator: PlaywrightのLocatorオブジェクト
        :param action: 実行するメソッド名 (例: "click", "fill", "press")
        :param args: アクションメソッドに渡す位置引数
        :param kwargs: アクションメソッドに渡すキーワード引数。'action_name'は特別で、SSのファイル名に使われる。
        """
        # スクリーンショット用の名前を取得（指定がなければ自動生成）
        # スクリーンショット撮影用の別ロケーターが指定されていれば取得、なければ操作対象ロケーターを使う
        screenshot_locator = kwargs.pop("screenshot_locator", locator)
        screenshot_name = kwargs.pop("action_name", f"{action}_{time.time():.0f}")

        if not self.dry_run:
            # --- 通常実行 ---
            method_to_call = getattr(locator, action)
            method_to_call(*args, **kwargs)
        else:
            # --- ドライラン実行 ---
            prefix = f"dry_run_{screenshot_name}"
            logging.info(f"  -> [DRY RUN] '{action}' アクションをスキップし、対象要素のスクリーンショットを保存します。")
            try:
                os.makedirs(SCREENSHOT_DIR, exist_ok=True)
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                screenshot_path = os.path.join(SCREENSHOT_DIR, f"{prefix}_{timestamp}.png")
                screenshot_locator.screenshot(path=screenshot_path)
                logging.debug(f"要素のスクリーンショットを保存しました: {screenshot_path}")
            except Exception as e:
                logging.error(f"要素のスクリーンショット撮影に失敗しました: {e}")

    def _execute_side_effect(self, func, *args, **kwargs):
        """
        DB更新など、副作用を伴うPython関数をドライランモードを考慮して実行する。

        使用例:
        self._execute_side_effect(commit_user_actions, user_ids=[...], is_comment_posted=False)

        :param func: 実行する関数オブジェクト
        :param args: 関数に渡す位置引数
        :param kwargs: 関数に渡すキーワード引数。'action_name'はログ出力用に予約されている。
        """
        action_name = kwargs.pop("action_name", func.__name__)

        if not self.dry_run:
            return func(*args, **kwargs)
        else:
            logging.info(f"  -> [DRY RUN] 副作用のあるアクション '{action_name}' をスキップします。")
            return None

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

                # 当初のシンプルなスクリーンショット撮影処理に戻す
                self.page.screenshot(path=screenshot_path)
                logging.info(f"スクリーンショットを保存しました: {screenshot_path}")
            except Exception as ss_e:
                logging.error(f"スクリーンショットの保存に失敗しました: {ss_e}")

    @abstractmethod
    def _execute_main_logic(self):
        """
        タスク固有のメインロジック。
        サブクラスで必ず実装する必要がある。
        """
        pass

    def _print_progress_bar(self, iteration, total, prefix='Progress', suffix='Complete', length=50, fill='■'):
        """
        コンソールにプログレスバーを表示する。
        loggingとは独立してsys.stdoutに直接書き込むことで、ログ出力と共存させる。
        """
        try:
            # ターミナルの幅を取得しようと試みる（失敗してもデフォルト値で動作）
            try:
                import os
                terminal_width = os.get_terminal_size().columns
                # プレフィックス、サフィックス、パーセンテージ表示などの長さを考慮
                bar_length = terminal_width - len(prefix) - len(suffix) - 20
                length = max(10, bar_length) # 最低10は確保
            except (ImportError, OSError):
                pass # ターミナルサイズが取得できない環境でも動作

            percent = ("{0:.1f}").format(100 * (iteration / float(total)))
            filled_length = int(length * iteration // total)
            bar = fill * filled_length + '-' * (length - filled_length)
            # Uvicornなどのバッファリング環境でもリアルタイムに表示させるため、
            # \nで改行して一度フラッシュさせ、次の行でカーソルを上に戻す
            # \033[F はカーソルを前の行の先頭に移動するANSIエスケープシーケンス
            line_to_print = f'{prefix} |{bar}| {percent}% ({iteration}/{total}) {suffix}'
            # ターミナルの幅に合わせて余分なスペースで上書きし、前の行の残骸を消す
            sys.stdout.write(f"\033[F{line_to_print.ljust(length + 30)}\n")
        except Exception:
            pass # プログレスバー表示でエラーが起きても本体処理には影響させない