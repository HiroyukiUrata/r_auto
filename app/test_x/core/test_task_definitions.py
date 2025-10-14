from app.test_x.tasks.sample_task_a import run_sample_task_a
from app.test_x.tasks.sample_task_b import run_sample_task_b
from app.test_x.tasks.sample_task_c import run_sample_task_c
from app.test_x.tasks.flow_runner import run_sample_flow_1
from app.test_x.tasks.sample_error_log_task import run_sample_error_log_task

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
        "flow": "test-sample-task-a | test-sample-task-b | test-sample-task-c",
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
}