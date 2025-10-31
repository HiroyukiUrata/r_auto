from app.utils.selector_utils import convert_to_robust_selector
# このスクリプトファイルの中では、'page' と 'context' という変数が自動的に使えます。

print("--- 「いいね済み」カードを非表示にするサンプルスクリプトを実行します ---")

# 1. 指定されたURLにアクセス
target_url = "https://room.rakuten.co.jp/room_be5dbb53b7/items"
print(f"URLにアクセスします: {target_url}")
page.goto(target_url, wait_until="domcontentloaded")

# 2. 「いいね済み」のカードを特定して非表示にする

# Step 1: まず、カード全体を特定するセレクタを定義します。
# 以前の調査から、カードは 'container--' をクラスに持つdiv要素であることが分かっています。
all_cards_locator = page.locator(convert_to_robust_selector('div[class*="container--JAywt"]'))

# Step 2: 次に、「いいね済み」ボタンを特定するセレクタを定義します。
liked_button_selector = convert_to_robust_selector('button:has(div[class*="rex-favorite-filled--2MJip"])')
liked_button_locator = page.locator(liked_button_selector)

try:
    # ページ上のカードが読み込まれるのを待ちます。
    all_cards_locator.first.wait_for(state="visible", timeout=10000)
    
    # Step 3: 全カードの中から、「いいね済み」ボタンを持つカードだけを絞り込みます。
    # これが最も堅牢で推奨される方法です。
    liked_cards_locator = all_cards_locator.filter(has=liked_button_locator)
    
    count = liked_cards_locator.count()
    print(f"{count} 件の「いいね済み」カードが見つかりました。")

    if count > 0:
        # Step 4: 絞り込んだカードを一括で非表示にします。
        print("「いいね済み」カードを非表示にします...")
        liked_cards_locator.evaluate_all("nodes => nodes.forEach(n => n.style.display = 'none')")
        print(f"合計 {count} 件のカードを非表示にしました。")
    else:
        print("非表示にする「いいね済み」カードはありませんでした。")

except Exception as e:
    print(f"エラー: 「いいね済み」の処理中に問題が発生しました。タイムアウトしたか、セレクタが古い可能性があります。")
    print(f"詳細: {e}") # 詳細なエラーメッセージを出力
print("--- スクリプトの処理はここまでです。ブラウザは開いたままになります。 ---")