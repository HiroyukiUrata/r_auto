import random
import time

from playwright.sync_api import expect
from app.core.base_task import BaseTask
import logging

logger = logging.getLogger(__name__)

class LikeTask(BaseTask):
    """
    楽天ROOMの検索結果を巡回し、「いいね」アクションを実行する。
    """
    def __init__(self, count: int = 10, max_duration_seconds: int = 600):
        super().__init__(count=count, max_duration_seconds=max_duration_seconds)
        self.action_name = "いいね"

    def _execute_main_logic(self):
        page = self.page

        # ひらがな「あ」から「ん」までのリストからランダムに異なる2文字を選び、全角スペースで連結
        hiragana_chars = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん"
        two_random_chars = random.sample(hiragana_chars, 2)
        random_keyword = "　".join(two_random_chars)
        target_url = f"https://room.rakuten.co.jp/search/item?keyword={random_keyword}&colle=&comment=&like=&user_id=&user_name=&original_photo=0"

        logger.debug(f"ランダムなキーワード「{random_keyword}」で検索結果ページに移動します...")
        page.goto(target_url)

        # ページのネットワークが落ち着くまで待つ（動的コンテンツの読み込み完了を期待）
        logger.debug("ページの読み込みと動的コンテンツの生成を待っています...")
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(2) # 念のため少し待つ

        # --- いいね済みボタンを非表示にする ---
        logger.debug("「いいね」済みボタンを非表示にします。")
        page.add_style_tag(content="a.icon-like.isLiked { display: none !important; }")

        # --- 「いいね」処理のループ ---
        liked_count = 0
        error_count = 0
        start_time = time.time()
        last_liked_user = None # 最後に「いいね」したユーザー名を記録
        user_like_counts = {} # ユーザーごとの「いいね」回数を記録

        while liked_count < self.target_count:
            elapsed_time = time.time() - start_time
            if elapsed_time > self.max_duration_seconds:
                logger.info(f"最大実行時間（{self.max_duration_seconds}秒）に達したため、タスクを終了します。")
                break

            # --- 「いいね」ボタンを1つずつ探してクリック ---
            # 「いいね」済みではない、最初の「いいね」ボタンを探す
            button_to_click = page.locator("a.icon-like.right:not(.isLiked):visible").first

            if button_to_click.count() > 0:
                try:
                    # ユーザー名を取得してログに出力
                    user_name = "不明なユーザー"
                    try:
                        # ボタンの祖先要素である投稿アイテム全体(<div class="item">)を探す
                        item_container = button_to_click.locator('xpath=ancestor::div[contains(@class, "item")][1]')
                        user_name_element = item_container.locator('div.owner span.name.ng-binding').first
                        user_name = user_name_element.inner_text().strip()
                    except Exception:
                        logger.warning("ユーザー名の取得に失敗しましたが、「いいね」処理は続行します。")

                    # ユーザーごとの「いいね」回数をチェック
                    current_user_likes = user_like_counts.get(user_name, 0)
                    if user_name != "不明なユーザー" and current_user_likes >= 3:
                        #logging.info(f"ユーザー「{user_name}」への「いいね」が上限の3回に達したため、このユーザーの投稿をスキップします。")
                        # このユーザーの投稿を非表示にする
                        try:
                            item_container.evaluate("node => node.style.display = 'none'")
                        except Exception as e:
                            logger.warning(f"投稿の非表示中にエラーが発生しましたが、処理を続行します: {e}")
                        
                        # 次の有効なボタンを見つけるためにループを継続
                        continue # 次のボタンを探す

                    # 直前に「いいね」したユーザーと同じでないかチェック
                    is_duplicate = user_name != "不明なユーザー" and user_name == last_liked_user

                    # ボタンがクリック可能になるまで最大5秒待つ
                    expect(button_to_click).to_be_enabled(timeout=5000)
                    button_to_click.click()

                    # 「いいね」した投稿をその場で非表示にして、次のループで見つけないようにする
                    try:
                        item_container.evaluate("node => node.style.display = 'none'")
                    except Exception as e:
                        logger.warning(f"投稿の非表示中にエラーが発生しましたが、処理を続行します: {e}")
                    
                    # このユーザーへの「いいね」が初めての場合のみ、全体の目標件数をカウントアップ
                    if current_user_likes == 0:
                        liked_count += 1
                    user_like_counts[user_name] = current_user_likes + 1
                    
                    user_likes_this_time = user_like_counts[user_name]
                    # このユーザーへの「いいね」が初めての場合のみログを出力する
                    if user_likes_this_time == 1:
                        log_message = f"「{user_name}」の投稿に「いいね」しました。({liked_count}/{self.target_count})"
                        if is_duplicate: logger.debug(f"連続で{log_message}")
                        else: logger.debug(log_message)

                    last_liked_user = user_name # 最後に「いいね」したユーザー名を更新
                    time.sleep(random.uniform(3, 4)) # 人間らしい間隔

                    # 新しい投稿を読み込むために少しスクロールする
                    page.evaluate("window.scrollBy(0, 300)") # 300ピクセル下にスクロール
                    time.sleep(random.uniform(1, 2)) # スクロール後の読み込みを待つ
                    continue 
                except Exception:
                    logger.error("「いいね」クリック中にエラーが発生しました。", exc_info=True)
                    error_count += 1
                    # エラーが発生しても処理を継続するため、ループを抜ける
                    break

            # 新しいボタンが見つからなかった場合、スクロールする
            else:
                #logging.info("いいね可能なボタンが見つかりません。ページをスクロールします...")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(3) # スクロール後の読み込みを待つ

        # 目標数と成功数の差をエラー件数として返す
        final_error_count = self.target_count - liked_count
        return liked_count, final_error_count

def run_like_action(count: int = 10, max_duration_seconds: int = 600):
    """ラッパー関数"""
    task = LikeTask(count=count, max_duration_seconds=max_duration_seconds)
    result = task.run()
    # 確実に (成功数, エラー数) のタプルを返すようにする
    return result if isinstance(result, tuple) and len(result) >= 2 else (0, count)