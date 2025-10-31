import logging
import os
import json
from app.core.base_task import BaseTask
import re
from app.core.database import get_products_for_caption_creation, update_ai_caption,get_products_count_for_caption_creation
from google import genai

PROMPT_FILE = "app/prompts/caption_prompt.txt"
class CreateCaptionApiTask(BaseTask):
    """
    Gemini APIを使用して商品の投稿文を生成するタスク。
    """
    def __init__(self, count: int = 5):
        super().__init__()
        self.action_name = "投稿文作成 (Gemini API)"
        self.target_count = count
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
            
            products = get_products_for_caption_creation()
            if not products:
                logging.info("投稿文作成対象の商品はありません。")
                return True

            items_data = [{"id": p["id"], "page_url": p["url"], "item_description": p["name"], "image_url": p["image_url"], "ai_caption": ""} for p in products]
            json_string = json.dumps(items_data, indent=2, ensure_ascii=False)

            # プロンプトファイルを読み込み、JSONデータと結合
            with open(PROMPT_FILE, "r", encoding="utf-8") as f:
                prompt_template = f.read()
            
            full_prompt = f"{prompt_template}\n\n以下のJSON配列の各要素について、`ai_caption`を生成してください。`id`をキーとして、元のJSON配列の形式を維持して返してください。\n\n```json\n{json_string}\n```"

            logging.info(f"--- Gemini APIで投稿文作成を開始します。対象: {len(products)}件 ---")
            logging.debug(f"送信するプロンプト:\n{full_prompt}")

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=full_prompt,
            )
            
            logging.debug("--- 応答結果 ---")
            logging.debug(response.text)

            # 応答からJSONを抽出してパース
            try:
                # AIの応答からJSON部分を抽出
                json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response.text)
                if not json_match:
                    logging.error("応答からJSONブロックが見つかりませんでした。")
                    return False
                
                generated_items = json.loads(json_match.group(1))

                id_to_caption = {item['id']: item.get('ai_caption') for item in generated_items}
                updated_count = 0
                for product in products:
                    caption = id_to_caption.get(product['id'])
                    if caption:
                        update_ai_caption(product['id'], caption)
                        updated_count += 1
                logging.info(f"{updated_count}件の投稿文をデータベースに保存しました。")
                return True
            except (json.JSONDecodeError, KeyError) as e:
                logging.error(f"応答JSONの解析に失敗しました: {e}")
                return False

        except Exception as e:
            logging.error(f"Gemini APIの呼び出し中にエラーが発生しました: {e}", exc_info=True)
            return False

def run_create_caption_api(count: int = 5):
    """ラッパー関数"""
    task = CreateCaptionApiTask(count=count)
    return task.run()