"""
Playwrightが使用するセレクタを一元管理するモジュール。
サイトのUI変更があった場合は、このファイルを修正します。
"""

# 楽天ROOM 投稿ページのセレクタ
POST_TEXTAREA = "textarea[name='content']"
SUBMIT_BUTTON = "button.collect-btn"