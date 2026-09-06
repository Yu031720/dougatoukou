# マルチ投稿アプリ（YouTube 版）

縦型ショート動画を、ブラウザから1本アップロード → YouTube に投稿する Web アプリ。
将来 TikTok / Instagram をこの構成に追加していく前提で作っています。

## 使い方

### 1. Google 側の準備（初回だけ）

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成
2. 「APIとサービス」→ **YouTube Data API v3** を有効化
3. 「OAuth同意画面」を設定
   - User Type = **外部**
   - テストユーザーに自分の Google アカウントを追加
4. 「認証情報」→ OAuthクライアントID を作成
   - アプリケーションの種類 = **ウェブアプリケーション**
   - 「承認済みのリダイレクトURI」に `http://localhost:8080/oauth2callback` を追加
5. 作成後、JSON をダウンロードし、**`client_secret.json`** という名前でこのフォルダに置く

### 2. 起動

```bash
./run.sh
```

初回は自動で仮想環境の作成と依存インストールを行います。
起動したらブラウザで **http://localhost:8080** を開く。

### 3. 投稿

1. 「YouTube を連携する」→ Google ログイン → 権限を許可
2. 動画を選択 → タイトル等を入力 → 「YouTube に投稿」

## 注意

- `client_secret.json` と `token.json` は**秘密情報**。GitHub には上げないこと（`.gitignore` 済み）。
- 無料枠は 1 日あたり 10,000 ユニット。**動画アップ1本 ≒ 1,600 ユニット**なので、無料だと **1日約6本**まで。
- 最初は公開設定を「非公開」にしてテストするのがおすすめ。

## Render へのデプロイ（公開URL）

このアプリは Render で公開URLとして動かせます。

1. [Render](https://render.com) にログイン → 「New +」→「Blueprint」
2. このリポジトリ（`dougatoukou`）を選択（`render.yaml` を自動読込）
3. 環境変数を設定：
   - `GOOGLE_CLIENT_ID` … Google Cloud のOAuthクライアントID
   - `GOOGLE_CLIENT_SECRET` … 同シークレット
   - `BASE_URL` … デプロイ後のURL（例 `https://dougatoukou.onrender.com`）
   - `GOOGLE_REFRESH_TOKEN`（任意）… 設定するとログイン不要で常時認証
4. デプロイ後、**Google Cloud の「承認済みリダイレクトURI」に
   `https://<あなたのURL>/oauth2callback` を追加**
5. 公開URLを開いて連携 → 投稿

> メモ: Render無料枠はしばらくアクセスが無いとスリープし、再起動で
> `token.json` が消えます。常時ログイン維持したい場合は
> `GOOGLE_REFRESH_TOKEN` を設定してください。

## 今後の拡張

- [ ] TikTok（Content Posting API / 要 `video.publish` 審査）
- [ ] Instagram（Graph API Reels / 要ビジネスアカウント＋審査）
- [ ] 3社同時投稿ボタン
