import logging
import random
import time
import os
import re

from playwright.sync_api import expect, Locator, Error
# BaseTaskのインポート
from app.core.base_task import BaseTask

# ロギング設定を簡略化（必要に応じて調整してください）
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class FollowTask(BaseTask):
    """
    楽天ROOMのユーザーを検索し、「フォロー」アクションを実行する。（導線修正・安定版）
    ログイン後のトップページから動的なMy ROOM、フォロワー一覧、ターゲットユーザーのルームへの遷移を実装。
    アクションフェーズでのPlaywrightエラー発生時に、リトライを試行し、タスク全体の続行を優先するようロジックを強化。
    """
    
    # クラス属性として定義
    list_container_selector = 'div#userList'

    def __init__(self, count: int = 10):
        super().__init__(count=count)
        self.action_name = "フォロー"
        self.target_users: list[str] = [] # フォロー対象のユーザー名を保持するリスト
        # 最終状態の確認時間を1秒に維持
        self.state_check_timeout = 1500 

    def hide_remaining_followed_users(self, page):
        """
        現在DOMに存在する「フォロー中」カードのみを非表示にする。
        """
        #logging.info("--- 残留している「フォロー中」ユーザーの非表示処理を実行します。---")
        stable_card_wrapper_selector = f'{self.list_container_selector} div[class*="padding-top-xxsmall"]'

        try:
            js_code = f"""
                document.querySelectorAll('{stable_card_wrapper_selector}').forEach(element => {{
                    const followedButton = element.querySelector('button'); 
                    if (followedButton && followedButton.textContent.includes('フォロー中')) {{
                        element.style.display = 'none';
                    }}
                }});
            """
            page.evaluate(js_code)
            #logging.info(f"残留していた「フォロー中」カードを非表示にしました。")
        except Exception as e:
            logging.error(f"残留カードの非表示処理中にエラーが発生しました: {e}")


    def scroll_to_load_more(self, page, scroll_delay=4, max_scrolls_per_attempt=5) -> bool:
        """
        リストを一定回数スクロールし、新しい要素がロードされた可能性があるかチェックする。
        Trueを返した場合、次のスクロールでも高さが変わらなかったため、リストの終端に達したと判断。
        """
        scroll_container_selector = self.list_container_selector
        current_height = page.locator(scroll_container_selector).evaluate("node => node.scrollHeight")
        initial_height = current_height
        
        #logging.info(f"--- 無限スクロールを {max_scrolls_per_attempt}回 試行します。---")

        for scroll_count in range(1, max_scrolls_per_attempt + 1):
            last_height = current_height
            
            try:
                page.locator(scroll_container_selector).evaluate("node => node.scrollTop = node.scrollHeight")
                time.sleep(scroll_delay)
                current_height = page.locator(scroll_container_selector).evaluate("node => node.scrollHeight")
            except Exception as e:
                logging.warning(f"スクロール中にエラーが発生しました: {e}。スクロールを終了します。")
                return True # エラー時は終端と見なす

            #logging.info(f"モーダルをスクロールしました。({scroll_count}/{max_scrolls_per_attempt})。現在の高さ: {current_height}px")
            
            # 高さの変化がない場合、次のロードは期待できないと判断
            if current_height == last_height:
                #logging.info(f"高さが変わらなかったため、このロードは完了したと判断します。")
                # 3回連続で変わらない場合、終端の可能性が高いと判断
                if scroll_count >= 3: 
                    logging.info("3回以上の連続スクロールで高さが変わらなかったため、リスト終端と判断します。")
                    return True
                # 連続で高さが変わらないがまだロード途中かもしれないので、今回はロード済みとしてループを抜ける
                break 

        return current_height == initial_height # 初回スクロールで全く高さが変わらなかった場合も終端と見なす


    def _execute_main_logic(self):
        page = self.page

        # ===================================================
        # ★★★ 導線修正: My ROOM、フォロワー一覧、ターゲットユーザーへ遷移 ★★★
        # ===================================================
        
        # 1. トップページにアクセス
        target_url = f"https://room.rakuten.co.jp/items" 
        #logging.info(f"トップページ「{target_url}」に移動します...")
        page.goto(target_url, wait_until="domcontentloaded")
        #time.sleep(2)

        # 2. My ROOM リンクをクリック (安定版セレクタを使用)
        myroom_link = page.locator('a:has-text("my ROOM")').first
        # logging.info("「my ROOM」リンクをクリックし、自己ルームに遷移します。")
        myroom_link.wait_for(state='visible', timeout=10000) 
        myroom_link.click()
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        #time.sleep(2)
        
        # 3. 自己ルーム内で「フォロワー」リンクをクリックし、モーダルを開く
        follower_button = page.get_by_text("フォロワー", exact=True).locator("xpath=ancestor::button").first
        #logging.info("自己ルーム内で「フォロワー」ボタンをクリックし、フォロワー一覧モーダルを開きます。")
        follower_button.wait_for(timeout=30000) 
        follower_button.click()
        # 固定sleepは削除

        # モーダル内のリストが表示されるのを待つ
        first_user_in_modal = page.locator(self.list_container_selector).first
        first_user_in_modal.wait_for(state="visible", timeout=30000)
        #logging.info("フォロワー一覧モーダルが表示されました。")

        # 4. モーダル内の最初のユーザーのプロフィール名をクリックし、そのユーザーのルームへ遷移
        first_user_in_modal = page.locator(self.list_container_selector).first
        first_user_profile_link = first_user_in_modal.locator('a.profile-name-content--iyogY').first
        try:
            user_name = first_user_profile_link.locator('span.profile-name--2Hsi5').first.inner_text().strip()
        except Exception:
            user_name = "（ユーザー名取得失敗）"
        
        logging.info(f"ユーザー「{user_name}」のルームに遷移します。")
        first_user_profile_link.click()
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        #time.sleep(3) # 遷移先の描画待ち

        # 5. 遷移先のターゲットユーザーのルーム内で「フォロワー」リンクを再度クリック (アクションの準備)
        target_follower_button = page.locator('button:has-text("フォロワー")').first
        #logging.info(f"ターゲットユーザー「{user_name}」のルームページで「フォロワー」ボタンをクリックします。")
        target_follower_button.wait_for(timeout=30000)
        target_follower_button.click(force=True)
        
        # モーダル内のリストが表示されるのを待つ
        first_button_in_list = page.locator(self.list_container_selector).get_by_role("button", name="フォローする").or_(
            page.locator(self.list_container_selector).get_by_role("button", name="フォロー中")
        ).first
        first_button_in_list.wait_for(timeout=30000)
        #logging.info(f"ターゲットユーザーのフォロワー一覧リストが表示されました。フォロー処理へ移行します。")
        
        # ===================================================
        # ★★★ リストアップフェーズ ★★★
        # ===================================================

        
        #logging.info("--- リストアップフェーズ: フォロー対象ユーザーの抽出を開始します。---")
        
        is_list_end = False
        iteration = 0
        while len(self.target_users) < self.target_count and iteration < 5: 
            iteration += 1
            #logging.info(f"--- リストアップ反復 {iteration}回目 (現在の取得件数: {len(self.target_users)}/{self.target_count}件) ---")
            
            # 1. 無限スクロールを試行し、終端に達したか確認
            if not is_list_end:
                is_list_end = self.scroll_to_load_more(page)

            # 2. 事前非表示を実行（フォロー済みの要素を無視できるように）
            self.hide_remaining_followed_users(page)

            # 3. DOMからフォロー対象ユーザーのリストを全て取得
            all_follow_buttons = page.locator(self.list_container_selector).get_by_role(
                "button", 
                name="フォローする"
            ).all()
            
            # 4. 未取得のユーザーをリストに追加
            initial_count = len(self.target_users)
            #logging.info(f"現在のDOMで検出された「フォローする」ボタン総数: {len(all_follow_buttons)}件") 

            for button in all_follow_buttons:
                if len(self.target_users) >= self.target_count:
                    break
                
                try:
                    user_row = button.locator('xpath=ancestor::div[contains(@class, "profile-wrapper")]').first
                    name_element = user_row.locator('span[class*="profile-name"]').first
                    
                    if name_element.count() > 0:
                        user_name_found = name_element.inner_text().strip()
                        if user_name_found and user_name_found not in self.target_users:
                            self.target_users.append(user_name_found)
                            #logging.info(f"ユーザー「{user_name_found}」をフォロー対象リストに追加しました。({len(self.target_users)}/{self.target_count}件)")
                except Exception:
                    logging.warning("ユーザー名の取得に失敗しましたが、リストアップ処理は続行します。")
            
            # 5. リストが更新されていない（新しいユーザーが見つからなかった）場合、リスト終端と判断
            if len(self.target_users) == initial_count and not is_list_end:
                 logging.warning("スクロールを繰り返しましたが、新しいフォロー対象ユーザーが見つからなかったため、リストの終端に達したと判断します。")
                 is_list_end = True
            
            # 6. リスト終端に達したと判断され、かつ目標件数に達していない場合はループを抜ける
            if is_list_end and len(self.target_users) < self.target_count:
                break
        
        
        if not self.target_users:
            logging.warning("フォロー対象ユーザーがリストアップされなかったため、タスクを終了します。")
            # logging.info("タスクの全フォロー処理が完了しました。ユーザーの要望に基づき、60秒間待機します。")
            # time.sleep(60)
            # logging.info("60秒間の待機を終了します。タスクを終了します。")
            return
            
        #logging.info(f"リストアップフェーズ完了。合計{len(self.target_users)}件のユーザーを対象とします。")


        # ===================================================
        # ★★★ アクションフェーズ: リトライ制御を強化（例外捕捉範囲を拡大） ★★★
        # ===================================================
        
        scroll_container_selector = self.list_container_selector
        page.locator(scroll_container_selector).evaluate("node => node.scrollTop = 0")
        #logging.info("モーダルを最上部までスクロールしました。アクションフェーズへ移行します。")
        time.sleep(1) # 描画待ち

        followed_count = 0
        start_time = time.time()
        
        for user_name_to_follow in self.target_users:
            
            elapsed_time = time.time() - start_time
            if elapsed_time > self.max_duration_seconds:
                logging.info(f"最大実行時間（{self.max_duration_seconds}秒）に達したため、タスクを終了します。")
                break
            
            # --- ロケータの準備 ---
            try:
                escaped_user_name = re.escape(user_name_to_follow)
                profile_wrapper_locator = page.locator(
                    f'{self.list_container_selector} div[class*="profile-wrapper"]:has(:text-is("{escaped_user_name}"))'
                ).first
                
                if profile_wrapper_locator.count() == 0:
                    logging.warning(f"ユーザー「{user_name_to_follow}」のカードが見つかりませんでした。スキップします。")
                    continue
            except Exception as e:
                logging.error(f"ユーザー行の特定中にエラーが発生しました（ユーザー: {user_name_to_follow}）: {e}")
                continue

            # --- フォローアクションとリトライ処理 (最大n回) ---
            max_retries = 3
            success = False

            for attempt in range(max_retries):
                
                # リトライのたびに最新のボタン要素をDOMから取得し直す
                follow_button = profile_wrapper_locator.get_by_role("button", name="フォローする")
                followed_button = profile_wrapper_locator.get_by_role("button", name="フォロー中")

                if follow_button.count() == 0 and followed_button.count() > 0:
                    logging.info(f"ユーザー「{user_name_to_follow}」は既にフォロー中でした。スキップします。")
                    success = True
                    break
                
                # ボタンが存在しない場合、そもそもスキップ
                if follow_button.count() == 0:
                    logging.warning(f"ユーザー「{user_name_to_follow}」の「フォローする」ボタンが見つかりません。スキップします。")
                    break 
                         
                
                if attempt > 0:
                    pass
                    #logging.warning(f"ユーザー「{user_name_to_follow}」：再クリックを試行します。({attempt + 1}/{max_retries}回目)")
                
                try:
                    # ★ フォロー実行 ★
                    follow_button.click(force=True)

                    # ★★★ 状態確認ロジック: 「フォロー中」ボタンの出現のみを確認する ★★★
                    #expect(followed_button).to_be_visible(timeout=self.state_check_timeout)
                    expect(followed_button).to_be_visible(timeout=self.state_check_timeout)
                    
                    success = True
                    break # 成功
                
                # 修正: PlaywrightのErrorだけでなく、予期せぬExceptionも捕捉する
                except (Error, Exception) as e:
                    # 状態遷移に失敗した場合（タイムアウトなど）
                    if attempt == max_retries - 1:
                        # 最終試行でも失敗した場合のみ、エラーログを出力し、次のユーザーへ
                        logging.error(f"ユーザー「{user_name_to_follow}」のフォローは、{max_retries}回の試行後も失敗しました。このユーザーをスキップします。エラー詳細: {e.__class__.__name__}")
                        break # 内側のループを抜けて、次のユーザーの処理へ
                    
                    # リトライが残っている場合は警告ログを出力して続行
                    #logging.warning(f"ユーザー「{user_name_to_follow}」：状態遷移タイムアウトまたはエラー発生。リトライします。")

                time.sleep(random.uniform(3, 4)) # リトライ前の待機 ここが十分じゃないとリトライ失敗になる。

            if success:
                followed_count += 1
                # log_message = f"ユーザー「{user_name_to_follow}」のフォローに成功し、状態遷移を確認しました。(実行: {followed_count}/{len(self.target_users)}件)"
                log_message = f"{user_name_to_follow}をフォローしました。({followed_count}/{len(self.target_users)})"
                logging.info(log_message)
            
            #time.sleep(random.uniform(2, 3)) # フォロー間隔

        logging.info(f"合計{followed_count}件のフォローを実行しました。")

        # ★★★ 処理完了後の60秒待機 ★★★
        # logging.info("タスクの全フォロー処理が完了しました。ユーザーの要望に基づき、60秒間待機します。")
        # time.sleep(60)

        # logging.info("60秒間の待機を終了します。タスクを終了します。")

def run_follow_action(count: int = 10):
    """ラッパー関数"""
    task = FollowTask(count=count)
    return task.run()