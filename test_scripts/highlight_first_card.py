import time

# このスクリプトファイルの中では、'page' と 'context' という変数が自動的に使えます。

print("--- カードハイライトのサンプルスクリプトを実行します ---")

# 1. 指定されたURLにアクセス
target_url = "https://room.rakuten.co.jp/room_be5dbb53b7/items"
print(f"URLにアクセスします: {target_url}")
page.goto(target_url, wait_until="domcontentloaded")

# ページの描画を少し待つ
time.sleep(2)

# 2. 最初のカード要素を特定
# ユーザーページのアイテムカードは 'div.item-card--root--...' という動的なクラス名を持っています。
# 'div[class*="item-card--root--"]' というセレクタで、クラス名に 'item-card--root--' を含むdiv要素を指定します。
card_selector = 'div[class*="item-card--root--"]'
print(f"最初のカード要素を探します... (セレクタ: {card_selector})")
first_card = page.locator(card_selector).first

if first_card.count() > 0:
    print("最初のカードが見つかりました。")
    # 3. 見つけたカードを赤い枠線でハイライト
    print("カードを赤い枠線でハイライトします。")
    first_card.evaluate("node => { node.style.border = '3px solid red'; node.style.boxSizing = 'border-box'; }")
else:
    print("カード要素が見つかりませんでした。ページの構造が変更された可能性があります。")

print("--- スクリプトの処理はここまでです。ブラウザは開いたままになります。 ---")
