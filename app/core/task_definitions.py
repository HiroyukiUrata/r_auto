from app.tasks import (
    run_check_login_status,
    run_get_post_url,
    run_get_post_url,
    run_posting,
    run_follow_action,
    run_like_action,
    run_save_auth_state,
    run_backup_database,
    run_restore_auth_state,
)
from app.tasks.procure_image_from_raw_url import run_procure_image_from_raw_url
from app.core.database import reset_products_for_caption_regeneration
from app.tasks import create_caption_browser
from app.tasks.procure_from_user_page import run_procure_from_user_page
from app.tasks.bind_product_url_room_url import run_bind_product_url_room_url
from app.tasks.recollect_posted_products import run_recollect_posted_products
from app.tasks.manual_test import run_manual_test

from app.tasks.commit_stale_actions import run_commit_stale_actions
from app.tasks.rakuten_search_procure import search_and_procure_from_rakuten
from app.tasks.notification_analyzer import run_notification_analyzer
from app.tasks.rakuten_api_procure import procure_from_rakuten_api
from app.tasks.delete_room_post import run_delete_room_post
from app.tasks.generate_engagement_comments import run_generate_engagement_comments
from app.tasks.generate_product_caption import generate_product_caption
from app.tasks.scrape_my_comments import run_scrape_my_comments
from app.tasks.generate_replies_to_my_room import run_generate_my_room_replies
from app.tasks.reply_to_comments import reply_to_comments
from app.tasks.new_like_back_task import run_new_like_back
from app.tasks.new_comment_back_task import run_new_comment_back

