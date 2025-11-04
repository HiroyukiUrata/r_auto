import logging
import json
import os
import random
import time
from playwright.sync_api import Page, Error, Locator
from app.core.database import product_exists_by_url, init_db, get_db_connection, add_product_if_not_exists
from app.tasks.import_products import process_and_import_products
from app.utils.selector_utils import convert_to_robust_selector

# --- 設定 ---
# テストで調達する商品数
TARGET_COUNT = 50
# デバッグフラグ: Trueにすると各ビューの最初と最後の要素のみを処理する
DEBUG_MODE_FIRST_AND_LAST_ONLY = False
# 出力ファイル名
OUTPUT_JSON_FILE = "test_scripts/output/procured_products.json"


logger = logging.getLogger(__name__)

def product_exists_by_image_url(image_url: str) -> bool:
    """指定されたimage_urlを持つ商品がDBに存在するか確認する"""
    if not image_url:
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM products WHERE image_url = ? LIMIT 1", (image_url,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def get_product_details_from_card(page: Page, image_src: str, required_scrolls: int) -> tuple[str | None, str | None]:
    """
    指定された画像srcを持つカードをクリックして商品詳細ページに遷移し、
    「楽天市場で見る」ボタンのURLと商品説明文を取得して、元の一覧ページに戻る。
    :param page: PlaywrightのPageオブジェクト
    :param image_src: 処理対象カードの画像src文字列
    :return: (URL文字列, 商品説明文文字列) のタプル。失敗した場合は (None, None)。
    :param required_scrolls: 高速スクロールを実行する回数
    """
    page_transitioned = False
    try:
        # 画像のsrcをキーにして、処理対象のカードを特定する
        # --- ★★★ 修正点: 対象カードが見つかるまでスクロールを試みる ★★★ ---
        card_locator = page.locator(f'div[class*="container--JAywt"]:has(img[src="{image_src}"])').first
        
        # --- ★★★ 最適化: 必要な回数だけ先にスクロールする ★★★ ---
        if required_scrolls > 0:
            logger.debug(f"  -> 目的のブロックに到達するため、{required_scrolls}回の高速スクロールを実行します。")
            for i in range(required_scrolls):
                if card_locator.is_visible():
                    logger.debug(f"    -> 高速スクロールの途中でカードが見つかりました。({i+1}回目)")
                    break # 途中で見つかったらスクロールを中断
                
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                try:
                    page.locator('div[aria-label="loading"]').wait_for(state="visible", timeout=1500)
                    page.locator('div[aria-label="loading"]').wait_for(state="hidden", timeout=30000)
                except Error:
                    pass # スピナーが出なくても気にしない
                page.wait_for_timeout(500) # 描画を待つ
            logger.debug(f"  -> 高速スクロールが完了しました。")


        # 対象カードが画面に表示されるまで、最大10回スクロールを試行
        is_card_found = False
        for attempt in range(10):
            if card_locator.is_visible():
                is_card_found = True
                break
            logger.debug(f"  -> カード({image_src[-20:]})が見つかりません。スクロールして探します... ({attempt + 1}/10)")
            
            # --- ★★★ 修正点: スピナーの表示・非表示を監視しながらスクロール ★★★ ---
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            try:
                # スピナーが表示されるのを短時間待つ
                page.locator('div[aria-label="loading"]').wait_for(state="visible", timeout=1500)
                # スピナーが消えるのを待つ
                page.locator('div[aria-label="loading"]').wait_for(state="hidden", timeout=30000)
                logger.debug("    -> ローディングスピナーによる読み込みを検知しました。")
            except Error:
                # スピナーが表示されなかった場合は、単純なスクロールとして扱う
                logger.debug("    -> スピナーは表示されませんでした。")
                pass
            page.wait_for_timeout(1000) # 描画の安定を待つ

        if not is_card_found:
            logger.error(f"  -> 10回スクロールを試みましたが、カード({image_src[-20:]})が見つかりませんでした。")
            return None, None

        # 画像リンクをクリックして商品詳細ページに遷移
        card_locator.locator('a[class*="link-image--"]').first.click()
        page.wait_for_load_state("domcontentloaded", timeout=20000)

        # 「楽天市場で見る」ボタンのリンクを取得
        rakuten_link_selector = convert_to_robust_selector('div[class*="ichiba-in-page--"] a')
        rakuten_link_element = page.locator(rakuten_link_selector).first
        rakuten_link_element.wait_for(state="visible", timeout=15000)
        rakuten_url = rakuten_link_element.get_attribute('href')
        # URLが取得できたかログに出力
        if rakuten_url:
            logger.debug(f"    -> 楽天URLの取得成功: {rakuten_url[:40]}...")
        else:
            logger.warning("    -> 楽天URLの取得に失敗しました。")

        # 商品説明文を取得
        # 複数のコンテナが入れ子になっているため、目的のテキストを直接含む一番内側の要素を特定する
        # ユーザーコメントと商品説明文の2つが存在するため、後者を特定する。
        # 後者は `word-break-break-all` クラスを持つ親要素の中にいることが多い。
        parent_selector = convert_to_robust_selector('div[class*="word-break-break-all--"]')
        description_selector = convert_to_robust_selector('div[class*="social-text-area--"]')
        detail_description_element = page.locator(f'{parent_selector} {description_selector}').first
        detail_description = None
        if detail_description_element.count() > 0:
            detail_description = detail_description_element.text_content().strip() # inner_text() から text_content() に変更
            logger.debug(f"    -> 商品説明の取得成功: {detail_description}")
        else:
            logger.warning("    -> 商品説明の取得に失敗しました。要素が見つかりません。")

        # ページ遷移が成功したことを記録
        page_transitioned = True
        return rakuten_url, detail_description

    except Error as e:
        logger.error(f"URL取得処理中にエラーが発生しました: {e}")
        return None, None
    finally:
        # ★★★ ページ遷移が成功した場合にのみ、ブラウザバックを実行 ★★★
        if page_transitioned:
            page.go_back(wait_until="domcontentloaded")
            page.wait_for_timeout(2000)


