"""
マルチ投稿アプリ（まずは YouTube 版）
- ブラウザから縦型ショート動画を1本アップ → タイトル等を入力 → YouTube にアップロード
- 将来 TikTok / Instagram をこの構成に追加していく想定
"""
import os
import tempfile

from flask import (
    Flask, redirect, request, session, url_for, render_template, jsonify
)

import google.oauth2.credentials
import google_auth_oauthlib.flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

# ローカル(http://localhost)でOAuthコールバックを受けるための許可
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
# Googleが余分なスコープを返しても許容する
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRETS_FILE = os.path.join(BASE_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
PORT = 8080
REDIRECT_URI = f"http://localhost:{PORT}/oauth2callback"

app = Flask(__name__)
app.secret_key = os.urandom(24)


# ---------- 認証まわり ----------
def save_credentials(creds):
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())


def load_credentials():
    if not os.path.exists(TOKEN_FILE):
        return None
    creds = google.oauth2.credentials.Credentials.from_authorized_user_file(
        TOKEN_FILE, SCOPES
    )
    if creds and creds.expired and creds.refresh_token:
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
    if not os.path.exists(CLIENT_SECRETS_FILE):
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
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES
    )
    flow.redirect_uri = REDIRECT_URI
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
    state = session.get("state")
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state
    )
    flow.redirect_uri = REDIRECT_URI
    # authorize時に生成したPKCE検証コードを復元
    flow.code_verifier = session.get("code_verifier")
    flow.fetch_token(authorization_response=request.url)
    save_credentials(flow.credentials)
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
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
    print(f"\n  ▶ ブラウザで  http://localhost:{PORT}  を開いてください\n")
    app.run(host="localhost", port=PORT, debug=False)
