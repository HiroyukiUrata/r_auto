"""
`run_task.py manual-test` 用の手動テストスクリプトです。
my ROOM へ遷移し、DB上で「投稿済 & room_url 未設定」の商品を取得して、
ai_caption と一致するカードをスクロールしながら特定します（更新処理はまだ行わず、特定まで）。

実行例:
  python run_task.py manual-test --script test_scripts/bind_product_url_room_url2.py --use-auth true \
    --url https://room.rakuten.co.jp/items --url-count 5

- 最初の `--url` を起点ページとして扱います（省略時は my ROOM 一覧）。
- `--url-count`（または2番目の位置引数）で、DBから取得する対象商品の件数を上書きできます。
- `page` と `context` は manual-test から注入されます。
"""

from __future__ import annotations

import logging
import sys
from typing import Sequence, Optional

from app.core.database import init_db, get_db_connection, update_product_room_url
from app.utils.selector_utils import convert_to_robust_selector

logger = logging.getLogger(__name__)

MY_ROOM_ENTRY_URL = "https://room.rakuten.co.jp/items"
# デフォルト件数: 0 or 以下は「上限なし」で全件を対象にする
DEFAULT_TARGET_COUNT = 0


def get_entry_and_count(argv: Sequence[str]) -> tuple[str, int]:
    """CLI引数から起点URLと処理件数を取得する。0以下の場合は上限なし。"""
    if not argv:
        return MY_ROOM_ENTRY_URL, DEFAULT_TARGET_COUNT

    entry_url = argv[0] or MY_ROOM_ENTRY_URL

    # `--url-count 3` のような指定を優先し、なければ2番目の位置引数を件数として解釈
    target_count = DEFAULT_TARGET_COUNT
    for i, val in enumerate(argv):
        if val == "--url-count" and i + 1 < len(argv):
            try:
                target_count = int(argv[i + 1])
            except ValueError:
                pass
            break
    else:
        if len(argv) > 1:
            try:
                target_count = int(argv[1])
            except ValueError:
                target_count = DEFAULT_TARGET_COUNT

    # 1件以上ならその件数、0以下なら「無制限」として0を返す
    return entry_url, target_count if target_count > 0 else 0


def prepare(page, context) -> tuple[str, int]:
    """DB初期化と起点ページへの遷移を行う。"""
    init_db()
    entry_url, target_count = get_entry_and_count(sys.argv[1:])
    logger.info("起点ページへ移動: %s", entry_url)
    page.goto(entry_url, wait_until="domcontentloaded")
    page.wait_for_timeout(500)
    return entry_url, target_count


