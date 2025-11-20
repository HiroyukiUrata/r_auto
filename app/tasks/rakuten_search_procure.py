import logging
import random
import json
import os
from app.core.database import product_exists_by_url
from app.core.base_task import BaseTask
from app.tasks.import_products import process_and_import_products

KEYWORDS_FILE = "db/keywords.json"
RECENT_KEYWORDS_FILE = "db/recent_keywords.json"
MAX_RECENT_KEYWORDS = 10

# 楽天ジャンルIDとジャンル名のマッピング
RAKUTEN_GENRES = {
    "100371": "レディースファッション", "551177": "メンズファッション", "100433": "インナー・下着・ナイトウェア", "216131": "バッグ・小物・ブランド雑貨", "558885": "靴", "558929": "腕時計", "216129": "ジュエリー・アクセサリー",
    "100533": "キッズ・ベビー・マタニティ", "566382": "おもちゃ", "101070": "スポーツ・アウトドア", "562637": "家電",
    "211742": "TV・オーディオ・カメラ", "100026": "パソコン・周辺機器", "564500": "スマートフォン・タブレット",
    "565004": "光回線・モバイル通信", "100227": "食品", "551167": "スイーツ・お菓子", "100316": "水・ソフトドリンク",
    "510915": "ビール・洋酒", "510901": "日本酒・焼酎", "100804": "インテリア・寝具・収納",
    "215783": "日用品雑貨・文房具・手芸", "558944": "キッチン用品・食器・調理器具", "200162": "本・雑誌・コミック",
    "101240": "CD・DVD", "101205": "テレビゲーム", "101164": "ホビー", "112493": "楽器・音響機器",
    "101114": "車・バイク", "503190": "車用品・バイク用品", "100939": "美容・コスメ・香水", "100938": "ダイエット・健康",
    "551169": "医薬品・コンタクト・介護", "101213": "ペット・ペットグッズ", "100005": "花・ガーデン・DIY",
    "101438": "サービス・リフォーム", "111427": "住宅・不動産", "101381": "カタログギフト・チケット", "100000": "百貨店・総合通販・ギフト"
}

