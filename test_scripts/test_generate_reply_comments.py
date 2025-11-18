import logging
import json
import os
import sys

import re
import random
import time
from google import genai
from google.genai.errors import ServerError
from dotenv import load_dotenv

# プロジェクトのルートディレクトリをPythonのパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.logging_config import setup_logging

logger = logging.getLogger(__name__)

INPUT_JSON_PATH = "test_scripts/output/scraped_comments.json"
OUTPUT_JSON_PATH = "test_scripts/output/replies_generated.json"
PROMPT_FILE_PATH = "app/prompts/my_room_reply_prompt.txt"

def _call_gemini_api_with_retry_sync(client: genai.Client, contents: str, log_context: str, max_retries: int = 5) -> str:
    """Gemini APIをリトライロジック付きで同期的に呼び出す共通関数"""
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(model="models/gemini-2.5-flash", contents=contents)
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

def run_test():
    """
    スクレイピングしたコメント情報(JSON)を元に、AIに返信コメントを生成させるテストスクリプト。
    """
    logger.info(f"--- AIによる返信コメント生成テストを開始します ---")

    # 1. 入力ファイルの存在チェック
    try:
        # .envファイルから環境変数を読み込む
        load_dotenv()
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("環境変数 'GEMINI_API_KEY' が設定されていません。")
        
        if not os.path.exists(INPUT_JSON_PATH):
            raise FileNotFoundError(f"入力ファイルが見つかりません: {INPUT_JSON_PATH}")
        
        with open(PROMPT_FILE_PATH, "r", encoding="utf-8") as f:
            prompt_template = f.read()

        with open(INPUT_JSON_PATH, "r", encoding="utf-8") as f:
            comments_data = json.load(f)
        
        logger.info(f"{len(comments_data)}件のコメントを処理します。")

        # --- 新しいプロンプトのためのデータ準備 ---
        # 1. 最近のやり取りの例を作成 (最新10件)
        #    タイムスタンプでソートし、新しいものが上に来るようにする
        sorted_comments = sorted(comments_data, key=lambda x: x['post_timestamp'], reverse=True)
        recent_examples_list = []
        for comment in sorted_comments[:10]:
            example_str = f"- {comment['user_name']}: {comment['comment_text']}"
            recent_examples_list.append(example_str)
        recent_examples_str = "\n".join(recent_examples_list)

        # 2. 返信対象のコメントを最新10件に絞り、JSON文字列にする
        logger.info(f"最新10件のコメントを返信対象とします。")
        target_comments = [{"user_name": c["user_name"], "comment_text": c["comment_text"], "nickname": ""} for c in sorted_comments[:10]]
        target_comments_json_str = json.dumps(target_comments, indent=2, ensure_ascii=False)
        
        # 3. プロンプトテンプレートに埋め込む
        full_prompt = prompt_template.replace("{{ recent_examples }}", recent_examples_str).replace("{{ target_comments_json }}", target_comments_json_str)

        logger.info("AIによる返信コメントの一括生成を開始します...")
        client = genai.Client(api_key=api_key)
        response_text = _call_gemini_api_with_retry_sync(client, full_prompt, "返信コメント一括生成")

        # 5. AIの応答からJSONを抽出してパース
        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response_text)
        if not json_match:
            raise ValueError(f"AIの応答からJSONブロックを抽出できませんでした。応答内容: {response_text}")
        
        generated_data = json.loads(json_match.group(1))

        # --- 6. AIの応答をマージして最終的な返信リストを作成 ---
        logger.info("AIの応答を解析し、重複をマージします...")
        merged_replies = {}
        for item in generated_data:
            reply_text = item.get("reply_text")
            # AIが空の返信を生成した場合などを考慮
            if not reply_text:
                continue
            
            if reply_text not in merged_replies:
                merged_replies[reply_text] = set()
            
            # replied_user_names リスト内のすべてのユーザー名をセットに追加
            for name in item.get("replied_user_names", []):
                merged_replies[reply_text].add(name)

        # 最終的な形式に再構築
        final_replies = [{"reply_text": text, "replied_user_names": sorted(list(names))} for text, names in merged_replies.items()]

        # 7. 結果を新しいJSONファイルに保存
        with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(final_replies, f, indent=2, ensure_ascii=False)
        
        logger.info(f"生成結果を {OUTPUT_JSON_PATH} に保存しました。")

    except (ValueError, FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"処理中にエラーが発生しました: {e}", exc_info=True)

if __name__ == "__main__":
    # このスクリプトを直接実行した場合の処理
    setup_logging()
    run_test()