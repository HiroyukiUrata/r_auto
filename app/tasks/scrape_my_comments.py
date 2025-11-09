import logging
import time
import re
import json
from playwright.sync_api import Page, Error as PlaywrightError
from datetime import datetime, timedelta
from app.utils.selector_utils import convert_to_robust_selector
from app.core.database import bulk_insert_my_post_comments, get_latest_comment_details_by_post, get_latest_comment_timestamps_by_post
from app.core.base_task import BaseTask

logger = logging.getLogger(__name__)

def parse_relative_time(time_str: str, reference_time: datetime) -> str:
    """
    「54分前」「19時間前」「3日前」「10月29日」のような相対的な時間表記を
    ISO 8601形式のタイムスタンプ文字列に変換する。
    """
    
    if "分前" in time_str:
        minutes = int(re.search(r'(\d+)', time_str).group(1))
        dt = reference_time.replace(second=0, microsecond=0) - timedelta(minutes=minutes)
    elif "時間前" in time_str:
        hours = int(re.search(r'(\d+)', time_str).group(1))
        dt = reference_time.replace(second=0, microsecond=0) - timedelta(hours=hours)
    elif "日前" in time_str:
        days = int(re.search(r'(\d+)', time_str).group(1))
        dt = reference_time.replace(second=0, microsecond=0) - timedelta(days=days)
    elif "月" in time_str and "日" in time_str:
        match = re.search(r'(\d+)月(\d+)日', time_str)
        month = int(match.group(1))
        day = int(match.group(2))
        # 今年の日付として解釈する
        dt = reference_time.replace(year=reference_time.year, month=month, day=day, hour=12, minute=0, second=0, microsecond=0)
    else:
        # 不明な形式の場合は秒とマイクロ秒を丸めた現在時刻を返す
        return reference_time.replace(second=0, microsecond=0).isoformat()
        
    return dt.isoformat()

