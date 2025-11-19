import logging
import os
import time
import shutil
import sys
from abc import ABC, abstractmethod
from typing import Optional
from playwright.sync_api import sync_playwright, BrowserContext, Page, Locator, Error as PlaywrightError
from app.core.config_manager import is_headless, SCREENSHOT_DIR, get_config

# --- プロファイルパスの定義 ---
PRIMARY_PROFILE_DIR = "db/playwright_profile"
SECONDARY_PROFILE_DIR = "db/playwright_profile_secondary"
BACKUP_PROFILE_DIR = "db/playwright_profile_backup"

class LoginRedirectError(Exception):
    """ログインページへのリダイレクトを検知した際に送出されるカスタム例外"""
    pass

class BaseTask(ABC):
    """
    すべてのタスククラスが継承する基本クラス。
    """
    def __init__(self, count: Optional[int] = None, max_duration_seconds: int = 600, dry_run: bool = False, preferred_profile: Optional[str] = None):
        self.target_count = count
        self.max_duration_seconds = max_duration_seconds
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.action_name = "アクション"  # サブクラスで上書きする
        self.needs_browser = True # デフォルトではブラウザを必要とする
        self.use_auth_profile = True # デフォルトでは認証プロファイルを使用する
        self.dry_run = dry_run

        # --- プロファイル切り替えロジック用の属性 ---
        # 引数で指定されていない場合、グローバル設定から読み込む
        profile_to_use = preferred_profile
        if profile_to_use is None:
            config = get_config()
            profile_to_use = config.get('preferred_profile', 'primary')

        if profile_to_use == 'secondary':
            self.profile_dirs = [SECONDARY_PROFILE_DIR, PRIMARY_PROFILE_DIR]
        else: # 'primary' またはデフォルト
            self.profile_dirs = [PRIMARY_PROFILE_DIR, SECONDARY_PROFILE_DIR]
        self.current_profile_dir = self.profile_dirs[0] # 最初は優先プロファイルを使用

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
            logging.debug(f"  -> [DRY RUN] 副作用のあるアクション '{action_name}' をスキップします。")
            return None

    def _setup_browser(self):
        """ブラウザコンテキストをセットアップする"""
        headless_mode = is_headless()
        logging.debug(f"Playwright ヘッドレスモード: {headless_mode}")

        if self.use_auth_profile: # 認証プロファイルを使用する場合
            logging.debug(f"認証プロファイル ({self.current_profile_dir}) を使用してブラウザを起動します。")
            # プロファイルディレクトリが存在しない場合は作成
            os.makedirs(self.current_profile_dir, exist_ok=True)

            lockfile_path = os.path.join(self.current_profile_dir, "SingletonLock")
            if os.path.exists(lockfile_path):
                logging.warning(f"古いロックファイル {lockfile_path} が見つかったため、削除します。")
                os.remove(lockfile_path)

            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.current_profile_dir,
                headless=headless_mode,
                slow_mo=250, # ヘッドレスでも少し遅延を入れて人間らしさを演出
                env={"DISPLAY": ":0"},
                args=["--disable-blink-features=AutomationControlled"] # 自動化検知を回避する引数を追加
            )
        else:
            logging.debug("新しいブラウザセッション（認証プロファイルなし）で起動します。")
            browser = self.playwright.chromium.launch(
                headless=headless_mode,
                slow_mo=250, # ヘッドレスでも少し遅延を入れて人間らしさを演出
                env={"DISPLAY": ":0"},
                args=["--disable-blink-features=AutomationControlled"] # 自動化検知を回避する引数を追加
            )
            self.context = browser.new_context(locale="ja-JP")

        self.page = self.context.new_page()
        # ビューポートサイズを固定して、ヘッドレスモードと通常モードの挙動の差をなくす
        self.page.set_viewport_size({"width": 1920, "height": 1080})

        # ★★★ ログ追加: ブラウザ起動後のロックファイル確認 ★★★
        if self.use_auth_profile:
            import glob
            singleton_files_after_setup = glob.glob(os.path.join(self.current_profile_dir, "Singleton*"))
            #logging.debug(f"[ロックファイル確認] ブラウザ起動直後のSingletonファイル: {singleton_files_after_setup}")

    def _teardown_browser(self):
        """ブラウザコンテキストを閉じる"""
        if self.context:
            try:
                #logging.debug("ブラウザコンテキストを閉じています...")
                self.context.close()
                time.sleep(2)  # 閉じるのを少し待つ
            except Exception as e:
                logging.error(f"ブラウザコンテキストのクローズ中にエラーが発生しました: {e}")
            finally:
                # ★★★ ログ追加 & 処理整理: ブラウザ終了後のロックファイルクリーンアップ ★★★
                if self.use_auth_profile:
                    import glob
                    # ブラウザプロセスが完全に終了するのを少し待つ
                    time.sleep(3)

                    # 10秒間、ロックファイルが消えるのを待機し、それでも残っていれば強制削除
                    for i in range(10): # 最大10秒
                        remaining_files = glob.glob(os.path.join(self.current_profile_dir, "Singleton*"))
                        if not remaining_files:
                            #logging.debug(f"[ロックファイル確認] プロファイルのロックが正常に解放されました。({i+1}秒)")
                            break
                        logging.debug(f"[ロックファイル確認] ロックファイルがまだ存在します。待機中... ({i+1}秒): {remaining_files}")
                        time.sleep(1)
                    else: # forループがbreakされずに完了した場合 (タイムアウト)
                        final_remaining_files = glob.glob(os.path.join(self.current_profile_dir, "Singleton*"))
                        if not final_remaining_files:
                            #logging.debug("[ロックファイル確認] 最終確認でロックファイルの解放を確認しました。")
                            return
                        logging.warning(f"ブラウザ終了後もSingletonファイルが残存しています。強制削除を試みます: {final_remaining_files}")
                        for file_path in final_remaining_files:
                            try:
                                os.remove(file_path)
                                logging.debug(f"  -> 残存ファイルを強制削除しました: {file_path}")
                            except OSError as e:
                                logging.error(f"  -> ファイルの削除に失敗しました: {file_path}, エラー: {e}")

    def _backup_current_profile(self):
        """現在使用している正常なプロファイルをバックアップする"""
        if not self.use_auth_profile or self.dry_run:
            return
        
        logging.debug(f"現在の正常なプロファイル '{self.current_profile_dir}' を '{BACKUP_PROFILE_DIR}' にバックアップします。")
        try:
            if os.path.exists(BACKUP_PROFILE_DIR):
                shutil.rmtree(BACKUP_PROFILE_DIR)
            ignore_patterns = shutil.ignore_patterns('Singleton*', '*.lock', '*Cache*')
            shutil.copytree(self.current_profile_dir, BACKUP_PROFILE_DIR, ignore=ignore_patterns)
            logging.debug("プロファイルのバックアップが完了しました。")
        except Exception as e:
            logging.error(f"プロファイルのバックアップ作成中にエラーが発生しました: {e}", exc_info=True)

    def run(self):
        """タスクの実行フローを管理する"""
        success = False
        message = "" # タスク結果のメッセージを格納する変数
        if self.target_count is not None:
            logging.debug(f"「{self.action_name}」アクションを開始します。目標件数: {self.target_count}")
        else:
            logging.debug(f"「{self.action_name}」アクションを開始します。")

        if self.needs_browser:
            with sync_playwright() as p:
                self.playwright = p
                
                for i, profile_dir in enumerate(self.profile_dirs):
                    self.current_profile_dir = profile_dir
                    try:
                        self._setup_browser()
                        success = self._execute_main_logic()
                        
                        # タスクが正常に完了し、かつプロファイルの切り替えが発生した場合（i > 0）のみ、
                        # 現在の正常なプロファイル（セカンダリ）をバックアップする。
                        if success and i > 0:
                            # --- ★★★ 重要 ★★★ ---
                            # ファイル操作の前に、現在のブラウザコンテキストを完全に閉じてファイルロックを解放する
                            logging.debug("自動復旧の前にブラウザコンテキストを閉じます...")
                            self._teardown_browser()

                            # --- 失敗したプロファイルの自動復旧ロジック ---
                            # self.profile_dirs[0] は最初に試行した（失敗した）プロファイル
                            # self.profile_dirs[1] は次に試行した（成功した）プロファイル
                            failed_profile = self.profile_dirs[0]
                            successful_profile = self.profile_dirs[1]

                            logging.debug(f"プロファイル '{failed_profile}' での失敗後、'{successful_profile}' で成功しました。失敗したプロファイルを自動復旧します。")
                            try:
                                # 1. 失敗したプロファイルを削除
                                if os.path.exists(failed_profile):
                                    shutil.rmtree(failed_profile)
                                    logging.debug(f"失敗したプロファイル '{failed_profile}' を削除しました。")

                                # 2. 成功したプロファイルを、失敗したプロファイルの場所にコピー（復旧）
                                shutil.copytree(successful_profile, failed_profile, ignore=shutil.ignore_patterns('Singleton*', '*.lock', '*Cache*'))
                                logging.debug(f"プロファイル '{failed_profile}' を正常なプロファイル '{successful_profile}' の内容で復旧しました。")

                                # 3. 復旧したプロファイル（元々失敗していた方）を新しいバックアップとして保存
                                # これにより、常に両方のプロファイルが正常な状態に保たれる
                                self.current_profile_dir = failed_profile # バックアップ対象を復旧したプロファイルに設定
                                self._backup_current_profile()
                                # 自動復旧が成功したことをメッセージに設定
                                message = "プロファイルの自動復旧が完了しました。"

                            except Exception as recovery_e:
                                logging.error(f"プロファイルの自動復旧中にエラーが発生しました: {recovery_e}", exc_info=True)

                        # 正常に完了したらループを抜ける
                        break

                    except LoginRedirectError as e:
                        logging.warning(e)
                        if i < len(self.profile_dirs) - 1:
                            logging.warning("別のプロファイルで再試行します...")
                            # ブラウザを閉じてから次のループへ
                            self._teardown_browser() 
                            continue
                        else:
                            logging.error("すべてのプロファイルでログインに失敗しました。タスクを中止します。")
                            success = False
                            break
                    except FileNotFoundError as e:
                        logging.error(f"ファイルが見つかりません: {e}")
                        success = False
                        break # ファイルがない場合は再試行しても無駄なので終了
                    except Exception as e:
                        is_detailed_log = os.getenv('LOG_FORMAT', 'detailed').lower() == 'detailed'
                        logging.error(f"「{self.action_name}」アクション中に予期せぬエラーが発生しました: {e}", exc_info=is_detailed_log)
                        self._take_screenshot_on_error()
                        success = False
                        break # 予期せぬエラーでも再試行はせず終了
                    finally:
                        # 各試行の最後に必ずブラウザを閉じる
                        # （ただし、ループの最後のエラーでない場合は、次のループの前に閉じる）
                        if self.page and not self.page.is_closed():
                            self._teardown_browser()
                
                # ループを抜けた後、万が一コンテキストが残っていれば閉じる
                if self.page and not self.page.is_closed():
                    self._teardown_browser()
        else:
            # ブラウザ不要のタスク
            try:
                success = self._execute_main_logic()
            except Exception as e:
                # 本番環境(simple)ではトレースバックを抑制し、開発環境(detailed)では表示する
                logging.error(f"「{self.action_name}」アクション中にエラーが発生しました: {e}", exc_info=is_detailed_log)
                success = False

        logging.debug(f"「{self.action_name}」アクションを終了します。")
        # 戻り値を (成功/失敗, メッセージ) のタプルに変更
        if message:
            return success, message
        return success

    def _take_screenshot_on_error(self, prefix: str = "error"):
        """エラー発生時にスクリーンショットを保存する"""
        if self.page:
            try:
                os.makedirs(SCREENSHOT_DIR, exist_ok=True)
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                # 日本語のアクション名ではなく、一意のタスクID(tag)を使用する
                # これにより、エラー管理画面でタスク名を正確に逆引きできるようになる
                safe_action_name = getattr(self, 'tag', self.action_name)
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
                # プレフィックス、サフィックス、パーセンテージ表示などの固定部分の長さを計算
                # | | % (/)  の分
                fixed_chars_len = len(prefix) + len(suffix) + 25
                bar_length = terminal_width - fixed_chars_len
                length = max(10, bar_length) # 最低10は確保
            except (ImportError, OSError):
                pass # ターミナルサイズが取得できない環境でも動作

            percent = ("{0:.1f}").format(100 * (iteration / float(total)))
            filled_length = int(length * iteration // total)
            bar = fill * filled_length + '-' * (length - filled_length)
            # \rでカーソルを行頭に戻し、sys.stdout.flush()で即時表示を強制する
            line_to_print = f'\r{prefix} |{bar}| {percent}% ({iteration}/{total}) {suffix}'
            sys.stdout.write(line_to_print)
            if iteration == total:
                sys.stdout.write('\n') # 完了したら改行
            sys.stdout.flush()
        except Exception:
            pass # プログレスバー表示でエラーが起きても本体処理には影響させない