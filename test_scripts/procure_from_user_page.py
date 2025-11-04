import logging
from playwright.sync_api import Page, Error
from app.core.database import get_db_connection, add_product_if_not_exists
from app.utils.selector_utils import convert_to_robust_selector

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
    :param required_scrolls: 高速スクロールを実行する回数
    :return: (URL文字列, 商品説明文文字列) のタプル。失敗した場合は (None, None)。
    """
    page_transitioned = False
    try:
        # 画像のsrcをキーにして、処理対象のカードを特定する
        card_locator = page.locator(f'div[class*="container--JAywt"]:has(img[src="{image_src}"])').first

        # 必要な回数だけ先にスクロールする
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

            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            try:
                page.locator('div[aria-label="loading"]').wait_for(state="visible", timeout=1500)
                page.locator('div[aria-label="loading"]').wait_for(state="hidden", timeout=30000)
                logger.debug("    -> ローディングスピナーによる読み込みを検知しました。")
            except Error:
                logger.debug("    -> スピナーは表示されませんでした。")
                pass
            page.wait_for_timeout(1000) # 描画の安定を待つ

        if not is_card_found:
            logger.error(f"  -> 10回スクロールを試みましたが、カード({image_src[-20:]})が見つかりませんでした。")
            return None, None

        # 画像リンクをクリックして商品詳細ページに遷移
        card_locator.locator('a[class*="link-image--"]').first.click()
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        page_transitioned = True

        # 「楽天市場で見る」ボタンのリンクを取得
        rakuten_link_selector = convert_to_robust_selector('div[class*="ichiba-in-page--"] a')
        rakuten_link_element = page.locator(rakuten_link_selector).first
        rakuten_link_element.wait_for(state="visible", timeout=15000)
        rakuten_url = rakuten_link_element.get_attribute('href')
        if rakuten_url:
            logger.debug(f"    -> 楽天URLの取得成功: {rakuten_url[:40]}...")
        else:
            logger.warning("    -> 楽天URLの取得に失敗しました。")

        # 商品説明文を取得
        parent_selector = convert_to_robust_selector('div[class*="word-break-break-all--"]')
        description_selector = convert_to_robust_selector('div[class*="social-text-area--"]')
        detail_description_element = page.locator(f'{parent_selector} {description_selector}').first
        detail_description = None
        if detail_description_element.count() > 0:
            detail_description = detail_description_element.text_content().strip()
            logger.debug(f"    -> 商品説明の取得成功: {detail_description}")
        else:
            logger.warning("    -> 商品説明の取得に失敗しました。要素が見つかりません。")

        return rakuten_url, detail_description

    except Error as e:
        logger.error(f"URL取得処理中にエラーが発生しました: {e}")
        return None, None
    finally:
        if page_transitioned:
            page.go_back(wait_until="domcontentloaded")
            page.wait_for_timeout(2000)


def procure_from_user_page(page: Page, source_url: str, target_count: int = 50) -> list[dict]:
    """
    指定されたユーザーページから商品を調達し、データベースに登録する。
    :param page: PlaywrightのPageオブジェクト
    :param source_url: 調達元のユーザーページURL
    :param target_count: 調達目標件数
    :return: 新規に獲得した商品データのリスト
    """
    logger.info(f"--- ユーザーページ巡回調達タスクを開始します ---")
    logger.info(f"調達元URL: {source_url}")
    logger.info(f"目標件数: {target_count}件")

    globally_processed_srcs = set()
    newly_procured_items = []
    block_scroll_count = 0
    consecutive_failures = 0
    MAX_CONSECUTIVE_FAILURES = 5

    try:
        page.goto(source_url.strip(), wait_until="domcontentloaded", timeout=60000)
        page_title = page.title()
        logger.info(f"ページタイトルを取得しました: {page_title}")

        spinner_selector = 'div[aria-label="loading"]'
        card_selector = convert_to_robust_selector('div[class*="container--JAywt"]')

        logger.debug("最初の商品カードが表示されるのを待ちます...")
        page.locator(card_selector).first.wait_for(state="visible", timeout=30000)
        page.wait_for_timeout(2000)

        scroll_count = 0
        max_scroll_attempts = 20

        while len(newly_procured_items) < target_count and scroll_count < max_scroll_attempts:
            logger.debug(f"--- ループ開始 (現在 {len(newly_procured_items)}/{target_count} 件) ---")

            # 画面上の未処理カードを収集
            logger.debug("画面上の未処理カードのID(src)を収集します...")
            current_visible_cards = page.locator(card_selector).all()
            srcs_to_process_this_time = []
            for card in current_visible_cards:
                try:
                    if not card.is_visible(): continue
                    image_src = card.locator('img').first.get_attribute('src')
                    if image_src and image_src not in globally_processed_srcs:
                        srcs_to_process_this_time.append(image_src)
                except Error:
                    continue
            logger.debug(f"  -> {len(srcs_to_process_this_time)} 件の未処理カードを画面上で発見しました。")

            # 未処理カードを1件ずつ処理
            if srcs_to_process_this_time:
                logger.debug("未処理カードを1件ずつ処理します...")
                for image_src in srcs_to_process_this_time:
                    if len(newly_procured_items) >= target_count:
                        logger.info("目標件数に達したため、処理を中断します。")
                        break

                    globally_processed_srcs.add(image_src)

                    if product_exists_by_image_url(image_src):
                        logger.debug(f"  -> スキップ(DB image_url重複): ...{image_src[-30:]}")
                        continue

                    logger.debug(f"  -> 処理試行: ...{image_src[-30:]}")
                    rakuten_url, detail_description = get_product_details_from_card(page, image_src, block_scroll_count)

                    if not rakuten_url:
                        consecutive_failures += 1
                        logger.warning(f"     -> URL取得失敗。このカードはスキップされます。")
                        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                            logger.error(f"カードの取得失敗が{MAX_CONSECUTIVE_FAILURES}回連続で発生したため、処理を中断します。")
                            newly_procured_items.append({"FORCE_EXIT": True}) # ループを抜けるためのダミー
                            break
                        continue

                    consecutive_failures = 0
                    item_data = {
                        "name": detail_description,
                        "url": rakuten_url,
                        "image_url": image_src,
                        "procurement_keyword": f"ユーザー巡回 ({page_title})"
                    }
                    if add_product_if_not_exists(**item_data):
                        newly_procured_items.append(item_data)
                        logger.info(f"  🎉 [{len(newly_procured_items)}/{target_count}] 新規商品獲得＆DB登録！ -> {str(item_data['name'])[:20]}... (URL: {item_data['url'][:40]}...)")

            # スクロール処理
            if len(newly_procured_items) < target_count:
                # 強制終了のダミー要素をチェック
                if any(item.get("FORCE_EXIT") for item in newly_procured_items):
                    newly_procured_items = [item for item in newly_procured_items if not item.get("FORCE_EXIT")]
                    break

                logger.debug("新しいカードを読み込むため、スクロール処理に移行します。")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                try:
                    page.locator(spinner_selector).wait_for(state="visible", timeout=5000)
                    logger.debug("  -> ローディングスピナーが表示されました。消えるのを待ちます...")
                    page.locator(spinner_selector).wait_for(state="hidden", timeout=30000)
                    logger.debug("  -> ローディングスピナーが消えました。")
                    block_scroll_count += 1
                    scroll_count += 1
                    page.wait_for_timeout(2000)
                except Error:
                    logger.warning("スピナーが表示されませんでした。ページの終端か、読み込みに時間がかかっている可能性があります。")
                    scroll_count += 1
                    if scroll_count >= max_scroll_attempts:
                        logger.warning("最大スクロール回数に達しました。")
                        break

    except Exception as e:
        logger.error(f"ユーザーページのスクレイピング中に予期せぬエラーが発生しました: {e}", exc_info=True)
    finally:
        logger.info(f"--- ユーザーページ巡回調達タスクを完了します ---")
        logger.info(f"最終的な新規獲得商品数: {len(newly_procured_items)}件")

    return newly_procured_items