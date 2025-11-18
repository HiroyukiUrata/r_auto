import logging
import time
import random
from google import genai
from google.genai.errors import ServerError

def call_gemini_api_with_retry(client: genai.Client, contents: str, log_context: str, max_retries: int = 5) -> str:
    """
    Gemini APIをリトライロジック付きで同期的に呼び出す共通関数。
    503 Server Errorの場合に指数バックオフでリトライする。
    """
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(model="gemini-2.5-flash", contents=contents)
            return response.text
        except ServerError as e:
            if "503" in str(e) and attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                logging.warning(f"Gemini APIが過負荷です（{log_context}）。{wait_time:.1f}秒待機して再試行します... ({attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                logging.error(f"Gemini API呼び出し中に永続的なエラーが発生しました（{log_context}）: {e}")
                raise
    return "" # リトライがすべて失敗した場合