def save_recent_keyword(keyword):
    """最近使ったキーワードをJSONファイルに保存する"""
    try:
        recent_keywords = []
        if os.path.exists(RECENT_KEYWORDS_FILE):
            with open(RECENT_KEYWORDS_FILE, "r", encoding="utf-8") as f:
                recent_keywords = json.load(f)
        
        # 既存のリストからキーワードを削除（順序を先頭にするため）
        if keyword in recent_keywords:
            recent_keywords.remove(keyword)
        
        # 先頭にキーワードを追加
        recent_keywords.insert(0, keyword)
        
        # 最大件数を超えたら古いものを削除
        with open(RECENT_KEYWORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(recent_keywords[:MAX_RECENT_KEYWORDS], f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"最近使ったキーワードの保存に失敗しました: {e}")

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

class RakutenSearchProcureTask(BaseTask):
    """
    楽天市場を検索して商品を調達するタスク。
    ログインプロファイルは不要。
    """
    def __init__(self, count: int = 5):
        super().__init__(count=count)
        self.action_name = "楽天市場から商品を検索・調達"
        self.use_auth_profile = False # 認証プロファイルは不要

    def _execute_main_logic(self):
        keywords_a, keywords_b = get_keywords_from_file()
    
        if not keywords_a or not keywords_b:
            logging.warning("キーワードA群（ジャンル）とキーワードB群（絞り込み用）の両方が設定されている必要があります。商品調達を中止します。")
            return
        
        # 検索キーワードを動的に生成
        # 目標件数に達するまで、キーワードA/Bからランダムに組み合わせて検索を試みる
        search_keyword_pairs = []
        # 検索の多様性を確保するため、目標件数の2倍のキーワードペアを上限として生成
        for _ in range(self.target_count * 2):
            genre_id = random.choice(keywords_a)
            keyword = random.choice(keywords_b)
            search_keyword_pairs.append({"genre_id": genre_id, "keyword": keyword})

        if not search_keyword_pairs:
            logging.warning("検索キーワードのペアを生成できませんでした。")
            return

        
        logging.debug(f"商品調達の目標件数: {self.target_count}件")

        items = []
        # BaseTaskが管理するページオブジェクトを使用
        page = self.page
        try:
            for pair in search_keyword_pairs:
                if len(items) >= self.target_count:
                    logging.debug(f"目標件数 ({self.target_count}件) に達したため、キーワード検索を終了します。")
                    break

                genre_id = pair["genre_id"]
                keyword = pair["keyword"]
                
                page_num = 1
                MAX_PAGES_PER_KEYWORD = 5
                logging.info(f"ジャンルID「{genre_id}」とキーワード「{keyword}」で商品検索を開始します。")
                # ジャンル名とキーワードの組み合わせを保存
                genre_name = RAKUTEN_GENRES.get(genre_id, f"ID:{genre_id}")
                save_recent_keyword({"keyword": keyword, "genre_name": genre_name, "genre_id": genre_id})

                while page_num <= MAX_PAGES_PER_KEYWORD:
                    if len(items) >= self.target_count:
                        break

                    search_url = f"https://search.rakuten.co.jp/search/mall/{keyword}/{genre_id}/?p={page_num}&s=5"
                    logging.debug(f"検索ページにアクセスします (Page {page_num}): {search_url}")
                    page.goto(search_url, wait_until="domcontentloaded", timeout=60000)

                    product_cards = page.locator("div.searchresultitem")
                    num_found_on_page = product_cards.count()
                    logging.debug(f"ページ {page_num} から {num_found_on_page} 件の商品が見つかりました。")

                    if num_found_on_page == 0:
                        logging.debug(f"このキーワード「{keyword}」ではこれ以上商品が見つかりませんでした。次のキーワードに進みます。")
                        break

                    for i, card in enumerate(product_cards.all()):
                        if len(items) >= self.target_count:
                            break
                        
                        url_element = card.locator("a[class*='image-link-wrapper--']").first
                        image_element = card.locator("img[class*='image--']").first

                        if url_element.count() and image_element.count():
                            page_url = url_element.get_attribute('href')
                            if product_exists_by_url(page_url):
                                logging.debug(f"  スキップ(DB重複): この商品は既にDBに存在します。 URL: {page_url[:50]}...")
                                continue

                            # procurement_keyword を「キーワード (ジャンル名)」の形式で保存
                            genre_name = RAKUTEN_GENRES.get(genre_id, f"ID:{genre_id}")
                            procurement_keyword_display = f"{keyword} ({genre_name})"

                            item_data = {"item_description": image_element.get_attribute('alt'), "page_url": page_url, "image_url": image_element.get_attribute('src'), "procurement_keyword": procurement_keyword_display}
                            items.append(item_data)
                            logging.debug(f"  [{len(items)}/{self.target_count}] 商品情報を収集: {item_data['item_description'][:30]}...")
                        else:
                            logging.warning(f"  商品カード {i+1} から必要な情報（商品名、URL、画像）を取得できませんでした。")
                    
                    page_num += 1
        except Exception as e:
            logging.error(f"楽天市場のスクレイピング中にエラーが発生しました: {e}")

        if items:
            logging.debug(f"収集した {len(items)} 件の商品をデータベースに登録します。")
            added_count, skipped_count = process_and_import_products(items)
            logging.info(f"商品登録処理が完了しました。新規追加: {added_count}件, スキップ: {skipped_count}件")
            return added_count # 処理件数を返す
        else:
            logging.info("楽天市場から調達できる商品がありませんでした。")
            return 0 # 処理件数0を返す

def search_and_procure_from_rakuten(count: int = 5):
    """ラッパー関数"""
    task = RakutenSearchProcureTask(count=count)
    # BaseTask.run()が返す結果(成功件数 or False)をハンドリング
    result = task.run()
    return result if isinstance(result, int) else 0