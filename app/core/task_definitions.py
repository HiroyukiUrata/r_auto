from app.tasks import (
    check_login_status,
    get_post_url,
    post_article,
    procure_products,
    run_follow_action,
    run_like_action,
    save_auth_state,
)

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
    "procure-products": {
        "name_ja": "商品調達",
        "function": procure_products,
        "is_debug": False,
        "order": 10,
    },
    "get-post-url": {
        "name_ja": "投稿URL取得",
        "function": get_post_url,
        "is_debug": False,
        "show_in_schedule": False, # スケジュール画面には表示しない
        "order": 15,
    },
    "post-article": {
        "name_ja": "記事投稿",
        "function": post_article,
        "is_debug": False,
        "order": 20,
    },
    "run-like-action": {
        "name_ja": "エンゲージメント（いいね）",
        "function": run_like_action,
        "is_debug": False,
        "description": "設定されたキーワードに基づいて「いいね」アクションを実行します。",
        "order": 30,
    },
    "run-follow-action": {
        "name_ja": "エンゲージメント（フォロー）",
        "function": run_follow_action,
        "is_debug": False,
        "description": "設定されたキーワードに基づいて「フォロー」アクションを実行します。",
        "order": 31, # いいねの次に表示
    },
    "save-auth-state": {
        "name_ja": "認証状態の保存",
        "function": save_auth_state,
        "is_debug": True,
        "description": "VNC経由で手動ログインし、認証情報（Cookieなど）をファイルに保存してログイン状態を維持します。",
        "order": 110,
    },
    "check-login-status": {
        "name_ja": "ログイン状態チェック",
        "function": check_login_status,
        "is_debug": True,
        "description": "保存された認証情報を使って、現在ログイン状態が維持されているかを確認します。",
        "order": 100,
    },
}