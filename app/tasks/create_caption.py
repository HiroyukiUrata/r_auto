import logging
import json
import os
import re
from playwright.sync_api import sync_playwright, TimeoutError
from app.core.database import get_products_for_caption_creation, get_products_count_for_caption_creation, update_ai_caption, update_product_status

PROMPT_FILE = "app/prompts/caption_prompt.txt"
PROFILE_DIR = "db/playwright_profile"

# --- Gemini応答のJSONを整形・修正するためのヘルパー関数 ---
def fix_indentation(text):
    """インデントの全角スペースを半角スペースに置換する"""
    def replace_indent(match):
        return match.group().replace("　", " ")
    return re.sub(r"^(　+)", replace_indent, text, flags=re.MULTILINE)

def clean_raw_json(text):
    """BOMや制御文字など、JSONパースの妨げになる不要な文字を除去する"""
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = ''.join(c for c in text if c >= ' ' or c in '\n\t')
    return text

def fix_ai_caption(data):
    """ai_caption内のMarkdown強調文字(**)を削除する"""
    if isinstance(data, dict):
        for k, v in data.items():
            if k == "ai_caption" and isinstance(v, str):
                data[k] = v.replace("**", "")
            else:
                fix_ai_caption(v)
    elif isinstance(data, list):
        for item in data:
            fix_ai_caption(item)

def extract_json_from_text(text):
    """テキストの中から ```json ... ``` または [...] のブロックを抽出する"""
    # ```json ... ``` ブロックを探す
    match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if match:
        logging.info("```json ... ``` ブロックを抽出しました。")
        return match.group(1)
    
    # [...] ブロックを探す (最も外側の括弧)
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        logging.info("[...] ブロックを抽出しました。")
        return match.group(0)
    
    logging.warning("テキストからJSONブロックを特定できませんでした。元のテキストをそのまま使用します。")
    return text

