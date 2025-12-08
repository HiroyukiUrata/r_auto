"""
`run_task.py manual-test` 用フォロー調査スクリプト。
フォローボタンは押さず、1件処理ごとにモーダルを閉じて再オープンする。
ターゲットユーザーページ: https://room.rakuten.co.jp/room_97336c51d3/items

実行例:
  python run_task.py manual-test --script test_scripts/follow.py --use-auth true --url-count 10
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Sequence

from app.utils.selector_utils import convert_to_robust_selector

logger = logging.getLogger(__name__)

LIST_CONTAINER = "div#userList"
DEFAULT_TARGET_COUNT = 10


def get_target_count(argv: Sequence[str]) -> int:
    for i, v in enumerate(argv):
        if v == "--url-count" and i + 1 < len(argv):
            try:
                return max(1, int(argv[i + 1]))
            except ValueError:
                pass
        elif i == 1:
            try:
                return max(1, int(v))
            except ValueError:
                pass
    return DEFAULT_TARGET_COUNT


def scroll_to_load(page, scroll_delay=1.5, max_scrolls=5):
    """モーダルを複数回スクロールしてロードを促す。終端判定は行わない。"""
    for i in range(max_scrolls):
        logger.debug("scroll_to_load: scroll attempt %s/%s", i + 1, max_scrolls)
        try:
            page.locator(LIST_CONTAINER).evaluate("n => n.scrollTop = n.scrollHeight")
        except Exception:
            pass
        time.sleep(scroll_delay)
        try:
            spinner = page.locator("div[aria-label='loading']").first
            spinner.wait_for(state="hidden", timeout=3000)
            logger.debug("scroll_to_load: spinner hidden")
        except Exception:
            pass


def open_modal(page):
    """ターゲットユーザーのフォロワーモーダルを開く。"""
    btn = page.locator('button:has-text("フォロワー")').first
    btn.wait_for(timeout=30000)
    btn.click(force=True)
    page.locator(LIST_CONTAINER).first.wait_for(state="visible", timeout=30000)
    card_locator = page.locator(f"{LIST_CONTAINER} div[class*='profile-wrapper']").first
    try:
        card_locator.wait_for(state="visible", timeout=10000)
        logger.debug("open_modal: カード表示を確認 (profile-wrapper)")
    except Exception:
        try:
            page.locator(LIST_CONTAINER).get_by_role("button", name="フォローする").first.wait_for(state="visible", timeout=5000)
            logger.debug("open_modal: 'フォローする' ボタンの表示を確認（フォールバック）")
        except Exception:
            page.wait_for_timeout(2000)
            logger.debug("open_modal: カード/ボタン待ちタイムアウト、2秒待機のみ")


def close_modal(page):
    """フォロワーモーダルを閉じる（優先的に close-button--2Se88 をクリック）。"""
    selectors = [
        "div.close-button--2Se88",
        "button[aria-label='閉じる']",
        "button[aria-label='Close']",
        "button[aria-label='close']",
        "button:has-text('閉じる')",
    ]
    for sel in selectors:
        btn = page.locator(sel).first
        try:
            if btn.count() > 0:
                btn.click()
                break
        except Exception:
            continue
    else:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
    try:
        page.locator(LIST_CONTAINER).first.wait_for(state="hidden", timeout=5000)
    except Exception:
        pass


def prepare_navigation(page):
    """ターゲットユーザーページへ移動してモーダルを開く。"""
    target_url = "https://room.rakuten.co.jp/room_97336c51d3/items"
    logger.info("ターゲットユーザーページへ移動: %s", target_url)
    start = time.time()
    page.goto(target_url, wait_until="domcontentloaded")
    logger.debug("ターゲットページDOM読み込み完了まで: %.2fs", time.time() - start)

    logger.debug("モーダルを開きます...")
    start = time.time()
    open_modal(page)
    logger.debug("モーダルオープン完了まで: %.2fs", time.time() - start)
    logger.info("ターゲットユーザーのフォロワーモーダルを開きました。")


def follow_targets(page, target_count: int) -> tuple[int, int]:
    """
    モーダルを開閉しながら未フォローの候補を収集し、ログとスクショを残す。
    1件処理するたびにモーダルを閉じて再オープンする。
    """
    collected = 0
    error = 0
    processed_keys = set()
    iteration = 0
    no_progress_rounds = 0
    screenshot_dir = Path("test_scripts/screenshots")
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    while collected < target_count and iteration < 100:
        iteration += 1
        logger.debug(
            "ループ開始: iter=%s collected=%s target=%s processed=%s",
            iteration,
            collected,
            target_count,
            len(processed_keys),
        )

        # その時点での未フォローボタンを最新取得
        follow_buttons = page.locator(LIST_CONTAINER).get_by_role("button", name="フォローする")
        follow_count = follow_buttons.count()
        follow_now_count = page.locator(LIST_CONTAINER).get_by_role("button", name="フォロー中").count()
        logger.debug("現在のフォローするボタン数: %s / フォロー中ボタン数: %s", follow_count, follow_now_count)

        # 未フォローボタンが無ければスクロール
        if follow_count == 0:
            logger.debug("未フォローボタンなし -> スクロール実施")
            scroll_to_load(page)
            page.wait_for_timeout(800)
            # スクロールしても増えなければ終了カウント
            no_progress_rounds += 1
            if no_progress_rounds >= 3:
                logger.debug("未フォローが見つからない状態が続いたため終了")
                break
            # モーダル開き直し
            close_modal(page)
            page.wait_for_timeout(300)
            open_modal(page)
            continue
        else:
            no_progress_rounds = 0

        # 一件ずつ処理して都度閉じる
        idx = 0
        new_found = False
        while idx < follow_count and collected < target_count:
            try:
                btn = follow_buttons.nth(idx)
                btn.evaluate("el => el.scrollIntoView({block:'center', behavior:'instant'})")
                page.wait_for_timeout(200)

                user_row = btn.locator('xpath=ancestor::div[contains(@class, "profile-wrapper")]').first
                img_loc = user_row.locator("img").first
                key = None
                try:
                    key = img_loc.get_attribute("src")
                except Exception:
                    key = None
                name_el = user_row.locator(convert_to_robust_selector('span.profile-name--2Hsi5')).first
                user_name = ""
                try:
                    if name_el.count() > 0:
                        user_name = name_el.inner_text().strip()
                        if not key:
                            key = user_name
                except Exception:
                    user_name = ""
                    if not key:
                        key = ""

                if key and key in processed_keys:
                    logger.debug("既処理カードをスキップ: key=%s name=%s", key, user_name)
                    idx += 1
                    continue

                processed_keys.add(key or f"idx-{len(processed_keys)}")
                collected += 1
                new_found = True
                logger.info("フォロー候補: %s件目 (ユーザー: %s)", collected, user_name or "取得失敗")
                try:
                    safe_name = (user_name or "unknown").replace("/", "_").replace("\\", "_")
                    screenshot_path = screenshot_dir / f"follow_candidate_{collected}_{safe_name}.png"
                    user_row.evaluate("el => { el.style.outline='3px solid tomato'; el.style.outlineOffset='2px'; }")
                    page.screenshot(path=str(screenshot_path), full_page=True)
                    user_row.evaluate("el => { el.style.outline=''; el.style.outlineOffset=''; }")
                    logger.debug("スクリーンショット保存: %s", screenshot_path)
                except Exception as ss_e:
                    logger.debug("スクリーンショット保存に失敗: %s", ss_e)
                page.wait_for_timeout(300)

                # 1件処理したらモーダル閉→開き直し
                logger.debug("モーダルを閉じます (processed=%s)", collected)
                close_modal(page)
                page.wait_for_timeout(300)
                if collected < target_count:
                    logger.debug("モーダルを再度開きます (次の処理に進みます)")
                    open_modal(page)
                    page.wait_for_timeout(300)
                break  # モーダルを開き直したので外側のwhileへ
            except Exception as e:
                error += 1
                logger.debug("カード処理中にエラー: %s", e)
                idx += 1

        # この周回で新規追加がなければ、リフレッシュのためモーダルを閉じて開き直す
        if not new_found:
            no_progress_rounds += 1
            pre_count = follow_count
            scroll_to_load(page, scroll_delay=1.0, max_scrolls=2)
            post_count = page.locator(LIST_CONTAINER).get_by_role("button", name="フォローする").count()
            logger.debug(
                "新規なし -> スクロール実施 (before=%s, after=%s) / モーダルを閉じて再オープン (no_progress=%s)",
                pre_count,
                post_count,
                no_progress_rounds,
            )
            close_modal(page)
            page.wait_for_timeout(300)
            open_modal(page)
            page.wait_for_timeout(300)
            if no_progress_rounds >= 3:
                logger.debug("新規追加なしのラウンドが続いたため終了します。")
                break
        else:
            no_progress_rounds = 0

    return collected, error


if "page" in globals():
    target_count = get_target_count(sys.argv[1:])
    prepare_navigation(page)
    success, error = follow_targets(page, target_count)
    logger.info("フォロー完了 成功=%s 失敗=%s", success, error)
    logger.info("ブラウザは開いたままです。")
