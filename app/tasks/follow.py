import logging
import random
import time
import os
import re

from playwright.sync_api import sync_playwright, expect
from app.core.config_manager import is_headless

# 永続的な認証情報を保存するプロファイルディレクトリ
PROFILE_DIR = "db/playwright_profile"


def run_follow_action(count: int = 10):
    """
    楽天ROOMのユーザーを検索し、「フォロー」アクションを実行する。
    """
    logging.info(f"「フォロー」アクションを開始します。目標件数: {count}")

    with sync_playwright() as p:
        if not os.path.exists(PROFILE_DIR):
            logging.error(f"認証プロファイル {PROFILE_DIR} が見つかりません。先に「認証状態の保存」タスクを実行してください。")
            return

        context = None
        try:
            # 保存されたプロファイルを使ってブラウザを起動
            headless_mode = is_headless()
            logging.info(f"Playwright ヘッドレスモード: {headless_mode}")
            context = p.chromium.launch_persistent_context(
                PROFILE_DIR,
                headless=headless_mode,
                slow_mo=500 if not headless_mode else 0,
                env={"DISPLAY": ":0"}
            )
            page = context.new_page()

            # ひらがな「あ」から「ん」までのリストからランダムに1文字選ぶ
            hiragana_chars = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん"
            random_keyword = random.choice(hiragana_chars)
            # ユーザー検索用のURL（以前のURLに戻しました）
            target_url = f"https://room.rakuten.co.jp/search/user?keyword={random_keyword}&follower=&items=&rank=4,5,3"
            logging.info(f"ランダムなキーワード「{random_keyword}」でユーザー検索ページに移動します...")
            page.goto(target_url)

            logging.info("ページの読み込みと動的コンテンツの生成を待っています...")
            page.wait_for_load_state("networkidle", timeout=30000)
            time.sleep(2)

            # --- 最初に見つかったユーザーのルームに移動 ---
            second_user_link = page.locator('span.username.ng-binding').nth(1).locator('xpath=..')
            if second_user_link.count() > 0:
                logging.info("2番目に見つかったユーザーのルームに移動します。")
                second_user_link.click()
            else:
                logging.warning("ユーザーが見つからなかったため、タスクを終了します。")
                return
            
            # --- ユーザーのルーム内で「フォロワー」リンクをクリック ---
            # 「フォロワー」と書かれたボタンを探す
            follower_link = page.locator('button.follow-button--erBoo:has-text("フォロワー")').first
            logging.info("ユーザーのルームページに遷移し、「フォロワー」ボタンが表示されるのを待っています...")
            # ページ遷移と要素の表示を最大30秒待つ
            follower_link.wait_for(timeout=30000)
            logging.info("「フォロワー」リンクをクリックして、フォロワー一覧ページに移動します。")
            follower_link.click()

            # --- フォロワー一覧画面が表示されるのを待つ ---
            follower_list_title = page.locator('div.title--2A1RR:has-text("フォロワー")')
            logging.info("フォロワー一覧画面の表示を待っています...")
            follower_list_title.wait_for(timeout=15000)
            logging.info("フォロワー一覧画面が表示されました。フォロー処理を開始します。")

            # --- フォロワー一覧の最初の要素が表示されるのを待つ ---
            logging.info("フォロワーリストの読み込みを待っています...")
            # フォローボタンが表示されるのを待つことで、リストの読み込みを確実にする
            page.locator('button[aria-label="フォローする"]').first.wait_for(timeout=15000)

            # --- フォロー処理 ---
            followed_count = 0
            scroll_attempts = 0
            MAX_SCROLL_ATTEMPTS = 5
            MAX_DURATION_SECONDS = 10 * 60
            start_time = time.time()
            processed_users = set() # 処理済みのユーザー名を保持するセット

            while followed_count < count:
                elapsed_time = time.time() - start_time
                if elapsed_time > MAX_DURATION_SECONDS:
                    logging.info(f"最大実行時間（{MAX_DURATION_SECONDS}秒）に達したため、タスクを終了します。")
                    break
                
                # ユーザーカードのリストを取得 (HTML構造に合わせてセレクタを調整)
                user_cards = page.locator("div.profile-wrapper--2SWLY")
                found_new_user_to_follow = False

                for card in user_cards.all():
                    username_element = card.locator("span.profile-name--2Hsi5")
                    if username_element.count() == 0:
                        continue # ユーザー名が取得できないカードはスキップ
                    
                    username = username_element.inner_text()
                    if username in processed_users:
                        continue # 既に処理済みのユーザーはスキップ

                    processed_users.add(username) # 処理済みセットに追加
                    #logging.info(f"ユーザー「{username}」をチェックします。")

                    # カード内の「フォローする」ボタンを探す
                    follow_button = card.locator('button:has-text("フォローする")')
                    
                    if follow_button.count() > 0:
                        #logging.info(f"ユーザー「{username}」をフォローします。")
                        try:
                            # ボタンがクリック可能になるまで最大5秒待つ
                            expect(follow_button).to_be_enabled(timeout=5000)
                            # クリックを実行
                            follow_button.click(force=True)
                            
                            # クリック後、ボタンの表示が「フォロー中」に変わるのを待つ（最大5秒）
                            try:
                                following_button = card.locator('button:has-text("フォロー中")')
                                expect(following_button).to_be_visible(timeout=5000)
                                # 状態確認が成功した場合のみ、カウントとログ出力を行う
                                followed_count += 1
                                logging.info(f"ユーザー「{username}」をフォローしました。(合計: {followed_count}件)")
                                found_new_user_to_follow = True
                            except Exception:
                                # タイムアウトした場合でもエラーで止めず、警告を出力して次に進む
                                logging.warning(f"ユーザー「{username}」をフォロー後、状態の確認に失敗しました。UIが更新されなかった可能性があります。")
                            
                            time.sleep(random.uniform(3, 4))
                            if followed_count >= count:
                                break # 目標件数に達したらループを抜ける
                        except Exception as e:
                            logging.warning(f"ユーザー「{username}」のフォローに失敗しました: {e}")
                            # 失敗した場合でも、次のユーザーへ進む
                    else:
                        #logging.info(f"ユーザー「{username}」はフォロー済み、またはフォロー対象外です。")
                        pass
                if followed_count >= count:
                    break # 目標件数に達したらwhileループも抜ける

                # 新しいフォロー対象が見つからなかった場合、スクロールする
                if not found_new_user_to_follow:
                    if scroll_attempts >= MAX_SCROLL_ATTEMPTS:
                        logging.info(f"{MAX_SCROLL_ATTEMPTS}回スクロールしても新しいユーザーが見つからなかったため、処理を終了します。")
                        break
                    logging.info("フォロー可能なユーザーが見つかりません。ページをスクロールします...")
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(3)
                    scroll_attempts += 1
                else:
                    scroll_attempts = 0 # フォロー成功時はスクロールカウントをリセット

            logging.info(f"合計{followed_count}件のフォローを実行しました。")
        except Exception as e:
            logging.error(f"「フォロー」アクション中にエラーが発生しました: {e}")
        finally:
            logging.info("処理が完了しました。5秒後にブラウザを閉じます...")
            time.sleep(30)
            if context:
                context.close()
            logging.info("ブラウザコンテキストを閉じました。")
            logging.info("「フォロー」アクションを終了します。")