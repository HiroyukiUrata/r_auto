import logging
import os
import re
import json
import unicodedata
from datetime import datetime, timedelta
import random

from playwright.sync_api import Error as PlaywrightError

from app.core.base_task import BaseTask
from app.core.config_manager import SCREENSHOT_DIR # For error screenshots
from app.core.database import (
    get_latest_engagement_timestamp,
    get_all_user_engagements_map,
    bulk_upsert_user_engagements,
    cleanup_old_user_engagements,
)

# --- DB/出力ディレクトリの定義 ---
DB_DIR = "db" # Relative to project root, where db/engagement_data.json will be
COMMENT_TEMPLATES_FILE = "app/prompts/comment_templates.json" # Assuming this path

# ロガーはBaseTaskが設定するので、ここでは取得するだけ
logger = logging.getLogger(__name__)

def extract_natural_name(full_name: str) -> str:
    """
    絵文字や装飾が含まれる可能性のあるフルネームから、自然な名前の部分を抽出する。
    例: '春🌷身長が3cm伸びました😳' -> '春'
    例: '𝐬𝐚𝐲𝐮¹²²⁵𝓡' -> 'sayu'
    例: '❁mizuki❁' -> 'mizuki'
    """
    if not full_name:
        return ""

    # Unicodeの絵文字や特定の記号を区切り文字として定義
    # 既存のリストに加えて、よく使われる記号を追加
    separators = re.compile(
        r'['
        u'\u2600-\u27BF'          # Miscellaneous Symbols
        u'\U0001F300-\U0001F5FF'  # Miscellaneous Symbols and Pictographs
        u'\U0001F600-\U0001F64F'  # Emoticons
        u'\U0001F680-\U0001F6FF'  # Transport & Map Symbols
        u'\U0001F1E0-\U0001F1FF'  # Flags (iOS)
        u'\U0001F900-\U0001F9FF'  # Supplemental Symbols and Pictographs
        u'|│￤＠@/｜*＊※☆★♪#＃♭🎀♡♥❤︎' # 全角・半角の記号類 (♡も追加)
        u']+' # 連続する区切り文字を一つとして扱う
    )

    # 区切り文字で文字列を分割
    parts = separators.split(full_name)

    # 分割されたパーツから、空でない最初の要素を探す
    name_candidate = ""
    for part in parts:
        cleaned_part = part.strip()
        if cleaned_part:
            name_candidate = cleaned_part
            break
    
    if not name_candidate:
        return full_name.strip() # 候補が見つからなければ元の名前を返す

    # 候補の文字列を正規化 (例: 𝐬𝐚𝐲𝐮¹²²⁵𝓡 -> sayu1225R)
    normalized_name = unicodedata.normalize('NFKC', name_candidate)

    # 正規化された名前から、最初の数字や特定の記号までの部分を抽出
    # 数字、アンダースコア、ハイフン、全角ハイフン、ダッシュなどを考慮
    match = re.search(r'[\d_‐\-\—]', normalized_name)
    if match:
        return normalized_name[:match.start()].strip()
    
    return normalized_name.strip()

