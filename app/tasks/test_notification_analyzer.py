import logging
import json
from datetime import datetime, timedelta
import pprint
import os
import sys

# --- プロジェクトルートのパスを追加 ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from app.core.database import get_all_user_engagements_map, bulk_upsert_user_engagements, init_db

# ロガー設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), "test_data")
STUB_DATA_FILE = os.path.join(TEST_DATA_DIR, "stub_notifications.json")

DEFAULT_STUB_DATA = [
  {
    "id": "user_A", "name": "Aさん（高スコア候補）", "profile_image_url": "/user_A.jpg",
    "action_text": "あなたの商品にいいねしました", "action_timestamp": "2025-10-26 10:00:00", "is_following": True
  },
  {
    "id": "user_A", "name": "Aさん（高スコア候補）", "profile_image_url": "/user_A.jpg",
    "action_text": "あなたの商品にいいねしました", "action_timestamp": "2025-10-26 10:01:00", "is_following": True
  },
  {
    "id": "user_A", "name": "Aさん（高スコア候補）", "profile_image_url": "/user_A.jpg",
    "action_text": "あなたの商品にいいねしました", "action_timestamp": "2025-10-26 10:02:00", "is_following": True
  },
  {
    "id": "user_A", "name": "Aさん（高スコア候補）", "profile_image_url": "/user_A.jpg",
    "action_text": "あなたの商品をコレ！しました", "action_timestamp": "2025-10-26 10:03:00", "is_following": True
  },
  {
    "id": "user_A", "name": "Aさん（高スコア候補）", "profile_image_url": "/user_A.jpg",
    "action_text": "あなたをフォローしました", "action_timestamp": "2025-10-26 10:04:00", "is_following": True
  },
  {
    "id": "user_B", "name": "Bさん（いいね多謝）", "profile_image_url": "/user_B.jpg",
    "action_text": "あなたの商品にいいねしました", "action_timestamp": "2025-10-26 11:00:00", "is_following": True
  },
  {
    "id": "user_B", "name": "Bさん（いいね多謝）", "profile_image_url": "/user_B.jpg",
    "action_text": "あなたの商品にいいねしました", "action_timestamp": "2025-10-26 11:01:00", "is_following": True
  },
  {
    "id": "user_B", "name": "Bさん（いいね多謝）", "profile_image_url": "/user_B.jpg",
    "action_text": "あなたの商品にいいねしました", "action_timestamp": "2025-10-26 11:02:00", "is_following": True
  },
  {
    "id": "user_C", "name": "Cさん（新規フォロー＆いいね）", "profile_image_url": "/user_C.jpg",
    "action_text": "あなたをフォローしました", "action_timestamp": "2025-10-26 12:00:00", "is_following": True
  },
  {
    "id": "user_C", "name": "Cさん（新規フォロー＆いいね）", "profile_image_url": "/user_C.jpg",
    "action_text": "あなたの商品にいいねしました", "action_timestamp": "2025-10-26 12:01:00", "is_following": True
  },
  {
    "id": "user_D", "name": "Dさん（未フォロー＆いいね）", "profile_image_url": "/user_D.jpg",
    "action_text": "あなたの商品にいいねしました", "action_timestamp": "2025-10-26 13:00:00", "is_following": False
  },
  {
    "id": "user_E", "name": "Eさん（いいね＆コレ！）", "profile_image_url": "/user_E.jpg",
    "action_text": "あなたの商品にいいねしました", "action_timestamp": "2025-10-26 14:00:00", "is_following": True
  },
  {
    "id": "user_E", "name": "Eさん（いいね＆コレ！）", "profile_image_url": "/user_E.jpg",
    "action_text": "あなたの商品をコレ！しました", "action_timestamp": "2025-10-26 14:01:00", "is_following": True
  },
  {
    "id": "user_F", "name": "Fさん（新規フォローのみ）", "profile_image_url": "/user_F.jpg",
    "action_text": "あなたをフォローしました", "action_timestamp": "2025-10-26 15:00:00", "is_following": True
  },
  {
    "id": "user_G", "name": "Gさん（いいね感謝）", "profile_image_url": "/user_G.jpg",
    "action_text": "あなたの商品にいいねしました", "action_timestamp": "2025-10-26 16:00:00", "is_following": True
  },
  {
    "id": "user_H", "name": "Hさん（コメントあり）", "profile_image_url": "/user_H.jpg",
    "action_text": "あなたの商品にコメントしました", "action_timestamp": "2025-10-26 17:00:00", "is_following": True
  },
  {
    "id": "user_I", "name": "Iさん（連コメ防止対象）", "profile_image_url": "/user_I.jpg",
    "action_text": "あなたの商品にいいねしました", "action_timestamp": "2025-10-26 18:00:00", "is_following": True
  },
  {
    "id": "user_J", "name": "Jさん（その他）", "profile_image_url": "/user_J.jpg",
    "action_text": "あなたの商品をROOM CLIPしました", "action_timestamp": "2025-10-26 19:00:00", "is_following": True
  }
]

