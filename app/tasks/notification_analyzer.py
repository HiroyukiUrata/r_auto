import logging
import os
import re
import json
import unicodedata
from datetime import datetime, timedelta
import random
from playwright.sync_api import Page, Locator
from playwright.sync_api import Error as PlaywrightError

from app.core.base_task import BaseTask
from app.core.config_manager import SCREENSHOT_DIR # For error screenshots
from app.core.database import (
    get_latest_engagement_timestamp,
    get_all_user_engagements_map,
    bulk_upsert_user_engagements,
    bulk_update_user_profiles,
    cleanup_old_user_engagements,
    get_users_for_url_acquisition,
    get_users_for_prompt_creation,
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
        # このタスクはヘッドレスモードではスクロールが不安定なため、常にOFFにする
        self.force_non_headless = True

    def _scroll_to_bottom_and_collect_items(self, page: Page) -> Locator:
        """
        お知らせページを最後までスクロールし、すべての通知アイテムのLocatorを返す。
        このメソッドはスクロール処理にのみ責任を持つ。
        """
        # --- スクロール停止条件の準備 ---
        latest_db_timestamp = get_latest_engagement_timestamp()
        # ユーザーの指定時間に1時間のバッファを加えて、より確実にデータを取得する
        buffer_hours = self.hours_ago + 1
        target_hours_ago = datetime.now() - timedelta(hours=buffer_hours)
        logger.debug(f"スクロール停止条件: DB最新時刻 ({latest_db_timestamp.strftime('%Y-%m-%d %H:%M:%S') if latest_db_timestamp > datetime.min else 'なし'}) または 約{self.hours_ago}時間前 ({target_hours_ago.strftime('%Y-%m-%d %H:%M:%S')})")

        # --- ループによる自動スクロール処理 ---
        logger.debug("条件に合致するまでアクティビティをスクロールして読み込みます...")
        last_count = 0
        no_change_count = 0 # 件数に変化がなかった回数をカウント
        for attempt in range(100): # 最大100回まで試行
            notification_list_items = page.locator("li[ng-repeat='notification in notifications.activityNotifications']")
            current_count = notification_list_items.count()

            if attempt > 0 and current_count == last_count:
                no_change_count += 1
            else:
                no_change_count = 0 # 件数が増えたらリセット

            # 10回連続で件数に変化がなければ、ページの終端とみなす
            if no_change_count >= 10:
                logger.debug("10回連続でスクロールしても新しい通知は読み込まれませんでした。")
                break

            last_count = current_count
            #logger.debug(f"  スクロール {attempt + 1}回目: {current_count}件のアクティビティ通知を検出。")
            
            page.evaluate("window.scrollBy(0, 500)")
            
            # 新しい要素が読み込まれるのを、DOMの変化を監視して待つ
            try:
                page.wait_for_function(
                    f"document.querySelectorAll(\"li[ng-repeat='notification in notifications.activityNotifications']\").length > {last_count}",
                    timeout=7000  # 7秒待っても増えなければタイムアウト
                )
                #logger.debug("  -> 新しい通知が読み込まれました。")
            except PlaywrightError:
                pass
                #logger.debug("  -> 待機時間が経過しましたが、新しい通知は読み込まれませんでした。")

            # --- 時刻ベースの停止条件 ---
            last_item_timestamp_str = notification_list_items.last.locator("span.notice-time").get_attribute("title")
            if last_item_timestamp_str:
                try:
                    last_item_time = datetime.strptime(last_item_timestamp_str, '%Y-%m-%d %H:%M:%S')
                    if last_item_time < target_hours_ago:
                        logger.debug(f"最終通知時刻が約{self.hours_ago}時間前を下回ったため、スクロールを停止します。")
                        break
                    if last_item_time < latest_db_timestamp:
                        logger.debug("最終通知時刻がDBの最新時刻を下回ったため、スクロールを停止します。")
                        break
                except (ValueError, TypeError):
                    logger.warning(f"タイムスタンプの解析に失敗しました: {last_item_timestamp_str}")

        logger.debug(f"スクロール完了。最終的な通知件数: {last_count}件")
        return page.locator("li[ng-repeat='notification in notifications.activityNotifications']")

    def _execute_main_logic(self):
        page = self.page # BaseTaskが提供するpageオブジェクトを使用

        logger.debug(f"楽天ROOMのトップページにアクセスします。")
        page.goto("https://room.rakuten.co.jp/items", wait_until="domcontentloaded")

        logger.debug("「お知らせ」リンクを探してクリックします。")
        try:
            page.get_by_role("link", name="お知らせ").click()
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            logger.debug(f"お知らせページに遷移しました: {page.url}")
        except PlaywrightError as e:
            logger.error(f"「お知らせ」リンクのクリックまたはページ遷移中にエラーが発生しました: {e}")
            self._take_screenshot_on_error(prefix="notification_link_error")
            return False

        # --- 2. 無限スクロールによる情報収集 ---
        logger.debug("「アクティビティ」セクションをスクロールして情報を収集します。")
        activity_title_locator = page.locator("div.title[ng-show='notifications.activityNotifications.length > 0']")
        try:
            activity_title_locator.wait_for(state='attached', timeout=10000)
        except PlaywrightError:
            logger.debug("「アクティビティ」セクションが見つかりませんでした。処理対象はありません。")
            return True # エラーではないのでTrueを返す

        # 修正: 最初の通知リスト項目が表示されるまで待機する
        try:
            first_notification_item = page.locator("li[ng-repeat='notification in notifications.activityNotifications']").first
            first_notification_item.wait_for(state='visible', timeout=15000)
        except PlaywrightError:
            logger.debug("アクティビティのタイトルはありますが、通知リストが見つかりませんでした。処理対象はありません。")
            return True

        # --- ステップ1: スクロール処理を呼び出し、全通知アイテムを取得 ---
        notification_list_items = self._scroll_to_bottom_and_collect_items(page)

        # --- 3. データ抽出 ---
        logger.debug(f"--- フェーズ1: {notification_list_items.count()}件の通知から基本情報を収集します。 ---")
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
                    action_timestamp_str = item.locator("span.notice-time").first.get_attribute("title")
                    
                    # タイムスタンプをISO 8601形式に統一
                    action_timestamp_iso = action_timestamp_str
                    if action_timestamp_str:
                        try:
                            action_timestamp_iso = datetime.strptime(action_timestamp_str, '%Y-%m-%d %H:%M:%S').isoformat()
                        except (ValueError, TypeError):
                            logger.warning(f"不正な日付形式のため、元の値を保持します: {action_timestamp_str}")
                    
                    # 「未フォロー」ボタンが存在しない、または非表示であればフォロー中と判断
                    is_following = not item.locator("span.follow:has-text('未フォロー')").is_visible()

                    all_notifications.append({
                        'id': user_id, 'name': user_name, 'profile_image_url': profile_image_url,
                        'action_text': action_text, 'action_timestamp': action_timestamp_iso, 'is_following': is_following
                    })
            except PlaywrightError as item_error:
                logger.warning(f"通知アイテムの取得中にPlaywrightエラー: {item_error}")
            except Exception as item_error:
                logger.warning(f"通知アイテムの取得中に予期せぬエラー: {item_error}")

        # --- フェーズ2: ユーザー単位で情報を集約し、過去データと合算 ---
        logger.debug(f"--- フェーズ2: {len(all_notifications)}件の通知をユーザー単位で集約します。 ---")
        aggregated_users = {}
        for notification in all_notifications:
            user_id_val = notification['id']
            if user_id_val not in aggregated_users:
                aggregated_users[user_id_val] = {
                    'id': user_id_val, 'name': notification['name'],
                    'profile_image_url': notification['profile_image_url'],
                    'recent_like_count': 0, 'recent_collect_count': 0,
                    'recent_comment_count': 0, 'recent_follow_count': 0,
                    'is_following': notification['is_following'],
                    'recent_action_timestamp': notification['action_timestamp'],
                }
            
            # 各アクションのカウントを更新
            if "いいねしました" in notification['action_text']:
                aggregated_users[user_id_val]['recent_like_count'] += 1
            if "コレ！しました" in notification['action_text']:
                aggregated_users[user_id_val]['recent_collect_count'] += 1
            if "あなたをフォローしました" in notification['action_text']:
                aggregated_users[user_id_val]['recent_follow_count'] += 1
            if "あなたの商品にコメントしました" in notification['action_text']:
                aggregated_users[user_id_val]['recent_comment_count'] += 1

            # 最新のアクションタイムスタンプを更新
            # 既存のタイムスタンプと比較し、新しい方で上書きする
            current_ts = aggregated_users[user_id_val]['recent_action_timestamp']
            new_ts = notification['action_timestamp']
            if new_ts > current_ts:
                aggregated_users[user_id_val]['recent_action_timestamp'] = notification['action_timestamp']

        logger.debug(f"  -> {len(aggregated_users)}人のユニークユーザーに集約しました。")

        # --- フェーズ3: DBへの一次保存 ---
        logger.debug(f"--- フェーズ3: {len(aggregated_users)}件の集約データをDBに保存します。 ---")
        if aggregated_users:
            upserted_count = bulk_upsert_user_engagements(list(aggregated_users.values()))
            logger.debug(f"{upserted_count}件のユーザーエンゲージメントデータをDBに保存/更新しました。")

        # --- フェーズ4: URL取得 ---
        logger.debug(f"--- フェーズ4: DBからURL未取得のユーザーを対象にURLを取得します。 ---")
        users_for_url_fetch = get_users_for_url_acquisition()
        logger.debug(f"URL取得対象: {len(users_for_url_fetch)}人")
        last_scroll_position = 0  # スクロール位置を記憶する変数を初期化

        total_users = len(users_for_url_fetch)
        for i, user_data in enumerate(users_for_url_fetch):
            # プログレスバーを表示
            self._print_progress_bar(i, total_users, prefix=f'URL取得中:', suffix=f"{user_data['name'][:15]:<15}")

            try:
                # 前回のスクロール位置に戻す
                if last_scroll_position > 0:
                    page.evaluate(f"window.scrollTo(0, {last_scroll_position})")
                    page.wait_for_timeout(500) # 復元後の描画を少し待つ
                    logger.debug(f"  スクロール位置を {last_scroll_position}px に復元しました。")

                # ユーザーの通知アイテムを見つける
                user_li_locator = page.locator(f"li[ng-repeat='notification in notifications.activityNotifications']:has-text(\"{user_data['name']}\")").filter(has=page.locator(f"span.notice-name span.strong:text-is(\"{user_data['name']}\")")).first
                
                # 要素が見つかるまでスクロール
                is_found = False
                for attempt in range(100):
                    if user_li_locator.is_visible():
                        is_found = True
                        break
                    #logger.debug(f"  ユーザー「{user_data['name']}」の要素が見つかりません。スクロールします... ({attempt + 1}/30)")
                    page.evaluate("window.scrollBy(0, 500)")
                    last_scroll_position = page.evaluate("window.scrollY")
                    page.wait_for_timeout(1000)
                
                if not is_found:
                    logger.warning(f"スクロールしてもユーザー「{user_data['name']}」の要素が見つかりませんでした。スキップします。")
                    user_data['profile_page_url'] = '取得失敗' # 取得失敗を記録
                    bulk_update_user_profiles([user_data]) # 失敗したことを記録
                    continue

                # ページ遷移の直前に現在のスクロール位置を記憶
                last_scroll_position = page.evaluate("window.scrollY")
                image_container_locator = user_li_locator.locator("div.left-img")
                image_container_locator.click()
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                
                user_data['profile_page_url'] = page.url
                logger.debug(f"  -> 取得したURL: {page.url}")
                
                page.go_back(wait_until="domcontentloaded")
                # networkidleは不安定なため、固定時間待機に変更
                page.wait_for_timeout(1000) # 軽く待つ
                # ページが戻った後、リストが再描画されるのを待つ
                page.locator("li[ng-repeat='notification in notifications.activityNotifications']").first.wait_for(state='visible', timeout=10000)
            except PlaywrightError as url_error:
                logger.warning(f"  ユーザー「{user_data['name']}」のURL取得中にPlaywrightエラー: {url_error}")
                self._take_screenshot_on_error(prefix=f"url_error_{user_data['id']}")
                continue
            except Exception as url_error:
                logger.warning(f"  ユーザー「{user_data['name']}」のURL取得中に予期せぬエラー: {url_error}")
                self._take_screenshot_on_error(prefix=f"url_error_{user_data['id']}")
                continue
            
            bulk_update_user_profiles([user_data]) # 1件ずつDBに保存
            page.wait_for_timeout(random.uniform(0.5, 1.5))

        # プログレスバーの行をクリア
        if total_users > 0:
            # 最終状態を表示して完了させる
            self._print_progress_bar(total_users, total_users, prefix='URL取得完了', suffix=' ' * 20)


        # --- フェーズ5: AIプロンプトメッセージの生成 ---
        logger.debug(f"--- フェーズ5: DBから対象ユーザーを取得し、AIプロンプトメッセージを生成します。 ---")
        users_for_prompt_creation = get_users_for_prompt_creation()
        logger.debug(f"AIプロンプト作成対象: {len(users_for_prompt_creation)}人")

        for user in users_for_prompt_creation:
            # AI向けの状況説明メッセージを生成
            messages = []
            total_likes = user.get('like_count', 0)
            recent_likes = user.get('recent_like_count', 0)
            follow_count = user.get('follow_count', 0)
            recent_follow_count = user.get('recent_follow_count', 0)
            # 今回のセッションでフォローがあったかどうかで判定
            is_new_follow = recent_follow_count > 0

            # 1. フォロー関係
            if is_new_follow:
                messages.append("新規にフォローしてくれました。")
            elif follow_count > recent_follow_count:
                messages.append("以前からフォローしてくれているユーザーです。")
            else:
                pass
                #messages.append("まだフォローされていないユーザーです。")

            # 2. いいね関係
            if recent_likes > 0:
                # 過去にもアクションがあるか (total_likes > recent_likes) で分岐
                if total_likes > recent_likes:
                    if total_likes > 10:
                        messages.append("いつもたくさんの「いいね」をくれる常連の方です。")
                    else:
                        messages.append("過去にも「いいね」をしてくれたことがあります。")
                    messages.append(f"今回も{recent_likes}件の「いいね」をしてくれました。")
                else:  # 今回が初めての「いいね」の場合
                    messages.append(f"今回、新たに{recent_likes}件の「いいね」をしてくれました。")


            user['ai_prompt_message'] = " ".join(messages)
            user['ai_prompt_updated_at'] = datetime.now().isoformat()

        # --- フェーズ6: AIプロンプトメッセージをDBに保存 ---
        logger.debug(f"--- フェーズ6: {len(users_for_prompt_creation)}件のAIプロンプトメッセージをDBに保存します。 ---")
        try:
            if users_for_prompt_creation:
                upserted_count = bulk_update_user_profiles(users_for_prompt_creation)
                logger.debug(f"{upserted_count}件のAIプロンプトメッセージをDBに保存/更新しました。")
            
            cleanup_old_user_engagements(days=30)
        except Exception as e:
            logger.error(f"データベースへの保存中にエラーが発生しました: {e}", exc_info=True)
            self._take_screenshot_on_error(prefix="db_save_error")
            return False
        
        logger.debug("検証タスクの全フェーズが正常に完了しました。")
        return True

def run_notification_analyzer(hours_ago: int = 12):
    """ラッパー関数"""
    task = NotificationAnalyzerTask(hours_ago=hours_ago)
    return task.run()