from app.tasks.dummy_log_task import run_dummy_log_reproducer
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
#     "summary_name": "サマリーログ用の名前", # [Action Summary]ログで使われる名前。ダッシュボード集計用。
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
        "name_ja": "商品調達",
        "function": None, # フローなので関数はなし
        "is_debug": False, # スケジュール専用なのでUIには表示しない
        "default_kwargs": {"count": 3}, # フロー全体のデフォルト件数を設定
        "show_in_schedule": True,
        "description": "設定された方法で商品を調達し、後続タスク（URL取得→投稿文作成）を自動実行します。",
        "flow": [
            # この部分はapi.pyで動的に挿入される
            ("get-post-url", {}),
            ("_create-caption-wrapper", {})
        ],
        "aggregate_results": True, # フロー全体で結果を合算する
        "order": 10,
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
        "description": "ログイン状態を確認後、DBから商品を取得して記事を投稿し、投稿した商品のURLを紐付けます。",
        "order": 50,
        "flow": [
            ("check-login-status", {}),
            ("_internal-post-article", {"count": "flow_count"}),
            ("bind-product-url-room-url", {"count": "flow_count"})
        ],
        "aggregate_results": True, # フロー全体で結果を合算する
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
        "flow": "check-login-status | _internal-like-action",
        "aggregate_results": True, # フロー全体で結果を合算する
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
        "flow": "check-login-status | _internal-follow-action",
        "aggregate_results": True, # フロー全体で結果を合算する
    },
    "json-import-flow": {
        "name_ja": "JSONインポート後フロー",
        "function": None, # フロー自体は関数を持たない
        "is_debug": False,
        "show_in_schedule": False, # UIには表示しない
        "description": "JSONインポート後に、URL取得と投稿文作成を連続実行します。",
        "flow": "get-post-url | create-caption-flow",
        "aggregate_results": True, # フロー全体で結果を合算する
        "order": 9999,
    },
    "url-import-flow": {
        "name_ja": "URLインポート後フロー",
        "function": None,
        "is_debug": False,
        "show_in_schedule": False,
        "description": "URLインポート後に、画像取得、URL取得、投稿文作成を連続実行します。",
        "flow": [
            ("procure-image-from-raw-url", {"urls_text": "flow_urls_text"}),
            ("get-post-url", {}),
            ("create-caption-flow", {})
        ],
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
        "name_ja": "バックアップ",
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
        "function": create_caption_browser.create_caption_prompt,
        "is_debug": False,
        "show_in_schedule": False,
        "description": "【旧方式】ブラウザを操作してGeminiで投稿文を作成します。",
        "order": 40,
    },
    "create-caption-gemini": {
        "name_ja": "投稿文作成 (Gemini API)",
        "function": generate_product_caption,
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
    "_create-caption-wrapper": {
        "name_ja": "（内部処理）投稿文作成ラッパー",
        "function": None, # 何も実行しないプレースホルダー
        "is_debug": False,
        "show_in_schedule": False,
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
        "flow": [ ("check-login-status",{}), ("_internal-notification-analyzer", {"hours_ago": "flow_hours_ago"}), ("commit-stale-actions", {}), ("generate-engagement-comments", {})],
        "aggregate_results": True, # フロー全体で結果を合算する
    },
    "generate-engagement-comments": {
        "name_ja": "エンゲージメントコメント生成",
        "function": run_generate_engagement_comments,
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
        "flow": "check-login-status | _internal-scrape-my-comments",
        "aggregate_results": True, # フロー全体で結果を合算する
    },
    "generate-my-room-replies-step": {
        "name_ja": "自分の投稿への返信コメント生成",
        "function": run_generate_my_room_replies,
        "is_debug": False,
        "show_in_schedule": False,
        "show_count_in_dashboard": False,
        "description": "DBに保存された、自分の投稿への新しいコメントを元に、AIが返信コメントを生成します。",
        "order": 89,
    },
    "generate-my-room-replies": {
        "name_ja": "ホームコメント分析",
        "function": None,
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
            ("generate-my-room-replies-step", {}),
        ],
        "aggregate_results": True, # フロー全体で結果を合算する
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
        "flow": [("check-login-status", {})], # フローの内容はシンプルでOK
        "aggregate_results": True, # フロー全体で結果を合算する
    },
    "delete-room-post": {
        "name_ja": "（内部処理）ROOM投稿削除",
        "function": run_delete_room_post,
        "is_debug": False,
        "show_in_schedule": False,
        "description": "指定されたROOMの投稿を削除または再コレ状態にします。",
        "order": 9999,
    },
    "recollect-product-flow": {
        "name_ja": "（内部処理）商品の再在庫化フロー",
        "function": None,
        "is_debug": False,
        "show_in_schedule": False,
        "description": "ログイン状態を確認後、商品を「再コレ」として再度在庫化します。",
        "summary_name": "再コレ",
        "flow": "check-login-status | delete-room-post",
        "aggregate_results": True, # フロー全体で結果を合算する
        "order": 9999,
    },
    "delete-product-flow": {
        "name_ja": "（内部処理）商品削除フロー",
        "function": None,
        "is_debug": False,
        "show_in_schedule": False,
        "description": "ログイン状態を確認後、商品を削除します。",
        "summary_name": "投稿削除",
        "flow": "check-login-status | delete-room-post",
        "aggregate_results": True, # フロー全体で結果を合算する
        "order": 9999,
    },
    "_internal-reply-to-comment": {
        "function": reply_to_comments,
        "name_ja": "（内部処理）コメントへの返信投稿",
        "description": "「リピーター育成」ページで選択されたコメントに返信を投稿します。",
        "is_debug": False,
        "show_in_schedule": False,
        "summary_name": "マイコメ返信", # ダッシュボード集計用
        "order": 9999,
    },
    "reply-to-comment": {
        "function": None,
        "name_ja": "コメントへの返信投稿",
        "description": "「リピーター育成」ページで選択されたコメントに返信を投稿します。",
        "is_debug": False,
        "show_in_schedule": False,
        "flow": "check-login-status | _internal-reply-to-comment",
        "aggregate_results": True,
    },
    "bind-product-url-room-url": {
        "name_ja": "商品URLとROOM URLの紐付け",
        "function": run_bind_product_url_room_url,
        "is_debug": False,
        "show_in_schedule": False,
        "description": "投稿直後の商品を巡回し、商品URLとROOMの個別URLをDB上で関連付けます。",
        "order": 95,
        "default_kwargs": {"count": 2},
    },
    "recollect-posted-products": {
        "name_ja": "投稿済を再コレ",
        "function": run_recollect_posted_products,
        "is_debug": False,
        "show_in_schedule": True,
        "description": "投稿済商品のROOM投稿を順に開き、「再コレ」状態に戻します。",
        "order": 96,
        "default_kwargs": {"count": 5},
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
    "reset-products-for-regeneration": {
        "name_ja": "（内部処理）投稿文再生成のための商品リセット",
        "function": reset_products_for_caption_regeneration,
        "is_debug": False,
        "show_in_schedule": False,
        "description": "指定された商品の投稿文とステータスをリセットします。",
        "order": 9999,
    },
    "bulk-regenerate-caption-flow": {
        "name_ja": "AI投稿文の再生成フロー",
        "function": None,
        "is_debug": False,
        "show_in_schedule": False,
        "description": "商品をリセットし、投稿文作成フローを呼び出します。",
        "flow": [
            ("reset-products-for-regeneration", {"product_ids": "flow_product_ids"}),
            ("create-caption-flow", {})
        ],
        "order": 9999,
    },
    "procure-image-from-raw-url": {
        "name_ja": "生URLから画像取得",
        "function": run_procure_image_from_raw_url,
        "is_debug": True,
        "description": "URLリストを貼り付けて、商品名と画像URLを一括で取得しDBに登録します。",
        "order": 25,
    },
}

