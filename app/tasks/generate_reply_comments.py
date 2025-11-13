import logging
import json
import os
import re
import random
import time
from google import genai
from google.genai.errors import ServerError
from app.core.base_task import BaseTask
from app.core.database import get_post_urls_with_unreplied_comments, get_unreplied_comments_for_post, bulk_update_comment_replies

logger = logging.getLogger(__name__)

PROMPT_FILE_PATH = "app/prompts/reply_to_comment_prompt.txt"

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
                time.sleep(wait_time)
            else:
                logging.error(f"Gemini API呼び出し中に永続的なエラーが発生しました（{log_context}）: {e}")
                raise
    return ""

class GenerateReplyCommentsTask(BaseTask):
    """
    DBから未返信のコメントを取得し、AIに返信コメントを生成させてDBを更新するタスク。
    """
    def __init__(self):
        super().__init__()
        self.action_name = "AIによる返信コメント生成"
        self.needs_browser = False

    def _execute_main_logic(self):
        logger.debug(f"--- {self.action_name}タスクを開始します ---")

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.error("環境変数 'GEMINI_API_KEY' が設定されていません。")
            return False

        try:
            with open(PROMPT_FILE_PATH, "r", encoding="utf-8") as f:
                prompt_template = f.read()
        except FileNotFoundError:
            logger.error(f"プロンプトファイルが見つかりません: {PROMPT_FILE_PATH}")
            return False

        # 1. 未返信コメントを持つ投稿URLのリストを取得
        post_urls_to_process = get_post_urls_with_unreplied_comments()
        if not post_urls_to_process:
            logger.info("返信対象の新しいコメントはありませんでした。")
            return True

        logger.debug(f"{len(post_urls_to_process)}件の投稿に未返信のコメントがあります。")
        total_updated_count = 0
        client = genai.Client(api_key=api_key)

        # 2. 投稿ごとにループ処理
        for i, post_url in enumerate(post_urls_to_process):
            logger.debug(f"--- 投稿 {i+1}/{len(post_urls_to_process)} の処理を開始: {post_url} ---")
            
            # 3. 投稿ごとの未返信コメントを取得
            comments_data = get_unreplied_comments_for_post(post_url)
            if not comments_data:
                logger.warning(f"  -> 対象コメントが見つかりませんでした。スキップします。")
                continue
            
            logger.debug(f"  -> {len(comments_data)}件の未返信コメントを処理します。")

            # 4. プロンプトの準備
            recent_examples_list = []
            for comment in comments_data[:10]:
                example_str = f"- {comment['user_name']}: {comment['comment_text']}"
                recent_examples_list.append(example_str)
            recent_examples_str = "\n".join(recent_examples_list)

            target_comments = [{"id": c["id"], "user_name": c["user_name"], "comment_text": c["comment_text"], "nickname": ""} for c in comments_data]
            target_comments_json_str = json.dumps(target_comments, indent=2, ensure_ascii=False)
            
            full_prompt = prompt_template.replace("{{ recent_examples }}", recent_examples_str).replace("{{ target_comments_json }}", target_comments_json_str)

            # 5. AIにリクエスト
            logger.debug("  -> AIによる返信コメントの生成を開始します...")
            response_text = _call_gemini_api_with_retry_sync(client, full_prompt, f"返信コメント生成 - 投稿 {i+1}")

            # 6. AIの応答をパース
            json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response_text)
            if not json_match:
                logger.error(f"  -> AIの応答からJSONブロックを抽出できませんでした。この投稿の処理をスキップします。")
                continue
            
            generated_data = json.loads(json_match.group(1))

            # 7. 結果をDBに保存
            updated_count = bulk_update_comment_replies(generated_data)
            logger.debug(f"  -> {updated_count}件のコメントに返信を生成し、DBを更新しました。")
            total_updated_count += updated_count

            # ログ出力用にマージ処理
            merged_replies = {}
            for item in generated_data:
                reply_text = item.get("reply_text")
                if not reply_text: continue
                if reply_text not in merged_replies: merged_replies[reply_text] = set()
                for name in item.get("replied_user_names", []): merged_replies[reply_text].add(name)

            logger.debug("  --- 生成された返信サマリー ---")
            for text, names in merged_replies.items():
                logger.debug(f"    -> To: {', '.join(sorted(list(names)))}")
                logger.debug(f"       Reply: {text}")
            logger.debug("  --------------------------")
        
        #logger.info(f"[Action Summary] name=返信コメント生成, count={total_updated_count}")
        return True

def run_generate_reply_comments():
    """ラッパー関数"""
    task = GenerateReplyCommentsTask()
    return task.run()