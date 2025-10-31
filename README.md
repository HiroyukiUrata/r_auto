# R-Auto: 楽天ROOM自動化ツール

（ここにプロジェクトの概要説明など）

## ローカル環境でのタスク実行とデバッグ

このプロジェクトはDockerコンテナでの実行を基本としていますが、開発やデバッグの効率を向上させるために、ローカルPCで直接タスクを実行する機能を提供しています。

`run_task.py` を使用することで、コンテナやVNCを起動することなく、使い慣れたローカル環境でブラウザを操作し、タスクの動作を確認できます。

### 初期セットアップ

ローカルでPlaywrightタスクを実行するには、操作対象のブラウザが必要です。以下のコマンドを一度だけ実行してください。

```bash
playwright install
```

### 基本的な使い方

プロジェクトのルートディレクトリで、以下の形式でコマンドを実行します。

```bash
python run_task.py [タスク名] --[引数名1] [値1] --[引数名2] [値2] ...
```

**例：ログイン状態を確認する**
```bash
python run_task.py check-login-status
```

---

## 手動テスト用フレームワーク (`manual-test`)

`manual-test` は、新しい自動化ロジックを開発・実験するための非常に強力なフレームワークです。指定したPythonスクリプトをPlaywrightのブラウザ環境内で実行し、処理が完了した後もブラウザを開いたままにすることができます。

### 主な用途

- **セレクタの調査**: 開発者ツールやPlaywright Inspectorを使い、操作したい要素の最適なセレクタをインタラクティブに探せます。
- **自動化ロジックの試作**: 小さなスクリプトを書いて、特定の操作（クリック、入力、待機など）が期待通りに動作するかを素早くテストできます。
- **手動での動作確認**: スクリプト実行後のページの状態を目で見て確認したり、手動で操作を続けたりできます。

### 使い方

1.  **実験用スクリプトの作成**
    `test_scripts` フォルダ内に、実行したい操作を記述したPythonファイルを作成します。
    このスクリプト内では、Playwrightの `page` と `context` オブジェクトを直接利用できます。

    **例: `test_scripts/highlight_first_card.py`**
    ```python
    # page と context は自動的に利用可能です

    # 1. ページにアクセス
    page.goto("https://room.rakuten.co.jp/room_be5dbb53b7/items")

    # 2. 最初のカード要素を特定
    first_card = page.locator('div[class*="item-card--root--"]').first

    # 3. 見つけたカードを赤い枠線でハイライト
    first_card.evaluate("node => { node.style.border = '3px solid red'; }")
    ```

2.  **コマンドラインから実行**
    `run_task.py` を使って、`--script` 引数で作成したスクリプトファイルを指定します。

    ```bash
    python run_task.py manual-test --script "test_scripts/highlight_first_card.py"
    ```

### Playwright Inspectorとの連携

`PWDEBUG=1` 環境変数を付けて実行すると、Playwright Inspectorが起動し、さらに強力なデバッグが可能になります。

```bash
PWDEBUG=1 python run_task.py manual-test --script "test_scripts/highlight_first_card.py"
```

Inspectorの「Record」機能で操作を記録したり、「Explore」機能でセレクタを調査したりすることで、開発効率が飛躍的に向上します。