import logging
import time
from playwright.sync_api import Error
from app.core.base_task import BaseTask
from app.core.database import init_db, update_room_url_by_rakuten_url
from app.utils.selector_utils import convert_to_robust_selector

logger = logging.getLogger(__name__)

class BindProductUrlRoomUrlTask(BaseTask):
    """
    投稿直後の商品をスクレイピングして、商品URLとROOMの個別URLを関連付けるタスク。
    """
    def __init__(self, count: int = 2):
        super().__init__(count=count)
        self.action_name = "商品URLとROOM URLの紐付け"

    def _execute_main_logic(self):
        """
        タスクのメインロジック。
        """
        logger.debug(f"--- {self.action_name}を開始します ---")
        logger.debug(f"処理目標件数: {self.target_count}件")

        page = self.page
        
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
            my_room_url = page.url # 自分のROOMのURLを保存
            logger.debug(f"対象URL: 「{my_room_url}」")

            # 処理済みのカードの画像srcを記録するためのセット
            globally_processed_srcs = set()
            processed_count = 0

            # ローディングスピナーのセレクタ
            spinner_selector = 'div[aria-label="loading"]'
            card_selector = convert_to_robust_selector('div[class*="container--JAywt"]')
            pin_icon_selector = convert_to_robust_selector('div.pin-icon--1FR8u')
            
            logger.debug("最初の商品カードが表示されるのを待ちます...")
            page.locator(card_selector).first.wait_for(state="visible", timeout=30000)
            # ページ描画が完全に安定するまで少し待機する (Masonryレイアウトの安定化のため)
            page.wait_for_timeout(2000)

            scroll_count = 0
            max_scroll_attempts = 20 # 無限ループを避けるための最大スクロール回数

            while processed_count < self.target_count and scroll_count < max_scroll_attempts:
                # 1. すべてのカードを取得し、未処理かつ可視のものをフィルタリング
                all_cards_on_page = page.locator(card_selector).all()
                
                visible_unprocessed_cards_with_bbox = []
                for card_loc in all_cards_on_page:
                    # is_visible() は要素がDOMにあり、表示されているかを確認する
                    if card_loc.is_visible():
                        # 画像のsrcを取得し、処理済みでないかチェック
                        image_src = card_loc.locator('img').first.get_attribute('src')
                        if not image_src or image_src in globally_processed_srcs:
                            continue

                        # ピン留めされているかチェック
                        if card_loc.locator(pin_icon_selector).count() > 0:
                            logger.debug("  -> ピン留めされたカードを発見しました。処理対象外とします。")
                            globally_processed_srcs.add(image_src) # 処理済みとして記録
                            continue # このカードはスキップ

                        bbox = card_loc.bounding_box()
                        # bounding_box()がNoneでないこと、幅と高さが0より大きいことを確認
                        if bbox and bbox['width'] > 0 and bbox['height'] > 0:
                            visible_unprocessed_cards_with_bbox.append((card_loc, bbox))
                
                cards_to_process_count = len(visible_unprocessed_cards_with_bbox)
                
                if cards_to_process_count == 0:
                    # 処理対象のカードがなければスクロール処理へ
                    logger.debug("画面上の未処理カードがなくなりました。スピナーが表示されるまでスクロールを試みます...")
                    
                    spinner_appeared = False
                    for scroll_attempt in range(5): # スピナーが表示されるまで最大5回スクロールを試行
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        try:
                            page.locator(spinner_selector).wait_for(state="visible", timeout=1000)
                            spinner_appeared = True
                            break
                        except Exception:
                            logger.debug(f"  スクロール試行 {scroll_attempt + 1}/5: スピナーはまだ表示されません。")
                            page.wait_for_timeout(500)
                    
                    if spinner_appeared:
                        logger.debug("  -> ローディングスピナーが表示されました。消えるのを待ちます...")
                        try:
                            page.locator(spinner_selector).wait_for(state="hidden", timeout=30000)
                            logger.debug("  -> ローディングスピナーが消えました。新しいカードを取得します。")
                            scroll_count += 1
                        except Exception:
                            logger.warning("スピナーが消えるのを待機中にタイムアウトしました。")
                    else:
                        logger.warning("複数回スクロールしてもスピナーが表示されませんでした。ページの終端と判断します。")
                        break 
                    continue

                # 2. 視覚的な位置に基づいてソート (Y座標 -> X座標)
                visible_unprocessed_cards_with_bbox.sort(key=lambda x: (x[1]['y'], x[1]['x']))
                
                if not visible_unprocessed_cards_with_bbox:
                    continue

                # 3. 視覚的に最も左上にある未処理のカードを処理対象とする
                target_card = visible_unprocessed_cards_with_bbox[0][0]

                try:
                    image_src_to_process = target_card.locator('img').first.get_attribute('src')
                    globally_processed_srcs.add(image_src_to_process)
                except Exception as e:
                    logger.warning(f"カードの画像src取得に失敗しました。このカードをスキップします。エラー: {e}")
                    continue

                page_transitioned = False
                rakuten_url = None
                detail_page_url = None
                try:
                    number_to_display = processed_count + 1
                    logger.debug(f"  [{number_to_display}/{self.target_count}] カードをクリックして詳細ページに遷移します...")
                    
                    image_link_selector = convert_to_robust_selector("a[class*='link-image--']")
                    target_card.locator(image_link_selector).first.click()
                    page.wait_for_load_state("domcontentloaded", timeout=20000)
                    page_transitioned = True
                    
                    detail_page_url = page.url
                    logger.debug(f"    -> 詳細ページURL取得: {detail_page_url}")

                    rakuten_link_selector = convert_to_robust_selector('div[class*="ichiba-in-page--"] a')
                    rakuten_link_element = page.locator(rakuten_link_selector).first
                    rakuten_link_element.wait_for(state="visible", timeout=15000)
                    rakuten_url = rakuten_link_element.get_attribute('href')
                    if rakuten_url:
                        logger.debug(f"    -> 楽天市場URL取得: {rakuten_url[:60]}...")
                    else:
                        logger.warning("    -> 楽天市場URLの取得に失敗しました。")

                except Error as detail_page_error:
                    logger.error(f"  -> 詳細ページの処理中にエラーが発生しました: {detail_page_error}", exc_info=True)
                finally:
                    if page_transitioned:
                        logger.debug("  -> 一覧ページに戻ります...")
                        page.go_back(wait_until="domcontentloaded")
                        page.wait_for_timeout(2000)
                    else:
                        logger.warning("  -> ページ遷移が失敗したため、ブラウザバックは行いません。")

                if rakuten_url and detail_page_url:
                    logger.debug(f"  -> DBのroom_urlを更新します (キー: {rakuten_url[:40]}...)")
                    update_room_url_by_rakuten_url(rakuten_url, detail_page_url)
                
                processed_count += 1

        except Exception as e:
            logger.error(f"タスクの実行中にエラーが発生しました: {e}", exc_info=True)
            return False
        finally:
            logger.debug(f"合計 {processed_count} 件のカードを処理しました。")
            logger.info(f"--- {self.action_name}を終了します ---")
        
        return True

def run_bind_product_url_room_url(count: int = 2, **kwargs):
    """
    BindProductUrlRoomUrlTask のラッパー関数。
    """
    # __init__からsource_urlを削除したため、引数も削除
    task = BindProductUrlRoomUrlTask(count=count)
    return task.run()