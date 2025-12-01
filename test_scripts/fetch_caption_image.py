import logging
import os
import json
from urllib.parse import urljoin
from playwright.sync_api import Page, Error, TimeoutError
from app.core.database import add_raw_product

logger = logging.getLogger(__name__)

DEFAULT_TARGET_URLS = [os.getenv("RAKUTEN_PRODUCT_URL", "https://item.rakuten.co.jp/kabegamiyahonpo/rknk-f-hokuo/").strip()]

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

def _normalize_asset_url(base_url: str, asset_url: str | None) -> str | None:
    if not asset_url:
        return None
    cleaned = asset_url.strip()
    if not cleaned:
        return None
    return urljoin(base_url, cleaned)

def _extract_meta_image(page: Page, base_url: str) -> str | None:
    for selector in META_IMAGE_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.count() == 0:
                continue
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
        if locator.count() == 0:
            continue
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
    """
    商品ページからタイトルと画像URLを取得する。
    :return: (商品名, 画像URL) のタプル
    """
    if not product_url:
        raise ValueError("product_url is required")

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
    if meta_image:
        return product_name, meta_image

    caption_image = _find_image_by_selectors(page, CAPTION_IMAGE_SELECTORS, product_url)
    if caption_image:
        return product_name, caption_image

    fallback_image = _find_image_by_selectors(page, FALLBACK_IMAGE_SELECTORS, product_url)
    if fallback_image:
        return product_name, fallback_image

    logger.warning("画像URLを取得できませんでした")
    return product_name, None

def _resolve_target_urls() -> list[str]:
    """コマンドライン引数から処理対象のURLリストを取得する"""
    import sys
    # manual_testタスクから渡された引数（スクリプト名以降）をURLとして扱う
    url_args = sys.argv[1:]
    
    if url_args:
        return [url.strip() for url in url_args if url.strip()]
    
    return DEFAULT_TARGET_URLS

def run_test(page: Page):
    target_urls = _resolve_target_urls()
    logger.info(f"{len(target_urls)}件のURLを処理します。")
    for i, url in enumerate(target_urls):
        logger.info(f"--- [{i+1}/{len(target_urls)}] 処理中: {url} ---")
        product_name, image_url = get_caption_and_image(page, url)
        if add_raw_product(name=product_name, url=url, image_url=image_url):
            logger.info(f"  -> DBに新規登録しました。 Name: {product_name}, Image: {image_url}")
        else:
            logger.info(f"  -> DB登録をスキップしました（URL重複またはデータ不足）。")

if 'page' in locals() or 'page' in globals():
    run_test(page)
else:
    logger.warning("このスクリプトは 'run_task.py manual-test' からの実行を想定しています")
