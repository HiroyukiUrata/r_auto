import logging
import random
import time

from playwright.sync_api import expect
from app.test_x.tasks.base_task import BaseTask

class LikeTestTask(BaseTask):
    """
    【検証用】楽天ROOMの検索結果を巡回し、「いいね」アクションを実行する。
    """
    def __init__(self, count: int = 10):
        super().__init__(count=count)
        self.action_name = "【検証用】いいね"

    def _execute_main_logic(self):
        page = self.page

        # ひらがな「あ」から「ん」までのリストからランダムに1文字選ぶ
        #hiragana_chars = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん"
        hiragana_chars = "ん"
        random_keyword = random.choice(hiragana_chars)
        target_url = f"https://room.rakuten.co.jp/search/item?keyword={random_keyword}&colle=&comment=&like=&user_id=&user_name=&original_photo=0"
       
        logging.info(f"ランダムなキーワード「{random_keyword}」で検索結果ページに移動します...")
        page.goto(target_url)

        # ページのネットワークが落ち着くまで待つ（動的コンテンツの読み込み完了を期待）
        logging.info("ページの読み込みと動的コンテンツの生成を待っています...")
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(2) # 念のため少し待つ

        # --- いいね済みボタンを非表示にする ---
        logging.info("「いいね」済みボタンを非表示にします。")
        page.add_style_tag(content="a.icon-like.isLiked { display: none !important; }")

        # --- 「いいね」処理のループ ---
        liked_count = 0
        start_time = time.time()
        last_liked_user = None # 最後に「いいね」したユーザー名を記録
        user_like_counts = {} # ユーザーごとの「いいね」回数を記録

        while liked_count < self.target_count:
            elapsed_time = time.time() - start_time
            if elapsed_time > self.max_duration_seconds:
                logging.info(f"最大実行時間（{self.max_duration_seconds}秒）に達したため、タスクを終了します。")
                break

            # --- 「いいね」ボタンを1つずつ探してクリック ---
            # 「いいね」済みではない、最初の「いいね」ボタンを探す
            button_to_click = page.locator("a.icon-like.right:not(.isLiked)").first

            if button_to_click.count() > 0:
                try:
                    # ユーザー名を取得してログに出力
                    user_name = "不明なユーザー"
                    try:
                        # ボタンの祖先要素である投稿アイテム全体(<div class="item">)を探す
                        item_container = button_to_click.locator('xpath=ancestor::div[contains(@class, "item") and not(contains(@class, "items-search"))]')
                        user_name_element = item_container.locator('div.owner span.name.ng-binding').first
                        user_name = user_name_element.inner_text().strip()
                    except Exception:
                        logging.warning("ユーザー名の取得に失敗しましたが、「いいね」処理は続行します。")

                    # ユーザーごとの「いいね」回数をチェック
                    current_user_likes = user_like_counts.get(user_name, 0)
                    if user_name != "不明なユーザー" and current_user_likes >= 3:
                        logging.info(f"ユーザー「{user_name}」への「いいね」が上限の3回に達したため、このユーザーの投稿をスキップします。")
                        # このユーザーの投稿をすべて非表示にする
                        # 特殊文字をエスケープする必要があるため、単純なf-stringは避ける
                        page.add_style_tag(content=f'div.item:has(div.owner span.name:has-text("{user_name}")) {{ display: none !important; }}')
                        time.sleep(1) # スタイル適用を待つ
                        continue # 次のボタンを探す

                    # 直前に「いいね」したユーザーと同じでないかチェック
                    is_duplicate = user_name != "不明なユーザー" and user_name == last_liked_user

                    # ボタンがクリック可能になるまで最大5秒待つ
                    expect(button_to_click).to_be_enabled(timeout=5000)
                    button_to_click.click()
                    
                    liked_count += 1
                    user_like_counts[user_name] = current_user_likes + 1
                    
                    log_message = f"ユーザー「{user_name}」の投稿に「いいね」しました。(合計: {liked_count}件, このユーザーへ: {user_like_counts[user_name]}回目)"
                    if is_duplicate:
                        logging.info(f"連続で{log_message}")
                    else:
                        logging.info(log_message)

                    last_liked_user = user_name # 最後に「いいね」したユーザー名を更新
                    time.sleep(random.uniform(1, 2)) # 人間らしい間隔

                    # 新しい投稿を読み込むために少しスクロールする
                    page.evaluate("window.scrollBy(0, 300)") # 300ピクセル下にスクロール
                    time.sleep(random.uniform(1, 2)) # スクロール後の読み込みを待つ
                    continue 
                except Exception as e:
                    logging.warning(f"「いいね」クリック中にエラーが発生しました: {e}")
                    # エラーが発生しても処理を継続するため、ループを抜ける
                    break

            # 新しいボタンが見つからなかった場合、スクロールする
            else:
                logging.info("いいね可能なボタンが見つかりません。ページをスクロールします...")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(3) # スクロール後の読み込みを待つ

        logging.info(f"合計{liked_count}件の「いいね」を実行しました。")

def run_like_test(count: int = 10):
    """ラッパー関数"""
    task = LikeTestTask(count=count)
    return task.run()