# --- 新しいエンゲージメントタスク定義 ---
TASK_DEFINITIONS.update({
    "new-like-back": {
        "function": run_new_like_back,
        "name_ja": "【新】いいね返し実行",
        "description": "新しい「いいね返し」専門タスクを実行します。",
        "is_debug": False, # config.htmlには表示しない
        "show_in_schedule": False,
        "summary_name": "いいね返し", # フロー集計用の名前
        "order": 101,
    },
    "new-comment-back": {
        "function": run_new_comment_back,
        "name_ja": "【新】コメント返し実行",
        "description": "新しい「コメント返し」専門タスクを実行します。",
        "is_debug": False, # config.htmlには表示しない
        "show_in_schedule": False,
        "summary_name": "コメント返し", # フロー集計用の名前
        "order": 102,
    },
    "new-engage-flow-all": {
        "name_ja": "【新】お返しフロー（いいね＆コメント）",
        "function": None,
        "show_in_schedule": False,
        "is_debug": False, # config.htmlには表示しない
        "description": "「いいね返し」と「コメント返し」を連続で実行します。",
        "flow": "check-login-status | new-like-back | new-comment-back",
        "aggregate_results": False, # 個別集計を行う
        "order": 103,
    },
    "new-engage-flow-like-only": {
        "name_ja": "【新】お返しフロー（いいねのみ）",
        "function": None,
        "show_in_schedule": False,
        "is_debug": False, # config.htmlには表示しない
        "description": "「いいね返し」のみを実行します。",
        "flow": "check-login-status | new-like-back",
        "aggregate_results": False,
        "order": 104,
    },
    "new-engage-flow-comment-only": {
        "name_ja": "【新】お返しフロー（コメントのみ）",
        "function": None,
        "show_in_schedule": False,
        "is_debug": False, # config.htmlには表示しない
        "description": "「コメント返し」のみを実行します。",
        "flow": "check-login-status | new-comment-back",
        "aggregate_results": False,
        "order": 105,
    },
})

# --- デバッグ用の特別なタスク ---
TASK_DEFINITIONS.update({
    "dummy-log-reproducer": {
        "name_ja": "（デバッグ用）ログ再現タスク",
        "function": run_dummy_log_reproducer,
        "is_debug": True,
        "description": "ダッシュボードのエラー件数問題を再現するためのログを生成します。",
        "order": 1, # デバッグタスクの一番上に表示
    },
})