def run_test():
    """
    スタブデータを使って通知分析ロジックをテストする。
    """
    logger.info("--- 通知分析ロジックのテストを開始します ---")

    # --- 0. テストデータの準備 ---
    if not os.path.exists(STUB_DATA_FILE):
        logger.warning(f"スタブデータファイルが見つかりません: {STUB_DATA_FILE}")
        try:
            os.makedirs(TEST_DATA_DIR, exist_ok=True)
            with open(STUB_DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_STUB_DATA, f, ensure_ascii=False, indent=2)
            logger.info(f"デフォルトのスタブデータファイルを自動生成しました。")
        except Exception as e:
            logger.error(f"スタブデータファイルの自動生成に失敗しました: {e}")
            return

    try:
        with open(STUB_DATA_FILE, 'r', encoding='utf-8') as f:
            all_notifications = json.load(f)
        logger.info(f"{STUB_DATA_FILE} から {len(all_notifications)} 件のスタブ通知データを読み込みました。")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"スタブデータの読み込みに失敗しました: {e}")
        return

    # テスト用に、特定のユーザーに過去のコメント履歴をDBに設定しておく
    init_db() # テストのたびにDBスキーマが最新であることを確認
    three_days_ago_str = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')
    mock_db_user = {
        'id': 'user_I',
        'name': 'Iさん（連コメ防止対象）',
        'last_commented_at': three_days_ago_str
    }
    bulk_upsert_user_engagements([mock_db_user])
    logger.info(f"ユーザー「{mock_db_user['name']}」に過去のコメント日時 ({three_days_ago_str}) を設定しました。")


    # --- 1. `notification_analyzer.py` のロジックを再現 ---

    # フェーズ2: ユーザー単位で情報を集約し、過去データと合算
    logger.info("--- フェーズ2: ユーザー単位で情報を集約します ---")
    aggregated_users = {}
    for notification in all_notifications:
        user_id_val = notification['id']
        if user_id_val not in aggregated_users:
            aggregated_users[user_id_val] = {
                'id': user_id_val, 'name': notification['name'],
                'recent_like_count': 0, 'recent_collect_count': 0,
                'recent_comment_count': 0, 'follow_count': 0,
                'is_following': notification['is_following'],
                'recent_action_timestamp': notification['action_timestamp'],
            }
        
        if "いいねしました" in notification['action_text']:
            aggregated_users[user_id_val]['recent_like_count'] += 1
        if "コレ！しました" in notification['action_text']:
            aggregated_users[user_id_val]['recent_collect_count'] += 1
        if "あなたをフォローしました" in notification['action_text']:
            aggregated_users[user_id_val]['follow_count'] += 1
        if "あなたの商品にコメントしました" in notification['action_text']:
            aggregated_users[user_id_val]['recent_comment_count'] += 1

        if notification['action_timestamp'] > aggregated_users[user_id_val]['recent_action_timestamp']:
            aggregated_users[user_id_val]['recent_action_timestamp'] = notification['action_timestamp']

    existing_users_map = get_all_user_engagements_map()

    for user_id_val, user_data in aggregated_users.items():
        past_data = existing_users_map.get(user_id_val)
        past_like, past_collect, past_comment, past_follow = 0, 0, 0, 0
        latest_action_timestamp = user_data['recent_action_timestamp']

        if past_data:
            past_like = past_data.get('like_count', 0)
            past_collect = past_data.get('collect_count', 0)
            past_comment = past_data.get('comment_count', 0)
            past_follow = past_data.get('follow_count', 0)
            if past_data.get('latest_action_timestamp') and past_data['latest_action_timestamp'] > latest_action_timestamp:
                latest_action_timestamp = past_data['latest_action_timestamp']

        user_data['like_count'] = past_like + user_data['recent_like_count']
        user_data['collect_count'] = past_collect + user_data['recent_collect_count']
        user_data['comment_count'] = past_comment + user_data['recent_comment_count']
        user_data['follow_count'] = past_follow + user_data['follow_count']
        user_data['latest_action_timestamp'] = latest_action_timestamp

    # カテゴリ付与
    logger.info("--- カテゴリを付与します ---")
    categorized_users = []
    for user in aggregated_users.values():
        total_like = user['like_count']
        total_collect = user['collect_count']
        total_follow = user['follow_count']
        is_following = user['is_following']

        if (total_like + total_collect + total_follow) >= 5:
            user['category'] = "高スコアユーザ（連コメOK）"
        elif total_like >= 3:
            user['category'] = "いいね多謝"
        elif total_follow > 0 and total_like > 0:
            user['category'] = "新規フォロー＆いいね感謝"
        elif total_like > 0 and not is_following:
            user['category'] = "未フォロー＆いいね感謝"
        elif total_like > 0 and total_collect > 0:
            user['category'] = "いいね＆コレ！感謝"
        elif total_follow > 0 and total_like == 0:
            user['category'] = "新規フォロー"
        elif total_like > 0:
            user['category'] = "いいね感謝"
        else:
            user['category'] = "その他"
        
        if user['category'] != "その他":
            categorized_users.append(user)

    # フェーズ3: フィルタリングとソート
    logger.info("--- フェーズ3: 優先度順にソートします ---")
    three_days_ago = datetime.now() - timedelta(days=3)
    users_to_process = []
    for user in categorized_users:
        existing_user_data = existing_users_map.get(user['id'])
        user['last_commented_at'] = existing_user_data.get('last_commented_at') if existing_user_data else None
        users_to_process.append(user)

    sorted_users = sorted(
        users_to_process,
        key=lambda u: (
            not ((datetime.strptime(u['last_commented_at'], '%Y-%m-%d %H:%M:%S') > three_days_ago) if u.get('last_commented_at') else False),
            (u.get('category') == "高スコアユーザ（連コメOK）"),
            (u.get('category') == "新規フォロー＆いいね感謝"),
            (u.get('category') == "新規フォロー"),
            (u.get('category') == "いいね多謝"),
            (u.get('category') == "いいね＆コレ！感謝"),
            (u.get('category') == "いいね感謝"),
            u.get('like_count', 0),
        ),
        reverse=True
    )

    # --- 2. 結果の表示 ---
    logger.info("\n\n" + "="*20 + " テスト結果 " + "="*20)
    for i, user in enumerate(sorted_users):
        print(f"\n--- {i+1}位: {user['name']} ---")
        print(f"  カテゴリ: {user['category']}")
        print(f"  優先度キー[0] (連コメ): {not ((datetime.strptime(user['last_commented_at'], '%Y-%m-%d %H:%M:%S') > three_days_ago) if user.get('last_commented_at') else False)}")
        print(f"  累計いいね: {user.get('like_count', 0)}, 累計コレ！: {user.get('collect_count', 0)}, 累計フォロー: {user.get('follow_count', 0)}")
        print(f"  今回のいいね: {user.get('recent_like_count', 0)}, 今回のコレ！: {user.get('recent_collect_count', 0)}")

    logger.info("="*50)

if __name__ == "__main__":
    run_test()