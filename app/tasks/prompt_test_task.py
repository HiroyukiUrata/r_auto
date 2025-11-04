import logging
import json
import re
from typing import List, Dict, Any
import os
import random
import time
from google import genai
from google.genai.errors import ServerError

from app.core.base_task import BaseTask

def _call_gemini_api_with_retry_sync(client: genai.Client, contents: str, log_context: str, max_retries: int = 5) -> str:
    """Gemini APIをリトライロジック付きで同期的に呼び出す共通関数"""
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(model="gemini-2.5-flash", contents=contents)
            return response.text
        except ServerError as e:
            if "503" in str(e) and attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                logging.warning(f"Gemini APIが過負荷です（{log_context}）。{wait_time:.1f}秒待機して再試行します... ({attempt + 1}/{max_retries})")
                time.sleep(wait_time) # 同期的に待機
            else:
                logging.error(f"Gemini API呼び出し中に永続的なエラーが発生しました（{log_context}）: {e}")
                raise
    return "" # リトライがすべて失敗した場合

class PromptTestTask(BaseTask):
    """
    プロンプトのテストを実行するタスク。
    """
    def __init__(self, prompt_key: str, prompt_content: str, test_data: List[Dict[str, Any]]):
        super().__init__()
        self.action_name = "プロンプトテスト実行"
        self.needs_browser = False
        self.prompt_key = prompt_key
        self.prompt_content = prompt_content
        self.test_data = test_data

    def _execute_main_logic(self):
        """
        同期的なタスク実行の起点。ここから非同期処理を呼び出す。
        """
        logging.info(f"[PromptTestTask] _execute_main_logic 開始: prompt_key='{self.prompt_key}'")
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logging.error("環境変数 'GEMINI_API_KEY' が設定されていません。")
            raise ValueError("GEMINI_API_KEYが設定されていません。")
        
        logging.info(f"プロンプトテストを実行します: key='{self.prompt_key}'")
        
        client = genai.Client(api_key=api_key)
        json_string = json.dumps(self.test_data, indent=2, ensure_ascii=False)
        full_prompt = f"{self.prompt_content}\n\n以下のJSON配列の各要素について、`ai_caption`または`comment_body`を生成し、JSON配列全体を完成させてください。\n\n```json\n{json_string}\n```"
        
        # --- ログ出力 ---
        logging.info("--- プロンプトテスト: AIへの入力 ---")
        logging.info(f"【使用プロンプト】\n{self.prompt_content}")
        logging.info(f"【テストデータ】\n{json_string}")
        logging.info(f"【最終的なプロンプト全体】\n{full_prompt}")
        logging.info("------------------------------------")

        response_text = _call_gemini_api_with_retry_sync(client, full_prompt, f"プロンプトテスト - {self.prompt_key}")
        logging.info("AIからのレスポンスを受信しました。")

        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response_text)
        if not json_match:
            raise ValueError(f"AIの応答からJSONブロックを抽出できませんでした。応答内容: {response_text}")
        
        return json.loads(json_match.group(1))