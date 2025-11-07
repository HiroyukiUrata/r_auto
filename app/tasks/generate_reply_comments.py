import logging
import json
import os
from app.core.base_task import BaseTask
from app.core.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

INPUT_JSON_PATH = "test_scripts/output/scraped_comments.json"
OUTPUT_JSON_PATH = "test_scripts/output/replies_generated.json"
PROMPT_FILE_PATH = "app/prompts/reply_to_comment_prompt.txt"

class GenerateReplyCommentsTask(BaseTask):
    """
    スクレイピングしたコメント情報(JSON)を元に、AIに返信コメントを生成させるタスク。
    """
    def __init__(self):
        super().__init__()
        self.action_name = "AIによる返信コメント生成"
        self.needs_browser = False # このタスクはブラウザを必要としない

    def _execute_main_logic(self):
        logger.info(f"--- {self.action_name}タスクを開始します ---")

        # 1. 入力ファイルの存在チェック
        if not os.path.exists(INPUT_JSON_PATH):
            logger.error(f"入力ファイルが見つかりません: {INPUT_JSON_PATH}")
            return False

        # 2. プロンプトファイルの読み込み
        try:
            with open(PROMPT_FILE_PATH, "r", encoding="utf-8") as f:
                prompt_template = f.read()
        except FileNotFoundError:
            logger.error(f"プロンプトファイルが見つかりません: {PROMPT_FILE_PATH}")
            return False

        # 3. JSONデータの読み込み
        with open(INPUT_JSON_PATH, "r", encoding="utf-8") as f:
            comments_data = json.load(f)
        
        logger.info(f"{len(comments_data)}件のコメントを処理します。")

        # 4. 各コメントに対してAIで返信を生成
        client = GeminiClient()
        for i, comment in enumerate(comments_data):
            self._print_progress_bar(i, len(comments_data), prefix="返信生成中:", suffix=f"{comment['user_name'][:15]:<15}")

            # プロンプトに変数を埋め込む
            prompt = prompt_template.replace("{{ user_name }}", comment["user_name"])
            prompt = prompt.replace("{{ comment_text }}", comment["comment_text"])

            # AIにリクエストを送信
            ai_reply = client.generate_content(prompt)
            comment["ai_reply_text"] = ai_reply.strip()

        self._print_progress_bar(len(comments_data), len(comments_data), prefix="返信生成完了", suffix=" " * 20)

        # 5. 結果を新しいJSONファイルに保存
        with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(comments_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"生成結果を {OUTPUT_JSON_PATH} に保存しました。")
        return True

def run_generate_reply_comments():
    """ラッパー関数"""
    task = GenerateReplyCommentsTask()
    return task.run()