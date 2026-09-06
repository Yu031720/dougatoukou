"""
マルチ投稿アプリ（まずは YouTube 版）
- ブラウザから縦型ショート動画を1本アップ → タイトル等を入力 → YouTube にアップロード
- 将来 TikTok / Instagram をこの構成に追加していく想定

ローカルでも Render 等の本番でも動くように、認証情報は
「client_secret.json（ローカル）」または「環境変数（本番）」の両対応。
"""
import os
import tempfile

from flask import (
    Flask, redirect, request, session, url_for, render_template, jsonify
)

import google_auth_oauthlib.flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

# Googleが余分なスコープを返しても許容する
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRETS_FILE = os.path.join(BASE_DIR, "client_secret.json")
# 本番の一時ディスクにも書けるよう、書き込み先は環境変数で上書き可
TOKEN_FILE = os.environ.get("TOKEN_FILE", os.path.join(BASE_DIR, "token.json"))
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
TOKEN_URI = "https://oauth2.googleapis.com/token"

# 公開URL（例: https://xxxx.onrender.com）。未設定ならローカル。
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8080").rstrip("/")
REDIRECT_URI = BASE_URL + "/oauth2callback"
# ローカル(http)のコールバックのときだけ、平文httpを許可する
if REDIRECT_URI.startswith("http://"):
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24)


# ---------- OAuthクライアント設定（ファイル or 環境変数） ----------
def _client_config():
    """client_secret.json が無い場合に環境変数から構築。無ければ None。"""
    cid = os.environ.get("GOOGLE_CLIENT_ID")
    csec = os.environ.get("GOOGLE_CLIENT_SECRET")
    if cid and csec:
        return {
            "web": {
                "client_id": cid,
                "client_secret": csec,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": TOKEN_URI,
                "redirect_uris": [REDIRECT_URI],
            }
        }
    return None


def has_client():
    return os.path.exists(CLIENT_SECRETS_FILE) or _client_config() is not None


def make_flow(state=None):
    if os.path.exists(CLIENT_SECRETS_FILE):
        flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE, scopes=SCOPES, state=state
        )
    else:
        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            _client_config(), scopes=SCOPES, state=state
        )
    flow.redirect_uri = REDIRECT_URI
    return flow


# ---------- 認証まわり ----------
def save_credentials(creds):
    try:
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    except OSError:
        # 書き込めない環境（読み取り専用FS等）は無視
        pass


def load_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    elif os.environ.get("GOOGLE_REFRESH_TOKEN"):
        # 本番: リフレッシュトークンを環境変数で渡すと、ログイン不要で常時認証
        creds = Credentials(
            token=None,
            refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
            token_uri=TOKEN_URI,
            client_id=os.environ.get("GOOGLE_CLIENT_ID"),
            client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
            scopes=SCOPES,
        )
    if creds and not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(creds)
    return creds


def get_youtube():
    creds = load_credentials()
    if not creds or not creds.valid:
        return None
    return build("youtube", "v3", credentials=creds)


# ---------- 画面 ----------
@app.route("/")
def index():
    if not has_client():
        return render_template("index.html", state="no_client")
    yt = get_youtube()
    if yt is None:
        return render_template("index.html", state="need_auth")
    channel = None
    try:
        resp = yt.channels().list(part="snippet", mine=True).execute()
        items = resp.get("items", [])
        if items:
            channel = items[0]["snippet"]["title"]
    except Exception:
        pass
    return render_template("index.html", state="ready", channel=channel)


@app.route("/authorize")
def authorize():
    flow = make_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["state"] = state
    # PKCE の検証コードをコールバックまで保持する
    session["code_verifier"] = flow.code_verifier
    return redirect(auth_url)


@app.route("/oauth2callback")
def oauth2callback():
    flow = make_flow(state=session.get("state"))
    # authorize時に生成したPKCE検証コードを復元
    flow.code_verifier = session.get("code_verifier")
    flow.fetch_token(authorization_response=request.url)
    save_credentials(flow.credentials)
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    try:
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
    except OSError:
        pass
    return redirect(url_for("index"))


# ---------- アップロード ----------
@app.route("/upload", methods=["POST"])
def upload():
    yt = get_youtube()
    if yt is None:
        return jsonify({"ok": False, "error": "未認証です。先にYouTube連携をしてください。"}), 401

    file = request.files.get("video")
    if not file or file.filename == "":
        return jsonify({"ok": False, "error": "動画ファイルが選択されていません。"}), 400

    title = (request.form.get("title") or "").strip() or "無題"
    description = request.form.get("description") or ""
    tags_raw = request.form.get("tags") or ""
    # カンマ・全角/半角スペース区切り、先頭の # は除去
    tags = [
        t.lstrip("#")
        for t in tags_raw.replace("　", " ").replace(",", " ").split()
        if t.strip()
    ]
    privacy = request.form.get("privacy") or "private"  # private / unlisted / public
    made_for_kids = request.form.get("made_for_kids") == "on"
    as_shorts = request.form.get("as_shorts") == "on"

    # Shorts扱いにしたい場合、#Shorts を説明末尾に付与（縦型・短尺が前提）
    if as_shorts and "#shorts" not in (title + description).lower():
        description = (description + "\n\n#Shorts").strip()

    # 一時ファイルに保存してからアップロード
    suffix = os.path.splitext(file.filename)[1] or ".mp4"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    file.save(tmp.name)
    tmp.close()

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "22",  # People & Blogs
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }

    try:
        media = MediaFileUpload(tmp.name, chunksize=-1, resumable=True)
        req = yt.videos().insert(
            part="snippet,status", body=body, media_body=media
        )
        response = None
        while response is None:
            _, response = req.next_chunk()
        video_id = response["id"]
        return jsonify({
            "ok": True,
            "video_id": video_id,
            "url": f"https://youtu.be/{video_id}",
            "studio_url": f"https://studio.youtube.com/video/{video_id}/edit",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"\n  ▶ ブラウザで  http://localhost:{port}  を開いてください\n")
    app.run(host="0.0.0.0", port=port, debug=False)
