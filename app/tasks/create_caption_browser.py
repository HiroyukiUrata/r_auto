import logging
import json
import os
import re
from playwright.sync_api import sync_playwright, TimeoutError
import math
import time
from app.core.base_task import BaseTask
from app.core.database import get_products_for_caption_creation, get_products_count_for_caption_creation, update_ai_caption, update_product_status
from app.utils.json_utils import parse_json_with_rescue

PROMPT_FILE = "app/prompts/product_caption_prompt.txt"
DEBUG_DIR = "db/debug"

class CreateCaptionTask(BaseTask):
    """
    Geminiを使い投稿文を生成するタスク。
    """
    def __init__(self, count: int = 0):
        super().__init__(count=count)
        self.action_name = "投稿文作成 (Gemini)"
        self.use_auth_profile = False # 認証プロファイルは不要
        self.needs_browser = True

    def _execute_main_logic(self):
        # 一度にGeminiに送信する最大件数
        MAX_PRODUCTS_PER_BATCH = 5

        if not os.path.exists(PROMPT_FILE):
            logging.error(f"プロンプトファイルが見つかりません: {PROMPT_FILE}")
            return

        # 最初に総件数を取得
        total_products_count = get_products_count_for_caption_creation()
        if total_products_count == 0:
            logging.info("投稿文作成対象の商品はありません。")
            return
        logging.info(f"投稿文作成対象の全商品: {total_products_count}件")

        max_batches = math.ceil(total_products_count / MAX_PRODUCTS_PER_BATCH)
        logging.debug(f"最大バッチ処理回数: {max_batches}回")

        for batch_num in range(1, max_batches + 1):
            products = get_products_for_caption_creation(limit=MAX_PRODUCTS_PER_BATCH)
            if not products:
                logging.info("投稿文作成対象の商品がなくなったため、処理を終了します。")
                break

            logging.info(f"--- バッチ {batch_num}/{max_batches} を開始します。処理件数: {len(products)}件 ---")

            items_data = [{"page_url": p["url"], "item_description": p["name"], "image_url": p["image_url"], "ai_caption": ""} for p in products]
            
            full_prompt = ""
            try:
                with open(PROMPT_FILE, "r", encoding="utf-8") as f:
                    prompt_template = f.read()

                json_string = json.dumps(items_data, indent=2, ensure_ascii=False)
                full_prompt = f"{prompt_template}\n\n以下のJSON配列の各要素について、`ai_caption`を生成してください。`page_url`をキーとして、元のJSON配列の形式を維持して返してください。\n\n```json\n{json_string}\n```"
                
                # 生成したプロンプトを毎回上書き保存
                os.makedirs(DEBUG_DIR, exist_ok=True)
                with open(os.path.join(DEBUG_DIR, "last_gemini_prompt.txt"), "w", encoding="utf-8") as f:
                    f.write(full_prompt)

                self.context.grant_permissions(["clipboard-read", "clipboard-write"])
                page = self.page
                page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=60000)

                prompt_input = page.get_by_label("ここにプロンプトを入力してください").or_(page.get_by_placeholder("Gemini に相談")).or_(page.get_by_role("textbox"))
                prompt_input.wait_for(state="visible", timeout=30000)
                prompt_input.click()

                page.evaluate("text => navigator.clipboard.writeText(text)", full_prompt)
                prompt_input.press("Control+V")
                prompt_input.press("Enter")
                logging.debug("プロンプトを送信しました。")
                
                try:
                    page.get_by_label("生成を停止").wait_for(state="hidden", timeout=120000)
                except TimeoutError:
                    logging.error(f"バッチ {batch_num}: Geminiの応答待機中にタイムアウトしました。")
                    self._save_debug_info(full_prompt, "gemini_response_timeout")
                    for product in products: update_product_status(product['id'], 'エラー')
                    continue

                try:
                    dynamic_timeout = (60 + len(products) * 60) * 1000 #なかなか読み込まないときは*Nを長く
                    page.wait_for_function("() => document.querySelectorAll('.response-container-content .code-container').length > 0 && document.querySelectorAll('.response-container-content .code-container')[document.querySelectorAll('.response-container-content .code-container').length - 1].innerText.trim().endsWith(']')", timeout=dynamic_timeout)
                except TimeoutError:
                    logging.warning("応答JSONの表示待機がタイムアウトしました。不完全な状態でもコピーを試みます。")
                    self._save_debug_info(full_prompt, "json_wait_timeout")
                
                copy_button_locator = page.locator(".response-container-content").last.get_by_label("コードをコピー")
                copy_button_locator.wait_for(state="visible", timeout=30000)
                copy_button_locator.click()
                page.wait_for_timeout(10000)

                generated_json_str = page.evaluate("() => navigator.clipboard.readText()")
                generated_items = parse_json_with_rescue(generated_json_str)

                if generated_items:
                    url_to_caption = {item['page_url']: item.get('ai_caption') for item in generated_items}
                    updated_count = 0
                    for product in products:
                        caption = url_to_caption.get(product['url'])
                        if caption:
                            update_ai_caption(product['id'], caption)
                            updated_count += 1
                    logging.info(f"バッチ {batch_num}: {updated_count}件の投稿文をデータベースに保存しました。")

            except Exception as e:
                # 本番環境(simple)ではトレースバックを抑制し、開発環境(detailed)では表示する
                is_detailed_log = os.getenv('LOG_FORMAT', 'detailed').lower() == 'detailed' # この行は既に修正済みですが、念のため記載
                logging.error(f"プロンプトの生成またはコピー中にエラーが発生しました: {e}", exc_info=is_detailed_log)
                self._save_debug_info(full_prompt, "general_error")
                for product in products: update_product_status(product['id'], 'エラー')
                # BaseTaskのエラーハンドリングに任せるため、例外を再送出
                raise

    def _save_debug_info(self, prompt_text: str, error_type: str):
        """エラー発生時のデバッグ情報（プロンプトとスクリーンショット）を保存する"""
        try:
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            # BaseTaskのスクリーンショット機能を利用
            self._take_screenshot_on_error(prefix=f"{error_type}_{timestamp}")

            # プロンプトを保存
            if prompt_text:
                prompt_filename = os.path.join(DEBUG_DIR, f"error_prompt_{error_type}_{timestamp}.txt")
                with open(prompt_filename, "w", encoding="utf-8") as f:
                    f.write(prompt_text)
                logging.info(f"エラー発生時のプロンプトを {prompt_filename} に保存しました。")
        except Exception as e:
            logging.error(f"デバッグ情報の保存中にエラーが発生しました: {e}")

def create_caption_prompt(count: int = 0):
    """ラッパー関数"""
    task = CreateCaptionTask(count=count)
    return task.run()