def fetch_posted_products_without_room_url(limit: int) -> list[dict]:
    """status='投稿済' かつ room_url が未設定のレコードを取得する。limit<=0 は全件。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    base_query = """
        SELECT id, ai_caption, name
        FROM products
        WHERE status = '投稿済'
          AND (room_url IS NULL OR TRIM(room_url) = '')
          AND ai_caption IS NOT NULL
          AND TRIM(ai_caption) != ''
        ORDER BY posted_at DESC, id DESC
    """
    if limit and limit > 0:
        cursor.execute(base_query + " LIMIT ?", (limit,))
    else:
        cursor.execute(base_query)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_unlinked_products() -> int:
    """room_url が未設定の投稿済件数を返す。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(*) FROM products
        WHERE status = '投稿済'
          AND (room_url IS NULL OR TRIM(room_url) = '')
        """
    )
    count = cursor.fetchone()[0]
    conn.close()
    return count


def normalize_text(text: str | None) -> str:
    """空白を畳み、比較しやすい形に正規化する。"""
    if not text:
        return ""
    return " ".join(text.split())


def caption_matches(card_text: str, target_caption: str) -> bool:
    """カードのテキストが ai_caption と一致（含有）するか判定する。"""
    normalized_card = normalize_text(card_text)
    normalized_target = normalize_text(target_caption)
    if not normalized_card or not normalized_target:
        return False
    # ai_caption がカードテキストを包含、またはその逆であれば一致とみなす
    return normalized_target in normalized_card or normalized_card in normalized_target


def extract_caption_text(card_locator):
    """カード内のキャプション候補テキストを抽出する。"""
    caption_selectors = [
        # 優先: social-text-area (ROOMのキャプション本体)
        "div.social-text-area--22OZg",
        "div[class*='social-text-area']",
        # item-comment 内の本文
        "div.item-comment--htQ-E",
        "div[class*='caption']",
        "p[class*='caption']",
        "div[class*='comment']",
        "p[class*='comment']",
        "div[class*='description']",
        "p[class*='description']",
        "div[class*='body']",
        "p",
    ]
    for selector in caption_selectors:
        candidate = card_locator.locator(selector).first
        try:
            text = candidate.inner_text().strip()
            if text:
                return text
        except Exception:
            continue
    # 最終手段: カード全体のテキスト
    try:
        fallback_text = card_locator.inner_text().strip()
        if fallback_text:
            return fallback_text
    except Exception:
        pass
    return ""


def make_search_snippet(caption: str, max_len: int = 120) -> str:
    """全文検索用に、空白を畳んだ先頭部分を取り出す。"""
    normalized = normalize_text(caption)
    if len(normalized) > max_len:
        return normalized[:max_len]
    return normalized


def highlight_card(card_locator) -> None:
    """見つけたカードを視覚的に枠線で強調する。"""
    try:
        card_locator.evaluate(
            "node => { node.style.outline = '3px solid tomato'; node.style.boxSizing = 'border-box'; }"
        )
    except Exception:
        pass


def find_cards_by_ai_caption(page, target_products: list[dict]) -> tuple[dict, dict]:
    """ai_caption が一致するカードをスクロールしながら特定し、詳細ページURLをroom_urlとして更新する。"""
    spinner_selector = 'div[aria-label="loading"]'
    card_selector = convert_to_robust_selector('div[class*="container--JAywt"]')
    pin_icon_selector = convert_to_robust_selector('div.pin-icon--1FR8u')
    image_link_selector = convert_to_robust_selector("a[class*='link-image--']")
    search_snippets = {p["id"]: make_search_snippet(p["ai_caption"]) for p in target_products}

    logger.info("my ROOM 一覧へ移動してカード探索を開始 (対象件数: %s)", len(target_products))

    # my ROOM へ遷移
    myroom_link = page.locator('a:has-text("my ROOM")').first
    myroom_link.wait_for(state="visible", timeout=10_000)
    myroom_link.click()
    page.wait_for_load_state("domcontentloaded", timeout=15_000)
    logger.debug("my ROOM URL: %s", page.url)

    # Masonry レイアウトが安定するまで待機
    page.locator(card_selector).first.wait_for(state="visible", timeout=30_000)
    page.wait_for_timeout(2_000)

    pending = {p["id"]: p for p in target_products}
    found: dict[int, dict] = {}
    processed_cards: set[str] = set()
    success_count = 0
    error_count = 0

    scroll_count = 0
    max_scroll_attempts = 30

    while pending and scroll_count < max_scroll_attempts:
        # 先に has_text 検索で直接一致を試みる（Ctrl+F 相当の単純テキスト検索）
        for product_id, product in list(pending.items()):
            snippet = search_snippets.get(product_id) or ""
            if not snippet:
                continue
            candidate = page.locator(card_selector).filter(has_text=snippet).first
            try:
                if candidate.count() > 0:
                    candidate.scroll_into_view_if_needed()
                    logger.info("一致(has_text): product_id=%s name=%s", product_id, product.get("name"))
                    highlight_card(candidate)
                    # 詳細を開き room_url 更新
                    try:
                        candidate.locator(image_link_selector).first.click()
                        page.wait_for_load_state("domcontentloaded", timeout=20_000)
                        detail_page_url = page.url
                        logger.info("  -> room_url を更新: %s", detail_page_url)
                        update_product_room_url(product_id, detail_page_url)
                        success_count += 1
                    except Exception as e:
                        logger.error("  -> 詳細ページ処理に失敗: %s", e, exc_info=True)
                        error_count += 1
                    finally:
                        try:
                            page.go_back(wait_until="domcontentloaded")
                            page.wait_for_timeout(2_000)
                        except Exception as be:
                            logger.warning("  -> ブラウザバックに失敗: %s", be)
                    found[product_id] = {"product": product, "card_text": snippet}
                    pending.pop(product_id, None)
            except Exception:
                continue

        if not pending:
            break

        all_cards_on_page = page.locator(card_selector).all()

        for card_loc in all_cards_on_page:
            if not card_loc.is_visible():
                continue

            # 再処理防止用キー（画像srcがあればそれを使用）
            key = None
            try:
                key = card_loc.locator("img").first.get_attribute("src")
            except Exception:
                pass
            if not key:
                try:
                    key = card_loc.inner_text()[:80]
                except Exception:
                    key = None

            if key and key in processed_cards:
                continue
            if key:
                processed_cards.add(key)

            # ピン留めカードは対象外
            if card_loc.locator(pin_icon_selector).count() > 0:
                logger.debug("  -> ピン留めカードをスキップ")
                continue

            card_text = extract_caption_text(card_loc)
            if not card_text:
                continue

            for product_id, product in list(pending.items()):
                if caption_matches(card_text, product["ai_caption"]):
                    logger.info("一致: product_id=%s name=%s", product_id, product.get("name"))
                    logger.debug("  カード文面: %s", card_text[:120])
                    highlight_card(card_loc)
                    try:
                        card_loc.locator(image_link_selector).first.click()
                        page.wait_for_load_state("domcontentloaded", timeout=20_000)
                        detail_page_url = page.url
                        logger.info("  -> room_url を更新: %s", detail_page_url)
                        update_product_room_url(product_id, detail_page_url)
                        success_count += 1
                    except Exception as e:
                        logger.error("  -> 詳細ページ処理に失敗: %s", e, exc_info=True)
                        error_count += 1
                    finally:
                        try:
                            page.go_back(wait_until="domcontentloaded")
                            page.wait_for_timeout(2_000)
                        except Exception as be:
                            logger.warning("  -> ブラウザバックに失敗: %s", be)
                    found[product_id] = {"product": product, "card_text": card_text}
                    pending.pop(product_id, None)
                    break

        if not pending:
            break

        # 未発見が残っている場合はスクロール
        spinner_appeared = False
        for _ in range(5):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            try:
                page.locator(spinner_selector).wait_for(state="visible", timeout=1_000)
                spinner_appeared = True
                break
            except Exception:
                page.wait_for_timeout(500)

        if spinner_appeared:
            try:
                page.locator(spinner_selector).wait_for(state="hidden", timeout=30_000)
                scroll_count += 1
            except Exception:
                logger.warning("スピナーが消えるまでにタイムアウト")
        else:
            logger.warning("スクロール上限に到達したため探索を終了")
            break

    return found, pending, success_count, error_count


def finish(found: dict, pending: dict, success_count: int, error_count: int) -> None:
    """実行結果の要約を出力する。"""
    logger.info("特定完了: 一致=%s件 / 未発見=%s件", len(found), len(pending))
    logger.info("room_url 更新 成功=%s件 / 失敗=%s件", success_count, error_count)
    if pending:
        logger.info("未発見 product_id: %s", list(pending.keys()))
    remaining = count_unlinked_products()
    logger.info("room_url 未設定の投稿済件数 (更新後): %s", remaining)
    logger.info("ブラウザは確認用に開いたままです。")


if 'page' in globals():
    entry_url, target_count = prepare(page, context)
    target_products = fetch_posted_products_without_room_url(limit=target_count)
    logger.info("抽出件数 (DB): %s", len(target_products))
    if target_products:
        logger.info("対象商品 (id, name 抜粋): %s", [(p['id'], p.get('name')) for p in target_products])
        # 上限指定がある場合のみスライス（0以下は上限なし）
        if target_count > 0 and len(target_products) > target_count:
            target_products = target_products[:target_count]
            logger.info("処理件数を指定値にスライス: %s", target_count)
        found, pending, success_count, error_count = find_cards_by_ai_caption(page, target_products)
        finish(found, pending, success_count, error_count)
    else:
        logger.warning("対象商品が見つかりませんでした（投稿済 & room_url 未設定）。")
