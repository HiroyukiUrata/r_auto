import logging
import os
import json
from app.core.base_task import BaseTask
import math
import time
import random
import re
from app.core.database import get_products_for_caption_creation, update_ai_caption,get_products_count_for_caption_creation
from google import genai
from app.core.ai_utils import call_gemini_api_with_retry
from app.utils.json_utils import parse_json_with_rescue

PROMPT_FILE = "app/prompts/product_caption_prompt.txt"

class CreateProductCaptionTask(BaseTask):
    """
    Gemini APIを使用して商品の紹介文（キャプション）を生成するタスク。
    """
    def __init__(self, count: int = 5):
        super().__init__()
        self.action_name = "商品紹介文作成 (Gemini API)"
        self.needs_browser = False

    def _execute_main_logic(self):
        """
        タスクのメインロジック。
        1. APIキーを環境変数から取得
        2. Gemini APIを呼び出す
        3. 結果をログに出力
        """
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logging.error("環境変数 'GEMINI_API_KEY' が設定されていません。")
            return False

        if not os.path.exists(PROMPT_FILE):
            logging.error(f"プロンプトファイルが見つかりません: {PROMPT_FILE}")
            return False

        try:
            client = genai.Client(api_key=api_key)
            total_products_count = get_products_count_for_caption_creation()
            if total_products_count == 0:
                logging.info("投稿文作成対象の商品はありません。")
                return True

            MAX_PRODUCTS_PER_BATCH = 10 # 一度に処理する件数
            max_batches = math.ceil(total_products_count / MAX_PRODUCTS_PER_BATCH)
            logging.info(f"投稿文作成対象の全商品: {total_products_count}件。バッチ処理を開始します（{max_batches}回）。")

            with open(PROMPT_FILE, "r", encoding="utf-8") as f:
                prompt_template = f.read()

            total_updated_count = 0
            for batch_num in range(1, max_batches + 1):
                products = get_products_for_caption_creation(limit=MAX_PRODUCTS_PER_BATCH)
                if not products:
                    logging.info("投稿文作成対象の商品がなくなったため、処理を終了します。")
                    break

                logging.info(f"--- バッチ {batch_num}/{max_batches} を開始します。処理件数: {len(products)}件 ---")

                items_data = [{"id": p["id"], "page_url": p["url"], "item_description": p["name"], "image_url": p["image_url"], "ai_caption": ""} for p in products]
                json_string = json.dumps(items_data, indent=2, ensure_ascii=False)
                full_prompt = f"{prompt_template}\n\n以下のJSON配列の各要素について、`ai_caption`を生成してください。`id`をキーとして、元のJSON配列の形式を維持して返してください。\n\n```json\n{json_string}\n```"

                response_text = call_gemini_api_with_retry(client, full_prompt, f"投稿文作成 - バッチ {batch_num}")

                if not response_text:
                    logging.error(f"バッチ {batch_num}: AIからの応答がありませんでした。このバッチをスキップします。")
                    continue

                generated_items = parse_json_with_rescue(response_text)
                if generated_items:
                    # 'id' がキーで、'ai_caption' が値の辞書を作成
                    id_to_caption = {item.get('id'): item.get('ai_caption') for item in generated_items if item.get('id')}
                    batch_updated_count = 0
                    for product in products:
                        caption = id_to_caption.get(product['id'])
                        if caption:
                            update_ai_caption(product['id'], caption)
                            batch_updated_count += 1
                    logging.info(f"バッチ {batch_num}: {batch_updated_count}件の投稿文をデータベースに保存しました。")
                    total_updated_count += batch_updated_count
                else:
                    logging.error(f"バッチ {batch_num}: AIの応答から有効なJSONデータを抽出できませんでした。")
                    logging.debug(f"AIからの生応答: {response_text}")
                    continue

                # APIへの負荷を軽減するため、バッチ間に短い待機時間を設ける
                if batch_num < max_batches:
                    time.sleep(random.uniform(1, 3))
            
            logging.info(f"--- 全バッチ処理完了。合計 {total_updated_count} 件の投稿文を更新しました。 ---")
            return True

        except Exception as e:
            logging.error(f"Gemini APIの呼び出し中にエラーが発生しました: {e}", exc_info=True)
            return False

def generate_product_caption(count: int = 5):
    """ラッパー関数"""
    task = CreateProductCaptionTask(count=count)
    return task.run()