import logging
import os
import json
import re
import random
import time
from google.genai.errors import ServerError
from google import genai
from app.core.base_task import BaseTask
from app.core.database import get_users_for_ai_comment_creation, update_user_comment

logger = logging.getLogger(__name__)

PROMPT_FILE = "app/prompts/user_comment_prompt.txt"
DEFAULT_PROMPT_TEXT = """あなたは、ユーザー名から自然な呼び名を抽出するのが得意なアシスタントです。
`name` フィールドから、コメントの冒頭で呼びかけるのに最も自然な名前やニックネームを抽出してください。

抽出ルール:
- 絵文字、記号、説明文（「〜好き」「〜ママ」など）は名前に含めないでください。
- どうしてもニックネームや名前らしき部分が見つからない場合は、`comment_name` を空文字列（""）にしてください。
- 判断例:
  - `nagi` -> `nagi`
  - `myk│妙佳(雅号)` -> `妙佳`
  - `MONOiROHA@色彩とお菓子と猫好き` -> `MONOiROHA`
  - `台湾🇹🇼⇄日本🇯🇵もちこ` -> `もちこ`
  - `あい♡３児ママ` -> `あい`
  - `黒糖抹茶わらび餅` -> `わらび`
"""

COMMENT_BODY_PROMPT = """あなたは、楽天ROOMで他のユーザーと交流するのが得意な、親しみやすいインフルエンサーです。
以下のユーザーの状況を考慮して、感謝の気持ちが伝わる自然で親しみやすいコメントの**本文のみ**を1つだけ生成してください。**名前は含めないでください。**

制約:
- 120文字以内で、読みやすく記述してください。
- 絵文字や顔文字を自由に使って、親しみやすさを表現してください。
- `recent_like_count` などの具体的な数値はコメントに含めず、「たくさん」「いつも」のような言葉で表現してください。
- 感謝の気持ちを伝えることを最優先してください。
- 馴れ馴れしくなく、「です。」「ます。」調で丁寧な言葉づかい。
- """


class CreateAiCommentTask(BaseTask):
    """
    AIを使用してユーザーへの返信コメントを生成するタスク。
    """
    def __init__(self):
        super().__init__(count=None) # 件数指定なし
        self.action_name = "AIコメント作成"
        self.needs_browser = False

    def _execute_main_logic(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.error("環境変数 'GEMINI_API_KEY' が設定されていません。")
            return False

        try:
            client = genai.Client(api_key=api_key)
            
            users = get_users_for_ai_comment_creation()
            if not users:
                logger.debug("AIコメント作成対象のユーザーはいません。")
                return True

            logger.debug(f"--- {len(users)}人のユーザーを対象にAIコメント作成を開始します ---")

            # --- ステップ1: 名前の抽出 ---
            logger.debug("--- ステップ1: 名前の抽出を開始します ---")
            name_extraction_prompt = f"{DEFAULT_PROMPT_TEXT}\n\n以下のJSON配列の各要素について、`comment_name`を生成し、JSON配列全体を完成させてください。\n\n```json\n"
            users_for_name_extraction = [{"id": u["id"], "name": u["name"], "comment_name": ""} for u in users]
            name_extraction_prompt += json.dumps(users_for_name_extraction, indent=2, ensure_ascii=False) + "\n```"
            
            response_name = client.models.generate_content(model="gemini-2.5-flash", contents=name_extraction_prompt)
            json_match_name = re.search(r"```json\s*([\s\S]*?)\s*```", response_name.text)
            if not json_match_name:
                logger.error("名前抽出の応答からJSONブロックが見つかりませんでした。")
                return False
            
            extracted_names = json.loads(json_match_name.group(1))
            id_to_comment_name = {item['id']: item.get('comment_name', '') for item in extracted_names}
            logger.debug("名前の抽出が完了しました。")

            # --- ステップ2: コメント本文の生成 ---
            logger.debug("--- ステップ2: コメント本文の生成を開始します ---")
            
            users_for_body_generation = [
                # AIに渡す情報を絞り、本文生成に集中させる
                {"id": u["id"], "ai_prompt_message": u["ai_prompt_message"], "comment_body": ""}
                for u in users
            ]
            body_generation_prompt = f"{COMMENT_BODY_PROMPT}\n\n以下のJSON配列の各要素について、`comment_body`を生成し、JSON配列全体を完成させてください。\n\n```json\n"
            body_generation_prompt += json.dumps(users_for_body_generation, indent=2, ensure_ascii=False) + "\n```"
            
            response_body = None
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response_body = client.models.generate_content(
                        model="gemini-2.5-flash", contents=body_generation_prompt
                    )
                    break # 成功したらループを抜ける
                except ServerError as e:
                    if "503" in str(e) and attempt < max_retries - 1:
                        wait_time = (2 ** attempt) + random.uniform(0, 1) # 1, 3, 7秒...と待機時間を増やす
                        logger.warning(f"Gemini APIが過負荷です。{wait_time:.1f}秒待機して再試行します... ({attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                    else:
                        raise # 503以外のエラー、または最終リトライでも失敗した場合はエラーを再送出

            json_match_body = re.search(
                r"```json\s*([\s\S]*?)\s*```", response_body.text if response_body else ""
            )
            if not json_match_body:
                logger.error("コメント本文生成の応答からJSONブロックが見つかりませんでした。")
                return False

            generated_bodies = json.loads(json_match_body.group(1))
            id_to_comment_body = {
                item["id"]: item.get("comment_body", "") for item in generated_bodies
            }
            logger.debug("コメント本文の生成が完了しました。")

            # --- 最終的な組み立てとDB更新 ---
            logger.debug("--- 最終的なコメントを組み立て、DBを更新します ---")
            updated_count = 0
            for user in users:
                comment_name = id_to_comment_name.get(user['id'], '')
                comment_body = id_to_comment_body.get(user['id'], '')

                if comment_body:
                    greeting = f"{comment_name}さん、" if comment_name else ""
                    final_comment = f"{greeting}{comment_body}"

                    update_user_comment(user['id'], final_comment)
                    logger.debug(f"  -> '{user['name']}'へのコメント生成成功: 「{final_comment}」")
                    updated_count += 1

            logger.info(f"--- AIコメント作成完了。{updated_count}件のコメントを更新しました。 ---")
            return True

        except Exception as e:
            logger.error(f"AIコメント作成タスクの実行中にエラーが発生しました: {e}", exc_info=True)
            return False

def run_create_ai_comment():
    """ラッパー関数"""
    task = CreateAiCommentTask()
    return task.run()