def create_caption_prompt():
    """
    ステータスが「URL取得済」の商品を1件取得し、プロンプトを生成してGeminiのページで実行する。
    """
    logging.info("投稿文作成用プロンプトの生成タスクを開始します。")

    # --- デバッグフラグ ---
    # Trueにすると、ブラウザが表示されます(headless=False)。
    # 通常実行時はFalseにしてください。
    is_debug = False
    
    # 一度にGeminiに送信する最大件数
    MAX_PRODUCTS_PER_BATCH = 15

    if not os.path.exists(PROMPT_FILE):
        logging.error(f"プロンプトファイルが見つかりません: {PROMPT_FILE}")
        return

    # 最初に総件数を取得
    total_products_count = get_products_count_for_caption_creation()
    if total_products_count == 0:
        logging.info("投稿文作成対象の商品はありません。")
        return
    logging.info(f"投稿文作成対象の全商品: {total_products_count}件")

    # Playwrightのインスタンスをループの外で一度だけ起動
    with sync_playwright() as p:
        # is_debug=True (ヘッドフル) の場合にディスプレイサーバーを指定する。is_debugがFalseの場合はheadlessで起動。
        browser = p.chromium.launch(headless=not is_debug, env={"DISPLAY": ":0"} if is_debug else {})
        try:
            batch_num = 0
            while True:
                # DBから指定件数だけ商品を取得
                products = get_products_for_caption_creation(limit=MAX_PRODUCTS_PER_BATCH)
                if not products:
                    logging.info("投稿文作成対象の商品がなくなったため、処理を終了します。")
                    break # ループを抜ける

                batch_num += 1
                logging.info(f"--- 対象全レコード{total_products_count}件中、バッチ{batch_num}回目、処理件数{len(products)}件 ---")

                # 複数の商品をリストとして整形
                items_data = [
                    {
                        "page_url": p["url"], # page_urlをキーとして使用
                        "item_description": p["name"],
                        "image_url": p["image_url"],
                        "ai_caption": ""
                    } for p in products
                ]

                page = None # page変数を初期化
                try:
                    # プロンプトファイルを読み込む
                    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
                        prompt_template = f.read()

                    json_string = json.dumps(items_data, indent=2, ensure_ascii=False)

                    # デバッグ用に、Geminiに送信する直前のJSONをファイルに保存
                    try:
                        with open("db/gemini_prompt.json", "w", encoding="utf-8") as f:
                            f.write(json_string)
                        logging.info("Geminiに送信するJSONを db/gemini_prompt.json に保存しました。")
                    except IOError as e:
                        logging.error(f"JSONファイルの保存に失敗しました: {e}")

                    full_prompt = f"{prompt_template}\n\n以下のJSON配列の各要素について、`ai_caption`を生成してください。`page_url`をキーとして、元のJSON配列の形式を維持して返してください。\n\n```json\n{json_string}\n```"

                    # 日本語ロケールとクリップボードのアクセス許可を指定してコンテキストを作成
                    context = browser.new_context(
                        locale="ja-JP",
                        timezone_id="Asia/Tokyo",
                        permissions=["clipboard-read", "clipboard-write"]
                    )
                    page = context.new_page()

                    logging.info("Geminiのページを開き、プロンプトを自動入力します。")
                    page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=60000)

                    # プロンプト入力欄に自動で貼り付け、送信する
                    prompt_input = page.get_by_label("ここにプロンプトを入力してください").or_(page.get_by_placeholder("Gemini に相談")).or_(page.get_by_role("textbox"))
                    
                    logging.info("プロンプト入力欄が表示されるのを待っています...")
                    prompt_input.wait_for(state="visible", timeout=30000)
                    prompt_input.click()

                    logging.info("ブラウザのクリップボードにプロンプトをコピーします...")
                    page.evaluate("text => navigator.clipboard.writeText(text)", full_prompt)
                    paste_shortcut = "Control+V"
                    prompt_input.press(paste_shortcut)

                    prompt_input.press("Enter")
                    logging.info("プロンプトを送信しました。")
                    
                    logging.info("Geminiの応答を待っています...「生成を停止」ボタンが非表示になるのを待ちます。")
                    try:
                        page.get_by_label("生成を停止").wait_for(state="hidden", timeout=120000)
                        logging.info("「生成を停止」ボタンが非表示になりました。応答の表示を待機します。")
                    except TimeoutError:
                        logging.error(f"バッチ {batch_num}: Geminiの応答待機中にタイムアウトしました。このバッチの商品のステータスを「エラー」に更新します。")
                        for product in products:
                            update_product_status(product['id'], 'エラー')
                        continue

                    logging.info("応答JSONが完全に表示されるのを待っています...")
                    try:
                        dynamic_timeout = (60 + len(products) * 15) * 1000
                        logging.info(f"商品数({len(products)}件)に応じた動的タイムアウトを設定します: {dynamic_timeout / 1000}秒")
                        
                        page.wait_for_function("""
                            () => {
                                const code_blocks = document.querySelectorAll('.response-container-content .code-container');
                                if (code_blocks.length === 0) return false;
                                const last_block_text = code_blocks[code_blocks.length - 1].innerText.trim();
                                return last_block_text.endsWith(']');
                            }
                        """, timeout=dynamic_timeout)
                    except TimeoutError:
                        logging.warning("応答JSONの表示待機がタイムアウトしました。不完全な状態でもコピーを試みます。")
                    
                    logging.info("最新の応答ブロック内の「コードをコピー」ボタンが表示されるのを待ちます。")
                    try:
                        copy_button_locator = page.locator(".response-container-content").last.get_by_label("コードをコピー")
                        copy_button_locator.wait_for(state="visible", timeout=30000)
                        logging.info("「コードをコピー」ボタンが表示されました。クリックします。")
                        copy_button_locator.click()
                        logging.info("クリップボードへのコピーを確実にするため10秒待機します。")
                        page.wait_for_timeout(10000)
                    except TimeoutError:
                        logging.error(f"バッチ {batch_num}: Geminiの応答から「コードをコピー」ボタンが見つかりませんでした。このバッチの商品のステータスを維持して次回再挑戦します。")
                        # for product in products:
                        #     update_product_status(product['id'], 'エラー')
                        # continue

                    logging.info("ブラウザのクリップボードから応答を読み取ります。")
                    generated_items = None
                    try:
                        generated_json_str = page.evaluate("() => navigator.clipboard.readText()")

                        try:
                            with open("db/gemini_response_after.json", "w", encoding="utf-8") as f:
                                f.write(generated_json_str)
                            logging.info("Geminiからの応答を db/gemini_response_after.json に保存しました。")
                        except IOError as e:
                            logging.error(f"応答JSONファイルの保存に失敗しました: {e}")

                        cleaned_str = fix_indentation(clean_raw_json(generated_json_str))
                        generated_items = json.loads(cleaned_str)

                    except json.JSONDecodeError as e:
                        logging.warning(f"JSONパースに一度失敗しました: {e}。JSONブロックの抽出を試みます。")
                        try:
                            json_part_str = extract_json_from_text(generated_json_str)
                            cleaned_str = fix_indentation(clean_raw_json(json_part_str))
                            generated_items = json.loads(cleaned_str)
                        except json.JSONDecodeError as final_e:
                            logging.error(f"バッチ {batch_num}: JSONブロックの抽出・再パースにも失敗しました: {final_e}")
                            logging.error(f"取得された内容: {generated_json_str}")
                            for product in products:
                                update_product_status(product['id'], 'エラー')
                            continue

                    if generated_items:
                        fix_ai_caption(generated_items)

                    url_to_caption = {item['page_url']: item.get('ai_caption') for item in generated_items}

                    updated_count = 0
                    for product in products:
                        caption = url_to_caption.get(product['url'])
                        if caption:
                            update_ai_caption(product['id'], caption)
                            updated_count += 1
                    
                    logging.info(f"バッチ {batch_num}: {updated_count}件の投稿文をデータベースに保存しました。")

                except Exception as e:
                    logging.error(f"プロンプトの生成またはコピー中にエラーが発生しました: {e}")
                    logging.error(f"バッチ {batch_num}: 不明なエラーのため、このバッチの商品のステータスを「エラー」に更新します。")
                    for product in products:
                        update_product_status(product['id'], 'エラー')
                    continue
                finally:
                    if page and not page.is_closed():
                        page.close()
                        logging.info(f"バッチ {batch_num} のページを閉じました。")

        finally:
            if browser and not browser.is_closed():
                if is_debug:
                    logging.info("デバッグモードのため、ブラウザを閉じる前に60秒間待機します...")
                    browser.contexts[0].pages[-1].wait_for_timeout(60000) # 最後のページで待機
                browser.close()
                logging.info("すべてのバッチ処理が完了したため、ブラウザを閉じました。")
