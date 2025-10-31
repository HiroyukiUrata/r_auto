# このスクリプトファイルの中では、'page' と 'context' という変数が自動的に使えます。

print("--- カードハイライトのサンプルスクリプトを実行します ---")

# 1. 指定されたURLにアクセス
target_url = "https://room.rakuten.co.jp/room_be5dbb53b7/items"
print(f"URLにアクセスします: {target_url}")
page.goto(target_url, wait_until="domcontentloaded")

# 2. 最初のカード要素を特定
# ユーザーページのアイテムカードは 'div.item-card--root--...' という動的なクラス名を持っています。
# Inspectorで調査した、より安定したセレクタを使用します。
# Inspectorが提案した '.container--JAywt' を使用します。
# このようなランダムに見える文字列を含むクラス名は、サイトの更新で変わりやすい点に注意が必要です。
card_selector = '.container--JAywt'
print(f"最初のカード要素を探します... (セレクタ: {card_selector})")

try:
    # time.sleep() の代わりに、要素が表示されるまで最大10秒間待機する
    first_card = page.locator(card_selector).first
    first_card.wait_for(state="visible", timeout=10000)

    print("最初のカードが見つかりました。")
    # 3. 見つけたカードを赤い枠線でハイライト
    print("カードを赤い枠線でハイライトします。")
    first_card.evaluate("node => { node.style.border = '3px solid red'; node.style.boxSizing = 'border-box'; }")
except Exception:
    print("エラー: カード要素が見つかりませんでした。セレクタが古いか、ページの構造が変更された可能性があります。")

print("--- スクリプトの処理はここまでです。ブラウザは開いたままになります。 ---")
