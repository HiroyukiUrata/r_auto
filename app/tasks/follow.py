import logging
import random
import time
import os
import re

from playwright.sync_api import expect
from app.core.base_task import BaseTask

class FollowTask(BaseTask):
    """
    楽天ROOMのユーザーを検索し、「フォロー」アクションを実行する。
    """
    def __init__(self, count: int = 10):
        super().__init__(count=count)
        self.action_name = "フォロー"

    def _execute_main_logic(self):
        page = self.page

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
        #logging.info("フォロー済みのユーザーを非表示にします。")
        #page.add_style_tag(content='div[class^="button-wrapper"]:has(button[aria-label*="フォロー中"]) { display: none !important; }')

        # --- フォロー処理 ---
        followed_count = 0
        user_follow_attempts = {} # ユーザーごとのフォロー試行回数を記録
        start_time = time.time()

        while followed_count < self.target_count:
            elapsed_time = time.time() - start_time
            if elapsed_time > self.max_duration_seconds:
                logging.info(f"最大実行時間（{self.max_duration_seconds}秒）に達したため、タスクを終了します。")
                break
            
            # 表示されている「フォローする」ボタンの最初のものを探す
            follow_button = page.get_by_role("button", name="フォローする").first
            
            if follow_button.count() > 0:
                try:
                    # ボタンがクリック可能になるまで最大5秒待つ
                    expect(follow_button).to_be_enabled(timeout=5000)

 # フォロー対象のユーザー名を取得
                    user_name = "不明なユーザー"
                    user_row = None # user_rowを初期化
                    try:
                        # follow_button から一番近い profile-wrapper を探す
                        user_row = follow_button.locator('xpath=ancestor::div[contains(@class, "profile-wrapper")]').first
                         
                        if user_row.count() > 0:
                            # profile-wrapper 内のプロフィール名を取得
                            name_element = user_row.locator('span[class*="profile-name"]').first
                            if name_element.count() > 0:
                                user_name = name_element.inner_text().strip()
                    except Exception:
                        logging.warning("ユーザー名の取得に失敗しましたが、フォロー処理は続行します。")


                    # like.pyを参考に、同じユーザーへの試行回数に上限を設ける
                    current_attempts = user_follow_attempts.get(user_name, 0)
                    if user_name != "不明なユーザー" and current_attempts >= 3:
                        logging.warning(f"ユーザー「{user_name}」へのフォロー試行が上限の3回に達したため、スキップします。")
                        # このユーザーの行を非表示にする
                        if user_row and user_row.count() > 0:
                            try:
                                user_row.evaluate("node => node.style.display = 'none'")
                            except Exception as e:
                                logging.warning(f"上限到達ユーザーの非表示中にエラーが発生しましたが、処理を続行します: {e}")
                        continue # 次のボタンを探す

                    # このユーザーへのフォローが初めての場合のみ、全体の目標件数をカウントアップ
                    if current_attempts == 0:
                        followed_count += 1
                    user_follow_attempts[user_name] = current_attempts + 1

                    follow_button.click(force=True)

                    # like.pyのロジックを参考に、フォローしたユーザーの行をその場で非表示にする
                    if user_row and user_row.count() > 0:
                        try:
                            user_row.evaluate("node => node.style.display = 'none'")
                        except Exception as e:
                            logging.warning(f"フォロー済みユーザーの非表示中にエラーが発生しましたが、処理を続行します: {e}")

                    # このユーザーへのフォローが初めての場合のみログを出力
                    if current_attempts == 0:
                        log_message = f"ユーザー「{user_name}」をフォローしました。(目標: {followed_count}/{self.target_count}件)"
                        logging.info(log_message)

                    time.sleep(random.uniform(3, 4))

                    # 次のボタンを探すためにループの先頭に戻る
                    continue

                except Exception as e:
                    logging.warning(f"フォロークリック中にエラーが発生しました: {e}")
                    break
            else:
                logging.info("フォロー可能なユーザーが見つかりません。モーダル内をスクロールします...")
                # ページ本体ではなく、フォロワー一覧のコンテナ(#userList)をスクロールする
                page.locator("div#userList").evaluate("node => node.scrollTop = node.scrollHeight")
                time.sleep(3) # スクロール後の読み込みを待つ

        logging.info(f"合計{followed_count}件のフォローを実行しました。")

def run_follow_action(count: int = 10):
    """ラッパー関数"""
    task = FollowTask(count=count)
    return task.run()