class ScrapeMyCommentsTask(BaseTask):
    """
    自分のROOMに遷移し、ピン留めされた投稿からコメントを収集してDBに保存するタスク。
    """
    def __init__(self):
        super().__init__(count=None)
        self.action_name = "自分の投稿コメント収集"
        self.needs_browser = True
        self.use_auth_profile = True
        self.task_start_time = datetime.now() # タスク開始時刻を記録

    def _execute_main_logic(self):
        page = self.context.new_page()
        total_inserted_count = 0

        # タスク開始時に、各投稿の最新コメントタイムスタンプをDBから取得
        latest_comment_details_map = get_latest_comment_details_by_post() # 修正：新しい関数を呼び出す

        try:
            # 1. トップページにアクセス
            target_url = f"https://room.rakuten.co.jp/items"
            logger.debug(f"トップページ「{target_url}」に移動します...")
            page.goto(target_url, wait_until="domcontentloaded")
            time.sleep(2)

            # 2. My ROOM リンクをクリック
            myroom_link = page.locator('a:has-text("my ROOM")').first
            logger.debug("「my ROOM」リンクをクリックし、自己ルームに遷移します。")
            myroom_link.wait_for(state='visible', timeout=10000)
            myroom_link.click()
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            logger.debug(f"ページ遷移成功。現在のURL: {page.url}")
            my_room_url = page.url # 自分のROOMのURLを保存

            # 3. 「ピン」アイコンを持つカードを探す
            card_selector = convert_to_robust_selector('div[class*="container--JAywt"]')
            logger.debug("投稿カードが読み込まれるのを待ちます...")
            page.locator(card_selector).first.wait_for(state="visible", timeout=30000)
            page.wait_for_timeout(2000) # Masonryレイアウトの安定を待つ

            logger.debug("ピン留めされた投稿からコメントを収集します...")
            pin_icon_selector = convert_to_robust_selector('div.pin-icon--1FR8u')
            
            pinned_cards = page.locator(f"{card_selector}:has({pin_icon_selector})").all()
            
            if not pinned_cards:
                logger.warning("ピン留めされた投稿が見つかりませんでした。")
                return True

            logger.debug(f"{len(pinned_cards)}件のピン留めされた投稿を発見しました。最大3件を処理します。")
            
            # 最大3件までをループ処理
            for i, card in enumerate(pinned_cards[:3]):
                card.wait_for(state="visible", timeout=10000)

                # カードをクリックして詳細ページに遷移
                try:
                    logger.debug(f"  -> {i+1}件目のピン留め投稿を処理します。")
                    image_link_selector = convert_to_robust_selector("a[class*='link-image--']")
                    card.locator(image_link_selector).first.click()
                    page.wait_for_load_state("domcontentloaded", timeout=20000)
                    post_detail_url = page.url
                    logger.debug(f"  -> 詳細ページに遷移しました: {post_detail_url}")
                    time.sleep(5)

                    # この投稿の最新処理済みタイムスタンプを取得
                    latest_comment_info = latest_comment_details_map.get(post_detail_url) # 修正：新しいマップから情報を取得

                    # 詳細ページで「コメント」ボタンをクリック
                    comment_text_pattern = re.compile(r"^コメント\(\d+件\)$")
                    comment_button_selector = page.locator('div[class*="container--3w_bo"]').filter(has_text=comment_text_pattern).first
                    comment_button_selector.wait_for(state="visible", timeout=15000)
                    comment_button_selector.click()
                    
                    # --- コメントリストのスクレイピング処理 ---
                    logger.debug("  -> コメントリストの全件取得を開始します。")
                    comment_list_container_selector = 'div#contentList'
                    user_name_selector = 'a[class*="user-name--"]'
                    comment_text_selector = 'div[class*="social-text-area--"]'
                    comment_item_selector = f'div[class*="spacer--1O71j"]:has({user_name_selector}):has({comment_text_selector})'
                    spinner_selector = 'svg[class*="spinner---"]'
                    
                    processed_comments = []
                    # (user_page_url, comment_text, post_detail_url) のタプルで重複を管理
                    processed_ids = set()
                    
                    # --- 1. 初回取得 (スクロールなし) ---
                    try:
                        page.locator(comment_item_selector).first.wait_for(state="visible", timeout=15000)
                    except PlaywrightError:
                        logger.debug("    -> コメントが見つかりませんでした。次の投稿に進みます。")
                        page.go_back(wait_until="domcontentloaded")
                        page.wait_for_timeout(2000)
                        continue

                    # --- 2. スクロールによる全件取得ループ ---
                    max_attempts = 15 # 無限ループ防止
                    stop_scraping_this_post = False
                    for attempt in range(max_attempts):
                        all_comment_elements = page.locator(comment_item_selector).all()
                        newly_found_count = 0
                        for item in all_comment_elements:
                            try:
                                user_name_element = item.locator(user_name_selector).first
                                user_name = user_name_element.inner_text()
                                user_page_url = f"https://room.rakuten.co.jp{user_name_element.get_attribute('href')}"
                                comment_text = item.locator(comment_text_selector).first.inner_text().replace('\n', ' ')
                                user_image_url = item.locator('img').first.get_attribute('src')

                                # 取得したコメント投稿者のURLが自分自身のURLと一致する場合、処理をスキップ
                                if user_page_url == my_room_url:
                                    logger.debug(f"    -> 自分のコメントのためスキップします: {user_name} - {comment_text[:20]}...")
                                    continue

                                # このコメントのユニークな識別子を作成
                                comment_unique_id = (user_page_url, comment_text, post_detail_url)
                                if comment_unique_id in processed_ids:
                                    continue

                                relative_time_str = item.locator('div[class*="size-x-small--"]').first.inner_text()
                                post_timestamp = parse_relative_time(relative_time_str, self.task_start_time)

                                # --- 処理済みタイムスタンプとの比較 ---
                                if latest_comment_info: # 修正：判定ロジックを強化
                                    # 条件1: タイムスタンプがDBの最新より古いか等しい
                                    is_older_or_equal_time = datetime.fromisoformat(post_timestamp) <= datetime.fromisoformat(latest_comment_info['post_timestamp'])
                                    # 条件2: ユーザーとコメント内容がDBの最新と一致する
                                    is_same_comment = (user_page_url == latest_comment_info['user_page_url'] and comment_text == latest_comment_info['comment_text'])

                                    # タイムスタンプの揺らぎを考慮し、内容が一致する場合も処理済みとみなす
                                    if is_older_or_equal_time or is_same_comment: # 修正：OR条件で判定
                                        log_reason = "タイムスタンプ" if is_older_or_equal_time else "コメント内容"
                                        logger.debug(f"    -> 処理済みのコメントに到達したため({log_reason}一致)、これ以降の収集を停止します。")
                                        stop_scraping_this_post = True
                                        break # この投稿のコメント収集ループを抜ける

                                processed_ids.add(comment_unique_id)
                                comment_data = {
                                    "user_name": user_name,
                                    "user_page_url": user_page_url,
                                    "comment_text": comment_text,
                                    "post_timestamp": post_timestamp,
                                    "post_detail_url": post_detail_url,
                                    "user_image_url": user_image_url
                                }
                                processed_comments.append(comment_data)
                                newly_found_count += 1
                            except PlaywrightError:
                                continue
                        
                        if stop_scraping_this_post:
                            break # スクロールループも抜ける

                        if newly_found_count > 0:
                            logger.debug(f"    -> {newly_found_count}件の新規コメントを取得 (累計: {len(processed_comments)}件)")

                        # --- スクロール実行とスピナー待機 ---
                        page.locator(comment_list_container_selector).evaluate("node => node.scrollTop = node.scrollHeight")
                        try:
                            page.wait_for_selector(spinner_selector, state='visible', timeout=5000)
                            page.wait_for_timeout(1500)
                            time.sleep(5)
                        except PlaywrightError:
                            logger.debug("    -> スピナーが表示されませんでした。ページの終端と判断します。")
                            break

                        # --- ★★★ 実装漏れ修正: スクロール後に新しく読み込まれたコメントを処理 ★★★ ---
                        all_comment_elements_after_scroll = page.locator(comment_item_selector).all()
                        for item in all_comment_elements_after_scroll:
                            try:
                                user_name_element = item.locator(user_name_selector).first
                                user_name = user_name_element.inner_text()
                                user_page_url = f"https://room.rakuten.co.jp{user_name_element.get_attribute('href')}"
                                comment_text = item.locator(comment_text_selector).first.inner_text().replace('\n', ' ')
                                user_image_url = item.locator('img').first.get_attribute('src')

                                # 自分のコメントはDB登録対象外とする
                                if user_page_url == my_room_url:
                                    logger.debug(f"    -> 自分のコメントのためスキップします: {user_name} - {comment_text[:20]}...")
                                    continue

                                comment_unique_id = (user_page_url, comment_text, post_detail_url)
                                if comment_unique_id in processed_ids:
                                    continue

                                relative_time_str = item.locator('div[class*="size-x-small--"]').first.inner_text()
                                post_timestamp = parse_relative_time(relative_time_str, self.task_start_time)

                                processed_ids.add(comment_unique_id)
                                comment_data = {
                                    "user_name": user_name, "user_page_url": user_page_url,
                                    "comment_text": comment_text, "post_timestamp": post_timestamp,
                                    "post_detail_url": post_detail_url,
                                    "user_image_url": user_image_url
                                }
                                processed_comments.append(comment_data)
                            except PlaywrightError:
                                continue
                    
                    logger.debug(f"  -> 投稿のコメント取得完了。合計 {len(processed_comments)} 件")

                    # --- 取得結果をDBに保存 ---
                    if processed_comments:
                        inserted_count = bulk_insert_my_post_comments(
                            comments_data=processed_comments
                        )
                        if inserted_count is not None:
                            logger.debug(f"  -> DBに新規コメントを{inserted_count}件保存しました。")
                            total_inserted_count += inserted_count

                    logger.debug("  -> 元のページに戻ります。")
                    page.go_back(wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                except PlaywrightError as click_error:
                    logger.error(f"  -> カードのクリックまたはページ遷移中にエラーが発生しました: {click_error}")
                    # エラーが発生しても次のカードの処理を試みるために戻る
                    if "my_room" not in page.url:
                        page.go_back(wait_until="domcontentloaded")
                        page.wait_for_timeout(2000)

        except Exception as e:
            logger.error(f"タスク実行中に予期せぬエラーが発生しました: {e}", exc_info=True)
            self._take_screenshot_on_error(prefix="scrape_my_comments_error")
            return False
        finally:
            if page:
                page.close()
        
        logger.info(f"[Action Summary] name=自分の投稿からコメント収集, count={total_inserted_count}")
        return True

def run_scrape_my_comments():
    """ラッパー関数"""
    task = ScrapeMyCommentsTask()
    return task.run()