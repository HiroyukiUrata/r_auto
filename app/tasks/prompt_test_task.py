import logging
import json
import re
from typing import List, Dict, Any
import os
import random
import time
from app.core.base_task import BaseTask
from app.core.ai_utils import call_gemini_api_with_retry
from app.utils.json_utils import parse_json_with_rescue
from google import genai

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
        logging.debug(f"[PromptTestTask] _execute_main_logic 開始: prompt_key='{self.prompt_key}'")
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logging.error("環境変数 'GEMINI_API_KEY' が設定されていません。")
            raise ValueError("GEMINI_API_KEYが設定されていません。")
        
        logging.debug(f"プロンプトテストを実行します: key='{self.prompt_key}'")
        
        client = genai.Client(api_key=api_key)
        json_string = json.dumps(self.test_data, indent=2, ensure_ascii=False)
        full_prompt = f"{self.prompt_content}\n\n以下のJSON配列の各要素について、`ai_caption`または`comment_body`を生成し、JSON配列全体を完成させてください。\n\n```json\n{json_string}\n```"
        
        # --- ログ出力 ---
        logging.debug("--- プロンプトテスト: AIへの入力 ---")
        logging.debug(f"【使用プロンプト】\n{self.prompt_content}")
        logging.debug(f"【テストデータ】\n{json_string}")
        logging.debug(f"【最終的なプロンプト全体】\n{full_prompt}")
        logging.debug("------------------------------------")

        response_text = call_gemini_api_with_retry(client, full_prompt, f"プロンプトテスト - {self.prompt_key}")
        logging.debug("AIからのレスポンスを受信しました。")

        result = parse_json_with_rescue(response_text)
        if not result:
            raise ValueError(f"AIの応答からJSONブロックを抽出できませんでした。応答内容: {response_text}")
        
        return result