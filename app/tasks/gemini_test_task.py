import logging
import os
import json
from app.core.base_task import BaseTask
from google import genai

PROMPT_FILE = "app/prompts/caption_prompt.txt"
class GeminiTestTask(BaseTask):
    """
    Gemini APIの動作をテストするためのタスク。
    """
    def __init__(self):
        super().__init__()
        self.action_name = "Gemini APIテスト"
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

            # テスト用のサンプルJSONデータ
            sample_products = [
                {"page_url": "https://example.com/product/1", "item_description": "高性能なワイヤレスイヤホン。ノイズキャンセリング機能付き。", "image_url": "https://example.com/image1.jpg", "ai_caption": ""},
                {"page_url": "https://example.com/product/2", "item_description": "オーガニックコットン100%のふわふわタオル。", "image_url": "https://example.com/image2.jpg", "ai_caption": ""}
            ]
            json_string = json.dumps(sample_products, indent=2, ensure_ascii=False)

            # プロンプトファイルを読み込み、JSONデータと結合
            with open(PROMPT_FILE, "r", encoding="utf-8") as f:
                prompt_template = f.read()
            
            full_prompt = f"{prompt_template}\n\n以下のJSON配列の各要素について、`ai_caption`を生成してください。\n\n```json\n{json_string}\n```"

            logging.info(f"--- Gemini APIテストを開始します ---")
            logging.debug(f"送信するプロンプト:\n{full_prompt}")

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=full_prompt,
            )
            
            logging.info("--- 応答結果 ---")
            logging.info(response.text)
            return True

        except Exception as e:
            logging.error(f"Gemini APIの呼び出し中にエラーが発生しました: {e}", exc_info=True)
            return False

def run_gemini_test_task():
    """ラッパー関数"""
    task = GeminiTestTask()
    return task.run()