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

COMMENT_BODY_PROMPT = """あなたは、楽天ROOMで他のユーザーと交流するのが得意な親しみやすいインフルエンサーです。
以下のユーザー情報をもとに、二人のキャラクターによる掛け合い形式で `comment_body` を生成してください。**名前は含めないでください。**

登場人物:
- 👸：やさしくて丁寧なお姉さん（フォロー・挨拶担当）
- 👦：明るく素直な男の子（フォロワーへの感謝担当）
- 👸👦：二人のハモり（締めのあいさつ）

出力フォーマット（必ずこの形式で出力）:
👸「<お姉さんのセリフ>」
👦「<男の子のセリフ>」
👸👦「「<二人のセリフ>」」

ルール:
- 各セリフは自然で親しみやすく丁寧な日本語にすること
- 感謝の気持ちを中心に、フォロー関係やアクション内容を反映すること
- 顔文字・絵文字を自由に使うこと
- recent_like_count などの具体的数値は使わず、「たくさん」「いつも」などで表現する
- セリフのトーンは落ち着いた自然な喜びにする。「ついに〜」「やっと〜」のような大げさな表現は避ける
- 出力は本文のみ。説明や補足は不要

【出力例1：以前からフォローしてくれているユーザーです。 いつもたくさんの「いいね」をくれる常連の方です。 今回も10件の「いいね」をしてくれました。」のケース】
👸「いつも応援ありがとうございます🌷」
👦「またお部屋に遊びに来てくださいね✨」
👸👦「「これからも仲良くお願いします💐」」

【出力例2：新規にフォローしてくれました。 今回、新たに3件の「いいね」をしてくれました。」のケース】
👸「フォローといいね嬉しいです😊」
👦「これからよろしくお願いします🌸」
👸👦「「今後とも楽しく交流しましょう💛」」

【出力例3：まだフォローされていないユーザーです。 今回、新たに2件の「いいね」をしてくれました。」のケース】
👸「いいね！本当にありがとうございます💐」
👦「もしよければフォローも検討してくださいね🌼」
👸👦「「今後ともよろしくお願いします😊」」

以下の JSON 配列の各要素について `comment_body` を生成してください。  
各要素のキー:
- id: ユーザーID
- comment_name: 呼びかけに使う名前（空文字の場合あり）
- ai_prompt_message: ユーザー状況
- comment_body: 生成されるコメント本文（AI が埋める）

JSON 配列例:
[
  {
    "id": "user01",
    "comment_name": "{{comment_name}}",
    "ai_prompt_message": "{{ai_prompt_message}}",
    "comment_body": ""
  }
]
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
            logger.error(f"名前抽出の応答からJSONブロックが見つかりませんでした（バッチ {batch_num}）。")
            return {}
            
        extracted_names = json.loads(json_match.group(1))
        return {item['id']: item.get('comment_name', '') for item in extracted_names}

    def _generate_bodies_for_batch(self, client, batch_users, batch_num):
        """バッチ単位でコメント本文を生成する"""
        users_for_generation = [
            {"id": u["id"], "ai_prompt_message": u["ai_prompt_message"], "comment_body": ""}
            for u in batch_users
        ]
        prompt = f"{COMMENT_BODY_PROMPT}\n\n以下のJSON配列の各要素について、`comment_body`を生成し、JSON配列全体を完成させてください。\n\n```json\n"
        prompt += json.dumps(users_for_generation, indent=2, ensure_ascii=False) + "\n```"
        
        response = self._call_gemini_api_with_retry(client, prompt, f"本文生成 - バッチ {batch_num}")

        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response.text if response else "")
        if not json_match:
            logger.error(f"コメント本文生成の応答からJSONブロックが見つかりませんでした（バッチ {batch_num}）。")
            return {}

        generated_bodies = json.loads(json_match.group(1))
        return {item["id"]: item.get("comment_body", "") for item in generated_bodies}

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
                bodies_batch = self._generate_bodies_for_batch(client, batch_users, batch_num)
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
                        lines = comment_body.strip().split('\n')
                        first_line = lines[0]
                        # 元のセリフから絵文字と括弧を取り除く
                        cleaned_first_line = first_line.replace('👸「', '').replace('」', '').strip()
                        # 新しい1行目を生成
                        new_first_line = f'👸「{comment_name}さん、{cleaned_first_line}」'
                        # コメント全体を再構築
                        final_comment = new_first_line + '\n' + '\n'.join(lines[1:])
                    else:
                        final_comment = comment_body

                    update_user_comment(user['id'], final_comment)
                    logger.debug(f"  -> '{user['name']}'へのコメント生成成功: {final_comment}")

                    updated_count += 1

            logger.debug(f"--- AIコメント作成完了。{updated_count}件のコメントを更新しました。 ---")
            if updated_count > 0:
                logger.info(f"[Action Summary] name=返信コメント生成, count={updated_count}")
            return True

        except Exception as e:
            logger.error(f"AIコメント作成タスクの実行中にエラーが発生しました: {e}", exc_info=True)
            return False

def run_create_ai_comment():
    """ラッパー関数"""
    task = CreateAiCommentTask()
    return task.run()