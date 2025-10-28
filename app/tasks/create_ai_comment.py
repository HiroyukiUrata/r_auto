import logging
import os
import json
import re
from google import genai
from app.core.base_task import BaseTask
from app.core.database import get_users_for_ai_comment_creation, update_user_comment

logger = logging.getLogger(__name__)

PROMPT_FILE = "app/prompts/user_comment_prompt.txt"
DEFAULT_PROMPT_TEXT = """あなたは、楽天ROOMで他のユーザーと交流するのが得意な、親しみやすいインフルエンサーです。
以下のユーザー情報（JSON配列）の各要素について、2つのステップで処理を行ってください。

ステップ1: `comment_name` の生成
- `name` フィールドから、コメントの冒頭で呼びかけるのに最も自然な名前やニックネームを抽出してください。
- 絵文字、記号、説明文（「〜好き」「〜ママ」など）は名前に含めないでください。
- 明らかに個人名ではない単語（例: 「お得情報」、「黒糖抹茶わらび餅」）の場合は、`comment_name` を空文字列（""）にしてください。
- 判断例:
  - `nagi` -> `nagi`
  - `myk│妙佳(雅号)` -> `妙佳`
  - `MONOiROHA@色彩とお菓子と猫好き` -> `MONOiROHA`
  - `台湾🇹🇼⇄日本🇯🇵もちこ` -> `もちこ`
  - `あい♡３児ママ` -> `あい`
  - `黒糖抹茶わらび餅` -> ""

ステップ2: `comment_text` の生成
- `ai_prompt_message` の状況を考慮し、感謝の気持ちが伝わる自然で親しみやすいコメントを生成してください。
- `comment_name` が空でなければ、「{comment_name}さん、」でコメントを始めてください。
- `recent_like_count` などの具体的な数値はコメントに含めず、「たくさん」「いつも」のような言葉で表現してください。

その他の制約:
- 150文字以内で、読みやすく記述してください。
- 絵文字や顔文字を自由に使って、親しみやすさを表現してください。
- 感謝の気持ちを伝えることを最優先してください。
"""


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

        # プロンプトファイルの存在チェックと自動生成
        if not os.path.exists(PROMPT_FILE):
            logger.warning(f"プロンプトファイルが見つかりません: {PROMPT_FILE}")
            try:
                os.makedirs(os.path.dirname(PROMPT_FILE), exist_ok=True)
                with open(PROMPT_FILE, 'w', encoding='utf-8') as f:
                    f.write(DEFAULT_PROMPT_TEXT)
                logger.info("デフォルトのプロンプトファイルを自動生成しました。")
            except Exception as e:
                logger.error(f"プロンプトファイルの自動生成に失敗しました: {e}")
                return False

        try:
            client = genai.Client(api_key=api_key)
            
            # AIコメント生成対象のユーザーを取得
            users = get_users_for_ai_comment_creation() # limitなしで全件取得
            if not users:
                logger.info("AIコメント作成対象のユーザーはいません。")
                return True

            logger.info(f"--- {len(users)}人のユーザーを対象にAIコメント作成を開始します ---")

            with open(PROMPT_FILE, "r", encoding="utf-8") as f:
                prompt_template = f.read()

            # 複数のユーザー情報をJSON形式でまとめる
            users_info_for_prompt = [
                {
                    "id": user['id'],
                    "name": user['name'],
                    "category": user['category'],
                    "ai_prompt_message": user['ai_prompt_message'],
                    "like_count": user['like_count'],
                    "recent_like_count": user['recent_like_count'],
                    "is_following": 'はい' if user['is_following'] else 'いいえ',
                    "comment_name": "", # ステップ1でAIに生成してもらう
                    "comment_text": "" # ステップ2でAIに生成してもらう
                } for user in users
            ]
            json_string = json.dumps(users_info_for_prompt, indent=2, ensure_ascii=False)

            full_prompt = f"{prompt_template}\n\n以下のJSON配列の各要素について、`comment_name`と`comment_text`を生成し、JSON配列全体を完成させてください。`id`をキーとして、元のJSON配列の形式を維持して返してください。\n\n```json\n{json_string}\n```"
            logger.debug(f"Geminiに送信するプロンプト:\n{full_prompt}")

            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=full_prompt,
                )
                
                logger.debug(f"Geminiからの応答:\n{response.text}")

                # 応答からJSONを抽出してパース
                json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response.text)
                if not json_match:
                    logger.error("応答からJSONブロックが見つかりませんでした。")
                    return False
                
                generated_items = json.loads(json_match.group(1))

                id_to_comment = {item['id']: item.get('comment_text') for item in generated_items}
                updated_count = 0
                for user in users:
                    comment = id_to_comment.get(user['id'])
                    if comment:
                        update_user_comment(user['id'], comment)
                        logger.info(f"  -> '{user['name']}'へのコメント生成成功: 「{comment}」")
                        updated_count += 1
            except Exception as e:
                logger.error(f"Gemini APIとの通信中または応答の解析中にエラーが発生しました: {e}", exc_info=True)
                # このバッチは失敗したが、タスク全体は続行可能かもしれないのでFalseは返さない

            logger.info(f"--- AIコメント作成完了。{updated_count}件のコメントを更新しました。 ---")
            return True

        except Exception as e:
            logger.error(f"AIコメント作成タスクの実行中にエラーが発生しました: {e}", exc_info=True)
            return False

def run_create_ai_comment():
    """ラッパー関数"""
    task = CreateAiCommentTask()
    return task.run()