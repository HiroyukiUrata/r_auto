from app.tasks import (
    run_check_login_status,
    create_caption,
    run_get_post_url,
    run_posting,
    run_follow_action,
    run_like_action,
    run_save_auth_state,
    run_backup_database,
    run_restore_auth_state,
)
from app.tasks.procure_from_user_page import run_procure_from_user_page
from app.tasks.manual_test import run_manual_test

from app.tasks.commit_stale_actions import run_commit_stale_actions
from app.tasks.rakuten_search_procure import search_and_procure_from_rakuten
from app.tasks.notification_analyzer import run_notification_analyzer
from app.tasks.rakuten_api_procure import procure_from_rakuten_api
from app.tasks.create_ai_comment import run_create_ai_comment
from app.tasks.create_caption_api import run_create_caption_api
from app.tasks.scrape_my_comments import run_scrape_my_comments
from app.tasks.generate_reply_comments import run_generate_reply_comments
from app.tasks.reply_to_comments import reply_to_comments
from app.tasks.engage_user import run_engage_user

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
        "function": None, # フローなので関数はなし
        "is_debug": False, # スケジュール専用なのでUIには表示しない
        "default_kwargs": {"count": 3}, # フロー全体のデフォルト件数を設定
        "show_in_schedule": True,
        "description": "設定された方法で商品を調達し、後続タスク（URL取得→投稿文作成）を自動実行します。",
        "flow": [
            ("_procure-wrapper", {"count": "flow_count"}), # 動的解決用のラッパーを呼び出す
            ("get-post-url", {}),
            ("create-caption-flow", {})
        ],
        "order": 10,
    },
    "procure-products-single": {
        "name_ja": "商品調達",
        "function": None, # ラッパーを呼び出す
        "is_debug": True, # UIに表示する
        "description": "設定画面で選択された方法（ブラウザ or API）で商品を調達します。",
        "default_kwargs": {"count": 5},
        "flow": [("_procure-wrapper", {"count": "flow_count"})],
        "order": 15,
    },
    "_procure-wrapper": {
        "name_ja": "（内部処理）商品調達ラッパー",
        "function": None, # 何も実行しないプレースホルダー
        "is_debug": False,
        "show_in_schedule": False,
    },
    "_internal-post-article": {
        "name_ja": "（内部処理）記事投稿実行",
        "function": run_posting,
        "default_kwargs": {"count": 3},
        "is_debug": False,
        "show_in_schedule": False, # UIには表示しない
        "description": "DBから商品を取得して記事を投稿します。",
        "order": 9999, # 表示されない
    },
    "post-article": { # UIに表示されるフロー
        "name_ja": "記事投稿",
        "function": None, # フローなので直接の関数はなし
        "is_debug": False,
        "default_kwargs": {"count": 3}, # フロー全体に渡す引数
        "description": "ログイン状態を確認後、DBから商品を取得して記事を投稿します。",
        "order": 50,
        "flow": "check-login-status | _internal-post-article"
    },
    "_internal-like-action": {
        "name_ja": "（内部処理）いいね実行",
        "function": run_like_action,
        "is_debug": False,
        "show_in_schedule": False, # UIには表示しない
        "default_kwargs": {"count": 15, "max_duration_seconds": 1800},
        "description": "設定されたキーワードに基づいて「いいね」アクションを実行します。",
        "order": 9999, # 表示されない
    },
    "run-like-action": { # UIに表示されるフロー
        "name_ja": "いいね活動",
        "function": None, # フローなので直接の関数はなし
        "is_debug": False,
        "default_kwargs": {"count": 15, "max_duration_seconds": 1800}, # フロー全体に渡す引数
        "description": "ログイン状態を確認後、設定されたキーワードに基づいて「いいね」アクションを実行します。",
        "order": 60,
        "flow": "check-login-status | _internal-like-action"
    },
    "_internal-follow-action": {
        "name_ja": "（内部処理）フォロー実行",
        "function": run_follow_action,
        "is_debug": False,
        "show_in_schedule": False, # UIには表示しない
        "default_kwargs": {"count": 10},
        "description": "設定されたキーワードに基づいて「フォロー」アクションを実行します。",
        "order": 9999, # 表示されない
    },
    "run-follow-action": { # UIに表示されるフロー
        "name_ja": "フォロー活動",
        "function": None, # フローなので直接の関数はなし
        "is_debug": False,
        "default_kwargs": {"count": 3}, # フロー全体に渡す引数
        "description": "ログイン状態を確認後、設定されたキーワードに基づいて「フォロー」アクションを実行します。",
        "order": 70,
        "flow": "check-login-status | _internal-follow-action"
    },
    "json-import-flow": {
        "name_ja": "JSONインポート後フロー",
        "function": None, # フロー自体は関数を持たない
        "is_debug": False,
        "show_in_schedule": False, # UIには表示しない
        "description": "JSONインポート後に、URL取得と投稿文作成を連続実行します。",
        "flow": "get-post-url | create-caption-flow",
        "order": 9999,
    },

    "save-auth-state": {
        "name_ja": "認証状態の保存",
        "function": run_save_auth_state,
        "is_debug": True,
        "description": "VNC経由で手動ログインし、認証情報を永続化・バックアップします。他のブラウザタスクが実行中でないことを確認してください。",
        "order": 40,
    },
    "restore-auth-state": {
        "name_ja": "認証プロファイルの復元",
        "function": run_restore_auth_state,
        "is_debug": True,
        "description": "バックアップから認証プロファイルを復元します。ログインが切れた際に使用します。他のブラウザタスクが実行中でないことを確認してください。",
        "order": 41,
    },
    "procure-from-user-page": {
        "name_ja": "ユーザーページから商品を調達",
        "function": run_procure_from_user_page,
        "is_debug": False,
        "show_in_schedule": False, # フローからのみ呼び出す
        "description": "指定されたユーザーページを巡回して商品を調達します。",
        "order": 999,
    },
    "check-login-status": {
        "name_ja": "ログイン状態チェック",
        "function": run_check_login_status,
        "is_debug": True,
        "description": "保存された認証情報を使って、現在ログイン状態が維持されているかを確認します。",
        "order": 42,
    },
    "backup-database": {
        "name_ja": "データベースのバックアップ",
        "function": run_backup_database,
        "is_debug": True,
        "show_in_schedule": True,
        "default_kwargs": {}, # 件数引数を持たないことを明示
        "show_count_in_schedule": False, # 件数入力は不要
        "description": "データベースファイル（商品情報など）のバックアップを作成します。",
        "order": 45,
    },

    "rakuten-api-procure": {
        "name_ja": "楽天APIから商品を調達",
        "function": procure_from_rakuten_api,
        "is_debug": False, # ラッパーフローに統合されたため非表示
        "show_in_schedule": False,
        "description": "【ダミー】楽天APIを利用して商品を調達し、DBに登録します。",
        "order": 10,
    },
    "search-and-procure-from-rakuten": {
        "name_ja": "楽天市場から商品を検索・調達",
        "function": search_and_procure_from_rakuten,
        "is_debug": False, # ラッパーフローに統合されたため非表示
        "show_in_schedule": False,
        "description": "キーワードを元に楽天市場を検索して商品を調達し、DBに登録します。",
        "order": 20,
    },
    "get-post-url": {
        "name_ja": "投稿URL取得",
        "function": run_get_post_url,
        "is_debug": True,
        "description": "ステータスが「生情報取得」の商品について、ROOMの投稿用URLを取得します。",
        "order": 30,
    },
    "create-caption-browser": {
        "name_ja": "投稿文作成 (ブラウザ)",
        "function": create_caption.create_caption_prompt,
        "is_debug": False,
        "show_in_schedule": False,
        "description": "【旧方式】ブラウザを操作してGeminiで投稿文を作成します。",
        "order": 40,
    },
    "create-caption-gemini": {
        "name_ja": "投稿文作成 (Gemini API)",
        "function": run_create_caption_api,
        "is_debug": False,
        "show_in_schedule": False,
        "description": "【新方式】Gemini APIを直接呼び出して投稿文を作成します。",
        "order": 41,
    },
    "create-caption-flow": {
        "name_ja": "投稿文作成",
        "function": None,
        "is_debug": True,
        "description": "設定画面で選択された方法（ブラウザ or API）で投稿文を作成します。",
        "order": 35,
    },
    "_internal-notification-analyzer": {
        "name_ja": "（内部処理）通知分析実行",
        "function": run_notification_analyzer,
        "is_debug": False,
        "default_kwargs": {"hours_ago": 12},
        "show_in_schedule": False,
        "description": "楽天ROOMのお知らせページからユーザーのエンゲージメント情報を分析し、DBに保存します。",
        "order": 9999,
    },
    "notification-analyzer": {
        "name_ja": "お知らせ解析",
        "function": None, # フローなので直接の関数はなし
        "default_kwargs": {"hours_ago": 12, "_": None}, # 件数入力が不要であることを示すダミー引数を追加
        "is_debug": False, # 即時実行にも表示する
        "show_count_in_dashboard": False, # ダッシュボードの「次の予定」に件数を表示しない
        "show_in_schedule": True,
        "show_count_in_schedule": False, # 件数入力は不要
        "description": "通知を分析しコメントを生成します。スケジュール実行時は12時間、即時実行時は30分(hours_ago=0.5)が推奨です。",
        "order": 80,
        "flow": [ ("check-login-status",{}), ("_internal-notification-analyzer", {"hours_ago": "flow_hours_ago"}), ("commit-stale-actions", {}), ("create-ai-comment", {})]
    },
    "create-ai-comment": {
        "name_ja": "AIコメント作成",
        "function": run_create_ai_comment,
        "is_debug": False,
        "show_in_schedule": False,
        "description": "分析結果を元に、ユーザーへの返信コメントをAIで生成します。",
        "order": 85,
    },
    "commit-stale-actions": {
        "name_ja": "古いアクションの自動コミット",
        "function": run_commit_stale_actions,
        "is_debug": False,
        "show_in_schedule": False,
        "description": "24時間以上放置されている未処理のアクションを自動的にスキップ扱いとしてコミットします。",
        "order": 90,
    },
    "engage-user": {
        "name_ja": "（内部処理）ユーザーエンゲージメント実行",
        "function": run_engage_user,
        "is_debug": False,
        "show_in_schedule": False, # APIからのみ呼び出す
        "description": "（内部処理用）指定された複数のユーザーにいいねバックとコメント投稿を行います。",
        "order": 9999,
    },
    "_internal-scrape-my-comments": {
        "name_ja": "（内部処理）自分の投稿からコメント収集",
        "function": run_scrape_my_comments,
        "is_debug": False,
        "show_in_schedule": False,
        "description": "自分のROOMに移動し、ピン留めされた投稿からコメントを収集してDBに保存します。",
        "order": 9999,
    },
    "scrape-my-comments": {
        "name_ja": "自分の投稿からコメント収集",
        "function": None, # フローなので直接の関数はなし
        "is_debug": False, # 通常タスクとして表示
        "show_in_schedule": False,
        "show_count_in_dashboard": False,
        "description": "ログイン状態を確認後、自分のROOMに移動し、ピン留めされた投稿からコメントを収集してDBに保存します。返信コメント生成の元データになります。",
        "order": 88,
        "flow": "check-login-status | _internal-scrape-my-comments"
    },
    "generate-reply-comments": {
        "name_ja": "自分の投稿への返信コメント生成",
        "function": run_generate_reply_comments,
        "is_debug": False,
        "show_in_schedule": False,
        "show_count_in_dashboard": False,
        "description": "DBに保存された、自分の投稿への新しいコメントを元に、AIが返信コメントを生成します。",
        "order": 89,
    },
    "generate-my-room-replies": {
        "name_ja": "自分の投稿への返信生成フロー",
        "function": None,
        "default_kwargs": {"dummy_arg_to_hide_count": None}, # UIに件数入力が不要であることを明示するためのダミー引数
        "default_kwargs": {"_": None}, # UIに件数入力が不要であることを明示するためのダミー引数
        "is_debug": False,
        "show_in_schedule": True,
        "show_count_in_dashboard": False,
        "show_count_in_schedule": False, # スケジュール設定画面で件数入力を非表示にする
        "description": "自分の投稿への新しいコメントを収集し、それに対する返信コメントをAIで生成します。",
        "order": 90,
        "flow": [
            ("check-login-status", {}),
            ("_internal-scrape-my-comments", {}),
            ("generate-reply-comments", {})
        ]
    },
    "dummy-flow-no-count": {
        "name_ja": "（ダミー）件数表示なしフロー",
        "function": None,
        "default_kwargs": {"_": None}, # countキーを含まないダミー引数を定義することで、UIに件数入力が不要と伝える
        "is_debug": False, # UIで確認できるように表示
        "show_in_schedule": False,
        "show_count_in_dashboard": False,
        "show_count_in_schedule": False,
        "description": "件数入力ボックスが表示されないことを確認するためのダミーフローです。",
        "order": 91,
        "flow": [("check-login-status", {})] # フローの内容はシンプルでOK
    },
    "reply-to-comment": {
        "function": reply_to_comments,
        "name_ja": "コメントへの返信投稿",
        "description": "「リピーター育成」ページで選択されたコメントに返信を投稿します。",
        "is_debug": True,
        "show_in_schedule": False,
    },
        "manual-test": {
        "name_ja": "手動テスト",
        "function": run_manual_test,
        "is_debug": True,
        "show_in_schedule": False,
        "description": "テストスクリプトの実行に必要です。",
        "order": 100,
        "default_kwargs": {"script": "test_scripts/example.py"},
    },
}