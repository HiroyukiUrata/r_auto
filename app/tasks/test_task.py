import logging
from playwright.sync_api import Error as PlaywrightError
import random
import re
from playwright.sync_api import Page, Locator
from app.core.base_task import BaseTask
from app.core.database import get_latest_engagement_timestamp, get_all_user_engagements_map, bulk_upsert_user_engagements, cleanup_old_user_engagements
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class TestTask(BaseTask):
    """
    通知分析のスクロールロジックを段階的に検証するための軽量タスク。
    お知らせページに遷移し、スクロール直前までの動作を確認する。
    """
    def __init__(self):
        super().__init__()
        self.action_name = "【検証用】スクロールテスト"
        self.needs_browser = True
        # TODO: 本番適用時は12時間に戻す
        self.hours_ago = 12 # 検証用に3時間に設定
        self.use_auth_profile = True

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
        #logger.debug("条件に合致するまでアクティビティをスクロールして読み込みます...")
        last_count = 0
        no_change_count = 0 # 件数に変化がなかった回数をカウント
        for attempt in range(50): # 最大50回まで試行
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
            page.wait_for_timeout(7000) # 読み込みに時間がかかるため、7秒待機

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
        page = self.page

        logger.debug("楽天ROOMのトップページにアクセスします。")
        page.goto("https://room.rakuten.co.jp/items", wait_until="domcontentloaded")

        logger.debug("「お知らせ」リンクを探してクリックします。")
        try:
            page.get_by_role("link", name="お知らせ").click()
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            logger.debug(f"お知らせページに遷移しました: {page.url}")
        except PlaywrightError as e:
            logger.error(f"ページ遷移中にエラーが発生しました: {e}")
            self._take_screenshot_on_error(prefix="test_task_nav_error")
            return False

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

        # --- ステップ2: 取得したアイテムから情報を抽出 ---
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
                    
                    if user_id == "unknown":
                        logger.debug(f"ユーザー「{user_name}」のユーザーIDを特定できませんでした。スキップします。")
                        continue

                    action_text = item.locator("div.right-text > p").first.inner_text()
                    action_timestamp_str = item.locator("span.notice-time").first.get_attribute("title")
                    
                    action_timestamp_iso = action_timestamp_str
                    if action_timestamp_str:
                        try:
                            action_timestamp_iso = datetime.strptime(action_timestamp_str, '%Y-%m-%d %H:%M:%S').isoformat()
                        except (ValueError, TypeError):
                            logger.warning(f"不正な日付形式のため、元の値を保持します: {action_timestamp_str}")
                    
                    is_following = not item.locator("span.follow:has-text('未フォロー')").is_visible()

                    all_notifications.append({
                        'id': user_id, 'name': user_name, 'profile_image_url': profile_image_url,
                        'action_text': action_text, 'action_timestamp': action_timestamp_iso, 'is_following': is_following
                    })
            except PlaywrightError as item_error:
                logger.warning(f"通知アイテムの取得中にPlaywrightエラー: {item_error}")
            except Exception as item_error:
                logger.warning(f"通知アイテムの取得中に予期せぬエラー: {item_error}")

        logger.info(f"情報抽出完了。{len(all_notifications)}件の通知を処理しました。")

        # --- ステップ3: 取得した通知をユーザー単位で集約 ---
        logger.debug(f"--- フェーズ2: {len(all_notifications)}件の通知をユーザー単位で集約します。 ---")
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

            # 最新のアクションタイムスタンプを更新
            current_ts = aggregated_users[user_id_val]['recent_action_timestamp']
            new_ts = notification['action_timestamp']
            if new_ts > current_ts:
                aggregated_users[user_id_val]['recent_action_timestamp'] = notification['action_timestamp']
        
        logger.info(f"集約完了。{len(aggregated_users)}人のユニークユーザーに集約しました。")

        # --- ステップ4: 時間条件でフィルタリングし、優先度順にソート ---
        logger.debug(f"--- フェーズ3: 時間条件でユーザーをフィルタリングします。 ---")
        
        latest_db_timestamp = get_latest_engagement_timestamp()
        target_hours_ago = datetime.now() - timedelta(hours=self.hours_ago)
        three_days_ago = datetime.now() - timedelta(days=3)
        
        logger.debug(f"  - DBの最新時刻: {latest_db_timestamp.strftime('%Y-%m-%d %H:%M:%S') if latest_db_timestamp > datetime.min else '（データなし）'}")
        logger.debug(f"  - {self.hours_ago}時間前の時刻: {target_hours_ago.strftime('%Y-%m-%d %H:%M:%S')}")

        users_to_process = []
        existing_users_map = get_all_user_engagements_map()

        for user in aggregated_users.values():
            try:
                action_time_str = user.get('recent_action_timestamp')
                if not action_time_str:
                    continue
                user['latest_action_timestamp'] = action_time_str
                action_time = datetime.fromisoformat(action_time_str)
                existing_user_data = existing_users_map.get(user['id'])
                user['last_commented_at'] = existing_user_data.get('last_commented_at') if existing_user_data else None
                
                if (action_time > target_hours_ago and 
                    action_time > latest_db_timestamp and 
                    (user.get('recent_like_count', 0) > 0 or 
                     user.get('recent_collect_count', 0) > 0 or 
                     user.get('recent_comment_count', 0) > 0)):
                    users_to_process.append(user)
            except (ValueError, TypeError) as e:
                logger.warning(f"ユーザー '{user.get('name')}' の不正な日付形式のタイムスタンプをスキップ: {user.get('latest_action_timestamp')} - {e}")
        
        logger.info(f"フィルタリング完了。{len(users_to_process)}人のユーザーが処理対象です。")

        if not users_to_process:
            logger.info("処理対象のユーザーが見つかりませんでした。タスクを終了します。")
            return True

        logger.debug("優先度順にソートします。")
        sorted_users = sorted(
            users_to_process,
            key=lambda u: (
                not ((datetime.fromisoformat(u['last_commented_at']) > three_days_ago) if u.get('last_commented_at') else False),
                (u.get('recent_like_count', 0) >= 5 and u.get('like_count', 0) > u.get('recent_like_count', 0)),
            ),
            reverse=True
        )
        logger.info(f"ソート完了。最終的な処理対象ユーザー: {len(sorted_users)}人")

        # --- ステップ5: URL取得とAIプロンプト生成のシミュレーション ---
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
                user_li_locator = page.locator(f"li[ng-repeat='notification in notifications.activityNotifications']:has-text(\"{user_info['name']}\")").filter(has=page.locator(f"span.notice-name span.strong:text-is(\"{user_info['name']}\")")).first
                
                # 要素が見つかるまでスクロール
                is_found = False
                for attempt in range(100):
                    if user_li_locator.is_visible():
                        is_found = True
                        break
                    logger.debug(f"  ユーザー「{user_info['name']}」の要素が見つかりません。スクロールします... ({attempt + 1}/30)")
                    page.evaluate("window.scrollBy(0, 500)")
                    last_scroll_position = page.evaluate("window.scrollY")
                    page.wait_for_timeout(1000)
                
                if not is_found:
                    logger.warning(f"スクロールしてもユーザー「{user_info['name']}」の要素が見つかりませんでした。スキップします。")
                    user_info['profile_page_url'] = "取得失敗"
                    final_user_data.append(user_info)
                    continue

                # ページ遷移の直前に現在のスクロール位置を記憶
                last_scroll_position = page.evaluate("window.scrollY")
                image_container_locator = user_li_locator.locator("div.left-img")
                image_container_locator.click()
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                
                user_info['profile_page_url'] = page.url
                logger.debug(f"  -> 取得したURL: {page.url}")
                
                page.go_back(wait_until="domcontentloaded")
                # networkidleは不安定なため、固定時間待機に変更
                page.wait_for_timeout(1000) # 軽く待つ
                # ページが戻った後、リストが再描画されるのを待つ
                page.locator("li[ng-repeat='notification in notifications.activityNotifications']").first.wait_for(state='visible', timeout=10000)
            except PlaywrightError as url_error:
                logger.warning(f"  ユーザー「{user_info['name']}」のURL取得中にPlaywrightエラー: {url_error}")
                self._take_screenshot_on_error(prefix=f"url_error_{user_info['id']}")
                continue
            except Exception as url_error:
                logger.warning(f"  ユーザー「{user_info['name']}」のURL取得中に予期せぬエラー: {url_error}")
                self._take_screenshot_on_error(prefix=f"url_error_{user_info['id']}")
                continue
            
            final_user_data.append(user_info)
            page.wait_for_timeout(random.uniform(0.5, 1.5))
            
        logger.info("\n--- 分析完了: 処理対象ユーザー一覧 ---")
        for i, user in enumerate(final_user_data):
            logger.info(f"  {i+1:2d}. {user['name']:<20} (URL: {user.get('profile_page_url', 'N/A')})")
        logger.info("------------------------------------")

        logger.info(f"--- フェーズ5: {len(final_user_data)}人のユーザーにAIプロンプトメッセージを紐付けます。 ---")
        for user in final_user_data:
            messages = []
            # 累計いいね数を取得 (DBに保存されていないので、recent_like_countを代用)
            total_likes = user.get('like_count', 0) or user.get('recent_like_count', 0)
            recent_likes = user.get('recent_like_count', 0)
            
            # is_new_followの判定 (all_notificationsが必要だが、このテストでは簡略化)
            is_new_follow = user.get('follow_count', 0) > 0
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
                if total_likes > recent_likes:
                    if total_likes > 10:
                        messages.append("いつもたくさんの「いいね」をくれる常連の方です。")
                    else:
                        messages.append("過去にも「いいね」をしてくれたことがあります。")
                    messages.append(f"今回も{recent_likes}件の「いいね」をしてくれました。")
                else:
                    messages.append(f"今回、新たに{recent_likes}件の「いいね」をしてくれました。")

            user['ai_prompt_message'] = " ".join(messages)
            user['ai_prompt_updated_at'] = datetime.now().isoformat()
            logger.debug(f"  - {user['name']}: {user['ai_prompt_message']}")

        # --- ステップ6: DB保存のシミュレーション ---
        # TODO: 本番適用時は if False を削除
        if True:
            logger.info(f"--- フェーズ6: {len(final_user_data)}件の新規・更新データをDBに保存します。 ---")
            try:
                data_to_save = []
                for user_data in final_user_data:
                    user_id_val = user_data['id']
                    if user_id_val in existing_users_map:
                        user_data['comment_text'] = user_data.get('comment_text') or existing_users_map[user_id_val].get('comment_text')
                        user_data['last_commented_at'] = existing_users_map[user_id_val].get('last_commented_at')
                    data_to_save.append(user_data)

                if data_to_save:
                    upserted_count = bulk_upsert_user_engagements(data_to_save)
                    logger.info(f"{upserted_count}件のユーザーエンゲージメントデータをDBに保存/更新しました。")

                cleanup_old_user_engagements(days=30)
            except Exception as e:
                logger.error(f"データベースへの保存中にエラーが発生しました: {e}", exc_info=True)
                self._take_screenshot_on_error(prefix="db_save_error")
                return False
        
        logger.info("検証タスクの全フェーズが正常に完了しました。")
        return True

def run_test_task():
    """ラッパー関数"""
    task = TestTask()
    return task.run()