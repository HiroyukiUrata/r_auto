-- ユーザーエンゲージメントのテストデータを挿入するSQLスクリプト
-- 実行前に `user_engagement` テーブルをクリアすることをお勧めします。
-- DELETE FROM user_engagement;

INSERT INTO user_engagement (id, name, profile_page_url, profile_image_url, like_count, collect_count, comment_count, follow_count, is_following, latest_action_timestamp, recent_like_count, recent_collect_count, recent_comment_count, recent_follow_count, recent_action_timestamp, comment_text, last_commented_at, ai_prompt_message, ai_prompt_updated_at, comment_generated_at, last_commented_post_url, last_engagement_error)
VALUES
-- パターン1: 新規コメント対象 (3いいね以上)
('user001', '新規コメント対象_3いいね', 'https://room.rakuten.co.jp/user/user001', 'https://api.dicebear.com/8.x/pixel-art/svg?seed=user001', 0, 0, 0, 0, 0, '2025-11-01T10:00:00', 3, 0, 0, 0, '2025-11-01T10:00:00', '初めまして！素敵な商品ですね！', NULL, '今回、新たに3件の「いいね」をしてくれました。', '2025-11-01T10:01:00', '2025-11-01T10:02:00', NULL, NULL),
('user002', '新規コメント対象_5いいね_新規フォロー', 'https://room.rakuten.co.jp/user/user002', 'https://api.dicebear.com/8.x/pixel-art/svg?seed=user002', 0, 0, 0, 0, 1, '2025-11-01T11:00:00', 5, 1, 0, 1, '2025-11-01T11:00:00', 'フォローさせていただきました！これからよろしくお願いします！', NULL, '新規にフォローしてくれました。 今回、新たに5件の「いいね」をしてくれました。', '2025-11-01T11:01:00', '2025-11-01T11:02:00', NULL, NULL),
('user003', '新規コメント対象_10いいね', 'https://room.rakuten.co.jp/user/user003', 'https://api.dicebear.com/8.x/pixel-art/svg?seed=user003', 0, 0, 0, 0, 0, '2025-11-01T12:00:00', 10, 0, 0, 0, '2025-11-01T12:00:00', 'たくさん「いいね」ありがとうございます！嬉しいです！', NULL, '今回、新たに10件の「いいね」をしてくれました。', '2025-11-01T12:01:00', '2025-11-01T12:02:00', NULL, NULL),

-- パターン2: 再コメント対象 (3日以上経過 & 5いいね以上)
('user004', '再コメント対象_5いいね', 'https://room.rakuten.co.jp/user/user004', 'https://api.dicebear.com/8.x/pixel-art/svg?seed=user004', 20, 5, 1, 1, 1, '2025-11-01T13:00:00', 5, 0, 0, 0, '2025-11-01T13:00:00', 'お久しぶりです！またまた素敵な商品ですね！', '2025-10-28T10:00:00', '以前からフォローしてくれているユーザーです。 過去にも「いいね」をしてくれたことがあります。 今回も5件の「いいね」をしてくれました。', '2025-11-01T13:01:00', '2025-11-01T13:02:00', 'https://room.rakuten.co.jp/post/xxxxxxxx', NULL),
('user005', '再コメント対象_常連_15いいね', 'https://room.rakuten.co.jp/user/user005', 'https://api.dicebear.com/8.x/pixel-art/svg?seed=user005', 150, 20, 5, 1, 1, '2025-11-01T14:00:00', 15, 2, 0, 0, '2025-11-01T14:00:00', 'いつも本当にありがとうございます！感謝です！', '2025-10-25T18:00:00', '以前からフォローしてくれているユーザーです。 いつもたくさんの「いいね」をくれる常連の方です。 今回も15件の「いいね」をしてくれました。', '2025-11-01T14:01:00', '2025-11-01T14:02:00', 'https://room.rakuten.co.jp/post/yyyyyyyy', NULL),

-- パターン3: いいね返しのみ対象 (コメント済みだが3日以内 or 5いいね未満)
('user006', 'いいね返しのみ_昨日コメント済', 'https://room.rakuten.co.jp/user/user006', 'https://api.dicebear.com/8.x/pixel-art/svg?seed=user006', 10, 2, 1, 1, 1, '2025-11-01T15:00:00', 10, 0, 0, 0, '2025-11-01T15:00:00', '（投稿済みの古いコメント）昨日ぶりです！', '2025-10-31T20:00:00', '...', '2025-10-31T19:00:00', '2025-10-31T19:05:00', 'https://room.rakuten.co.jp/post/zzzzzzzz', NULL),
('user007', 'いいね返しのみ_4いいね', 'https://room.rakuten.co.jp/user/user007', 'https://api.dicebear.com/8.x/pixel-art/svg?seed=user007', 5, 1, 1, 0, 0, '2025-11-01T16:00:00', 4, 0, 0, 0, '2025-11-01T16:00:00', '（投稿済みの古いコメント）いいねありがとうございます！', '2025-10-20T11:00:00', '...', '2025-10-20T10:00:00', '2025-10-20T10:05:00', 'https://room.rakuten.co.jp/post/aaaaaaaa', NULL),
('user008', 'いいね返しのみ_3いいね', 'https://room.rakuten.co.jp/user/user008', 'https://api.dicebear.com/8.x/pixel-art/svg?seed=user008', 8, 0, 2, 1, 1, '2025-11-01T17:00:00', 3, 0, 0, 0, '2025-11-01T17:00:00', '（投稿済みの古いコメント）こんにちは！', '2025-10-27T12:00:00', '...', '2025-10-27T11:00:00', '2025-10-27T11:05:00', 'https://room.rakuten.co.jp/post/bbbbbbbb', NULL),

