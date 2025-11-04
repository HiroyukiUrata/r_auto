import logging
from playwright.sync_api import Page, Locator

logger = logging.getLogger(__name__)

class MasonryScraper:
    """
    Masonryレイアウトのような、DOMの順序と視覚的な順序が一致しない
    動的なグリッドレイアウトから、要素を安定して順番に取得するためのヘルパークラス。

    使い方:
    scraper = MasonryScraper(page, card_selector, spinner_selector)
    for card in scraper.scrape_cards(limit=50):
        # 各カードに対する処理
        process_card(card)
    """
    def __init__(self, page: Page, card_selector: str, spinner_selector: str):
        self.page = page
        self.card_selector = card_selector
        self.spinner_selector = spinner_selector
        self.scroll_count = 0
        self.max_scroll_attempts = 20

    def _wait_for_initial_load(self):
        """最初のカードが表示され、レイアウトが安定するのを待つ"""
        logger.debug("最初の商品カードが表示されるのを待ちます...")
        self.page.locator(self.card_selector).first.wait_for(state="visible", timeout=30000)
        # MasonryレイアウトがJavaScriptによって再配置されるのを待つための時間
        self.page.wait_for_timeout(2000)
        logger.debug("初期ロードが完了しました。")

    def _scroll_and_wait_for_spinner(self) -> bool:
        """
        ページをスクロールし、ローディングスピナーの表示・非表示を待つ。
        :return: 新しいコンテンツがロードされた可能性がある場合はTrue、ページの終端に達した場合はFalse
        """
        logger.debug("スピナーが表示されるまでスクロールを試みます...")
        spinner_appeared = False
        for _ in range(5):  # スピナーが表示されるまで最大5回スクロールを試行
            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            try:
                self.page.locator(self.spinner_selector).wait_for(state="visible", timeout=1000)
                spinner_appeared = True
                break
            except Exception:
                self.page.wait_for_timeout(500)

        if spinner_appeared:
            logger.debug("  -> ローディングスピナーが表示されました。消えるのを待ちます...")
            try:
                self.page.locator(self.spinner_selector).wait_for(state="hidden", timeout=30000)
                logger.debug("  -> ローディングスピナーが消えました。")
                self.scroll_count += 1
                return True
            except Exception:
                logger.warning("スピナーが消えるのを待機中にタイムアウトしました。")
                return False
        else:
            logger.warning("複数回スクロールしてもスピナーが表示されませんでした。ページの終端と判断します。")
            return False

    def scrape_cards(self, limit: int):
        """
        指定された件数に達するまで、カードを順番にyieldするジェネレータ。
        :param limit: 取得するカードの上限数
        """
        self._wait_for_initial_load()
        
        scraped_count = 0
        while scraped_count < limit and self.scroll_count < self.max_scroll_attempts:
            # 1. 画面上の未処理カードをすべて取得
            all_cards_on_page = self.page.locator(f"{self.card_selector}:not([data-processed-by-scraper='true'])").all()
            
            visible_unprocessed_cards_with_bbox = []
            for card_loc in all_cards_on_page:
                if card_loc.is_visible():
                    bbox = card_loc.bounding_box()
                    if bbox and bbox['width'] > 0 and bbox['height'] > 0:
                        visible_unprocessed_cards_with_bbox.append((card_loc, bbox))

            if not visible_unprocessed_cards_with_bbox:
                # 処理対象がなければスクロール
                if not self._scroll_and_wait_for_spinner():
                    break # スクロールしても新しいものがなければ終了
                continue

            # 2. 視覚的な位置でソート
            visible_unprocessed_cards_with_bbox.sort(key=lambda x: (x[1]['y'], x[1]['x']))

            # 3. ソートされたリストを順番に処理
            for card_loc, _ in visible_unprocessed_cards_with_bbox:
                if scraped_count >= limit:
                    return

                # 処理済みマークを付ける
                card_loc.evaluate("node => node.setAttribute('data-processed-by-scraper', 'true')")
                
                yield card_loc
                scraped_count += 1