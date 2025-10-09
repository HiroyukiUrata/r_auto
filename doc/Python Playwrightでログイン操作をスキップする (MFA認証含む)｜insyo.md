---
title: "[Python] Playwrightでログイン操作をスキップする (MFA認証含む)｜insyo"
source: "https://note.com/insyo99/n/n0b03d5c6847e"
author:
  - "[[insyo]]"
published: 2024-12-15
created: 2025-10-09
description: "Playwright使ってますか～？便利ですよねー。 退屈なブラウザ操作を簡単にコードで自動化できるので、重宝しています。  Fast and reliable end-to-end testing for modern web apps | Playwright PythonCross-browser end-to-end testing for modern web appsplaywright.dev  この記事では、PythonでPlaywrightを操作して、ログイン操作をスキップする方法を解説します。  毎回ログインするのがめんどくさい  ログイ"
tags:
  - "clippings"
---
![見出し画像](https://assets.st-note.com/production/uploads/images/165865287/rectangle_large_type_2_2f3c5c940747ac781586caafd9d77ec0.png?width=1200)

## \[Python\] Playwrightでログイン操作をスキップする (MFA認証含む)

[insyo](https://note.com/insyo99)

Playwright使ってますか～？便利ですよねー。  
退屈なブラウザ操作を簡単にコードで自動化できるので、重宝しています。

[**Fast and reliable end-to-end testing for modern web apps | Playwright Python** *Cross-browser end-to-end testing for modern web apps* *playwright.dev*](https://playwright.dev/python/)

この記事では、PythonでPlaywrightを操作して、ログイン操作をスキップする方法を解説します。

## 毎回ログインするのがめんどくさい

ログイン画面、特にMFA(多要素認証)を伴うログイン画面は、自動化が難しいですよね。  
TOTPでのMFAでは一定期間で変化する認証コードを手動でブラウザに入力しなくてはならないので、自動化するのは実質不可能です。

Webサイトでの認証処理が成功したあと一定期間は再ログインしなくてもアクセスできるのは、Cookieが認証成功後にサーバーから発行され、それをブラウザが適切に管理・処理することで実現されています。

Playwrightでは「Cookieの取得」や「任意のCookieの設定」を行うことができます。この機能を利用して、

- ログイン操作を一回だけ実施し、そのときのCookieをファイルに保存しておく
- ファイルに保存したCookieを読み込んでブラウザに設定することで、ログイン処理をスキップする

という方法で毎回ログインする操作をしなくても良いようにしてみました。

## Playwrightのインストール

まずはPythonの仮想環境を作成します。  
下記ではuvを使用していますが、他の仮想環境コマンドでも問題ありません。  
ブラウザを操作する必要があるので、WindowsやmacなどのGUIがあるOS上で動作させるものとします。  
(CLIのみのLinuxではブラウザ起動時にエラーになります)

```ruby
# プロジェクトディレクトリを作成して移動
$ mkdir PlaywrightPrj
$ cd PlaywrightPrj

# プロジェクトの初期化とPythonバージョンの指定
$ uv init .
$ uv python pin 3.12

# playwrightのインストール
$ uv add playwright

# 仮想環境の有効化
# - PowerShellの場合
$ source .venv/Scripts/activate.ps1
# - コマンドプロンプトの場合
$ .venv\Scripts\activate.bat
# - mac/Linuxの場合
$ source .venv/bin/activate

# ブラウザのインストール
$ playwright install
```

## ログイン操作をコード化する

まずは、ログイン操作の雛形になるコードを作成します。  
ターミナルから下記のコマンドを実行します。

```ruby
$ playwright codegen
```

ブラウザが開くので、ログインしたいサイトをアドレスバーで指定してログイン完了までの操作を行います。 今回はGitHubのページでやってみましょう。 URLは [https://github.com/](https://github.com/%60) です。

![画像](https://assets.st-note.com/img/1734262029-L5vKS8JUl2gfhOzq0MrpDGEt.png?width=1200)

GitHubのトップページ。右上の"Sign In"をクリック

![画像](https://assets.st-note.com/img/1734262056-Kr0Xc5vqFihyGdmeE6fPWoZM.png?width=1200)

GitHubのログイン画面。IDとパスワードを入力して、"Sign in"ボタンをクリック

![画像](https://assets.st-note.com/img/1734262080-oG0SFHJDMxcvr2LKt4qVhPdy.png?width=1200)

MFAを有効にしてあるので、Authenticatorアプリのコードを入力

![画像](https://assets.st-note.com/img/1734262109-90eFp2mjKLZ7dcsBltygDTUG.png?width=1200)

無事ログイン成功

Playwright Inspectorというウィンドウに、操作内容がPythonコードとして自動生成されています。  
コードの内容をコピーして保存しておきましょう。

![画像](https://assets.st-note.com/img/1734262618-JgOrQXz7lCR42FD1bkeZTcVM.png?width=1200)

操作内容がPythonコードとして出力されているので、保存しておく

上記のコードを改造して、ログイン直後のCookieをファイルに保存するようにします

## ログインした直後のCookieを保存する

まずはコードです。

ブラウザでのログイン操作を手動で行ったあと、コードを起動したターミナルでEnterを打ってください。  
  
context.coockies() でブラウザのCookieを取得することができます。  
これをJSON形式に変換して cookies.json というファイルに保存しています。

cookies.json には下記のようなデータが格納されています。

![画像](https://assets.st-note.com/img/1734263359-IUADzCq4ko1mEdnewXh7iYJF.png?width=1200)

cookie.jsonの内容

## 保存済Cookieを利用してサイトにアクセスする

今度は、上記のコードで保存したCookieを読み込んで、ログイン済の状態でサイトにアクセスするコードです。  
私のGitHub上のリポジトリのIssueページにアクセスし、そのページのスクリーンショットを取得してみました。

context.add\_cookies(辞書) で、Cookieをブラウザに設定することができます。

下記のようなスクリーンショットも取得できました。

![画像](https://assets.st-note.com/img/1734263677-K9F04jQmEJid3I6v7Lq8X2ex.png?width=1200)

Playwrightで取得したスクリーンショット

  

このように、PlaywrightでCookieの取得/設定を簡単に行うことができます。Cookieの有効期間が切れると再度認証＆Cookieの保存が必要ですが、毎回ログイン操作するよりはだいぶ楽になったと思います。

では、良いPlaywrightライフを！

  

## コメント

\[Python\] Playwrightでログイン操作をスキップする (MFA認証含む)｜insyo