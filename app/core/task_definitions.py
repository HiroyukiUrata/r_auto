from app.tasks import (
    check_login_status,
    procure,
    create_caption,
    get_post_url,
    post_article,
    run_follow_action,
    run_like_action,
    save_auth_state,
)
from app.tasks.rakuten_search_procure import search_and_procure_from_rakuten
from app.tasks.rakuten_api_procure import procure_from_rakuten_api

"""
システム内の全タスクの定義を一元管理する。
キー: プログラム内部で使われる一意の識別子（タグ）
値:
  name_ja: UIに表示される日本語名
  function: 実行されるタスク関数オブジェクト
  is_debug: デバッグ用タスクかどうかを示すフラグ
  description: UIに表示されるタスクの説明文
  order: UIでの表示順
"""
TASK_DEFINITIONS = {
    "procure-products-flow": {
        "name_ja": "商品調達フロー",
#        "function": procure.run_procurement_flow,
        "function": procure.search_and_procure_from_rakuten,
        "is_debug": False, # スケジュール専用タスク
        "show_in_schedule": True,
        "description": "設定された方法（APIまたは検索）で商品を調達し、後続タスクを自動実行します。",
        "on_success": "get-post-url",
        "order": 10,
    },
    "rakuten-api-procure": {
        "name_ja": "楽天APIから商品を調達",
        "function": procure_from_rakuten_api,
        "is_debug": True,
        "description": "【未実装】楽天APIを利用して商品を調達し、後続タスク（URL取得→投稿文作成）を実行します。",
        "on_success": "get-post-url",
        "order": 80,
    },
    "search-and-procure-from-rakuten": {
        "name_ja": "楽天市場から商品を検索・調達",
        "function": search_and_procure_from_rakuten,
        "is_debug": True,
        "description": "DBのキーワードを元に楽天市場を検索して商品を調達し、後続タスク（URL取得→投稿文作成）を実行します。",
        "on_success": "get-post-url",
        "order": 90,
    },
    "get-post-url": {
        "name_ja": "投稿URL取得",
        "function": get_post_url,
        "is_debug": True,
        "on_success": "create-caption-prompt",
        "order": 10,
    },
    "post-article": {
        "name_ja": "記事投稿",
        "function": post_article,
        "is_debug": False,
        "order": 50,
    },
    "run-like-action": {
        "name_ja": "エンゲージメント（いいね）",
        "function": run_like_action,
        "is_debug": False,
        "description": "設定されたキーワードに基づいて「いいね」アクションを実行します。",
        "order": 60,
    },
    "run-follow-action": {
        "name_ja": "エンゲージメント（フォロー）",
        "function": run_follow_action,
        "is_debug": False,
        "description": "設定されたキーワードに基づいて「フォロー」アクションを実行します。",
        "order": 70,
    },
    "save-auth-state": {
        "name_ja": "認証状態の保存",
        "function": save_auth_state,
        "is_debug": True,
        "description": "VNC経由で手動ログインし、認証情報（Cookieなど）をファイルに保存してログイン状態を維持します。",
        "order": 40,
    },
    "check-login-status": {
        "name_ja": "ログイン状態チェック",
        "function": check_login_status,
        "is_debug": True,
        "description": "保存された認証情報を使って、現在ログイン状態が維持されているかを確認します。",
        "order": 30,
    },
    "create-caption-prompt": {
        "name_ja": "投稿文作成 (Gemini)",
        "function": create_caption.create_caption_prompt,
        "is_debug": True,
        "description": "ステータスが「URL取得済」の商品について、Geminiで投稿文を作成します。",
        "order": 20,
    },
}