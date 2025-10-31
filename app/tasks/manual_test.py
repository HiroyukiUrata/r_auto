import logging
import os
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
    def __init__(self, script: str = None):
        # --- ここで手動テストの挙動を切り替えます ---
        # True: GUIなし / False: GUIあり
        self.headless_mode = False
        # True: ログイン情報を引き継ぐ / False: 新規セッションで起動
        self.use_auth = True
        # -----------------------------------------

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

        logger.info("ブラウザは起動したままです。")
        logger.info("手動での確認や操作、またはスクリプト実行後の状態確認が完了したら、ブラウザウィンドウを閉じてください。")
        logger.info("ブラウザが閉じられるのを待機しています...")
        
        # ユーザーがブラウザを閉じるまで無期限に待機する
        self.context.wait_for_event("close", timeout=0)
        
        logger.info("ブラウザが閉じられたため、タスクを正常に終了します。")
        return True

def run_manual_test(script: str = None):
    """ラッパー関数"""
    task = ManualTestTask(script=script)
    return task.run()