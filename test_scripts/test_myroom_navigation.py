import logging
import time
import re
from playwright.sync_api import Page
import json
from datetime import datetime, timedelta
from app.utils.selector_utils import convert_to_robust_selector

logger = logging.getLogger(__name__)

def parse_relative_time(time_str: str) -> str:
    """
    「54分前」「19時間前」「3日前」「10月29日」のような相対的な時間表記を
    ISO 8601形式のタイムスタンプ文字列に変換する。
    """
    now = datetime.now()
    
    if "分前" in time_str:
        minutes = int(re.search(r'(\d+)', time_str).group(1))
        dt = now - timedelta(minutes=minutes)
    elif "時間前" in time_str:
        hours = int(re.search(r'(\d+)', time_str).group(1))
        dt = now - timedelta(hours=hours)
    elif "日前" in time_str:
        days = int(re.search(r'(\d+)', time_str).group(1))
        dt = now - timedelta(days=days)
    elif "月" in time_str and "日" in time_str:
        match = re.search(r'(\d+)月(\d+)日', time_str)
        month = int(match.group(1))
        day = int(match.group(2))
        # 今年の日付として解釈する
        dt = now.replace(month=month, day=day, hour=12, minute=0, second=0, microsecond=0)
    else:
        # 不明な形式の場合は現在時刻を返す
        return now.isoformat()
        
    return dt.isoformat()

