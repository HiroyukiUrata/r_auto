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
            # プロファイルロックファイルを削除して、多重起動エラーを防ぐ
            lockfile_path = os.path.join(PROFILE_DIR, "SingletonLock")
            if os.path.exists(lockfile_path):
                logging.warning(f"古いロックファイル {lockfile_path} が見つかったため、削除します。")
                os.remove(lockfile_path)

            # 保存されたプロファイルを使ってブラウザを起動
            headless_mode = is_headless()
            logging.info(f"Playwright ヘッドレスモード: {headless_mode}")
            context = p.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                headless=headless_mode,
                slow_mo=500 if not headless_mode else 0,
                env={"DISPLAY": ":0"}
            )
            page = context.new_page()

#検証中は以下はスキップ
            if True:
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
            else:
#検証中は固定URLにアクセス

                target_url = f"https://room.rakuten.co.jp/room_8d0de95bd1/items"
                logging.info(f"移動します...")
                page.goto(target_url)

            # --- ユーザーのルーム内で「フォロワー」リンクをクリック ---
            # 「フォロワー」と書かれたボタンを探す
            follower_link = page.locator('button.follow-button--erBoo:has-text("フォロワー")').first
            logging.info("ユーザーのルームページに遷移し、「フォロワー」ボタンが表示されるのを待っています...")
            # ページ遷移と要素の表示を最大30秒待つ
            follower_link.wait_for(timeout=30000)

            # ボタン表示後、ページの他の要素が読み込まれるのを待つ
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            time.sleep(2) # イベントハンドラなどが登録されるのを待つための短い待機

            logging.info("「フォロワー」リンクをクリックして、フォロワー一覧ページに移動します。")
            
            # 「フォロワー」リンクをクリックし、モーダル内のリストが表示されるのを待つ
            follower_link.click(force=True)
            
            # コンテナ(#userList)の中に、最初の「フォローする」ボタンが表示されるまで待つ
            logging.info("フォロワー一覧リストの最初の要素が表示されるのを待っています...")
            first_button_in_list = page.locator("div#userList").get_by_role("button", name="フォローする").or_(
                page.locator("div#userList").get_by_role("button", name="フォロー中")
            ).first
            first_button_in_list.wait_for(timeout=30000)
            logging.info("フォロワー一覧リストが表示されました。")

            # --- フォロー済みユーザーの行を非表示にする ---
            # 「フォロー中」ボタンを持つ親要素を非表示にするCSSを適用
            # Tampermonkeyのロジックを参考に、aria-labelが「フォロー中」のボタンを持つbutton-wrapperを非表示にする
            logging.info("フォロー済みのユーザーを非表示にします。")
            page.add_style_tag(content='div[class^="button-wrapper"]:has(button[aria-label*="フォロー中"]) { display: none !important; }')

            # --- フォロー処理 ---
            followed_count = 0
            MAX_DURATION_SECONDS = 10 * 60
            last_followed_user = None # 最後にフォローしたユーザー名を記録
            start_time = time.time()

            while followed_count < count:
                elapsed_time = time.time() - start_time
                if elapsed_time > MAX_DURATION_SECONDS:
                    logging.info(f"最大実行時間（{MAX_DURATION_SECONDS}秒）に達したため、タスクを終了します。")
                    break
                
                # 表示されている「フォローする」ボタンの最初のものを探す
                follow_button = page.get_by_role("button", name="フォローする").first
                
                if follow_button.count() > 0:
                    try:
                        # ボタンがクリック可能になるまで最大5秒待つ
                        expect(follow_button).to_be_enabled(timeout=5000)

                        # フォローするユーザー名を取得してログに出力
                        user_name = "不明なユーザー"
                        try:
                            # ボタンの祖先要素であるユーザー情報ブロックを取得
                            # ページによって構造が違うため、より汎用的なセレクタに変更
                            # ボタンの祖先から、プロフィール情報全体を囲む 'profile-wrapper' を探す
                            profile_wrapper = follow_button.locator('xpath=ancestor::div[contains(@class, "profile-wrapper")]')
                            user_name_element = profile_wrapper.locator('span[class^="profile-name"]').first
                            user_name = user_name_element.inner_text().strip()
                        except Exception as e:
                            logging.warning("ユーザー名の取得に失敗しましたが、フォロー処理は続行します。")

                        # クリック前の「フォローする」ボタンの数を数える
                        follow_buttons_locator = page.get_by_role("button", name="フォローする")
                        before_count = follow_buttons_locator.count()

                        is_duplicate = user_name != "不明なユーザー" and user_name == last_followed_user

                        # 直前にフォローしたユーザーと同じでないかチェック
                        #if is_duplicate:
                            #logging.warning(f"ユーザー「{user_name}」を連続でフォローしますが、カウントはしません。")

                        follow_button.click(force=True)

                        if not is_duplicate:
                            followed_count += 1
                            log_message = f"ユーザー「{user_name}」をフォローしました。(合計: {followed_count}件)"
                            logging.info(log_message)

                        last_followed_user = user_name # 最後にフォローしたユーザー名を更新
                        time.sleep(random.uniform(3, 4))

                        # 実験: フォロー後に一度スクロールしてリストを更新し、同じユーザーを再度フォローするのを防ぐ
                        #logging.info("次のユーザーを探すため、モーダル内をスクロールします。")
                        page.locator("div#userList").evaluate("node => node.scrollTop = node.scrollHeight")
                        time.sleep(3) # スクロール後の読み込みを待つ

                        # 1回クリックしたら、再度ボタンを探すためにループの先頭に戻る
                        continue

                    except Exception as e:
                        logging.warning(f"フォロークリック中にエラーが発生しました: {e}")
                        break
                else:
                    #logging.info("フォロー可能なユーザーが見つかりません。モーダル内をスクロールします...")
                    # ページ本体ではなく、フォロワー一覧のコンテナ(#userList)をスクロールする
                    page.locator("div#userList").evaluate("node => node.scrollTop = node.scrollHeight")
                    time.sleep(3) # スクロール後の読み込みを待つ

            logging.info(f"合計{followed_count}件のフォローを実行しました。")

        except Exception as e:
            logging.error(f"「フォロー」アクション中にエラーが発生しました: {e}")
        finally:
            time.sleep(5) # 終了前に5秒待機
            if context:
                context.close()
            logging.info("ブラウザコンテキストを閉じました。")
            logging.info("「フォロー」アクションを終了します。")