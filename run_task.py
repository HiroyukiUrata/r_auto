import sys
import os
import argparse
import logging

# プロジェクトのルートディレクトリをPythonのパスに追加
# これにより、`app.tasks`のような絶対パスでのインポートが可能になる
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.task_definitions import TASK_DEFINITIONS
from app.core.logging_config import setup_logging

def main():
    """
    コマンドラインからタスクを直接実行するためのローカル開発用ランチャー。
    """
    # 最初にロギングを設定
    setup_logging()
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="ローカル環境で自動化タスクを直接実行します。")
    parser.add_argument("task_name", help=f"実行するタスクの名前 (例: manual_test, check-login-status)")
    
    # 残りの引数を未知の引数としてパース
    args, unknown = parser.parse_known_args()

    # 未知の引数をキーと値のペアに変換 (--url "value" -> {"url": "value"})
    kwargs = {}
    i = 0
    # manual-testタスクの場合、--で始まらない引数は 'urls' キーにリストとしてまとめる
    if args.task_name == 'manual-test':
        kwargs['urls'] = []

    while i < len(unknown):
        arg = unknown[i]
        if arg.startswith('--'):
            key = arg.lstrip('-').replace('-', '_')
            if i + 1 < len(unknown) and not unknown[i+1].startswith('--'):
                value = unknown[i+1]
                if value.lower() == 'true':
                    kwargs[key] = True
                elif value.lower() == 'false':
                    kwargs[key] = False
                elif key == 'script':
                    kwargs[key] = os.path.normpath(value)
                else:
                    kwargs[key] = value
                i += 2
            else:
                kwargs[key] = True
                i += 1
        else:
            if args.task_name == 'manual-test':
                kwargs['urls'].append(arg)
            i += 1

    task_func = TASK_DEFINITIONS.get(args.task_name, {}).get("function")
    if task_func:
        logger.info(f"ローカルでタスク '{args.task_name}' を引数 {kwargs} で実行します。")
        task_func(**kwargs)
    else:
        logger.error(f"タスク '{args.task_name}' が見つかりません。")
        logger.error(f"利用可能なタスク: {list(TASK_DEFINITIONS.keys())}")

if __name__ == "__main__":
    main()