def run_test(page: Page):
    """
    認証ブラウザでmy ROOMへの基本的なページ遷移をテストします。
    """
    logger.info(f"--- my ROOMへのページ遷移テストを開始します ---")

    try:
        # 1. トップページにアクセス
        target_url = f"https://room.rakuten.co.jp/items"
        logger.info(f"トップページ「{target_url}」に移動します...")
        page.goto(target_url, wait_until="domcontentloaded")
        time.sleep(2)

        # 2. My ROOM リンクをクリック (安定版セレクタを使用)
        myroom_link = page.locator('a:has-text("my ROOM")').first
        logger.info("「my ROOM」リンクをクリックし、自己ルームに遷移します。")
        myroom_link.wait_for(state='visible', timeout=10000)
        myroom_link.click()
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        logger.info(f"ページ遷移成功。現在のURL: {page.url}")
        time.sleep(2) # 描画安定のため少し待機

        # 3. 「ピン」アイコンを持つカードを探してハイライト
        logger.info("「ピン」アイコンを持つカードを探してハイライトします...")
        # カードのセレクタと、その中にあるピンアイコンのセレクタを定義
        card_selector = convert_to_robust_selector('div[class*="container--JAywt"]')
        pin_icon_selector = convert_to_robust_selector('div.pin-icon--1FR8u')
        
        # ピンアイコンを持つすべてのカードを特定
        pinned_cards = page.locator(f"{card_selector}:has({pin_icon_selector})").all()
        
        if not pinned_cards:
            logger.warning("ピン留めされたカードが見つかりませんでした。")
            return

        logger.info(f"{len(pinned_cards)}件のピン留めされたカードを発見しました。最大3件をハイライトします。")
        
        highlight_colors = ["red", "green", "blue"]
        pinned_card_srcs = [] # 取得したsrcを保存するリスト
        
        # 最大3件までをループ処理
        for i, card in enumerate(pinned_cards[:1]):
            color = highlight_colors[i]
            card.wait_for(state="visible", timeout=10000)

            # カード内の画像のsrc属性を取得
            try:
                image_src = card.locator("img").first.get_attribute("src")
                if image_src:
                    pinned_card_srcs.append(image_src)
                    logger.info(f"  -> {i+1}件目のカードを {color} 色の枠線でハイライトします。(src: ...{image_src[-30:]})")
            except Exception as e:
                logger.warning(f"  -> {i+1}件目のカードの画像src取得中にエラー: {e}")

            card.evaluate(f"node => {{ node.style.border = '5px solid {color}'; }}")

            # カードをクリックして詳細ページに遷移
            try:
                logger.info(f"  -> {i+1}件目のカードをクリックして詳細ページに遷移します。")
                image_link_selector = convert_to_robust_selector("a[class*='link-image--']")
                card.locator(image_link_selector).first.click()
                page.wait_for_load_state("domcontentloaded", timeout=20000)
                post_detail_url = page.url # ★★★ 詳細ページのURLを保持 ★★★
                logger.info(f"  -> 詳細ページに遷移しました: {page.url}")
                time.sleep(2) # ページ表示の確認

                # 詳細ページで「コメント」ボタンをクリック
                logger.info("  -> 詳細ページで「コメント」ボタンをクリックします。")
                # 「コメント(XXX件)」というテキストを含む、クリック可能なコンテナ要素全体を特定する
                comment_text_pattern = re.compile(r"^コメント\(\d+件\)$")
                comment_button_selector = page.locator('div[class*="container--3w_bo"]').filter(has_text=comment_text_pattern).first
                comment_button_selector.wait_for(state="visible", timeout=15000)
                comment_button_selector.click()
                
                # --- コメントリストのスクレイピング処理 ---
                logger.info("  -> コメントリストの全件取得を開始します。")
                # スクロールバーを持つコンテナをIDで正確に指定
                comment_list_container_selector = 'div#contentList'
                # ユーザー名とコメント本文の両方を持つ要素をコメントカードとして正確に特定する
                user_name_selector = 'a[class*="user-name--"]'
                comment_text_selector = 'div[class*="social-text-area--"]'
                # ユーザー名とコメント本文の両方を含むことで、コメントカードを正確に特定する
                comment_item_selector = f'div[class*="spacer--1O71j"]:has({user_name_selector}):has({comment_text_selector})'
                spinner_selector = 'svg[class*="spinner---"]' # スピナーのセレクタ
                processed_comments = [] # ★★★ 取得したコメント情報を辞書で格納するリスト ★★★
                processed_ids = set() # ★★★ 重複チェック用のIDセット ★★★
                
                # --- 1. 初回取得 (スクロールなし) ---
                logger.info("  -> 最初に表示されているコメントを取得します。")
                page.locator(comment_item_selector).first.wait_for(state="visible", timeout=15000)
                initial_comment_elements = page.locator(comment_item_selector).all()
                for item in initial_comment_elements:
                    try:
                        # --- 項目取得ロジックを拡充 ---
                        unique_id = item.locator('img').first.get_attribute('src')
                        user_name_element = item.locator('a[class*="user-name--"]').first
                        user_name = user_name_element.inner_text()
                        user_page_url = f"https://room.rakuten.co.jp{user_name_element.get_attribute('href')}"
                        comment_text = item.locator('div[class*="social-text-area--"]').first.inner_text().replace('\n', ' ')
                        # title属性に絶対日時が格納されているため、優先的に取得する
                        relative_time_str = item.locator('div[class*="size-x-small--"]').first.inner_text()
                        post_timestamp = parse_relative_time(relative_time_str)

                        if unique_id not in processed_ids:
                            processed_ids.add(unique_id)
                            comment_data = {
                                "unique_id": unique_id,
                                "user_name": user_name,
                                "user_page_url": user_page_url,
                                "comment_text": comment_text,
                                "post_timestamp": post_timestamp,
                                "post_detail_url": post_detail_url
                            }
                            processed_comments.append(comment_data)
                            logger.info(f"    - [{len(processed_comments)}] {post_timestamp} - {user_name}: {comment_text}")
                    except Exception as e:
                        # logger.warning(f"初回取得中にエラーが発生した項目がありました: {e}")
                        continue
                
                logger.info(f"  -> 初回取得完了。{len(processed_comments)}件のコメントを取得しました。")

                # --- 2. スクロールによる追加取得 ---
                max_attempts = 15 # 無限ループ防止
                for attempt in range(max_attempts):
                    logger.info(f"  -> スクロール試行 {attempt + 1}/{max_attempts} (現在取得済み: {len(processed_comments)}件)")
                    
                    # --- スクロール実行とスピナー待機 ---
                    page.locator(comment_list_container_selector).evaluate("node => node.scrollTop = node.scrollHeight")
                    try:
                        # 1. スピナーが表示されるのを待つ (タイムアウトは短め)
                        page.wait_for_selector(spinner_selector, state='visible', timeout=5000)
                        logger.debug("  -> スピナーが表示されました。")
                        
                        # 2. スピナーが表示された後、描画のために少しだけ待つ
                        page.wait_for_timeout(1500)
                        logger.debug("  -> 新しいコメントを処理します。")
                    except Exception:
                        logger.warning("  -> スピナーが表示されませんでした。ページの終端と判断し、取得を完了します。")
                        break

                    # --- スピナー消失後、カードを再取得して処理 ---
                    all_comment_elements = page.locator(comment_item_selector).all()
                    for item in all_comment_elements:
                        try:
                            # --- 項目取得ロジックを拡充 ---
                            unique_id = item.locator('img').first.get_attribute('src')
                            user_name_element = item.locator('a[class*="user-name--"]').first
                            user_name = user_name_element.inner_text()
                            user_page_url = f"https://room.rakuten.co.jp{user_name_element.get_attribute('href')}"
                            comment_text = item.locator('div[class*="social-text-area--"]').first.inner_text().replace('\n', ' ')
                            # title属性に絶対日時が格納されているため、優先的に取得する
                            relative_time_str = item.locator('div[class*="size-x-small--"]').first.inner_text()
                            post_timestamp = parse_relative_time(relative_time_str)

                            if unique_id not in processed_ids:
                                processed_ids.add(unique_id)
                                comment_data = {
                                    "unique_id": unique_id,
                                    "user_name": user_name,
                                    "user_page_url": user_page_url,
                                    "comment_text": comment_text,
                                    "post_timestamp": post_timestamp,
                                    "post_detail_url": post_detail_url
                                }
                                processed_comments.append(comment_data)
                                logger.info(f"    - [{len(processed_comments)}] {post_timestamp} - {user_name}: {comment_text}")
                        except Exception as e:
                            # logger.warning(f"スクロール取得中にエラーが発生した項目がありました: {e}")
                            continue
                
                logger.info(f"--- コメント取得完了。合計 {len(processed_comments)} 件 ---")

                # --- ★★★ 取得結果をJSONファイルに保存 ★★★ ---
                output_path = "test_scripts/output/scraped_comments.json"
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(processed_comments, f, indent=2, ensure_ascii=False)
                logger.info(f"取得したコメント情報を {output_path} に保存しました。")

                logger.info("  -> 元のページに戻ります。")
                page.go_back(wait_until="domcontentloaded")
                page.wait_for_timeout(2000) # 戻った後の描画を待つ
            except Exception as click_error:
                logger.error(f"  -> カードのクリックまたはページ遷移中にエラーが発生しました: {click_error}")

    except Exception as e:
        logger.error(f"テスト実行中にエラーが発生しました: {e}", exc_info=True)
        # エラー時のスクリーンショットは manual_test.py 側で自動的に撮影されます。

# --- スクリプトのエントリーポイント ---
if 'page' in locals() or 'page' in globals():
    run_test(page)
else:
    logger.warning("このスクリプトは 'run_task.py manual-test --script test_scripts/test_myroom_navigation.py' からの実行を想定しています。")