import logging
import json
import os
import random
import time
from playwright.sync_api import Page
from app.core.database import product_exists_by_url, init_db
from app.tasks.import_products import process_and_import_products
from app.utils.selector_utils import convert_to_robust_selector

# --- 設定 ---
# テストで処理する目標件数
TARGET_COUNT = 50
# テスト対象のURL（固定）
SOURCE_URL = "https://room.rakuten.co.jp/room_79a45994e0/items"

logger = logging.getLogger(__name__)

def run_test(page: Page):
    """
    Masonryレイアウトのユーザーページを視覚的な順序で処理するテストのテンプレート。
    """
    logger.info("--- Masonryレイアウト ループ処理テストを開始します ---")
    
    # データベースを初期化（必要に応じて）
    # init_db()

    logger.info(f"対象URL: 「{SOURCE_URL}」")
    logger.info(f"処理目標件数: {TARGET_COUNT}件")

    processed_count = 0
    try:
        # URLの前後の空白を除去
        page.goto(SOURCE_URL.strip(), wait_until="domcontentloaded", timeout=60000)

        # ローディングスピナーのセレクタ
        spinner_selector = 'div[aria-label="loading"]'
        highlight_colors = ["red", "blue", "yellow", "green", "orange"]
        card_selector = convert_to_robust_selector('div[class*="container--JAywt"]')
        pin_icon_selector = convert_to_robust_selector('div.pin-icon--1FR8u')
        
        logger.debug("最初の商品カードが表示されるのを待ちます...")
        page.locator(card_selector).first.wait_for(state="visible", timeout=30000)
        # ページ描画が完全に安定するまで少し待機する (Masonryレイアウトの安定化のため)
        page.wait_for_timeout(2000)

        scroll_count = 0
        max_scroll_attempts = 20 # 無限ループを避けるための最大スクロール回数

        while processed_count < TARGET_COUNT and scroll_count < max_scroll_attempts:
            # 1. すべてのカードを取得し、未処理かつ可視のものをフィルタリング
            all_cards_on_page = page.locator(card_selector).all()
            
            visible_unprocessed_cards_with_bbox = []
            for card_loc in all_cards_on_page:
                # is_visible() は要素がDOMにあり、表示されているかを確認
                # evaluate() で data-processed 属性の有無を確認
                if card_loc.is_visible() and not card_loc.evaluate("node => node.hasAttribute('data-processed')"):
                    # ピン留めされているかチェック
                    if card_loc.locator(pin_icon_selector).count() > 0:
                        logger.debug("  -> ピン留めされたカードを発見しました。処理対象外とします。")
                        # 処理済みマークを付けて、次回以降のループで無視するようにする
                        card_loc.evaluate("node => node.setAttribute('data-processed', 'true')")
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
                        # 短いタイムアウトでスピナーの表示をチェック
                        page.locator(spinner_selector).wait_for(state="visible", timeout=1000)
                        spinner_appeared = True
                        break # スピナーが表示されたらループを抜ける
                    except Exception:
                        logger.debug(f"  スクロール試行 {scroll_attempt + 1}/5: スピナーはまだ表示されません。")
                        page.wait_for_timeout(500) # 次の試行まで少し待つ
                
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
                continue # スクロール処理が終わったので、whileループの先頭に戻って新しいカードを探す

            # 2. 視覚的な位置に基づいてソート (Y座標 -> X座標)
            visible_unprocessed_cards_with_bbox.sort(key=lambda x: (x[1]['y'], x[1]['x']))
            
            if not visible_unprocessed_cards_with_bbox:
                continue

            # 3. 視覚的に最も左上にある未処理のカードを処理対象とする
            target_card = visible_unprocessed_cards_with_bbox[0][0] # Locatorオブジェクトを取得

            # 処理済みのマークを付ける
            target_card.evaluate("node => node.setAttribute('data-processed', 'true')")

            # --- ここに、カードに対する具体的な処理を記述します ---
            # 例: ハイライト、情報取得、クリックなど
            
            # カードにハイライトと番号を付与する
            color = highlight_colors[processed_count % len(highlight_colors)]
            number_to_display = processed_count + 1
            target_card.evaluate("""
                (node, args) => {
                    const randomTop = Math.floor(Math.random() * 50) + 5; // 5%から55%の範囲
                    const randomLeft = Math.floor(Math.random() * 70) + 5; // 5%から75%の範囲
    
                    // ハイライト用の枠線
                    node.style.border = `5px solid ${args.color}`;
                    node.style.position = 'relative'; // 番号を配置するための基準
    
                    // 番号表示用の要素を作成
                    const numberDiv = document.createElement('div');
                    numberDiv.textContent = args.number;
                    Object.assign(numberDiv.style, {
                        position: 'absolute',
                        top: `${randomTop}%`,
                        left: `${randomLeft}%`,
                        backgroundColor: args.color, color: 'white',
                        width: '30px', height: '30px', borderRadius: '50%',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: '16px', fontWeight: 'bold', zIndex: '1000'
                    });
                    node.appendChild(numberDiv);
                }
            """, {"color": color, "number": number_to_display})

            # カードのテキストラベルを取得してログに出力
            card_label_full = target_card.inner_text().replace('\n', ' ').strip()
            card_label_full = " ".join(card_label_full.split())
            card_label_short = (card_label_full[:10] + '...') if len(card_label_full) > 10 else card_label_full
            
            logger.info(f"  [{number_to_display}/{TARGET_COUNT}] カードをハイライトし、番号 {number_to_display} を振りました。 -> {card_label_short}")
            # ----------------------------------------------------
    
            processed_count += 1

    except Exception as e:
        logger.error(f"テストの実行中にエラーが発生しました: {e}", exc_info=True)
    finally:
        logger.info(f"合計 {processed_count} 件のカードを処理しました。")

    logger.info("--- テスト完了 ---")

# --- スクリプトのエントリーポイント ---
if 'page' in locals() or 'page' in globals():
    run_test(page)
else:
    logger.warning("このスクリプトは 'run_task.py manual-test' からの実行を想定しています。")