import logging
import os
import time
from app.core.base_task import BaseTask


logger = logging.getLogger(__name__)

# --- ★★★ ローカルPCのChromeプロファイルパスを設定 ★★★ ---
# Seleniumで使用していたプロファイルパスを設定します。
# r"..." (raw文字列) を使うと、パス区切り文字 `\` をエスケープする必要がなく便利です。
LOCAL_CHROME_PROFILE_PATH = r"C:\Users\Admin\AppData\Local\Google\Chrome\SeleniumProfile"


class ManualTestTask(BaseTask):
    """
    指定されたURLにアクセスし、ブラウザが閉じられるまで待機する手動テスト用のタスク。
    """
    def __init__(self, script: str = None, use_auth: bool = True):
        # --- ここで手動テストの挙動を切り替えます ---
        # True: GUIなし / False: GUIあり
        self.headless_mode = True

        # True: ログイン情報を引き継ぐ / False: 新規セッションで起動
        # コマンドライン引数 `use_auth` で制御される
        self.use_auth = use_auth

        super().__init__(count=None)
        if not script:
            raise ValueError("実行するスクリプトファイル (--script) を指定する必要があります。")

        self.script_path = script
        self.action_name = f"手動テスト (スクリプト: {self.script_path})"
        
    def _setup_browser(self):
        """
        ManualTestTask専用のブラウザセットアップ。
        BaseTaskのロジックをオーバーライドし、このタスク固有の設定を適用します。
        """
        logger.info(f"手動テストモードでブラウザを起動します (headless: {self.headless_mode}, use_auth: {self.use_auth})")

        if self.use_auth:
            if not os.path.exists(LOCAL_CHROME_PROFILE_PATH):
                raise FileNotFoundError(f"指定されたローカルプロファイルが見つかりません: {LOCAL_CHROME_PROFILE_PATH}")

            lockfile_path = os.path.join(LOCAL_CHROME_PROFILE_PATH, "SingletonLock")
            if os.path.exists(lockfile_path):
                logger.warning(f"古いロックファイル {lockfile_path} が見つかったため、削除します。")
                os.remove(lockfile_path)
            
            # 安定性とプロセスの完全終了のため、launch_persistent_context を使用します。
            # channel="chrome" を指定することで、PCにインストール済みのChromeを直接利用し、
            # プロファイルの競合によるハングアップを防ぎます。
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=LOCAL_CHROME_PROFILE_PATH,
                headless=self.headless_mode,
                slow_mo=500,
                channel="chrome", # ★★★ この引数が重要 ★★★
                args=["--disable-blink-features=AutomationControlled"]
            )
        else:
            logger.info("認証情報を使用せずに、新しいブラウザセッションで起動します。")
            browser = self.playwright.chromium.launch(
                headless=self.headless_mode,
                slow_mo=500,
            )
            self.context = browser.new_context(locale="ja-JP")
        
        self.page = self.context.new_page()

    def _execute_main_logic(self):
        # --- ★★★ 修正点: manual-test実行時のみデバッグログを有効化 ★★★ ---
        # このタスクはデバッグが主目的のため、DEBUGレベルのログを強制的に表示する
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("manual-testタスクのため、デバッグログを有効にしました。")

        page = self.page
        logger.debug("ブラウザの準備が完了しました。外部スクリプトを実行します。")
        
        if self.script_path:
            if not os.path.exists(self.script_path):
                logger.error(f"指定されたスクリプトファイルが見つかりません: {self.script_path}")
                return False
            
            logger.info(f"外部スクリプト '{self.script_path}' を実行します...")
            with open(self.script_path, "r", encoding="utf-8") as f:
                script_code = f.read()
            
            # スクリプト内で 'page' と 'context' 変数を使えるようにして実行
            exec(script_code, {'page': page, 'context': self.context})
            logger.info(f"スクリプト '{self.script_path}' の実行が完了しました。")

        if self.headless_mode:
            logger.info("ヘッドレスモードのため、処理完了後に自動でブラウザを閉じます。")
        else:
            logger.info("ブラウザは起動したままです。")
            logger.info("手動での確認や操作、またはスクリプト実行後の状態確認が完了したら、ブラウザウィンドウを閉じてください。")
            logger.info("ブラウザが閉じられるのを待機しています...")
            # ユーザーがブラウザウィンドウを閉じるのを待機する。
            # self.context.wait_for_event("close") は、認証なしモードでは正しく発火しないことがあるため、
            # 代わりに self.page.wait_for_event("close") を使用して、最初のページが閉じられたことを検知する。
            # これにより、ウィンドウが閉じられた際にタスクが確実に終了するようになる。
            self.page.wait_for_event("close", timeout=0)
            logger.info("ブラウザが閉じられたため、タスクを正常に終了します。")
        return True
    
    def _take_screenshot_on_error(self, prefix: str = "error"):
        """
        エラー発生時にスクリーンショットを保存する。
        manual-test専用に保存先を 'test_scripts/screenshots' に変更する。
        """
        if self.page:
            try:
                screenshot_dir = "test_scripts/screenshots"
                os.makedirs(screenshot_dir, exist_ok=True)
                
                # スクリプトファイル名から安全なプレフィックスを生成
                script_name = os.path.splitext(os.path.basename(self.script_path))[0]
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                screenshot_path = os.path.join(screenshot_dir, f"error_{script_name}_{timestamp}.png")

                self.page.screenshot(path=screenshot_path)
                logging.info(f"スクリーンショットを保存しました: {screenshot_path}")
            except Exception as ss_e:
                logging.error(f"スクリーンショットの保存に失敗しました: {ss_e}")

def run_manual_test(script: str = None, use_auth: bool = True):
    """ラッパー関数"""
    task = ManualTestTask(script=script, use_auth=use_auth)
    return task.run()