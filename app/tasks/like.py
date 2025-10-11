import logging
import os
import random
import time
import re

from playwright.sync_api import sync_playwright, expect
from app.core.config_manager import is_headless

# 永続的な認証情報を保存するプロファイルディレクトリ
PROFILE_DIR = "db/playwright_profile"


def run_like_action(count: int = 10):
    """
    楽天ROOMの検索結果を巡回し、「いいね」アクションを実行する。
    """
    logging.info(f"「いいね」アクションを開始します。目標件数: {count}")

    with sync_playwright() as p:
        if not os.path.exists(PROFILE_DIR):
            logging.error(f"認証プロファイル {PROFILE_DIR} が見つかりません。先に「認証状態の保存」タスクを実行してください。")
            return

        context = None
        try:
            # 保存されたプロファイルを使ってブラウザを起動
            # headless=False にすることで、VNCでブラウザの動作が見える
            headless_mode = is_headless()
            logging.info(f"Playwright ヘッドレスモード: {headless_mode}")
            context = p.chromium.launch_persistent_context(
                PROFILE_DIR,
                headless=headless_mode,
                slow_mo=500 if not headless_mode else 0,  # ヘッドレスでない場合のみ遅延
                env={"DISPLAY": ":0"} # VNC用の仮想ディスプレイを指定
            )
            page = context.new_page()

            # ひらがな「あ」から「ん」までのリストからランダムに1文字選ぶ
            hiragana_chars = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん"
            random_keyword = random.choice(hiragana_chars)
            target_url = f"https://room.rakuten.co.jp/search/item?keyword={random_keyword}&colle=&comment=&like=&user_id=&user_name=&original_photo=0"
           
            logging.info(f"ランダムなキーワード「{random_keyword}」で検索結果ページに移動します...")
            page.goto(target_url)
 
            # ページのネットワークが落ち着くまで待つ（動的コンテンツの読み込み完了を期待）
            logging.info("ページの読み込みと動的コンテンツの生成を待っています...")
            page.wait_for_load_state("networkidle", timeout=30000)
            time.sleep(2) # 念のため少し待つ

            # --- 時間制限とループ制御のための変数を設定 ---
            liked_count = 0
            scroll_attempts = 0
            MAX_SCROLL_ATTEMPTS = 5 # 新しいボタンが見つからない場合にスクロールを試行する最大回数
            MAX_DURATION_SECONDS = 2 * 60 # 最大実行時間を2分に設定
            start_time = time.time()

            while liked_count < count:
                # --- 最大実行時間のチェック ---
                elapsed_time = time.time() - start_time
                if elapsed_time > MAX_DURATION_SECONDS:
                    logging.info(f"最大実行時間（{MAX_DURATION_SECONDS}秒）に達したため、タスクを終了します。")
                    break

                # 画面に見えている「未いいね」ボタンの最初の1つを取得
                button_to_click = page.locator("a.icon-like:not(.isLiked)").first

                if button_to_click.count() > 0:
                    try:
                        # ボタンが見つかったらクリック
                        button_to_click.click()

                        # 成功した場合のみカウントを増やす
                        liked_count += 1
                        logging.info(f"投稿に「いいね」しました。(合計: {liked_count}件)")
                        scroll_attempts = 0 # 見つかったのでリセット
                        time.sleep(random.uniform(1, 3))
                    except Exception:
                        logging.warning("「いいね」クリックに失敗したか、上限に達した可能性があります。タスクを終了します。")
                        break # ループを抜ける
                else:
                    # ボタンが見つからなければスクロール
                    if scroll_attempts >= MAX_SCROLL_ATTEMPTS:
                        logging.info(f"{MAX_SCROLL_ATTEMPTS}回スクロールしても新しいボタンが見つからなかったため、処理を終了します。")
                        break

                    logging.info("「未いいね」ボタンが見つかりません。ページをスクロールします...")
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(3) # スクロール後の読み込みを待つ
                    scroll_attempts += 1

            logging.info(f"合計{liked_count}件の「いいね」を実行しました。")
        except Exception as e:
            logging.error(f"「いいね」アクション中にエラーが発生しました: {e}")
        finally:
            logging.info("処理が完了しました。5秒後にブラウザを閉じます...")
            time.sleep(5)
            if context:
                context.close()
            logging.info("ブラウザコンテキストを閉じました。")
            logging.info("「いいね」アクションを終了します。")