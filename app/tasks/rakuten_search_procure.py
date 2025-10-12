import logging
import random
import json
import os
from playwright.sync_api import sync_playwright
from app.core.config_manager import is_headless
from app.core.database import product_exists_by_url
from app.tasks.import_products import process_and_import_products

KEYWORDS_FILE = "db/keywords.json"

def get_keywords_from_file():
    """キーワードファイルを読み込んで、AとBのリストを返す"""
    if not os.path.exists(KEYWORDS_FILE):
        logging.warning(f"キーワードファイルが見つかりません: {KEYWORDS_FILE}")
        return [], []
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("keywords_a", []), data.get("keywords_b", [])
    except (IOError, json.JSONDecodeError) as e:
        logging.error(f"キーワードファイルの読み込みに失敗しました: {e}")
        return [], []

def search_and_procure_from_rakuten(count: int = 5):
    """
    DBに登録されたキーワードを使って楽天市場を検索し、見つかった商品をDBに登録する。
    :param count: 調達する商品の目標総件数
    """
    logging.info("楽天市場の検索による商品調達タスクを開始します。")
    
    keywords_a, keywords_b = get_keywords_from_file()
    
    if not keywords_a:
        logging.warning("キーワードAが設定されていません。商品調達を中止します。")
        return
    
    # キーワードを生成
    search_keywords = []
    if keywords_a and keywords_b:
        # AとB両方に設定がある場合、ランダムに1つずつ選んで組み合わせる
        keyword_a = random.choice(keywords_a)
        keyword_b = random.choice(keywords_b)
        combined_keyword = f"{keyword_a} {keyword_b}"
        search_keywords.append(combined_keyword)
        logging.info(f"キーワードA「{keyword_a}」とキーワードB「{keyword_b}」を組み合わせて検索します: 「{combined_keyword}」")
    else:
        # Aのみ設定がある場合、Aのリストをそのまま使う
        search_keywords = keywords_a
        random.shuffle(search_keywords) # 毎回違う順番で試す
        logging.info("キーワードAのみで検索します。")
    
    total_count_target = count
    logging.info(f"商品調達の目標件数: {total_count_target}件")

    items = []
    with sync_playwright() as p:
        headless_mode = is_headless()
        browser = p.chromium.launch(headless=headless_mode, slow_mo=250 if not headless_mode else 0)
        page = browser.new_page()
        try:
            for keyword in search_keywords:
                if len(items) >= total_count_target:
                    logging.info(f"目標件数 ({total_count_target}件) に達したため、キーワード検索を終了します。")
                    break

                page_num = 1
                MAX_PAGES_PER_KEYWORD = 5 # 1キーワードあたりの最大探索ページ数（無限ループ防止）
                logging.info(f"キーワード「{keyword}」での商品検索を開始します。")

                while page_num <= MAX_PAGES_PER_KEYWORD:
                    if len(items) >= total_count_target:
                        break # 目標件数に達したらページネーションループを抜ける

                    # ページネーションに対応したURLを生成
                    search_url = f"https://search.rakuten.co.jp/search/mall/{keyword}/?p={page_num}"
                    logging.info(f"検索ページにアクセスします (Page {page_num}): {search_url}")
                    page.goto(search_url, wait_until="domcontentloaded", timeout=60000)

                    # 検索結果の各商品アイテムをループ
                    # 新しいセレクタ: data-testid属性を持つdiv要素を商品カードとして特定
                    # 新しいセレクタ: 'searchresultitem' クラスを持つdiv要素を商品カードとして特定
                    product_cards = page.locator("div.searchresultitem")
                    num_found_on_page = product_cards.count()
                    logging.info(f"ページ {page_num} から {num_found_on_page} 件の商品が見つかりました。")

                    if num_found_on_page == 0:
                        logging.info(f"このキーワード「{keyword}」ではこれ以上商品が見つかりませんでした。次のキーワードに進みます。")
                        break # 商品がなければこのキーワードでの探索を終了

                    # ページ上のすべての商品をチェックする
                    for i, card in enumerate(product_cards.all()):
                        # ループの先頭で目標件数に達しているか再度チェック
                        if len(items) >= total_count_target:
                            break
                        
                        # 新しいセレクタ: 'image-link-wrapper--...' クラスを持つa要素からURLを取得
                        url_element = card.locator("a[class*='image-link-wrapper--']").first
                        # 新しいセレクタ: 'image--...' クラスを持つimg要素から画像と商品名を取得
                        image_element = card.locator("img[class*='image--']").first

                        if url_element.count() and image_element.count():
                            page_url = url_element.get_attribute('href')

                            # DBに既に存在するURLか、都度チェックする
                            if product_exists_by_url(page_url):
                                logging.info(f"  スキップ(DB重複): この商品は既にDBに存在します。 URL: {page_url[:50]}...")
                                continue # 次の商品へ

                            item_data = {
                                "item_description": image_element.get_attribute('alt'),
                                "page_url": page_url,
                                "image_url": image_element.get_attribute('src'),
                                "procurement_keyword": keyword # どのキーワードで調達したかを記録
                            }
                            items.append(item_data)
                            logging.info(f"  [{len(items)}/{total_count_target}] 商品情報を収集: {item_data['item_description'][:30]}...")
                        else:
                            logging.warning(f"  商品カード {i+1} から必要な情報（商品名、URL、画像）を取得できませんでした。")
                    
                    page_num += 1 # 次のページへ

        except Exception as e:
            logging.error(f"楽天市場のスクレイピング中にエラーが発生しました: {e}")
        finally:
            browser.close()

    if items:
        logging.info(f"収集した {len(items)} 件の商品をデータベースに登録します。")
        # 共通関数を呼び出してDBに保存
        added_count, skipped_count = process_and_import_products(items)
        logging.info(f"商品登録処理が完了しました。新規追加: {added_count}件, スキップ: {skipped_count}件")
    else:
        logging.info("楽天市場から調達できる商品がありませんでした。")

    logging.info("楽天市場の検索による商品調達タスクを終了します。")