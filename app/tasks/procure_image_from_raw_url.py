import logging
from urllib.parse import urljoin
from playwright.sync_api import Page, Error, TimeoutError

from app.core.base_task import BaseTask
from app.core.database import add_raw_product

logger = logging.getLogger(__name__)

# --- 元のスクリプトから流用したセレクタ定義 ---
META_IMAGE_SELECTORS = [
    'head meta[property="og:image"]',
    'head meta[name="twitter:image"]',
]
CAPTION_IMAGE_SELECTORS = [
    'div#rakutenLimitedId_ImageCarousel img',
    'div[itemprop="image"] img',
    'div#itemDetail img[itemprop="image"]',
    'div#itemDetail img',
    'div#productDescription img',
    'section[itemprop="description"] img',
    'div#itemDescription img',
]
FALLBACK_IMAGE_SELECTORS = [
    'img[data-track-action="image"]',
    'img[itemprop="image"]',
    'img[src]',
]

# --- 元のスクリプトから流用したヘルパー関数 ---
def _normalize_asset_url(base_url: str, asset_url: str | None) -> str | None:
    if not asset_url: return None
    cleaned = asset_url.strip()
    if not cleaned: return None
    return urljoin(base_url, cleaned)

def _extract_meta_image(page: Page, base_url: str) -> str | None:
    for selector in META_IMAGE_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.count() == 0: continue
            content = locator.get_attribute("content")
            normalized = _normalize_asset_url(base_url, content)
            if normalized:
                logger.debug("metaタグから画像URLを取得しました (%s)", selector)
                return normalized
        except Error:
            continue
    return None

def _find_image_by_selectors(page: Page, selectors: list[str], base_url: str) -> str | None:
    for selector in selectors:
        locator = page.locator(selector).first
        if locator.count() == 0: continue
        try:
            if not locator.is_visible():
                locator.scroll_into_view_if_needed()
                page.wait_for_timeout(250)
            src = locator.get_attribute("src")
            normalized = _normalize_asset_url(base_url, src)
            if normalized:
                logger.debug("selector '%s' から画像URLを取得しました", selector)
                return normalized
        except Error:
            continue
    return None

def get_caption_and_image(page: Page, product_url: str) -> tuple[str | None, str | None]:
    if not product_url: raise ValueError("product_url is required")
    logger.info("商品ページにアクセスします: %s", product_url)
    try:
        page.goto(product_url.strip(), wait_until="domcontentloaded", timeout=60000)
    except TimeoutError:
        logger.error(f"ページへのアクセスがタイムアウトしました: {product_url}")
        return None, None
    except Error as e:
        logger.error(f"ページへのアクセス中にエラーが発生しました: {e}")
        return None, None

    product_name = page.title()
    meta_image = _extract_meta_image(page, product_url)
    if meta_image: return product_name, meta_image

    caption_image = _find_image_by_selectors(page, CAPTION_IMAGE_SELECTORS, product_url)
    if caption_image: return product_name, caption_image

    fallback_image = _find_image_by_selectors(page, FALLBACK_IMAGE_SELECTORS, product_url)
    if fallback_image: return product_name, fallback_image

    logger.warning("画像URLを取得できませんでした")
    return product_name, None

class ProcureImageFromRawUrlTask(BaseTask):
    """
    URLリストを受け取り、各URLから画像URLを取得してDBに登録するタスク。
    """
    def __init__(self, urls_text: str):
        super().__init__()
        self.action_name = "生URLから画像URLを取得"
        # 改行で区切られたURL文字列をリストに変換
        self.urls = [url.strip() for url in urls_text.strip().splitlines() if url.strip()]
        self.target_count = len(self.urls) # 処理件数を設定

    def _execute_main_logic(self):
        if not self.urls:
            logger.warning("処理対象のURLがありません。")
            return 0, 0

        logger.info(f"{self.target_count}件のURLを処理します。")
        success_count = 0
        error_count = 0

        for i, url in enumerate(self.urls):
            page = self.context.new_page()
            try:
                logger.info(f"--- [{i+1}/{self.target_count}] 処理中: {url} ---")
                product_name, image_url = get_caption_and_image(page, url)
                if add_raw_product(name=product_name, url=url, image_url=image_url):
                    logger.info(f"  -> DBに新規登録しました。 Name: {product_name}, Image: {image_url}")
                    success_count += 1
                else:
                    logger.info(f"  -> DB登録をスキップしました（URL重複またはデータ不足）。")
            except Exception as e:
                logger.error(f"URL処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
                error_count += 1
            finally:
                if page and not page.is_closed():
                    page.close()
        
        return success_count, error_count

def run_procure_image_from_raw_url(urls_text: str = ""):
    """タスク実行用のラッパー関数"""
    task = ProcureImageFromRawUrlTask(urls_text=urls_text)
    result = task.run()
    return result if isinstance(result, tuple) else (0, 0)