def run_test(page: Page):
    """
    ユーザーページからの商品調達ロジックをテスト実行する。
    """
    logger.info("--- ユーザーページ巡回調達テストを開始します ---")
    
    init_db()

    # --- 準備フェーズ ---
    # 実際のタスクでは動的にURLを取得するが、テストでは固定
    source_url = "https://room.rakuten.co.jp/room_26a31b6a4e/items"
    logger.info(f"ユーザーページ「{source_url}」から商品調達を開始します。")
    logger.info(f"商品調達の目標件数: {TARGET_COUNT}件")

    skip_image_urls = set()
    if os.path.exists(OUTPUT_JSON_FILE):
        try:
            with open(OUTPUT_JSON_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    # 空行を無視する
                    if line.strip():
                        skip_image_urls.add(json.loads(line).get("image_url"))
            logger.info(f"テスト用のスキップリストを読み込みました。対象: {len(skip_image_urls)}件")
        except (IOError, json.JSONDecodeError) as e:
            logger.warning(f"スキップ用JSONファイルの読み込みに失敗しました: {e}")

    # 出力ディレクトリを作成し、既存のファイルを削除
    os.makedirs(os.path.dirname(OUTPUT_JSON_FILE), exist_ok=True)
    if os.path.exists(OUTPUT_JSON_FILE):
        os.remove(OUTPUT_JSON_FILE)

    # 1. グローバルな状態管理リストを準備
    globally_processed_srcs = set() # URL取得を「試みた」カードのsrcを記録
    items = [] # 「新規獲得に成功した」商品データを格納
    # ★★★ 最適化: スクロール回数を記録するカウンター ★★★
    block_scroll_count = 0

    # ★★★ 無限ループ回避のための連続失敗カウンター ★★★
    consecutive_failures = 0
    MAX_CONSECUTIVE_FAILURES = 5

    try:
        page.goto(source_url.strip(), wait_until="domcontentloaded", timeout=60000)
        page_title = page.title() # ページタイトルを取得
        logger.info(f"ページタイトルを取得しました: {page_title}")

        spinner_selector = 'div[aria-label="loading"]'
        card_selector = convert_to_robust_selector('div[class*="container--JAywt"]')

        logger.debug("最初の商品カードが表示されるのを待ちます...")
        page.locator(card_selector).first.wait_for(state="visible", timeout=30000)
        page.wait_for_timeout(2000)

        scroll_count = 0
        max_scroll_attempts = 20 # 無限ループを避けるための最大スクロール回数

        # --- 2. メインループ ---
        while len(items) < TARGET_COUNT and scroll_count < max_scroll_attempts:
            logger.debug(f"--- ループ開始 (現在 {len(items)}/{TARGET_COUNT} 件) ---")

            # --- ステップA: 画面上の未処理カードを収集 ---
            # このステップでは、スクロールせずに現在画面に見えているカードのみを対象とします。
            logger.debug("ステップA: 画面上の未処理カードのID(src)を収集します...")
            current_visible_cards = page.locator(card_selector).all()
            srcs_to_process_this_time = []
            for card in current_visible_cards:
                try:
                    # is_visible() で、実際に表示されているか最終確認
                    if not card.is_visible(): continue

                    image_src = card.locator('img').first.get_attribute('src')
                    if image_src and image_src not in globally_processed_srcs:
                        srcs_to_process_this_time.append(image_src)
                except Error:
                    # カードの取得中にDOMが変更された場合のエラーを無視
                    continue
            
            logger.debug(f"  -> {len(srcs_to_process_this_time)} 件の未処理カードを画面上で発見しました。")

            # --- ステップB: 未処理カードを1件ずつ処理 ---
            if srcs_to_process_this_time:
                logger.debug("ステップB: 未処理カードを1件ずつ処理します...")
                for image_src in srcs_to_process_this_time:
                    if len(items) >= TARGET_COUNT:
                        logger.info("目標件数に達したため、処理を中断します。")
                        break

                    # 1. 処理済みとしてマーク
                    globally_processed_srcs.add(image_src)

                    # 2. DB重複チェック
                    if product_exists_by_image_url(image_src):
                        logger.debug(f"  -> スキップ(DB image_url重複): ...{image_src[-30:]}")
                        continue

                    # 3. 詳細情報を取得
                    logger.debug(f"  -> 処理試行: ...{image_src[-30:]}")

                    rakuten_url, detail_description = get_product_details_from_card(page, image_src, block_scroll_count)

                    # 4. 取得結果のハンドリング
                    if not rakuten_url:
                        consecutive_failures += 1
                        logger.warning(f"     -> URL取得失敗。このカードはスキップされます。")
                        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                            logger.error(f"カードの取得失敗が{MAX_CONSECUTIVE_FAILURES}回連続で発生したため、処理を中断します。")
                            # メインのwhileループを抜けるために、itemsの数をTARGET_COUNT以上にする
                            items.append("FORCE_EXIT") # ループを抜けるためのダミー要素
                            break # このforループを抜ける
                        continue

                    # 5. 新規獲得成功
                    consecutive_failures = 0 # 成功したらカウンターをリセット
                    item_data = {
                        "name": detail_description,
                        "url": rakuten_url,
                        "image_url": image_src,
                        "procurement_keyword": f"ユーザー巡回 ({page_title})"
                    }
                    if add_product_if_not_exists(**item_data):
                        items.append(item_data)
                        logger.info(f"  🎉 [{len(items)}/{TARGET_COUNT}] 新規商品獲得＆DB登録！ -> {str(item_data['name'])[:20]}... (URL: {item_data['url'][:40]}...)")

            # --- ステップC: スクロール処理 ---
            # 画面上の未処理カードがなくなった、または目標に達していない場合にスクロール
            if len(items) < TARGET_COUNT: # 強制終了のダミー要素も考慮される
                logger.debug("ステップC: 新しいカードを読み込むため、スクロール処理に移行します。")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                try:
                    page.locator(spinner_selector).wait_for(state="visible", timeout=5000)
                    logger.debug("  -> ローディングスピナーが表示されました。消えるのを待ちます...")
                    page.locator(spinner_selector).wait_for(state="hidden", timeout=30000)
                    logger.debug("  -> ローディングスピナーが消えました。")
                    block_scroll_count += 1 # ★★★ 最適化: スクロール回数をカウントアップ ★★★
                    scroll_count += 1
                    page.wait_for_timeout(2000) # 新しいカードの描画を待つ
                except Error:
                    logger.warning("スピナーが表示されませんでした。ページの終端か、読み込みに時間がかかっている可能性があります。")
                    scroll_count += 1 # 試行回数としてカウント
                    if scroll_count >= max_scroll_attempts:
                        logger.warning("最大スクロール回数に達しました。")
                        break

    except Exception as e:
        logger.error(f"ユーザーページのスクレイピング中にエラーが発生しました: {e}", exc_info=True)
    finally:
        if items:
            logger.info(f"収集した {len(items)} 件の商品をデータベースに登録します。")
            added_count, skipped_count = process_and_import_products(items)
            logger.info(f"商品登録処理が完了しました。新規追加: {added_count}件, スキップ: {skipped_count}件")
        else:
            logger.info("調達できる新しい商品がありませんでした。")


    logger.info("--- テスト完了 ---")

# --- スクリプトのエントリーポイント ---
# manual-testタスクは、スクリプトファイル内で 'page' と 'context' という名前の
# グローバル変数にアクセスできる状態でコードを実行します。
if 'page' in locals() or 'page' in globals():
    run_test(page)
else:
    logger.warning("このスクリプトは 'run_task.py manual-test' からの実行を想定しています。")