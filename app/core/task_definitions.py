from app.tasks import (
    run_check_login_status,
    create_caption,
    run_get_post_url,
    run_posting,
    run_follow_action,
    run_like_action,
    run_save_auth_state,
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

# --- タスク定義の基本構造 ---
# "タスクID": {
#     "name_ja": "UIに表示される日本語名",
#     "function": 実行される関数オブジェクト,
#     "is_debug": Trueにするとシステムコンフィグのデバッグ用タスク一覧に表示される,
#     "show_in_schedule": Falseにするとスケジュール設定画面に表示されなくなる（デフォルトはTrue）,
#     "description": "UIに表示されるタスクの説明文",
#     "order": UIでの表示順（小さいほど上）,
#     "default_kwargs": {"引数名": デフォルト値}, # タスク実行時のデフォルト引数
# }

# --- フロー定義の構造 ---
# "フローID": {
#     "name_ja": "フローの日本語名",
#     "function": None または プレースホルダー関数 (例: run_sample_flow_1),
#     "flow": [ ... ], # フローの内容を定義
#     ... (他のキーはタスク定義と同様)
# }

# --- `flow` キーの設定方法 ---
# 1. シンプルな文字列形式（引数なし）
#    "flow": "task-a | task-b | task-c"
#    -> task-a, task-b, task-c を順番に実行する。
#
# 2. 引数を指定できるリスト形式
#    "flow": [
#        ("task-a", {"arg1": "value1"}),  # task-a を arg1="value1" で実行
#        ("task-b", {}),                  # task-b を引数なしで実行
#        ("task-c", {"arg1": 123})        # task-c を arg1=123 で実行
#    ]
#
# --- フローからタスクへの引数引き渡し ---
# フロー定義の "default_kwargs" で設定した値を、フロー内の特定のタスクに引き渡すことができる。
#
# "default_kwargs": {"count": 25},
# "flow": [
#     ("some-task", {"count": "flow_count"})
# ]
# -> "flow_count" という特別なキーワードを指定すると、フローに渡された 'count' 引数（この場合は25）が
#    some-task の 'count' 引数として渡される。
# -> このキーワード "flow_count" は app/web/api.py で解釈される固定値。

TASK_DEFINITIONS = {
    "procure-products-flow": {
        "name_ja": "商品調達フロー",
        "function": None,
        "is_debug": False, # スケジュール専用タスク
        "default_kwargs": {"count": 3}, # フロー全体のデフォルト件数を設定
        "show_in_schedule": True,
        "description": "設定された方法で商品を調達し、後続タスク（URL取得→投稿文作成）を自動実行します。",
        "flow": [
            ("search-and-procure-from-rakuten", {"count": "flow_count"}),
            ("get-post-url", {}),
            ("create-caption-prompt", {})
        ],
        "order": 10,
    },
    "post-article": {
        "name_ja": "記事投稿",
        "function": run_posting,
        "default_kwargs": {"count": 3},
        "is_debug": False,
        "order": 50,
    },
    "run-like-action": {
        "name_ja": "いいね活動",
        "function": run_like_action,
        "is_debug": False,
        "default_kwargs": {"count": 3},
        "description": "設定されたキーワードに基づいて「いいね」アクションを実行します。",
        "order": 60,
    },
    "run-follow-action": {
        "name_ja": "フォロー活動",
        "function": run_follow_action,
        "is_debug": False,
        "default_kwargs": {"count": 3},
        "description": "設定されたキーワードに基づいて「フォロー」アクションを実行します。",
        "order": 70,
    },
    "json-import-flow": {
        "name_ja": "JSONインポート後フロー",
        "function": None, # フロー自体は関数を持たない
        "is_debug": False,
        "show_in_schedule": False, # UIには表示しない
        "description": "JSONインポート後に、URL取得と投稿文作成を連続実行します。",
        "flow": "get-post-url | create-caption-prompt",
        "order": 9999,
    },

    "save-auth-state": {
        "name_ja": "認証状態の保存",
        "function": run_save_auth_state,
        "is_debug": True,
        "description": "VNC経由で手動ログインし、認証情報（Cookieなど）をファイルに保存してログイン状態を維持します。",
        "order": 40,
    },
    "check-login-status": {
        "name_ja": "ログイン状態チェック",
        "function": run_check_login_status,
        "is_debug": True,
        "description": "保存された認証情報を使って、現在ログイン状態が維持されているかを確認します。",
        "order": 30,
    },

    "rakuten-api-procure": {
        "name_ja": "楽天APIから商品を調達",
        "function": procure_from_rakuten_api,
        "is_debug": True,
        "description": "【未実装】楽天APIを利用して商品を調達し、DBに登録します。",
        "order": 80,
    },
    "search-and-procure-from-rakuten": {
        "name_ja": "楽天市場から商品を検索・調達",
        "function": search_and_procure_from_rakuten,
        "is_debug": True,
        "description": "キーワードを元に楽天市場を検索して商品を調達し、DBに登録します。",
        "order": 90,
    },
    "get-post-url": {
        "name_ja": "投稿URL取得",
        "function": run_get_post_url,
        "is_debug": True,
        "description": "ステータスが「生情報取得」の商品について、ROOMの投稿用URLを取得します。",
        "order": 10,
    },
    "create-caption-prompt": {
        "name_ja": "投稿文作成 (Gemini)",
        "function": create_caption.create_caption_prompt,
        "is_debug": True,
        "description": "ステータスが「URL取得済」の商品について、Geminiで投稿文を作成します。",
        "order": 20,
    },

}