import logging
import json
import os
import time
from datetime import datetime
import re
from playwright.sync_api import Page, Error
from app.utils.selector_utils import convert_to_robust_selector
from app.core.database import init_db, add_recollection_product
### ROOM商品削除しながら商品登録するスクリプト（後々の再コレタスク） ###

# --- 設定 ---
# テスト対象のユーザーページURL
TARGET_URL = "https://room.rakuten.co.jp/room_79a45994e0/items"
# 探したい日付の文字列（例: "10月29日", "3日前" など、ページに表示されるままの形式）
TARGET_DATE_STR = "11月15日"
# 取得する最大件数
MAX_FETCH_COUNT = 5 #ここは手動で設定するから変更しないで！！
# 1日あたりの平均投稿数（スクロール計算用）
POSTS_PER_DAY = 30
# 1回のスクロールで読み込まれるおおよそのカード数（スクロール計算用）
CARDS_PER_SCROLL = 20
# 出力ファイル名
OUTPUT_JSON_FILE = "test_scripts/output/deleted_products.json"

logger = logging.getLogger(__name__)

def process_and_delete_if_needed(page: Page, image_src: str) -> dict | None:
    """
    指定された画像srcを持つカードをクリックして商品詳細ページに遷移し、
    「#オリジナル写真」タグがなければ商品を削除し、URL情報を返す。

    :param page: PlaywrightのPageオブジェクト
    :param image_src: 処理対象カードの画像src文字列
    :return: 削除に成功した場合、URL情報を含む辞書。それ以外はNone。
    """
    page_transitioned = False
    detail_page_url = ""
    deletion_successful = False # 削除が成功したかを追跡するフラグ
    try:
        # 画像のsrcをキーにして、処理対象のカードを特定
        card_locator = page.locator(f'div[class*="container--JAywt"]:has(img[src="{image_src}"])').first
        
        # カードが表示されるまでスクロール
        card_locator.scroll_into_view_if_needed()
        page.wait_for_timeout(1000) # スクロール後の描画を待つ

        card_locator.locator('a[class*="link-image--"]').first.click()
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        page_transitioned = True

        # ★★★ エラーページに遷移した場合のハンドリング ★★★
        if "https://room.rakuten.co.jp/common/error" in page.url:
            logger.warning("エラーページに遷移しました。商品が存在しない可能性があります。一覧ページに戻ります。")
            page.go_back(wait_until="domcontentloaded")
            return None

        detail_page_url = page.url # 詳細ページのURLを保存

        # ★★★ 投稿日の取得を追加 ★★★
        post_date_text = ""
        try:
            date_element = page.locator('div:text-matches(".*に投稿されました")').first
            date_element.wait_for(state="visible", timeout=5000) # タイムアウトを短めに設定
            post_date_text = date_element.text_content().strip()
            logger.debug(f"    -> 投稿日を取得: '{post_date_text}'")
        except Error:
            logger.warning("    -> 投稿日の取得に失敗しましたが、処理を続行します。")

        # --- 情報取得 ---
        # 「楽天市場で見る」ボタンのリンクを取得
        rakuten_link_selector = convert_to_robust_selector('div[class*="ichiba-in-page--"] a')
        rakuten_link_element = page.locator(rakuten_link_selector).first
        rakuten_link_element.wait_for(state="visible", timeout=15000)
        rakuten_url = rakuten_link_element.get_attribute('href')

        # --- ★★★ 修正: app.core.databaseの関数を使用してDB登録 ★★★ ---
        try:
            # 商品名の取得
            # ユーザーの指定に基づき、商品説明文のセレクタを修正
            parent_selector = convert_to_robust_selector('div[class*="word-break-break-all--"]')
            description_selector = convert_to_robust_selector('div[class*="social-text-area--"]')
            name_element = page.locator(f'{parent_selector} {description_selector}').first
            name_text = name_element.text_content().strip()

            # 画像URLの取得
            image_selector = 'div[class*="swiper-slide-active"] img[class*="image--"]'
            image_element = page.locator(image_selector).first
            image_url = image_element.get_attribute('src')

            # --- ★★★ ショップ名の取得を追加 ★★★ ---
            shop_name = ""
            try:
                # ショップアイコンを含むボタンを特定
                shop_button_selector = 'button:has(div[class*="shop-outline--"])'
                shop_button_locator = page.locator(shop_button_selector).first
                shop_button_locator.wait_for(state="visible", timeout=5000)
                
                # ボタン内のテキストを持つspanからショップ名を取得
                shop_name_text_selector = 'span[class*="text--"]'
                shop_name = shop_button_locator.locator(shop_name_text_selector).text_content().strip()
                logger.info(f"    -> ショップ名を取得: '{shop_name}'")
            except Error:
                logger.warning("    -> ショップ名の取得に失敗しましたが、処理を続行します。")

            # DBへの登録を試みる (add_product_if_not_existsが重複チェックを行う)
            if add_recollection_product(name=name_text, url=rakuten_url, image_url=image_url, shop_name=shop_name, procurement_keyword="再コレ再利用"):
                logger.info(f"    -> [DB] 新規商品をDBに登録しました: {name_text[:30]}...")

        except Error as db_save_error:
            logger.error(f"    -> DB登録用の情報取得または保存処理中にエラーが発生しました: {db_save_error}")

        # 商品説明コンテナからハッシュタグを取得
        description_selector = convert_to_robust_selector('div[class*="social-text-area--"]')
        description_container = page.locator(description_selector).first
        hashtag_elements = description_container.locator('a[class*="tag-link--"]').all()
        hashtags = [tag.text_content().strip() for tag in hashtag_elements if tag.text_content().strip().startswith('#')]
        logger.debug(f"    -> ハッシュタグを {len(hashtags)} 件取得しました: {hashtags}")

        # --- ★★★ 投稿日のチェックを追加 ★★★ ---
        if post_date_text and "10月" not in post_date_text:
            logger.info(f"    -> 投稿日が10月ではないため、スキップします。 ({post_date_text})")
            return None

        # --- ★★★ 削除ロジック ★★★ ---
        if "#オリジナル写真" in hashtags:
            logger.info("    -> '#オリジナル写真' タグが含まれているため、スキップします。")
            return None
        
        # logger.info("    -> '#オリジナル写真' タグがありません。削除処理を開始します。")
        delete_button_locator = page.locator('button[aria-label="削除"]').first
        if delete_button_locator.count() == 0:
            logger.warning("    -> 削除ボタンが見つかりませんでした。スキップします。")
            return None

        # --- 削除処理 ---
        dialog_accepted = False
        def handle_dialog(dialog):
            nonlocal dialog_accepted
            logger.debug(f"確認ダイアログを検出しました: '{dialog.message}'。自動的に承認します。")
            dialog.accept()
            dialog_accepted = True

        page.on("dialog", handle_dialog)
        try:
            logger.debug("    -> 削除ボタンをクリックします。")
            delete_button_locator.click()
        finally:
            page.remove_listener("dialog", handle_dialog)

        page.wait_for_load_state("domcontentloaded", timeout=20000) # 削除後のページ遷移を待つ
        logger.info(f"    -> 削除が完了しました。(確認ダイアログ: {'表示あり' if dialog_accepted else '表示なし'})")
        deletion_successful = True # 削除成功フラグを立てる

        return {
            "deleted_item_detail_url": detail_page_url,
            "deleted_item_rakuten_url": rakuten_url,
            "post_date": post_date_text
        }

    except Error as e:
        logger.error(f"詳細ページ処理中にエラーが発生しました: {e}")
        # エラーが発生した場合は、削除成功とは見なさない
        return None
    finally:
        # ★★★ 修正: 削除が成功しなかった場合のみブラウザバックを試みる ★★★
        try:
            if not deletion_successful and page_transitioned and not page.is_closed():
                logger.debug("削除は実行されなかったため、ブラウザバックで一覧に戻ります。")
                page.go_back(wait_until="domcontentloaded")
                page.wait_for_timeout(2000) # 一覧ページの再描画を待つ
        except Error as e:
            logger.warning(f"finallyブロックでのページ操作中にエラーが発生しましたが、処理を続行します: {e}")


