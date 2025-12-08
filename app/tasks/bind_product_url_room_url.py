import logging
import time
from typing import List, Dict
from playwright.sync_api import Error
from app.core.base_task import BaseTask
from app.core.database import init_db, get_db_connection, update_product_room_url
from app.utils.selector_utils import convert_to_robust_selector

logger = logging.getLogger(__name__)


class BindProductUrlRoomUrlTask(BaseTask):
    """
    投稿済だが room_url が未設定の商品を、ROOM上のカードから特定して room_url を更新するタスク。
    """

    def __init__(self, count: int = 0):
        # count <= 0 の場合は上限なしで処理
        super().__init__(count=count)
        self.action_name = "商品URLとROOM URLの紐付け"

    def _execute_main_logic(self):
        logger.debug(f"--- {self.action_name}を開始します ---")
        logger.debug(f"処理目標件数: {self.target_count if self.target_count > 0 else '上限なし'}")

        page = self.page
        success_count = 0
        error_count = 0

        def fetch_targets(limit: int) -> List[Dict]:
            """status='投稿済' かつ room_url 未設定、ai_caption ありの商品を取得する。"""
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

        def normalize_text(text: str) -> str:
            return " ".join(text.split()) if text else ""

        def extract_caption_text(card_loc):
            """カード内のキャプション候補テキストを抽出する。"""
            caption_selectors = [
                "div.social-text-area--22OZg",
                "div[class*='social-text-area']",
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
                candidate = card_loc.locator(selector).first
                try:
                    text = candidate.inner_text().strip()
                    if text:
                        return text
                except Exception:
                    continue
            try:
                fallback = card_loc.inner_text().strip()
                if fallback:
                    return fallback
            except Exception:
                pass
            return ""

        def caption_matches(card_text: str, target_caption: str) -> bool:
            norm_card = normalize_text(card_text)
            norm_target = normalize_text(target_caption)
            if not norm_card or not norm_target:
                return False
            return norm_target in norm_card or norm_card in norm_target

        def make_search_snippet(caption: str, max_len: int = 120) -> str:
            normalized = normalize_text(caption)
            return normalized[:max_len] if len(normalized) > max_len else normalized

        try:
            init_db()
            target_products = fetch_targets(self.target_count)
            logger.debug("抽出件数 (DB): %s", len(target_products))
            logger.debug("対象商品 (id, name 抜粋): %s", [(p["id"], p.get("name")) for p in target_products])

            if not target_products:
                return success_count, error_count

            # 1. トップページにアクセス（残す）
            target_url = "https://room.rakuten.co.jp/items"
            logger.debug(f"トップページ「{target_url}」に移動します...")
            page.goto(target_url, wait_until="domcontentloaded")
            time.sleep(2)

            # 2. My ROOM リンクをクリック（残す）
            myroom_link = page.locator('a:has-text("my ROOM")').first
            logger.debug("「my ROOM」リンクをクリックし、自己ルームに遷移します。")
            myroom_link.wait_for(state="visible", timeout=10000)
            myroom_link.click()
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            my_room_url = page.url  # 自分のROOMのURLを保存
            logger.debug(f"対象URL: 「{my_room_url}」")

            spinner_selector = 'div[aria-label="loading"]'
            card_selector = convert_to_robust_selector('div[class*="container--JAywt"]')
            pin_icon_selector = convert_to_robust_selector('div.pin-icon--1FR8u')
            image_link_selector = convert_to_robust_selector("a[class*='link-image--']")
            search_snippets = {p["id"]: make_search_snippet(p["ai_caption"]) for p in target_products}

            logger.debug("最初の商品カードが表示されるまで待機します...")
            page.locator(card_selector).first.wait_for(state="visible", timeout=30000)
            page.wait_for_timeout(2000)

            pending = {p["id"]: p for p in target_products}
            processed_cards = set()
            scroll_count = 0
            max_scroll_attempts = 30

            while pending and (scroll_count < max_scroll_attempts):
                # has_text による直接検索（Ctrl+F 相当）
                for product_id, product in list(pending.items()):
                    snippet = search_snippets.get(product_id) or ""
                    if not snippet:
                        continue
                    candidate = page.locator(card_selector).filter(has_text=snippet).first
                    try:
                        if candidate.count() > 0:
                            candidate.scroll_into_view_if_needed()
                            logger.info("一致(has_text): product_id=%s name=%s", product_id, product.get("name"))
                            try:
                                candidate.locator(image_link_selector).first.click()
                                page.wait_for_load_state("domcontentloaded", timeout=20000)
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
                                    page.wait_for_timeout(2000)
                                except Exception as be:
                                    logger.warning("  -> ブラウザバックに失敗: %s", be)
                            pending.pop(product_id, None)
                    except Exception:
                        continue

                if not pending:
                    break

                all_cards_on_page = page.locator(card_selector).all()
                for card_loc in all_cards_on_page:
                    if not card_loc.is_visible():
                        continue

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

                    if card_loc.locator(pin_icon_selector).count() > 0:
                        logger.debug("  -> ピン留めされたカードをスキップ")
                        continue

                    card_text = extract_caption_text(card_loc)
                    if not card_text:
                        continue

                    matched = False
                    for product_id, product in list(pending.items()):
                        if caption_matches(card_text, product["ai_caption"]):
                            logger.info("一致: product_id=%s name=%s", product_id, product.get("name"))
                            logger.debug("  カード文面: %s", card_text[:120])
                            try:
                                card_loc.locator(image_link_selector).first.click()
                                page.wait_for_load_state("domcontentloaded", timeout=20000)
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
                                    page.wait_for_timeout(2000)
                                except Exception as be:
                                    logger.warning("  -> ブラウザバックに失敗: %s", be)
                            pending.pop(product_id, None)
                            matched = True
                            break

                    if not pending:
                        break
                    if matched:
                        continue

                if not pending:
                    break

                spinner_appeared = False
                for _ in range(5):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    try:
                        page.locator(spinner_selector).wait_for(state="visible", timeout=1000)
                        spinner_appeared = True
                        break
                    except Exception:
                        page.wait_for_timeout(500)

                if spinner_appeared:
                    try:
                        page.locator(spinner_selector).wait_for(state="hidden", timeout=30000)
                        scroll_count += 1
                    except Exception:
                        logger.warning("スピナーが消えるまでにタイムアウトしました")
                else:
                    logger.warning("スクロール上限に到達したため探索を終了します")
                    break

        except Exception as e:
            logger.error(f"タスクの実行中にエラーが発生しました: {e}", exc_info=True)
            return success_count, error_count + 1
        finally:
            logger.info(f"--- {self.action_name}を終了します ---")

        return success_count, error_count


def run_bind_product_url_room_url(count: int = 0, **kwargs):
    """
    BindProductUrlRoomUrlTask のラッパー関数。
    """
    task = BindProductUrlRoomUrlTask(count=count)
    result = task.run()
    return result if isinstance(result, tuple) else (0, 0)
