# R-Auto Control Panel v.1.0.3

某SNSの自動化タスクを管理・実行するためのWebアプリケーションです。

## 主な機能

- **タスクのスケジュール実行**: 「いいね」「フォロー」「商品調達」「記事投稿」などのタスクを、指定した時刻に自動で実行します。
- **Web UIによる管理**: ブラウザから簡単にスケジュールの設定や変更、タスクの即時実行が可能です。
- **在庫管理**: 調達した商品を一覧で確認し、手動でステータスを変更したり、投稿したりできます。
- **ログ確認**: 実行されたタスクのログをリアルタイムで確認できます。
- **VNC連携**: デバッグモードでは、実行中のブラウザ操作をVNCクライアント経由で視覚的に確認できます。

## 技術スタック

- **バックエンド**: Python, FastAPI
- **フロントエンド**: HTML, CSS, JavaScript, Bootstrap
- **スケジューラ**: schedule
- **ブラウザ自動化**: Playwright
- **コンテナ化**: Docker, Docker Compose

## ディレクトリ構成

```
.
├── app/
│   ├── core/         # アプリケーションの中核機能（DB, スケジューラ, タスク定義など）
│   ├── tasks/        # 各自動化タスクのロジック
│   ├── web/          # FastAPIのAPIエンドポイントとWebサーバー関連
│   ├── locators/     # (削除済み) Playwrightのセレクタ管理
│   ├── prompts/      # AI用のプロンプトファイル
│   ├── Dockerfile
│   └── main.py       # アプリケーションのエントリポイント
├── db/               # データベースファイル、プロファイル、キーワード、スケジュール設定
├── web/
│   └── templates/    # HTMLテンプレート
├── docker-compose.yml
└── README.md
```

## セットアップと実行

1.  **Dockerのインストール**: DockerとDocker Composeがインストールされていることを確認してください。
2.  **環境変数の設定**: `.env.sample` を参考に `.env` ファイルを作成し、必要な環境変数を設定します。
3.  **コンテナのビルドと起動**:

    ```bash
    docker-compose up --build -d
    ```

4.  **Web UIへのアクセス**:
    ブラウザで `http://localhost:8000` にアクセスします。

5.  **VNCでの動作確認**:
    VNCクライアントで `localhost:5900` に接続します。（パスワードは `.env` で設定）

## タスクとフローの仕組み

このアプリケーションのタスク実行は、`app/core/task_definitions.py` で一元管理されています。

### タスク定義

個々のタスクは、以下のような辞書形式で定義されます。

```python
# "タスクID": {
#     "name_ja": "UIに表示される日本語名",
#     "function": 実行される関数オブジェクト,
#     "is_debug": Trueにするとシステムコンフィグのデバッグ用タスク一覧に表示される,
#     "show_in_schedule": Falseにするとスケジュール設定画面に表示されなくなる,
#     "description": "UIに表示されるタスクの説明文",
#     "order": UIでの表示順（小さいほど上）,
#     "default_kwargs": {"引数名": デフォルト値}, # タスク実行時のデフォルト引数
# }
```

### フロー定義

複数のタスクを順番に実行する「フロー」も同様に定義できます。

```python
# "フローID": {
#     "name_ja": "フローの日本語名",
#     "function": None, # フロー自体は関数を持たない
#     "flow": [ ... ], # フローの内容を定義
#     ...
# }
```

#### `flow` キーの設定方法

1.  **シンプルな文字列形式（引数なし）**

    ```python
    "flow": "task-a | task-b | task-c"
    ```

2.  **引数を指定できるリスト形式**

    ```python
    "flow": [
        ("task-a", {"arg1": "value1"}),  # task-a を arg1="value1" で実行
        ("task-b", {}),                  # task-b を引数なしで実行
    ]
    ```

#### フローからタスクへの引数引き渡し

フロー全体に渡された引数を、フロー内の特定のタスクに引き渡すことができます。

```python
# "default_kwargs": {"count": 25},
# "flow": [
#     ("some-task", {"count": "flow_count"})
# ]
```

-   `"flow_count"` という特別なキーワードを指定すると、フローに渡された `'count'` 引数（この場合は25）が `some-task` の `'count'` 引数として渡されます。
-   このキーワードは `app/web/api.py` で解釈される固定値です。

---

## 開発者向け情報

- 新しいタスクを追加する場合は、`app/tasks` にファイルを作成し、`app/core/task_definitions.py` に定義を追加してください。
- UIの変更は `web/templates` 内のHTMLファイルを編集します。
- APIエンドポイントの追加・変更は `app/web/api.py` を編集します。