def run_test(page: Page):
    """
    指定されたユーザーページを巡回し、「#オリジナル写真」がない商品を削除するテスト。
    """
    logger.info(f"--- 「#オリジナル写真」なし商品の削除テストを開始します ---")
    logger.info(f"対象URL: {TARGET_URL}")
    logger.info(f"探索開始日付の目安: '{TARGET_DATE_STR}'")
    logger.info(f"最大削除件数: {MAX_FETCH_COUNT}件")

    # 出力ディレクトリを作成
    os.makedirs(os.path.dirname(OUTPUT_JSON_FILE), exist_ok=True)    
  
    globally_processed_srcs = set() # 処理を試みたカードのimage_src
    deleted_items = [] # 削除した商品のリスト

    try:
        page.goto(TARGET_URL.strip(), wait_until="domcontentloaded", timeout=60000)
        logger.info(f"ページにアクセスしました: {page.title()}")

        spinner_selector = 'div[aria-label="loading"]'
        card_selector = convert_to_robust_selector('div[class*="container--JAywt"]')

        loop_count = 0
        max_loops = 100 # 無限ループを避けるための最大試行回数

        # --- ★★★ 修正点: 新しいメインループ ★★★ ---
        while len(deleted_items) < MAX_FETCH_COUNT and loop_count < max_loops:
            # --- ★★★ 修正点: ループ開始時にページの安定を待つ ★★★ ---
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Error as e:
                logger.warning(f"ループ開始時のページ待機中にタイムアウトしましたが、処理を続行します: {e}")

            try:
                loop_count += 1
                logger.info(f"--- ループ {loop_count}/{max_loops} (現在 {len(deleted_items)}/{MAX_FETCH_COUNT} 件) ---")

                # ★★★ ループ開始時にエラーページにいないか確認 ★★★
                if "https://room.rakuten.co.jp/common/error" in page.url:
                    logger.warning("ループ開始時にエラーページを検出しました。ターゲットURLに再アクセスします。")
                    page.goto(TARGET_URL.strip(), wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(2000) # ページ再描画を待つ

                # 1. 目的の日付までのスクロール回数を推定計算
                required_scrolls = 0
                match = re.search(r"(\d+)月(\d+)日", TARGET_DATE_STR)
                if match:
                    month, day = int(match.group(1)), int(match.group(2))
                    today = datetime.now()
                    year = today.year if (today.month, today.day) >= (month, day) else today.year - 1
                    target_date = datetime(year, month, day)
                    days_diff = (today - target_date).days
                    
                    if days_diff > 0:
                        total_posts_to_skip = days_diff * POSTS_PER_DAY
                        required_scrolls = total_posts_to_skip // CARDS_PER_SCROLL
                
                if required_scrolls <= 0:
                    logger.info("スクロール回数の計算結果が0以下です。スクロールせずに探索します。")
                else:
                    # 2. 毎回、計算された回数の高速スクロールを実行
                    logger.info(f"目的の日付 ({TARGET_DATE_STR}) まで、推定 {required_scrolls} 回の高速スクロールを実行します...")
                    for i in range(required_scrolls):
                        # まず1回スクロール
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        try:
                            # スピナーの表示を短時間待つ
                            page.locator(spinner_selector).wait_for(state="visible", timeout=1500)
                            # スピナーが消えるのを待つ
                            page.locator(spinner_selector).wait_for(state="hidden", timeout=15000)
                        except Error:
                            # スピナーが出なかった場合、追加のアクションを試みる
                            logger.debug(f"  -> スピナーが表示されませんでした。追加のスクロールを試みます。({i + 1}/{required_scrolls})")
                            try:
                                # 少し上にスクロールしてから再度下にスクロール
                                page.evaluate("window.scrollBy(0, -500)") # 500px上にスクロール
                                page.wait_for_timeout(200)
                                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                # 追加アクション後、スピナーの表示・非表示を待つ
                                page.locator(spinner_selector).wait_for(state="visible", timeout=3000)
                                page.locator(spinner_selector).wait_for(state="hidden", timeout=15000)
                            except Error:
                                logger.warning(f"  -> 追加スクロール後もスピナーが表示されませんでした。ページの終端か、読み込みが遅い可能性があります。")
                                time.sleep(1.5) # 念のため待機
                    logger.info("高速スクロールが完了しました。")

                # 3. 画面上の最初の「未処理」カードを探す
                next_card_src = None
                # ★★★ 修正点: 画面下部から探索するため、取得したカードリストを逆順にする ★★★
                all_visible_cards_reversed = reversed(page.locator(f"{card_selector}:visible").all())
                
                for card in all_visible_cards_reversed:
                    try:
                        image_src = card.locator('img').first.get_attribute('src')
                        if image_src and image_src not in globally_processed_srcs:
                            next_card_src = image_src
                            break # 最初の未処理カードを見つけたらループを抜ける
                    except Error:
                        continue
                
                # 4. 未処理カードが見つからなければ、ループを終了
                if not next_card_src:
                    logger.warning("スクロール後、画面上に未処理のカードが見つかりませんでした。処理を終了します。")
                    break

                # 5. 見つけたカードを処理
                globally_processed_srcs.add(next_card_src)
                logger.info(f"  -> 処理試行: ...{next_card_src[-30:]}")

                deleted_item_data = process_and_delete_if_needed(page, next_card_src)

                if deleted_item_data:
                    deleted_items.append(deleted_item_data)
                    logger.info(f"  🗑️ [{len(deleted_items)}/{MAX_FETCH_COUNT}] 商品削除成功！")
                time.sleep(2) # 次のループまでのインターバル
                # 削除処理後は一覧ページに戻っているはずなので、そのまま次のループへ
                # スキップした場合もブラウザバックで一覧に戻っているので、そのまま次のループへ
            except Error as loop_playwright_error:
                logger.error(f"  -> メインループ内でPlaywrightエラーが発生しました: {str(loop_playwright_error).splitlines()[0]}", exc_info=False)
                logger.info("  -> エラーから復旧を試みます...")
                try:
                    if TARGET_URL not in page.url:
                        logger.info(f"    -> 現在のURLが異なるため、{TARGET_URL} に再アクセスします。")
                        page.goto(TARGET_URL.strip(), wait_until="domcontentloaded", timeout=60000)
                    else:
                        logger.info("    -> 既に目的のURLにいるため、ページの安定を待ちます。")
                        # ループ開始時に待機するので、ここでは不要
                    
                    page.wait_for_timeout(3000) # ページ再描画を待つ
                except Exception as recovery_error:
                    logger.error(f"    -> 復旧処理中にさらにエラーが発生しました: {recovery_error}")
                continue # 次のループイテレーションへ
            except Exception as loop_general_error:
                logger.error(f"  -> メインループ内で予期せぬエラーが発生しました: {loop_general_error}", exc_info=True)
                logger.info(f"  -> {TARGET_URL} に戻り、処理を継続します。")
                page.goto(TARGET_URL.strip(), wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000) # ページ再描画を待つ
                continue # 次のループイテレーションへ

    except Exception as e:
        logger.error(f"テスト実行中に予期せぬエラーが発生しました: {e}", exc_info=True)
    finally:
        logger.info(f"--- テスト完了 ---")
        # ★★★ 修正点: 最後にまとめてJSONファイルに書き込む ★★★
        if deleted_items:
            all_items = []
            # 既存のファイルがあれば読み込んで結合する
            if os.path.exists(OUTPUT_JSON_FILE):
                try:
                    with open(OUTPUT_JSON_FILE, "r", encoding="utf-8") as f:
                        all_items = json.load(f)
                except (json.JSONDecodeError, FileNotFoundError):
                    logger.warning(f"既存のJSONファイル '{OUTPUT_JSON_FILE}' の読み込みに失敗しました。新しいファイルを作成します。")
            
            all_items.extend(deleted_items)
            with open(OUTPUT_JSON_FILE, "w", encoding="utf-8") as f:
                json.dump(all_items, f, indent=2, ensure_ascii=False)
            logger.info(f"今回 {len(deleted_items)} 件の商品を削除し、合計 {len(all_items)} 件の情報を '{OUTPUT_JSON_FILE}' に保存しました。")
        else:
            logger.info("今回削除した商品はありませんでした。")


# --- スクリプトのエントリーポイント ---
if 'page' in locals() or 'page' in globals():
    run_test(page)
else:
    logger.warning("このスクリプトは 'run_task.py manual-test' からの実行を想定しています。")