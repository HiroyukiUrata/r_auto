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
COMMENT_BODY_PROMPT_FILE = "app/prompts/user_comment_body_prompt.txt"
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


BATCH_SIZE = 10 # 一度に処理するユーザー数





class CreateAiCommentTask(BaseTask):
    """
    AIを使用してユーザーへの返信コメントを生成するタスク。
    """
    def __init__(self):
        super().__init__(count=None) # 件数指定なし
        self.action_name = "AIコメント作成"
        self.needs_browser = False

    def _call_gemini_api_with_retry(self, client, contents, log_context, max_retries=10):
        """Gemini APIをリトライロジック付きで呼び出す共通関数"""
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(model="gemini-2.5-flash", contents=contents)
                return response
            except ServerError as e:
                if "503" in str(e) and attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"Gemini APIが過負荷です（{log_context}）。{wait_time:.1f}秒待機して再試行します... ({attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Gemini API呼び出し中に永続的なエラーが発生しました（{log_context}）: {e}")
                    raise
        return None

    def _extract_names_for_batch(self, client, batch_users, batch_num):
        """バッチ単位でユーザー名を抽出する"""
        prompt = f"{DEFAULT_PROMPT_TEXT}\n\n以下のJSON配列の各要素について、`comment_name`を生成し、JSON配列全体を完成させてください。\n\n```json\n"
        users_for_extraction = [{"id": u["id"], "name": u["name"], "comment_name": ""} for u in batch_users]
        prompt += json.dumps(users_for_extraction, indent=2, ensure_ascii=False) + "\n```"
        
        response = self._call_gemini_api_with_retry(client, prompt, f"名前抽出 - バッチ {batch_num}")
        
        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response.text if response else "")
        if not json_match:
            error_message = f"名前抽出の応答からJSONブロックが見つかりませんでした（バッチ {batch_num}）。"
            logger.error(error_message)
            logger.error(f"Gemini APIからの応答(生): {response.text if response else '応答なし'}")
            return {}
            
        extracted_names = json.loads(json_match.group(1))
        return {item['id']: item.get('comment_name', '') for item in extracted_names}

    def _generate_bodies_for_batch(self, client, batch_users, batch_num, comment_body_prompt):
        """バッチ単位でコメント本文を生成する"""
        users_for_generation = [
            {"id": u["id"], "ai_prompt_message": u["ai_prompt_message"], "comment_body": ""}
            for u in batch_users
        ]
        prompt = f"{comment_body_prompt}\n\n以下のJSON配列の各要素について、`comment_body`を生成し、JSON配列全体を完成させてください。\n\n```json\n"
        prompt += json.dumps(users_for_generation, indent=2, ensure_ascii=False) + "\n```"
        
        response = self._call_gemini_api_with_retry(client, prompt, f"本文生成 - バッチ {batch_num}")

        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response.text if response else "")
        if not json_match:
            error_message = f"コメント本文生成の応答からJSONブロックが見つかりませんでした（バッチ {batch_num}）。"
            logger.error(error_message)
            logger.error(f"Gemini APIからの応答(生): {response.text if response else '応答なし'}")
            return {}

        generated_bodies = json.loads(json_match.group(1))
        return {item["id"]: item.get("comment_body", "") for item in generated_bodies}

    def _execute_main_logic(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.error("環境変数 'GEMINI_API_KEY' が設定されていません。")
            return False

        if not os.path.exists(COMMENT_BODY_PROMPT_FILE):
            logger.error(f"コメント本文プロンプトファイルが見つかりません: {COMMENT_BODY_PROMPT_FILE}")
            return False
        
        with open(COMMENT_BODY_PROMPT_FILE, "r", encoding="utf-8") as f:
            comment_body_prompt = f.read()

        try:
            client = genai.Client(api_key=api_key)
            
            users = get_users_for_ai_comment_creation()
            if not users:
                logger.debug("AIコメント作成対象のユーザーはいません。")
                return True

            logger.debug(f"--- {len(users)}人のユーザーを対象にAIコメント作成を開始します ---")

            id_to_comment_name = {}
            id_to_comment_body = {}
            total_batches = (len(users) + BATCH_SIZE - 1) // BATCH_SIZE

            for i in range(0, len(users), BATCH_SIZE):
                batch_users = users[i:i + BATCH_SIZE]
                batch_num = (i // BATCH_SIZE) + 1
                logger.debug(f"--- バッチ {batch_num}/{total_batches} ({len(batch_users)}人) の処理を開始 ---")

                # ステップ1: 名前の抽出
                names_batch = self._extract_names_for_batch(client, batch_users, batch_num)
                id_to_comment_name.update(names_batch)
                logger.debug(f"バッチ {batch_num}: 名前の抽出が完了。")

                # ステップ2: コメント本文の生成
                bodies_batch = self._generate_bodies_for_batch(client, batch_users, batch_num, comment_body_prompt)
                id_to_comment_body.update(bodies_batch)
                logger.debug(f"バッチ {batch_num}: コメント本文の生成が完了。")

                # APIへの負荷を軽減するため、バッチ間に短い待機時間を設ける
                if batch_num < total_batches:
                    time.sleep(random.uniform(1, 3))

            # ステップ3: 最終的な組み立てとDB更新
            logger.debug("--- 最終的なコメントを組み立て、DBを更新します ---")
            updated_count = 0
            for user in users:
                comment_name = id_to_comment_name.get(user['id'], '')
                comment_body = id_to_comment_body.get(user['id'], '')
 
                if comment_body:
                    # 呼び名がある場合、1行目にそれを組み込む
                    if comment_name:
                        body_lines = comment_body.strip().split('\n')
                        first_line = body_lines[0]
                        # 1行目が「👸「...」」の形式かチェック
                        match = re.match(r"^\s*👸「(.*)」\s*$", first_line)
                        if match:
                            # 形式に一致する場合、括弧の中身に呼びかけを追加
                            inner_text = match.group(1).strip()
                            new_first_line = f"👸「{comment_name}さん、{inner_text}」"
                            final_comment = new_first_line + '\n' + '\n'.join(body_lines[1:])
                        else:
                            # 形式に一致しない場合、全体の先頭に呼びかけを追加
                            final_comment = f"{comment_name}さん、{comment_body}"
                    else:
                        final_comment = comment_body

                    update_user_comment(user['id'], final_comment)
                    logger.debug(f"  -> '{user['name']}'へのコメント生成成功: {final_comment}")

                    updated_count += 1

            logger.debug(f"--- AIコメント作成完了。{updated_count}件のコメントを更新しました。 ---")
            if updated_count > 0:
                summary_message = f"{updated_count}件のコメントを生成しました。"
                #logger.info(f"[Action Summary] name=返信コメント生成, count={updated_count}, message='{summary_message}'")
            return True

        except Exception as e:
            logger.error(f"AIコメント作成タスクの実行中にエラーが発生しました: {e}", exc_info=True)
            return False

def run_create_ai_comment():
    """ラッパー関数"""
    task = CreateAiCommentTask()
    return task.run()