-- パターン4: コメント対象外 (いいね3未満)
('user009', '対象外_2いいね', 'https://room.rakuten.co.jp/user/user009', 'https://api.dicebear.com/8.x/pixel-art/svg?seed=user009', 2, 0, 0, 0, 0, '2025-11-01T18:00:00', 2, 0, 0, 0, '2025-11-01T18:00:00', NULL, NULL, NULL, NULL, NULL, NULL, NULL),
('user010', '対象外_1いいね', 'https://room.rakuten.co.jp/user/user010', 'https://api.dicebear.com/8.x/pixel-art/svg?seed=user010', 1, 1, 0, 0, 0, '2025-11-01T19:00:00', 1, 1, 0, 0, '2025-11-01T19:00:00', NULL, NULL, NULL, NULL, NULL, NULL, NULL),

-- パターン5: エラー発生ユーザー
('error_user_01', 'エラーユーザー1_いいね失敗', 'https://room.rakuten.co.jp/user/error_user_01', 'https://api.dicebear.com/8.x/pixel-art/svg?seed=error01', 10, 2, 1, 1, 1, '2025-11-02T15:00:00', 5, 0, 0, 0, '2025-11-02T15:00:00', 'このコメントは投稿されないはず', '2025-10-30T10:00:00', '...', '2025-11-02T15:01:00', '2025-11-02T15:02:00', 'https://room.rakuten.co.jp/post/error_post_1', '「いいね返し」中にエラーが発生しました: Timeout 30000ms exceeded.'),
('error_user_02', 'エラーユーザー2_コメント失敗', 'https://room.rakuten.co.jp/user/error_user_02', 'https://api.dicebear.com/8.x/pixel-art/svg?seed=error02', 5, 0, 0, 0, 0, '2025-11-02T16:00:00', 4, 0, 0, 0, '2025-11-02T16:00:00', 'このコメントは投稿に失敗する', NULL, '今回、新たに4件の「いいね」をしてくれました。', '2025-11-02T16:01:00', '2025-11-02T16:02:00', NULL, '「コメント返し」中にエラーが発生しました: Locator.click: Timeout 10000ms exceeded.'),

-- パターン6: その他エッジケース
('user016', 'URL取得失敗ユーザー', '取得失敗', 'https://api.dicebear.com/8.x/pixel-art/svg?seed=user016', 5, 0, 0, 0, 0, '2025-11-02T01:00:00', 5, 0, 0, 0, '2025-11-02T01:00:00', 'コメント生成済みだがURLなし', NULL, '今回、新たに5件の「いいね」をしてくれました。', '2025-11-02T01:01:00', '2025-11-02T01:02:00', NULL, NULL),
('user017', 'コメント未生成ユーザー', 'https://room.rakuten.co.jp/user/user017', 'https://api.dicebear.com/8.x/pixel-art/svg?seed=user017', 0, 0, 0, 0, 0, '2025-11-02T02:00:00', 4, 0, 0, 0, '2025-11-02T02:00:00', NULL, NULL, '今回、新たに4件の「いいね」をしてくれました。', '2025-11-02T02:01:00', NULL, NULL, NULL),
('user018', '古いコメントのままのユーザー', 'https://room.rakuten.co.jp/user/user018', 'https://api.dicebear.com/8.x/pixel-art/svg?seed=user018', 10, 1, 1, 1, 1, '2025-11-02T03:00:00', 6, 0, 0, 0, '2025-11-02T03:00:00', '（これは古いはずのコメント）', '2025-10-29T12:00:00', '以前からフォローしてくれているユーザーです。 過去にも「いいね」をしてくれたことがあります。 今回も6件の「いいね」をしてくれました。', '2025-11-02T03:01:00', '2025-10-29T11:00:00', 'https://room.rakuten.co.jp/post/eeeeeeee', NULL),
('user019', '日本語名ユーザー', '山田 花子', 'https://api.dicebear.com/8.x/pixel-art/svg?seed=hanako', 0, 0, 0, 0, 0, '2025-11-02T04:00:00', 3, 0, 0, 0, '2025-11-02T04:00:00', 'こんにちは、山田です。', NULL, '今回、新たに3件の「いいね」をしてくれました。', '2025-11-02T04:01:00', '2025-11-02T04:02:00', NULL, NULL),
('user020', '絵文字入りユーザー名😊✨', '絵文字入りユーザー名😊✨', 'https://api.dicebear.com/8.x/pixel-art/svg?seed=emoji_user', 0, 0, 0, 0, 0, '2025-11-02T05:00:00', 4, 0, 0, 0, '2025-11-02T05:00:00', '絵文字ユーザーさん、こんにちは！', NULL, '今回、新たに4件の「いいね」をしてくれました。', '2025-11-02T05:01:00', '2025-11-02T05:02:00', NULL, NULL);
