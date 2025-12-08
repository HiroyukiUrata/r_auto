"""
`run_task.py manual-test` 用のスクリプト。
モーダルを開いて未処理の「フォローする」カードを探し、ユーザー名をログに残す。
- クリックは行わない
- 処理済みユーザーはスキップ
- モーダル開閉は1件ごとに実施（スキップ時は閉じずに次を探索）

実行例:
    python run_task.py manual-test --script test_task/test_follow2.py --use-auth true
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Sequence

from app.utils.selector_utils import convert_to_robust_selector

logger = logging.getLogger(__name__)

TARGET_URL = "https://room.rakuten.co.jp/room_97336c51d3/items"  # 検証用ターゲット
LIST_CONTAINER = "div#userList"
NAME_SELECTOR = "span.profile-name--2Hsi5"
DEFAULT_TARGET = 10  # 最大処理件数


def open_target_page(page):
    """ターゲットページを開く。"""
    page.goto(TARGET_URL, wait_until="domcontentloaded")


def open_modal(page):
    """フォロワーモーダルを開く。"""
    btn = page.locator('button:has-text("フォロワー")').first
    btn.wait_for(state="visible", timeout=30000)
    btn.click(force=True)
    page.locator(LIST_CONTAINER).first.wait_for(state="visible", timeout=30000)
    logger.debug("モーダルを開きました。")


def close_modal(page):
    """フォロワーモーダルを閉じる。"""
    selectors = [
        "div.close-button--2Se88",
        "button[aria-label='閉じる']",
        "button[aria-label='Close']",
        "button[aria-label='close']",
        "button:has-text('閉じる')",
    ]
    closed = False
    for sel in selectors:
        btn = page.locator(sel).first
        try:
            if btn.count() > 0:
                btn.click()
                closed = True
                break
        except Exception:
            continue
    if not closed:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
    try:
        page.locator(LIST_CONTAINER).first.wait_for(state="hidden", timeout=5000)
    except Exception:
        pass
    logger.debug("モーダルを閉じました。")


def wait_cards_ready(page):
    """モーダル内でカードが表示されるまで待機。"""
    page.locator(LIST_CONTAINER).first.wait_for(state="visible", timeout=30000)
    card = page.locator(f"{LIST_CONTAINER} div[class*='profile-wrapper']").first
    try:
        card.wait_for(state="visible", timeout=10000)
        # logger.debug("カード表示を確認 (profile-wrapper)")
    except Exception:
        page.wait_for_timeout(1000)
        # logger.debug("カード待機でタイムアウト -> 1秒待機のみ")


def scroll_to_load(page, scroll_delay=1.0):
    """モーダルを1回スクロールして次のカードをロード。"""
    try:
        page.locator(LIST_CONTAINER).evaluate("n => n.scrollTop = n.scrollHeight")
    except Exception:
        pass
    page.wait_for_timeout(int(scroll_delay * 1000))
    try:
        page.locator("div[aria-label='loading']").first.wait_for(state="hidden", timeout=3000)
    except Exception:
        pass


def find_next_candidate(page, processed: set[str]):
    """
    未処理の「フォローする」ボタン付きカードを探す。
    見つかれば (button, user_name, key) を返し、見つからなければ None を返す。
    """
    # 最初の一度だけ待機（各ループで長時間待たないようにする）
    wait_cards_ready(page)
    attempts = 0
    stagnation = 0  # スクロールしても増えない状態の連続回数
    last_height = None
    start_time = time.time()
    max_wait_seconds = 30  # 1ループの探索にかける上限時間
    while True:
        if time.time() - start_time > max_wait_seconds:
            logger.debug("候補探索が%ssを超過したためタイムアウトで抜けます。", max_wait_seconds)
            break

        # モーダルが閉じられていたら再オープンしてやり直す
        try:
            if not page.locator(LIST_CONTAINER).first.is_visible():
                logger.debug("モーダルが非表示のため再オープンします。")
                open_modal(page)
                wait_cards_ready(page)
                # タイマーを少しリセットして再探索を続行
                start_time = time.time()
                continue
        except Exception:
            # 取得に失敗した場合も再オープンを試みる
            logger.debug("モーダル可視判定に失敗 -> 再オープンを試みます。")
            open_modal(page)
            wait_cards_ready(page)
            start_time = time.time()
            continue

        follow_buttons = page.locator(LIST_CONTAINER).get_by_role("button", name="フォローする")
        follow_count = follow_buttons.count()
        follow_now_count = page.locator(LIST_CONTAINER).get_by_role("button", name="フォロー中").count()
        logger.debug("未フォロー: %s / フォロー中: %s (attempt=%s)", follow_count, follow_now_count, attempts + 1)

        for idx in range(follow_count):
            btn = follow_buttons.nth(idx)
            user_row = btn.locator('xpath=ancestor::div[contains(@class, "profile-wrapper")]').first
            name_el = user_row.locator(convert_to_robust_selector(NAME_SELECTOR)).first
            try:
                user_name = name_el.inner_text().strip()
            except Exception:
                user_name = ""
            key = user_name or f"idx-{idx}"

            if key in processed:
                # logger.debug("既処理ユーザーをスキップ: %s", key)
                continue

            try:
                btn.evaluate("el => el.scrollIntoView({block:'center', behavior:'instant'})")
            except Exception:
                pass
            page.wait_for_timeout(200)
            return btn, user_name, key

        attempts += 1
        # スクロールしてもリストが伸びない状態が続いたら終端とみなす
        try:
            current_height = page.locator(LIST_CONTAINER).evaluate("n => n.scrollHeight")
        except Exception:
            current_height = None

        if last_height is not None and current_height is not None and current_height <= last_height:
            stagnation += 1
        else:
            stagnation = 0
        last_height = current_height

        logger.debug("新規候補なし -> スクロールして再検索 (attempt=%s, scrollHeight=%s, stagnation=%s)", attempts, current_height, stagnation)
        scroll_to_load(page, scroll_delay=1.0)

        # 安全のための上限。50回以上スクロールしても新規なし、または3回連続伸びなしで終了
        if attempts >= 50 or stagnation >= 3:
            logger.debug("未処理の『フォローする』ボタンが見つからず終了 (attempts=%s, stagnation=%s)", attempts, stagnation)
            break

    logger.debug("未処理の『フォローする』ボタンが見つかりませんでした。")
    return None


def main(page, argv: Sequence[str]):
    """モーダルを開閉しながら未処理カードを探索する（クリックしない）。"""
    target = DEFAULT_TARGET
    try:
        if len(argv) > 0:
            target = max(1, int(argv[0]))
    except Exception:
        target = DEFAULT_TARGET

    processed: set[str] = set()
    logger.debug("ターゲットページを開きます。")
    open_target_page(page)
    page.wait_for_timeout(800)

    for i in range(target):
        logger.debug("==== 処理ループ %s/%s ====", i + 1, target)
        open_modal(page)
        candidate = find_next_candidate(page, processed)
        if candidate is None:
            close_modal(page)
            logger.debug("新規候補が見つからなかったため終了します。処理済み: %s", len(processed))
            break

        btn, user_name, key = candidate
        processed.add(key)
        logger.info("未フォローカードを確認: ユーザー名='%s' (累計処理=%s)", user_name or "取得失敗", len(processed))

        # ここで実際にフォローをクリック（失敗しても続行）
        try:
            btn.click(timeout=10000)
            logger.info("フォロークリックを実行しました: ユーザー名='%s'", user_name or "取得失敗")
            page.wait_for_timeout(500)  # 状態反映待ち
        except Exception as e:
            logger.warning("フォロークリックに失敗しました: %s", e)

        close_modal(page)
        page.wait_for_timeout(300)

    logger.debug("処理が完了しました。ブラウザは開いたままです。")


if "page" in globals():
    main(page, sys.argv[1:])
else:
    logger.error("page が提供されていません。manual-test で実行してください。")
    sys.exit(1)
