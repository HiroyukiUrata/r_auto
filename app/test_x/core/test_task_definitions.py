from app.test_x.tasks.sample_task_a import run_sample_task_a
from app.test_x.tasks.sample_task_b import run_sample_task_b
from app.test_x.tasks.sample_task_c import run_sample_task_c
from app.test_x.tasks.flow_runner import run_sample_flow_1
from app.test_x.tasks.sample_error_log_task import run_sample_error_log_task # 抜けていたimportを追加
from app.test_x.tasks.create_caption_test import run_create_caption_test
from app.test_x.tasks.rakuten_search_procure_test import run_rakuten_search_procure_test
from app.test_x.tasks.get_post_url_test import run_get_post_url_test
from app.test_x.tasks.posting_test import run_posting_test
from app.test_x.tasks.follow_test import run_follow_test
from app.test_x.tasks.like_test import run_like_test
from app.test_x.tasks.rakuten_api_procure_test import run_rakuten_api_procure_test
from app.test_x.tasks.check_login_status_test import run_check_login_status_test
from app.test_x.tasks.save_auth_state_test import run_save_auth_state_test

"""
検証用のタスク定義。
この内容はメインのTASK_DEFINITIONSにマージされる。
"""
TEST_TASK_DEFINITIONS = {
    "test-sample-task-a": {
        "name_ja": "【テスト】サンプルタスクA",
        "function": run_sample_task_a,
        "is_debug": True,
        "description": "「タスクAを実行しました。」とログに出力します。",
        "order": 300,
    },
    "test-sample-task-b": {
        "name_ja": "【テスト】サンプルタスクB",
        "function": run_sample_task_b,
        "is_debug": True,
        "description": "「タスクBを実行しました。」とログに出力します。",
        "order": 310,
    },
    "test-sample-task-c": {
        "name_ja": "【テスト】サンプルタスクC",
        "function": run_sample_task_c,
        "is_debug": True,
        "description": "「タスクCを実行しました。」とログに出力します。",
        "order": 320,
    },
    "test-sample-task-flow-1": {
        "name_ja": "【テスト】サンプルタスクフロー",
        "function": run_sample_flow_1,
        "is_debug": True,
        "description": "タスクA -> B -> C を順番に実行します。",
        "flow": "test-rakuten-search-procure | test-get-post-url | test-create-caption",
        "order": 999,
    },
    "test-sample-error-log": {
        "name_ja": "【テスト】サンプルエラータスク",
        "function": run_sample_error_log_task,
        "is_debug": True,
        "description": "意図的にエラーを発生させます。",
        "order": 305,
    },
    "test-sample-task-flow-2": {
        "name_ja": "【テスト】サンプルタスクフロー（エラーケース）",
        "function": run_sample_flow_1,
        "is_debug": True,
        "description": "タスクA -> エラー -> C を順番に実行します。",
        "flow": "test-sample-task-a | test-sample-error-log | test-sample-task-c",
        "order": 1000,
    },
    "test-create-caption": {
        "name_ja": "【テスト】投稿文作成 (Gemini)",
        "function": run_create_caption_test,
        "is_debug": True,
        "description": "リファクタリング版の投稿文作成タスクを検証します。",
        "order": 25,
    },
    "test-rakuten-search-procure": {
        "name_ja": "【テスト】楽天市場から商品を検索・調達",
        "function": run_rakuten_search_procure_test,
        "is_debug": True,
        "description": "リファクタリング版の楽天検索・調達タスクを検証します。",
        "default_kwargs": {"count": 1},
        "order": 95,
    },
    "test-get-post-url": {
        "name_ja": "【テスト】投稿URL取得",
        "function": run_get_post_url_test,
        "is_debug": True,
        "description": "リファクタリング版の投稿URL取得タスクを検証します。",
        "order": 15,
    },
    "test-procurement-flow": {
        "name_ja": "【テスト】商品調達フロー",
        "function": run_sample_flow_1,
        "is_debug": True,
        "default_kwargs": {"count": 25}, # フロー全体のデフォルト件数を設定
        "description": "【新しい仕組み】検索・調達→URL取得→投稿文作成を連続実行します。",
        "flow": [
            ("test-rakuten-search-procure", {"count": "flow_count"}), # "flow_count" はフローのcount引数を参照する特殊な値
            ("test-get-post-url", {}),
            ("test-create-caption", {})
        ],
        "order": 6,
    },
    "test-post-article": {
        "name_ja": "【テスト】記事投稿",
        "function": run_posting_test,
        "is_debug": True,
        "description": "リファクタリング版の記事投稿タスクを検証します。",
        "default_kwargs": {"count": 3},
        "order": 55,
    },
    "test-post-then-procure-flow": {
        "name_ja": "【テスト】投稿→調達フロー",
        "function": run_sample_flow_1,
        "is_debug": True,
        "description": "3件投稿した後に、5件商品を調達します。",
        "flow": [
            ("test-post-article", {"count": 3}),
            ("test-rakuten-search-procure", {"count": 5})
        ],
        "order": 7,
    },
    "test-follow-action": {
        "name_ja": "【テスト】フォロー",
        "function": run_follow_test,
        "is_debug": True,
        "description": "リファクタリング版のフォロータスクを検証します。",
        "default_kwargs": {"count": 10},
        "order": 75,
    },
    "test-like-action": {
        "name_ja": "【テスト】いいね",
        "function": run_like_test,
        "is_debug": True,
        "description": "リファクタリング版のいいねタスクを検証します。",
        "default_kwargs": {"count": 10},
        "order": 65,
    },
    "test-rakuten-api-procure": {
        "name_ja": "【テスト】楽天APIから商品を調達",
        "function": run_rakuten_api_procure_test,
        "is_debug": True,
        "description": "【未実装】楽天APIを利用して商品を調達するタスクのプレースホルダーです。",
        "default_kwargs": {"count": 5},
        "order": 85,
    },
    "test-check-login-status": {
        "name_ja": "【テスト】ログイン状態チェック",
        "function": run_check_login_status_test,
        "is_debug": True,
        "description": "リファクタリング版のログイン状態チェックタスクを検証します。",
        "order": 35,
    },
    "test-save-auth-state": {
        "name_ja": "【テスト】認証状態の保存",
        "function": run_save_auth_state_test,
        "is_debug": True,
        "description": "リファクタリング版の認証状態の保存タスクを検証します。",
        "order": 45,
    },
    "json-import-flow": {
        "name_ja": "【テスト】JSONインポート後フロー",
        "function": run_sample_flow_1,
        "is_debug": False, # UIには表示しない
        "show_in_schedule": False,
        "description": "JSONインポート後に、URL取得と投稿文作成を連続実行します。",
        "flow": "test-get-post-url | test-create-caption",
        "order": 9999,
    },
}