---
title: "Playwrightで2回目以降のログインを自動スキップする実践ガイド｜koふみ"
source: "https://note.com/knowledge_oasis/n/nbc8c68e4564d"
author:
  - "[[koふみ]]"
published: 2025-08-20
created: 2025-10-09
description: "一度ログインしたら、次からは待ち時間ゼロで走らせたい。 カギは「認証状態（storageState）の安全な保存と再利用」です。 “動くコード”に埋め込まれたベストプラクティスを、Playwright初心者にもわかる言葉で丁寧に解説します。   なぜ「認証スキップ」を設計に入れるのか  実行時間の短縮  毎回のログインはネットワーク遅延やMFA待ちで時間が読めません。stateを再利用すれば、2回目以降は画面遷移だけで業務操作に入れます。  安定性の向上  ログインフローはIdPのUI変更やA/Bテストの影響を受けやすいです。stateが有効な限り、脆い「ログイン自動化」を避けられます"
tags:
  - "clippings"
---
![見出し画像](https://assets.st-note.com/production/uploads/images/209804634/rectangle_large_type_2_1d7f0a969be5c9acc654b237a4c1cace.png?width=1200)

## Playwrightで2回目以降のログインを自動スキップする実践ガイド

[koふみ](https://note.com/knowledge_oasis)

一度ログインしたら、次からは待ち時間ゼロで走らせたい。  
カギは「認証状態（storageState）の安全な保存と再利用」です。  
“動くコード”に埋め込まれたベストプラクティスを、Playwright初心者にもわかる言葉で丁寧に解説します。

## なぜ「認証スキップ」を設計に入れるのか

**実行時間の短縮**

毎回のログインはネットワーク遅延やMFA待ちで時間が読めません。stateを再利用すれば、2回目以降は画面遷移だけで業務操作に入れます。

**安定性の向上**

ログインフローはIdPのUI変更やA/Bテストの影響を受けやすいです。stateが有効な限り、脆い「ログイン自動化」を避けられます。

**セキュリティと運用の両立**

初回だけ安全にログイン → 有効なstateを最小権限で保存。期限切れや無効化を **検知してだけ** 再ログイン。最小接触が安全につながります。

## Playwrightの基礎（最短理解）

**Browser / BrowserContext / Page**

- **Browser**: 実ブラウザ（Chromium）プロセス。
- **BrowserContext**: 独立した“ユーザーごとのプロファイル”のような単位。 **認証cookieやlocalStorageはここに紐づきます** 。
- **Page**: 単一タブ。操作対象のDOMはここ。

このコードは **BrowserContext作成時に storageState を渡す** ことで、2回目以降の自動ログイン（=ログイン省略）を実現しています。

## 設計の全体像（コードの骨格）

1. 既存の **storageState** （認証情報）があれば **BrowserContext作成時に読み込む**
2. 保護ページへアクセスして **stateの有効性を判定**
3. **必要なときだけ** ログイン → 成功を確証（アプリ固有の要素を待つ）
4. **原子的に** storageState を保存（安全・確実）
5. 本来やりたい操作へ（リンククリック・スクショ取得など）

---

## ベストプラクティスのコード

```javascript
import { chromium, BrowserContext, BrowserContextOptions, Page } from 'playwright';
import fs from 'fs';
import fsp from 'fs/promises';
import path from 'path';
import 'dotenv/config';

/** OZO CloudのベースURL */
const BASE_URL = 'https://sample-site.com';
/** 認証情報保存ディレクトリ */
const STATE_DIR = 'state';
/** 認証情報保存パス */
const STATE_PATH = path.join(STATE_DIR, 'site-name.json');

// ---- Utilities --------------------------------------------------------------

/**
 * ファイルの存在確認（非同期）
 * @param p ファイルパス
 * @returns 存在すればtrue
 */
async function fileExists(p: string): Promise<boolean> {
  try { await fsp.access(p, fs.constants.F_OK); return true; } catch { return false; }
}

/**
 * storageStateを一時ファイル経由で原子的に保存
 * @param page PlaywrightのPage
 * @param outPath 保存先パス
 */
async function saveStorageStateAtomically(page: Page, outPath: string): Promise<void> {
  await fsp.mkdir(path.dirname(outPath), { recursive: true });
  const tmp = outPath + '.tmp';
  await page.context().storageState({ path: tmp });
  try { await fsp.chmod(tmp, 0o600); } catch {}
  await fsp.rename(tmp, outPath);
}

/**
 * 保存済みstateがあればcontextオプションとして返す
 * @returns BrowserContextOptions
 */
function usingSavedStateOptions(): BrowserContextOptions {
  return fs.existsSync(STATE_PATH) ? { storageState: STATE_PATH } : {};
}

/**
 * Microsoft/AAD ログイン: ポップアップ対応で Page を取得
 * @param page PlaywrightのPage
 * @returns ログイン用Page
 */
async function getActiveLoginPage(page: Page): Promise<Page> {
  const ctx = page.context();
  // 元タブは commit まで（about:blank でハング回避）
  await page.goto(BASE_URL, { waitUntil: 'commit' });
  return page;
}

/**
 * ログイン実行（必要なときだけ）
 * @param page PlaywrightのPage
 * @returns void
 * @description 実運用では .env を使う。ここで直値を使わない！
 */
async function loginIfNeeded(page: Page): Promise<void> {
  // AAD ログインへ流れるのを待ち、メール欄 (#i0116) を待つ
  await page.waitForURL(/login\.microsoftonline\.com/i, { timeout: 30_000 }).catch(() => {});
  const email = page.locator('#i0116, input[type="email"]');
  await email.waitFor({ state: 'visible', timeout: 30_000 });
  await email.fill(process.env.WF_USERNAME!);
  await page.locator('#idSIButton9').click();

  // ここから先はテナント固有。SSO→IdP→パスワード→MFAの順に分岐しうる。
  // 例: IdP ログイン（テキストは環境に合わせて修正）
  // パスワード欄
  const pass = page.getByRole('textbox', { name: 'Password' });
  await pass.waitFor({ state: 'visible', timeout: 30_000 }).catch(() => {});
  if (await pass.isVisible()) {
    await pass.fill(process.env.WF_PASSWORD!);
    await page.getByRole('button', { name: 'Log in' }).click();
  }

  // 「サインインの状態を維持しますか？」等の確認ボタン
  const staySignedIn = page.locator('#idSIButton9');
  if (await staySignedIn.isVisible()) {
    await staySignedIn.click();
  }
}

/**
 * ログイン成功の“証拠”を待つ（アプリに合わせて要素を変更）
 * @param page PlaywrightのPage
 */
async function assertLoggedIn(page: Page): Promise<void> {
  // 例：ダッシュボードに来ている or ナビゲーションの特定リンクが見える
  await page.waitForURL(/sample-site\.com\/mainmenue/i, { timeout: 30_000 }).catch(() => {});
  await page.getByRole('link', { name: /新規文書を申請する/ }).waitFor({ state: 'visible', timeout: 30_000 });
}

/**
 * state が古い/無効なら true（ログイン画面に戻された等）
 * @param page PlaywrightのPage
 * @returns 無効ならtrue
 */
async function stateIsStale(page: Page): Promise<boolean> {
  // 保護ページにアクセスしてログインフォームに飛ばされたら無効
  await page.goto(BASE_URL, { waitUntil: 'commit' });
  const onMsLogin = /login\.microsoftonline\.com/i.test(page.url());
  // あるいはアプリ側のログインリンクが見えたら無効判定、など
  return onMsLogin;
}

// ---- Main -------------------------------------------------------------------

/**
 * PlaywrightによるOZO Cloud自動ログイン・操作メイン処理
 */
(async () => {
  // 1) ブラウザ起動
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext(usingSavedStateOptions());
  const page = await context.newPage();
  page.setDefaultTimeout(30_000);

  // 2) アクティブなログインPageを取得（popup対応）
  const activePage = await getActiveLoginPage(page);

  // 3) 既存 state が有効か確認 → ダメならログインして state を作り直す
  let needLogin: boolean = !(await fileExists(STATE_PATH)) || (await stateIsStale(activePage));
  if (needLogin) {
    await loginIfNeeded(activePage);
    await assertLoggedIn(activePage);                    // 成功の証拠を待つ
    await saveStorageStateAtomically(activePage, STATE_PATH);  // 原子的に保存
  }

  // 4) 以降は通常操作（例：新規文書申請へ）
  await activePage.getByRole('link', { name: '新規文書を申請する' }).click();
  await activePage.screenshot({ path: 'step-new-doc.png' });

  await browser.close();
})().catch((e: unknown) => {
  console.error('予期せぬエラー:', e);
  process.exit(1);
});
```

---

## ベストプラクティス解説（コード順）

**環境変数で資格情報を扱う（.env + dotenv/config）**

```python
import 'dotenv/config'
await email.fill(process.env.WF_USERNAME!)
await pass.fill(process.env.WF_PASSWORD!)
```

- **コードにID/パスワードを直書きしない** のは大前提。**.env** → **process.env** 経由に統一しています。
- **!** はTypeScriptの非nullアサーション。実運用では **未設定時の明示的エラー** （例外）にしたほうが安全ですが、ここではコード改変なしでベスト意図を読み解きます。

**パスの一元管理とプラットフォーム互換**

```cs
const STATE_DIR = 'state';
const STATE_PATH = path.join(STATE_DIR, 'site-name.json');
```

- **path.join** を使うのは **OS差異（/ と \\）吸収** の基本。
- “どこに保存するか”を定数に寄せると、 **CI/ローカル** の切り替えも楽です。

**まずは「あるか」を軽量に判定**

```javascript
function usingSavedStateOptions(): BrowserContextOptions {
  return fs.existsSync(STATE_PATH) ? { storageState: STATE_PATH } : {};
}
```

- **BrowserContext作成前** に同期I/Oで存在チェック → オプション付与。
- 早い段階でstateを適用でき、 **余計なログイン動線に入らない** のがポイント。

**画面遷移の「待ち」は最小限かつ意図的に**

```javascript
await page.goto(BASE_URL, { waitUntil: 'commit' });
```

- **commit** は **サーバー応答で初期HTML受信した時点** 。
- フルロード待ちではなく **「確実に次へ進める最短地点」** を待つのが、安定化と速度の両立に効きます。

**ログインフローの検出はURLと要素の二段構え**

- **URLの正規表現** でAADC（Microsoft）へ流れたことを幅広く検出。クエリやサブドメイン差異に強いです。
- 次に **具体的なUI要素（email入力）を待つ** 。ネットワークや遅延を吸収し、フレークを防ぎます。

**アクセシビリティに基づく堅牢なロケータ**

```javascript
page.getByRole('textbox', { name: 'Password' })
page.getByRole('button', { name: 'Log in' })
page.getByRole('link', { name: /新規文書を申請する/ })
```

- **getByRole** は **見た目のクラス名変更に強い** 。
- **name:** はアクセシブルネーム。i18nやA/Bで変わるときは **正規表現** にするなど運用で吸収できます。

**「必要なときだけ」ログインする自己修復パターン**

- まずはファイルの有無。次に **保護ページへ行ってログインへリダイレクトされたら“無効”** と判断。
- **stateが生きている限りログインをスキップ** でき、UI変更の影響を最小化します。

**成功の「証拠」を明示的に待つ（アサーション指向）**

- URLだけでなく、 **アプリ固有の“見えているべき要素”** を待つのが堅牢。
- これにより **「本当にログイン成功した」** と言い切れます（=state保存のタイミング保証）。

**storageStateは「原子的に」保存して壊さない**

```javascript
const tmp = outPath + '.tmp';
await page.context().storageState({ path: tmp });
try { await fsp.chmod(tmp, 0o600); } catch {}
await fsp.rename(tmp, outPath);
```

- **一時ファイルに出力 → パーミッション設定 → renameで入替** は、途中失敗で壊れたJSONを残さないための鉄板パターン。
- **0o600** は **所有者のみ読書き可** 。最小権限が基本です。Windowsで失敗する可能性があるため **chmod** は握りつぶし（クロスプラットフォーム配慮）になっています。

**デフォルトの待ち時間を統一**

```javascript
page.setDefaultTimeout(30_000);
```

- 個別の **waitFor** だけに頼らず、 **全体の下限** を持たせるとブレを抑えられます。
- 過剰に長いとデバッグ効率が落ちるので、 **まず30秒** からが現実的です。

**最小限の成果物を残す（証跡）**

```javascript
await activePage.screenshot({ path: 'step-new-doc.png' });
```

- 重要なステップごとに **スクリーンショットを残す** と、CIの失敗分析や後追い調査がぐっと楽になります。

---

## セキュリティ運用のポイント

**シークレットは.envで、権限は最小に**

- **.env** は **リポジトリに含めず** 、CIのシークレットやローカルの安全な保管庫で管理します。
- stateファイルは **可読範囲を最小** に（ **0o600** ）。共有ストレージでの扱いにも注意。

**stateの寿命と再発行戦略**

- AAD/IdP側のポリシーで **セッションの期限や再認証** が発生します。
- このコードは **無効化検知→再ログイン→再保存** の自己修復で運用負荷を下げています。

**ログ・成果物の扱い**

- スクショやログに **個人情報が写らない工夫** を。必要に応じてマスキングや保存先分離を検討します。

---

## よくある落とし穴と回避策

**ロケータが見つからない**

- UIテキストの微変更に備え、 **正規表現** や **代替セレクタ** （ **#i0116, input\[type="email"\]** のように複数指定）を組み合わせると強いです。

**予期せぬポップアップ／リダイレクト**

- **waitForURL** と **“決め打ちの要素待ち”をセットで置く** と、不意の画面遷移にも耐えます。

**ヘッドレス固有の挙動差**

- CIは **headless: true** が基本。ローカルデバッグ時に **false** に切り替えることで **目視検証** ができます（※本稿のコードは変更しませんが、運用Tipsとして）。

**タイムアウトの設計**

- ネットワークやIdP応答の遅さを考慮し、 **ページ全体の既定（30秒）＋重要箇所の個別待ち** の二段構えが安定します。

---

## 実行フローの復習（このコードで何が起きている？）

1. Chromiumを起動し、 **既存stateがあれば適用** して新しいContextを作成
2. 保護ページへアクセスし、 **stateの有無・有効性をチェック**
3. **必要時のみ** ログインフローを踏み、 **成功の証拠（URL＋リンクの可視）を確認**
4. **原子的にstate保存** （壊れない・漏れない）
5. 目的リンクをクリックし、 **成果物（スクショ）** を残して終了

---

## まとめ

- 2回目以降のログイン省略は **BrowserContextの** storageState **再利用** が王道です。
- **“必要なときだけ”ログイン** し、 **“成功の証拠を待ってから”安全に保存** するのが本質。
- 保存は **原子的に・最小権限で** 。無効化検知→再発行の自己修復で運用が軽くなります。
- ロケータは **URL検知＋アクセシビリティベース** で堅牢に。待機は **最短地点（commit）＋既定タイムアウト** でフレークを抑えます。
- この設計をテンプレート化すれば、他サービスでも **ほぼ流用** できます。あなたの自動化は、もっと速く・強く・安全になります。

---

知識は武器とかけまして、レゴブロックと解く、その心は？  
知識のひとつひとつは小さなレゴブロック  
でも、組み合わせれば世界を変えるアイディアをカタチにする武器になる！

またKnowledge Oasisでお会いしましょう  
案内人はkoふみでした

- [
	#playwright
	](https://note.com/hashtag/playwright)
- [
	#storageState
	](https://note.com/hashtag/storageState)

Playwrightで2回目以降のログインを自動スキップする実践ガイド｜koふみ