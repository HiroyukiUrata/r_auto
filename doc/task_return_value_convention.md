# タスクの戻り値に関する実装規約

## 1. 目的

各タスクフロー（例: 「記事投稿フロー」）が完了した際に、その成果（何件成功し、何件失敗したか）を `[Action Summary]` ログとして正確に出力するための実装規約を定めます。
これにより、ダッシュボードでのアクティビティ追跡の精度を向上させます。

## 2. 基本方針

フローを構成する各タスクは、その処理結果を **戻り値の型** で明確に表現する必要があります。
フロー実行エンジン (`api.py`) は、この戻り値の型を解釈し、フロー全体の成功件数とエラー件数を集計します。

## 3. 戻り値の規約

各タスクは、その役割に応じて以下のいずれかの型を返すように実装してください。

### A. 主たる成果を返すタスク

フローの**主目的**となるアクション（例: 記事投稿、いいね活動）を実行するタスクです。

- **戻り値の型**: `int` または `tuple[int, int]`
- **意味**:
  - `int`: 処理に成功した件数を返します。
  - `tuple[int, int]`: `(成功件数, 失敗件数)` を返します。
- **フロー側の挙動**:
  - フロー内で**最初に返された**このタスクの成功件数が、フロー全体の主たる成功件数 (`count`) として記録されます。
  - 失敗件数は、フロー全体のエラー件数 (`errors`) に加算されます。

#### 実装例 (`posting.py`)

```python
# d:\Desktop\r_auto\app\tasks\posting.py

class PostingTask(BaseTask):
    # ...
    def _execute_main_logic(self):
        posted_count = 0
        error_count = 0
        for product in products:
            try:
                # ... 投稿処理 ...
                posted_count += 1
            except Exception as e:
                # ... エラー処理 ...
                error_count += 1
        
        # 成功件数と失敗件数をタプルで返す
        return posted_count, error_count
```

### B. 補助的な処理を行うタスク

フローの中で補助的な役割を担うタスク（例: URL紐付け、DBクリーンアップ）です。

- **戻り値の型**: `tuple[int, int]`
- **意味**: `(処理成功件数, 処理失敗件数)` を返します。
- **フロー側の挙動**:
  - 1番目の成功件数は**原則として無視されます**。
  - 2番目の失敗件数のみが、フロー全体のエラー件数 (`errors`) に加算されます。

#### 実装例 (`bind_product_url_room_url.py`)

```python
# d:\Desktop\r_auto\app\tasks\bind_product_url_room_url.py

class BindProductUrlRoomUrlTask(BaseTask):
    # ...
    def _execute_main_logic(self):
        success_count = 0
        error_count = 0
        # ... 処理ループ ...
        if is_success:
            success_count += 1
        else:
            error_count += 1
        
        # 成功件数と失敗件数をタプルで返す
        return success_count, error_count
```

### C. フローの続行/中断を判定するタスク

フローの実行を続けるか、途中で中断するかを判定するためのタスク（例: ログインチェック）です。

- **戻り値の型**: `bool`
- **意味**:
  - `True`: 処理は成功し、フローは続行します。
  - `False`: 処理は失敗し、フローは中断されます。
- **フロー側の挙動**:
  - このタスクの戻り値は、件数の集計には一切影響しません。
  - `False` が返された場合、フローは即座に停止し、フロー自体が失敗したとしてエラー件数が `1` 加算されます。

#### 実装例 (`check_login_status.py`)

```python
# d:\Desktop\r_auto\app\tasks\check_login_status.py

class CheckLoginStatusTask(BaseTask):
    # ...
    def _execute_main_logic(self):
        # ... ログイン状態の確認処理 ...
        if is_logged_in:
            return True
        else:
            raise LoginRedirectError("ログインページにリダイレクトされました。") # 最終的にFalseが返る

---

## 4. 単体実行時の規約

フローを介さずに、APIなどから直接呼び出されるタスク（例: `okaeshi_action.py`, `posting.py`）のための規約です。

- **目的**: フロー実行エンジンによる集計が行われないため、タスク自身がダッシュボードで集計可能なログを出力することを保証します。
- **基本方針**: タスクは、処理の最後に**必ず `[Action Summary]` ログを `INFO` レベルで出力**しなければなりません。

### `[Action Summary]` のフォーマット

以下の形式でログを出力してください。

```
[Action Summary] name={name}, count={count}, errors={errors}
```

- `name`: **`scheduler_utils.py`** の `actions` 辞書に定義されているキー（`投稿`, `いいね`, `フォロー`, `いいね返し`, `コメント返し` など）と完全に一致させる必要があります。これにより、ダッシュボードでの集計が正しく行われます。
- `count`: 処理に成功した件数。
- `errors`: 処理に失敗した件数。

### 実装例 (`okaeshi_action.py`)

```python
# d:\Desktop\r_auto\app\tasks\okaeshi_action.py

# --- 最終サマリーログの出力 ---
# このタスクは単体で実行されるため、自身でサマリーログを出力する
if like_back_processed_count > 0 or like_back_error_count > 0:
    logger.info(f"[Action Summary] name=いいね返し, count={like_back_processed_count}, errors={like_back_error_count}")
if comment_processed_count > 0 or comment_error_count > 0:
    logger.info(f"[Action Summary] name=コメント返し, count={comment_processed_count}, errors={comment_error_count}")
```
```