class NotificationAnalyzerTask(BaseTask):
    """
    楽天ROOMのお知らせページからユーザー情報をスクレイピングし、
    エンゲージメントの高いユーザーを特定してDBに保存するタスク。
    """
    def __init__(self, hours_ago: int = 12):
        super().__init__(count=None) # このタスクはcount引数を直接使わない
        self.hours_ago = hours_ago
        self.action_name = "通知分析"
        self.needs_browser = True
        self.use_auth_profile = True # ログイン状態が必要

    def _execute_main_logic(self):
        page = self.page # BaseTaskが提供するpageオブジェクトを使用

        # --- 1. ページ遷移 ---
        logger.info(f"楽天ROOMのトップページにアクセスします。")
        page.goto("https://room.rakuten.co.jp/items", wait_until="domcontentloaded")

        logger.info("「お知らせ」リンクを探してクリックします。")
        try:
            page.get_by_role("link", name="お知らせ").click()
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            logger.info(f"お知らせページに遷移しました: {page.url}")
        except PlaywrightError as e:
            logger.error(f"「お知らせ」リンクのクリックまたはページ遷移中にエラーが発生しました: {e}")
            self._take_screenshot_on_error(prefix="notification_link_error")
            return False

        # --- 2. 無限スクロールによる情報収集 ---
        logger.info("「アクティビティ」セクションをスクロールして情報を収集します。")
        activity_title_locator = page.locator("div.title[ng-show='notifications.activityNotifications.length > 0']")
        try:
            activity_title_locator.wait_for(state='attached', timeout=10000)
        except PlaywrightError:
            logger.info("「アクティビティ」セクションが見つかりませんでした。処理対象はありません。")
            return True # エラーではないのでTrueを返す

        # 修正: 最初の通知リスト項目が表示されるまで待機する
        try:
            first_notification_item = page.locator("li[ng-repeat='notification in notifications.activityNotifications']").first
            first_notification_item.wait_for(state='visible', timeout=15000)
        except PlaywrightError:
            logger.info("アクティビティのタイトルはありますが、通知リストが見つかりませんでした。処理対象はありません。")
            return True

        logger.info("遅延読み込みされるコンテンツを表示するため、ページをスクロールします。")
        last_count = 0
        # 複数回スクロールして、新しい要素がロードされるのを待つ
        for attempt in range(5): # 試行回数を増やしても良い
            notification_list_items = page.locator("li[ng-repeat='notification in notifications.activityNotifications']")
            current_count = notification_list_items.count()

            # 3回以上スクロールして、かつ要素数に変化がない場合は終了
            if attempt >= 2 and current_count == last_count:
                logger.info("スクロールしても新しいアクティビティ通知は読み込まれませんでした。")
                break

            last_count = current_count
            logger.debug(f"  スクロール {attempt + 1}回目: {current_count}件のアクティビティ通知を検出。")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500) # 少し待つ

        # --- 3. データ抽出 ---
        notification_list_items = page.locator("li[ng-repeat='notification in notifications.activityNotifications']")
        logger.info(f"--- フェーズ1: {notification_list_items.count()}件の通知から基本情報を収集します。 ---")
        all_notifications = []
        for item in notification_list_items.all():
            try:
                user_name_element = item.locator("span.notice-name span.strong").first
                # 要素がDOMに存在し、かつ表示されていることを確認
                if not user_name_element.is_visible():
                    continue

                user_name = user_name_element.inner_text().strip()
                profile_image_url = item.locator("div.left-img img").get_attribute("src")

                # プロフィール画像がないユーザーはスキップ
                if profile_image_url and "img_noprofile.gif" in profile_image_url:
                    continue

                if user_name:
                    # user_idをprofile_image_urlから抽出
                    user_id = "unknown"
                    if profile_image_url:
                        match = re.search(r'/([^/]+?)(?:\.\w+)?(?:\?.*)?$', profile_image_url)
                        if match: user_id = match.group(1)
                    
                    # user_idがunknownのままの場合はスキップ（画像URLがないか、解析できない場合）
                    if user_id == "unknown":
                        logger.debug(f"ユーザー「{user_name}」のユーザーIDを特定できませんでした。スキップします。")
                        continue

                    action_text = item.locator("div.right-text > p").first.inner_text()
                    action_timestamp = item.locator("span.notice-time").first.get_attribute("title")
                    
                    # 「未フォロー」ボタンが存在しない、または非表示であればフォロー中と判断
                    is_following = not item.locator("span.follow:has-text('未フォロー')").is_visible()

                    all_notifications.append({
                        'id': user_id, 'name': user_name,
                        'profile_image_url': profile_image_url,
                        'action_text': action_text,
                        'action_timestamp': action_timestamp,
                        'is_following': is_following
                    })
            except PlaywrightError as item_error:
                logger.warning(f"通知アイテムの取得中にPlaywrightエラー: {item_error}")
            except Exception as item_error:
                logger.warning(f"通知アイテムの取得中に予期せぬエラー: {item_error}")

        # --- フェーズ2: ユーザー単位で情報を集約し、過去データと合算 ---
        logger.info(f"--- フェーズ2: {len(all_notifications)}件の通知をユーザー単位で集約します。 ---")
        aggregated_users = {}
        for notification in all_notifications:
            user_id_val = notification['id']
            if user_id_val not in aggregated_users:
                aggregated_users[user_id_val] = {
                    'id': user_id_val, 'name': notification['name'],
                    'profile_image_url': notification['profile_image_url'],
                    'recent_like_count': 0, 'recent_collect_count': 0,
                    'recent_comment_count': 0, 'follow_count': 0, # followは累計に直接加算
                    'is_following': notification['is_following'],
                    'recent_action_timestamp': notification['action_timestamp'],
                }
            
            # 各アクションのカウントを更新
            if "いいねしました" in notification['action_text']:
                aggregated_users[user_id_val]['recent_like_count'] += 1
            if "コレ！しました" in notification['action_text']:
                aggregated_users[user_id_val]['recent_collect_count'] += 1
            if "あなたをフォローしました" in notification['action_text']:
                aggregated_users[user_id_val]['follow_count'] += 1 # followは累計に直接加算
            if "あなたの商品にコメントしました" in notification['action_text']:
                aggregated_users[user_id_val]['recent_comment_count'] += 1

            # 最新のアクションタイムスタンプとテキストを更新
            if notification['action_timestamp'] > aggregated_users[user_id_val]['recent_action_timestamp']:
                aggregated_users[user_id_val]['recent_action_timestamp'] = notification['action_timestamp']

        logger.info(f"  -> {len(aggregated_users)}人のユニークユーザーに集約しました。")

        # 既存DBのデータを取得し、過去のアクション数と合算
        existing_users_map = get_all_user_engagements_map()

        for user_id_val, user_data in aggregated_users.items():
            # 過去の累計値を取得
            past_data = existing_users_map.get(user_id_val)
            past_like = 0
            past_collect = 0
            past_comment = 0
            past_follow = 0
            latest_action_timestamp = user_data['recent_action_timestamp']

            if past_data:
                past_like = past_data.get('like_count', 0)
                past_collect = past_data.get('collect_count', 0)
                past_comment = past_data.get('comment_count', 0)
                past_follow = past_data.get('follow_count', 0)
                # 過去と今回のタイムスタンプを比較して新しい方を採用
                if past_data.get('latest_action_timestamp') and past_data['latest_action_timestamp'] > latest_action_timestamp:
                    latest_action_timestamp = past_data['latest_action_timestamp']

            # 今回のアクション数と合算して新しい累計値を計算
            user_data['like_count'] = past_like + user_data['recent_like_count']
            user_data['collect_count'] = past_collect + user_data['recent_collect_count']
            user_data['comment_count'] = past_comment + user_data['recent_comment_count']
            user_data['follow_count'] = past_follow + user_data['follow_count'] # followは既に累計に加算済み
            user_data['latest_action_timestamp'] = latest_action_timestamp
        
        # --- カテゴリ付与 ---
        categorized_users = []
        for user in aggregated_users.values():
            # カテゴリ判定には累計値を使用
            total_like = user['like_count']
            total_collect = user['collect_count']
            total_follow = user['follow_count']
            recent_like = user['recent_like_count']
            is_following = user['is_following']

            # カテゴリ判定ロジック（高スコアユーザを最優先）
            # 仕様: like_count + collect_count + follow_count が一定値以上
            if (total_like + total_collect + total_follow) >= 5 and recent_like > 0:
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
            
            # 「その他」カテゴリは処理対象から除外
            if user['category'] != "その他":
                categorized_users.append(user)

        # --- フェーズ3: 時間条件でフィルタリングし、優先度順にソート ---
        logger.info(f"--- フェーズ3: 時間条件でユーザーをフィルタリングします。 ---")
        
        latest_db_timestamp = get_latest_engagement_timestamp()
        
        # 過去12時間以内のアクションを対象とする
        target_hours_ago = datetime.now() - timedelta(hours=self.hours_ago)
        # 3日以内にコメント済みのユーザーを除外するための閾値
        three_days_ago = datetime.now() - timedelta(days=3)
        
        logger.info(f"  - DBの最新時刻: {latest_db_timestamp.strftime('%Y-%m-%d %H:%M:%S') if latest_db_timestamp > datetime.min else '（データなし）'}")
        logger.info(f"  - {self.hours_ago}時間前の時刻: {target_hours_ago.strftime('%Y-%m-%d %H:%M:%S')}")

        users_to_process = []
        # 既存DBのデータを取得（last_commented_at を参照するため）
        existing_users_map = get_all_user_engagements_map()

        for user in categorized_users:
            try:
                action_time = datetime.strptime(user['latest_action_timestamp'], '%Y-%m-%d %H:%M:%S')
                # 既存の last_commented_at をユーザー情報に付与 (キーを 'id' に修正)
                existing_user_data = existing_users_map.get(user['id'])
                user['last_commented_at'] = existing_user_data.get('last_commented_at') if existing_user_data else None
                # 条件: 12時間以内で、かつDBの最新時刻より新しい
                if action_time > target_hours_ago and action_time > latest_db_timestamp:
                    users_to_process.append(user)
            except ValueError:
                logger.warning(f"ユーザー '{user.get('name')}' の不正な日付形式のタイムスタンプをスキップ: {user['latest_action_timestamp']}")
        
        logger.info(f"  -> {len(users_to_process)}人のユーザーが処理対象です。")

        if not users_to_process:
            logger.info("処理対象のユーザーが見つかりませんでした。")
            return True

        logger.info("優先度順にソートします。")
        sorted_users = sorted(
            users_to_process,
            key=lambda u: (
                # 0. 投稿対象フィルタ: 3日以内にコメント済みのユーザーは優先度を最低にする
                not ((datetime.strptime(u['last_commented_at'], '%Y-%m-%d %H:%M:%S') > three_days_ago) if u.get('last_commented_at') else False),
                
                # 1. AIプロンプトメッセージの内容に基づく優先度
                ("新規にフォローしてくれました" in u.get('ai_prompt_message', '') and "いいね" in u.get('ai_prompt_message', '')), # 新規フォロー＆いいね
                ("新規にフォローしてくれました" in u.get('ai_prompt_message', '')), # 新規フォローのみ
                ("常連の方です" in u.get('ai_prompt_message', '')), # いいね常連
                ("過去にも「いいね」をしてくれたことがあります" in u.get('ai_prompt_message', '')), # 過去にもいいね
                ("今回も" in u.get('ai_prompt_message', '')), # 今回いいねがあった
                
                # 3. 最終的な調整（累計いいね数が多いほど優先）
                u.get('like_count', 0),
            ),
            reverse=True # 降順ソート
        )
        
        # --- フェーズ4: URL取得 ---
        logger.info(f"--- フェーズ4: {len(sorted_users)}人のプロフィールURLを取得します。 ---")
        final_user_data = []
        last_scroll_position = 0  # スクロール位置を記憶する変数を初期化

        for i, user_info in enumerate(sorted_users):
            logger.debug(f"  {i+1}/{len(sorted_users)}: 「{user_info['name']}」のURLを取得中...")

            # DBにURLが既に存在するかチェック
            existing_user = existing_users_map.get(user_info['id'])
            if existing_user and existing_user.get('profile_page_url') and existing_user.get('profile_page_url') != '取得失敗':
                user_info['profile_page_url'] = existing_user['profile_page_url']
                logger.debug(f"  -> DBにURLが既に存在するためスキップ: {user_info['profile_page_url']}")
                final_user_data.append(user_info)
                continue

            try:
                # 前回のスクロール位置に戻す
                if last_scroll_position > 0:
                    page.evaluate(f"window.scrollTo(0, {last_scroll_position})")
                    page.wait_for_timeout(500) # 復元後の描画を少し待つ
                    logger.debug(f"  スクロール位置を {last_scroll_position}px に復元しました。")

                # ユーザーの通知アイテムを見つける
                # `has-text` は部分一致なので、正確なユーザー名で絞り込む
                user_li_locator = page.locator(f"li[ng-repeat='notification in notifications.activityNotifications']:has-text(\"{user_info['name']}\")").filter(has=page.locator(f"span.notice-name span.strong:text-is(\"{user_info['name']}\")")).first
                
                # 要素が見つかるまでスクロール
                max_scroll_attempts_find = 10 # 試行回数を調整
                is_found = False
                for attempt in range(max_scroll_attempts_find):
                    if user_li_locator.is_visible():
                        is_found = True
                        break
                    logger.debug(f"  ユーザー「{user_info['name']}」の要素が見つかりません。スクロールします... ({attempt + 1}/{max_scroll_attempts_find})")
                    page.evaluate("window.scrollBy(0, 500)")
                    page.wait_for_timeout(1000) # 少し待つ
                
                if not is_found:
                    logger.warning(f"スクロールしてもユーザー「{user_info['name']}」の要素が見つかりませんでした。スキップします。")
                    user_info['profile_page_url'] = "取得失敗"
                    final_user_data.append(user_info)
                    continue

                # sample.pyの成功ロジックに合わせて、プロフィール画像コンテナをクリックする
                # ページ遷移の直前に現在のスクロール位置を記憶
                last_scroll_position = page.evaluate("window.scrollY")
                image_container_locator = user_li_locator.locator("div.left-img")
                image_container_locator.click()
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                
                user_info['profile_page_url'] = page.url
                logger.debug(f"  -> 取得したURL: {page.url}")
                
                page.go_back(wait_until="domcontentloaded")
                page.wait_for_load_state("domcontentloaded", timeout=15000) # 戻ったページが完全にロードされるのを待つ
            except PlaywrightError as url_error:
                logger.warning(f"  ユーザー「{user_info['name']}」のURL取得中にPlaywrightエラー: {url_error}")
                self._take_screenshot_on_error(prefix=f"url_error_{user_info['id']}")
                user_info['profile_page_url'] = "取得失敗"
            except Exception as url_error:
                logger.warning(f"  ユーザー「{user_info['name']}」のURL取得中に予期せぬエラー: {url_error}")
                self._take_screenshot_on_error(prefix=f"url_error_{user_info['id']}")
                user_info['profile_page_url'] = "取得失敗"
            
            final_user_data.append(user_info)
            page.wait_for_timeout(random.uniform(0.5, 1.5)) # 人間らしい間隔

        logger.info("\n--- 分析完了: 処理対象ユーザー一覧 ---")
        for i, user in enumerate(final_user_data):
            logger.info(f"  {i+1:2d}. {user['name']:<20} (カテゴリ: {user['category']}, URL: {user.get('profile_page_url', 'N/A')})")
        logger.info("------------------------------------")

        # --- フェーズ5: コメント生成 ---
        logger.info(f"--- フェーズ5: {len(final_user_data)}人のユーザーにコメントを紐付けます。 ---")
        # --- フェーズ5: AIプロンプトメッセージとコメントの生成 ---
        logger.info(f"--- フェーズ5: {len(final_user_data)}人のユーザーにAIプロンプトメッセージとコメントを紐付けます。 ---")
        try:
            comment_templates = {}
            if os.path.exists(COMMENT_TEMPLATES_FILE):
                with open(COMMENT_TEMPLATES_FILE, 'r', encoding='utf-8') as f:
                    comment_templates = json.load(f)
                comment_templates["高スコアユーザ（連コメOK）"] = comment_templates.get("いいね多謝", ["いつもありがとうございます！"]) # 高スコアユーザ用のテンプレートをいいね多謝から流用
            else:
                logger.warning(f"コメントテンプレートファイルが見つかりません: {COMMENT_TEMPLATES_FILE}。デフォルトのテンプレートを使用します。")
                comment_templates = {
                    "コメント感謝": ["{user_name}さん、コメントありがとうございます！とても嬉しいです。", "素敵なコメント、{user_name}さん、ありがとうございます！"],
                    "いいね多謝": ["{user_name}さん、たくさんのいいね、ありがとうございます！", "いつもいいね、ありがとうございます！{user_name}さんのROOMも拝見させていただきますね。"],
                    "新規フォロー＆いいね感謝": ["{user_name}さん、フォローといいね、ありがとうございます！", "フォローといいね、{user_name}さん、ありがとうございます！これからもよろしくお願いします。"],
                    "未フォロー＆いいね感謝": ["{user_name}さん、いいね、ありがとうございます！", "いいね、ありがとうございます！{user_name}さんのROOMも覗かせていただきますね。"],
                    "いいね＆コレ！感謝": ["{user_name}さん、いいねとコレ！、ありがとうございます！", "いいねとコレ！、{user_name}さん、ありがとうございます！"],
                    "新規フォロー": ["{user_name}さん、フォローありがとうございます！", "フォローありがとうございます！{user_name}さんのROOMも楽しみにしています。"],
                    "いいね感謝": ["{user_name}さん、いいね、ありがとうございます！", "いいね、ありがとうございます！"],
                    "その他": ["ご訪問ありがとうございます！"],
                    "高スコアユーザ（連コメOK）": ["{user_name}さん、いつも本当にありがとうございます！", "いつもたくさんの反応、感謝しています！"]
                }
            
            for user in final_user_data:
                # AI向けの状況説明メッセージを生成
                prompt_message = ""
                messages = []
                total_likes = user.get('like_count', 0)
                recent_likes = user.get('recent_like_count', 0)
                # 累計フォロー数が1回、かつ今回のアクションでフォローがあった場合を「新規フォロー」とみなす
                is_new_follow = user.get('follow_count', 0) == 1 and any("あなたをフォローしました" in n['action_text'] for n in all_notifications if n['id'] == user['id'])
                is_following_me = user.get('is_following', False)

                # 1. フォロー関係
                if is_new_follow:
                    messages.append("新規にフォローしてくれました。")
                elif is_following_me:
                    messages.append("以前からフォローしてくれているユーザーです。")
                else:
                    messages.append("まだフォローされていないユーザーです。")

                # 2. いいね関係
                if recent_likes > 0:
                    if total_likes > 10:
                        messages.append("いつもたくさんの「いいね」をくれる常連の方です。")
                    elif total_likes > recent_likes:
                        messages.append("過去にも「いいね」をしてくれたことがあります。")
                    messages.append(f"今回も{recent_likes}件の「いいね」をしてくれました。")

                user['ai_prompt_message'] = " ".join(messages)
                user['ai_prompt_updated_at'] = datetime.now().isoformat()

                # comment_textがまだ設定されていない場合のみ、テンプレートから初期コメントを生成
                if not user.get('comment_text'):
                    category = user.get('category', 'その他')
                    templates = comment_templates.get(category, comment_templates.get('その他', []))
                    if templates:
                        comment_template = random.choice(templates)
                        natural_name = extract_natural_name(user.get('name', ''))
                        # 名前が取得でき、かつ適切な長さの場合のみ名前を挿入
                        if natural_name and 1 <= len(natural_name) <= 6: # 1文字以上6文字以下
                            user['comment_text'] = comment_template.format(user_name=natural_name)
                        else:
                            # 名前が取得できなかったり長すぎる場合は、プレースホルダー部分を削除して不自然さをなくす
                            user['comment_text'] = comment_template.replace("{user_name}さん、", "").replace("{user_name}さん", "").strip()
                    else:
                        user['comment_text'] = "ご訪問ありがとうございます！" # フォールバック
        except Exception as e:
            logger.error(f"コメント生成中にエラーが発生しました: {e}")
            self._take_screenshot_on_error(prefix="comment_gen_error")

        # --- フェーズ6: 結果をDBに保存 ---
        try:
            # 1. 既存DBのデータを取得（last_commented_at を保持するため）
            existing_users_map = get_all_user_engagements_map()

            # 2. 新しいデータと既存データをマージ
            logger.info(f"--- フェーズ6: {len(final_user_data)}件の新規・更新データをDBに保存します。 ---")
            data_to_save = []
            for user_data in final_user_data:
                user_id_val = user_data['id']
                # 既存のレコードがあれば、last_commented_at を引き継ぐ
                if user_id_val in existing_users_map:
                    # 既存のcomment_textも引き継ぐ
                    user_data['comment_text'] = user_data.get('comment_text') or existing_users_map[user_id_val].get('comment_text')
                    user_data['last_commented_at'] = existing_users_map[user_id_val].get('last_commented_at')
                
                data_to_save.append(user_data)

            # 3. DBに一括で挿入/更新 (UPSERT)
            if data_to_save:
                upserted_count = bulk_upsert_user_engagements(data_to_save)
                logger.info(f"{upserted_count}件のユーザーエンゲージメントデータをDBに保存/更新しました。")

            # 4. 1ヶ月以上前の古いデータをクリーンアップ
            cleanup_old_user_engagements(days=30)

            return True
        except Exception as e:
            logger.error(f"データベースへの保存中にエラーが発生しました: {e}", exc_info=True)
            self._take_screenshot_on_error(prefix="db_save_error")
            return False

def run_notification_analyzer(hours_ago: int = 12):
    """ラッパー関数"""
    task = NotificationAnalyzerTask(hours_ago=hours_ago)
    return task.run()