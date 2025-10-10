import logging
import json
import os
import re
from playwright.sync_api import sync_playwright
from app.core.database import get_products_for_caption_creation, update_ai_caption, update_product_status

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

def create_caption_prompt():
    """
    ステータスが「URL取得済」の商品を1件取得し、プロンプトを生成してGeminiのページで実行する。
    """
    logging.info("投稿文作成用プロンプトの生成タスクを開始します。")

    # --- デバッグフラグ ---
    # Trueにすると、ブラウザが表示されます(headless=False)。
    # 通常実行時はFalseにしてください。
    is_debug = True

    products = get_products_for_caption_creation()
    if not products:
        logging.info("投稿文作成対象の商品はありません。")
        return

    if not os.path.exists(PROMPT_FILE):
        logging.error(f"プロンプトファイルが見つかりません: {PROMPT_FILE}")
        return

    if not os.path.exists(PROFILE_DIR):
        logging.error(f"認証プロファイルが見つかりません: {PROFILE_DIR}")
        return

    logging.info(f"{len(products)}件の商品を対象にプロンプトを生成します。")

    # 複数の商品をリストとして整形
    items_data = [
        {
            "page_url": p["url"], # page_urlをキーとして使用
            "item_description": p["name"],
            "image_url": p["image_url"],
            "ai_caption": ""
        } for p in products
    ]

    browser = None # browser変数を初期化
    try:
        # プロンプトファイルを読み込む
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            prompt_template = f.read()
        
        # PlaywrightでGeminiのページを開く
        with sync_playwright() as p:
            json_string = json.dumps(items_data, indent=2, ensure_ascii=False)
            full_prompt = f"{prompt_template}\n\n以下のJSON配列の各要素について、`ai_caption`を生成してください。`page_url`をキーとして、元のJSON配列の形式を維持して返してください。\n\n```json\n{json_string}\n```"

            # デバッグ用に組み立てられたプロンプトをログに出力
            logging.info(f"--- 生成されたプロンプト ---\n{full_prompt}\n--------------------------")

            # is_debug=True (ヘッドフル) の場合にディスプレイサーバーを指定する。is_debugがFalseの場合はheadlessで起動。
            browser = p.chromium.launch(headless=not is_debug, env={"DISPLAY": ":0"} if is_debug else {})
            # 日本語ロケールとクリップボードのアクセス許可を指定してコンテキストを作成
            context = browser.new_context(
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
                permissions=["clipboard-read", "clipboard-write"]
            )
            page = context.new_page()

            logging.info("Geminiのページを開き、プロンプトを自動入力します。")
            # networkidleはタイムアウトしやすいため、domcontentloadedに変更し、タイムアウトを60秒に延長。
            # ページの準備完了は、後続の要素待機処理で担保する。
            page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=60000)

            # プロンプト入力欄に自動で貼り付け、送信する
            # UIの変更に強くするため、複数のセレクタを試す
            # 1. 日本語のaria-label (最も確実)
            # 2. プレースホルダー (言語設定が変わっても追従しやすい)
            # 3. role=textbox (最終手段)
            prompt_input = page.get_by_label("ここにプロンプトを入力してください").or_(page.get_by_placeholder("Gemini に相談")).or_(page.get_by_role("textbox"))
            
            # 要素が表示され、編集可能になるまで待機する
            logging.info("プロンプト入力欄が表示されるのを待っています...")
            prompt_input.wait_for(state="visible", timeout=30000)
            prompt_input.click() # 入力前にクリックしてフォーカスを当てる

            # Playwrightのevaluateを使い、ブラウザのクリップボードAPIを直接叩いてプロンプトをコピーする
            logging.info("ブラウザのクリップボードにプロンプトをコピーします...")
            page.evaluate("text => navigator.clipboard.writeText(text)", full_prompt)
            paste_shortcut = "Control+V" # Dockerコンテナ内(Linux)なのでControl+Vで固定
            prompt_input.press(paste_shortcut)

            prompt_input.press("Enter")
            logging.info("プロンプトを送信しました。")
            
            # Geminiの応答が完了するのを待つ。「生成を停止」ボタンが非表示になるのを待つのが確実。
            logging.info("Geminiの応答を待っています...「生成を停止」ボタンが非表示になるのを待ちます。")
            try:
                page.get_by_label("生成を停止").wait_for(state="hidden", timeout=120000) # 2分待機
                logging.info("「生成を停止」ボタンが非表示になりました。応答の表示を待機します。")
            except TimeoutError:
                logging.error("Geminiの応答待機中にタイムアウトしました。「生成を停止」ボタンが2分以内に非表示になりませんでした。")
                return # 応答が完了しない場合はここで処理を終了

            # 応答が完全に表示されるのを待つ (JSONの末尾文字 `]` が表示されるかで判断)
            logging.info("応答JSONが完全に表示されるのを待っています...")
            try:
                # 商品数に応じてタイムアウトを動的に計算 (基本60秒 + 1件あたり15秒)
                dynamic_timeout = (60 + len(products) * 15) * 1000
                logging.info(f"商品数({len(products)}件)に応じた動的タイムアウトを設定します: {dynamic_timeout / 1000}秒")
                
                # ページ内のJS関数がtrueを返すまで待機する
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
                # タイムアウトしても処理を中断せず、コピー処理に進む
            
            # 最新の応答ブロック内の「コードをコピー」ボタンが表示されるまで待機
            # これにより、応答ブロック自体も表示されていることを確認
            logging.info("最新の応答ブロック内の「コードをコピー」ボタンが表示されるのを待ちます。")
            generated_json_str = "" # generated_json_strを初期化
            try:
                # page.locator().last を使用して、最も新しい応答ブロックをターゲットにする
                copy_button_locator = page.locator(".response-container-content").last.get_by_label("コードをコピー")
                copy_button_locator.wait_for(state="visible", timeout=30000) # 30秒待機
                logging.info("「コードをコピー」ボタンが表示されました。クリックします。")
                copy_button_locator.click()
            except TimeoutError:
                logging.error("Geminiの応答から「コードをコピー」ボタンが見つかりませんでした。応答が正しく生成されていない可能性があります。")
                return # コピーボタンが見つからない場合はここで処理を終了

            # ブラウザのクリップボードからJSON文字列を取得
            logging.info("ブラウザのクリップボードから応答を読み取ります。")
            try:
                generated_json_str = page.evaluate("() => navigator.clipboard.readText()")
                logging.info(f"クリップボードから取得した文字列(整形前): {generated_json_str[:200]}...") # デバッグ用に最初の200文字をログ出力
                
                # JSON文字列を整形
                cleaned_str = clean_raw_json(generated_json_str)
                fixed_indent_str = fix_indentation(cleaned_str)
                
                generated_items = json.loads(fixed_indent_str)
                # パース後のデータから不要な文字を削除
                fix_ai_caption(generated_items)
            except json.JSONDecodeError as e:
                logging.error(f"クリップボードの内容が有効なJSONではありませんでした: {e}")
                logging.error(f"取得された内容: {generated_json_str}") # 不正な内容もログ出力
                return # JSONパースエラーの場合はここで処理を終了
            except Exception as e:
                logging.error(f"クリップボードからのJSON取得またはパース中に予期せぬエラーが発生しました: {e}")
                return # その他のエラーの場合はここで処理を終了

            # page_urlをキーにして、生成されたキャプションを元のproductにマッピング
            url_to_caption = {item['page_url']: item.get('ai_caption') for item in generated_items}

            updated_count = 0
            for product in products:
                caption = url_to_caption.get(product['url'])
                if caption:
                    update_ai_caption(product['id'], caption)
                    updated_count += 1
            
            logging.info(f"{updated_count}件の投稿文をデータベースに保存しました。") # 処理完了ログ

    except Exception as e:
        logging.error(f"プロンプトの生成またはコピー中にエラーが発生しました: {e}")
    finally:
        if browser and not browser.is_closed(): # browserが正常に起動していた場合のみ閉じる
            if is_debug:
                logging.info("デバッグモードのため、ブラウザを閉じる前に60秒間待機します...")
                page.wait_for_timeout(60000) # 60秒待機
            browser.close() # 待機後、ブラウザを閉じる

    logging.info("投稿文作成用プロンプトの生成タスクを終了します。")
