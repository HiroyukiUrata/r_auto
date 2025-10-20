# Hugging Face + Pythonアプリ組み込みロードマップ

このドキュメントは、Google Geminiの代わりにHugging Faceでホストされているオープンソースの大規模言語モデル（LLM）を利用して、投稿文を生成するための技術的なロードマップです。

## STEP 1: Hugging Face アカウント作成

1.  **サインアップ**: [Hugging Faceのサイト](https://huggingface.co/join)でアカウントを作成します。
2.  **メール認証**: 登録したメールアドレスに届く認証リンクをクリックして、アカウントを有効化します。
3.  **プラン**: 無料プランで問題ありません。無料でも十分なリクエスト数が利用可能です。

## STEP 2: APIトークンの作成

1.  **アクセストークンページへ移動**: ログイン後、右上のプロフィールアイコン → `Settings` → `Access Tokens` を選択します。
2.  **新規トークン作成**: `New Token` ボタンをクリックし、トークンに名前を付けます。`Role`は `read` のままでOKです。
3.  **トークンをコピー**: 生成されたAPIトークンをコピーして安全な場所に控えておきます。
4.  **環境変数に設定**: このトークンをアプリケーションの環境変数として設定します。`.env`ファイルに以下のように追記します。

    ```
    HF_TOKEN="hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    ```

## STEP 3: Python環境の整備

1.  **Pythonバージョン**: Python 3.10以上が推奨されます。
2.  **ライブラリのインストール**: 必要なライブラリをインストールします。`app/requirements.txt`に`huggingface-hub`を追加し、コンテナを再ビルドするのがおすすめです。

    ```
    pip install huggingface-hub pillow requests
    ```

## STEP 4: モデルの選定

-   **投稿文生成モデル**: `meta-llama/Llama-2-7b-chat-hf` や、より軽量な日本語モデルなどが候補になります。
-   **画像→テキスト変換（任意）**: `Salesforce/blip-image-captioning-base` などのモデルを利用すれば、画像の内容を説明するテキストを生成できます。

## STEP 5: Pythonアプリへの組み込み（サンプルコード）

`create_caption.py`などのタスクファイル内で、以下のようなロジックを実装します。

```python
from huggingface_hub import InferenceClient
import json
import os

# .envファイルからトークンを読み込む
hf_token = os.getenv("HF_TOKEN")

# Hugging Face クライアントを初期化
client = InferenceClient(
    model="meta-llama/Llama-2-7b-chat-hf", # 使用するモデルのリポジトリID
    token=hf_token
)

# ... (商品データをDBから取得する処理) ...

for item in products_data:
    # 各商品に合わせたプロンプトを生成
    prompt = f"""
    あなたはプロの楽天ROOMユーザーです。
    以下の商品情報（JSON形式）を元に、魅力的でフレンドリーな投稿文を200文字程度で作成してください。
    投稿文には必ずハッシュタグ「#なんなんなあに」を含めてください。

    商品情報:
    {item}
    """
    # モデルを呼び出してテキストを生成
    response_text = client.text_generation(prompt, max_new_tokens=250) # max_new_tokensで最大文字数を調整
    
    # 生成されたテキストをDBに保存
    item["ai_caption"] = response_text.strip()
    # ... (DB更新処理) ...

```

## STEP 6: 運用とリクエスト管理

-   **バッチ処理**: 1回のAPI呼び出しで複数の商品を処理するのではなく、商品1件ごとにAPIを呼び出す形になります。
-   **リクエスト制限**: 無料プランのリクエスト上限を超えないように、一度に処理する件数や実行頻度をスケジュールで調整する必要があります。

## STEP 7: 公開・配布

-   このアプリケーションはDockerコンテナ内で完結しているため、特別なWeb公開は不要です。
-   環境変数 `.env` に `HF_TOKEN` を設定し、コンテナを再起動するだけで、新しいAIモデルを利用した投稿文生成が可能になります。