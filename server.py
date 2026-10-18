"""VD Downloader — link ချပေးရုံနဲ့ video download ရတဲ့ webapp backend.

Engine နှစ်မျိုး:
  1) yt-dlp engine  — TikTok, YouTube/Shorts, Facebook, Instagram, X, Pinterest...
     (server IP ကနေ တိုက်ရိုက်ရတဲ့ platform တွေ)
  2) parse-API engine — Xiaohongshu/RedNote, Douyin, Bilibili, Weibo, Kuaishou...
     (China platform တွေက datacenter IP ကို security wall ချထားလို့
      third-party 解析 API ကနေတစ်ဆင့် ယူရတယ်)

Endpoints:
  GET  /                      -> webapp UI
  GET  /health                -> {"ok": true}
  POST /api/resolve  {url}    -> video info + qualities (download မလုပ်သေးဘူး)
  GET  /api/dl?url=..&q=..    -> video file download (attachment)
  GET  /api/zip?url=..        -> photo-note image တွေကို zip နဲ့ download
"""
import io
import json
import os
import re
import subprocess
import tempfile
import zipfile
from urllib.parse import quote, urlparse

import requests
from flask import Flask, Response, jsonify, request, send_file

app = Flask(__name__)

# ---------------------------------------------------------------- config
DL_TOKEN = os.environ.get("DL_TOKEN", "").strip()
PARSE_API = os.environ.get(
    "PARSE_API",
    "https://www.yhqsj.cn/api/short_videos.php?url=",
).strip()
MAX_MB = int(os.environ.get("MAX_MB", "500"))
RESOLVE_TIMEOUT = 90
UA = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36")

# parse-API engine သုံးမယ့် domain တွေ (China IP-wall ရှိတဲ့ platform တွေ)
API_ENGINE = {
    "xiaohongshu.com": "小红书 RedNote",
    "xhslink.com": "小红书 RedNote",
    "douyin.com": "Douyin 抖音",
    "iesdouyin.com": "Douyin 抖音",
    "v.douyin.com": "Douyin 抖音",
    "bilibili.com": "Bilibili",
    "b23.tv": "Bilibili",
    "weibo.com": "Weibo 微博",
    "weibo.cn": "Weibo 微博",
    "kuaishou.com": "Kuaishou 快手",
    "v.kuaishou.com": "Kuaishou 快手",
    "gifshow.com": "Kuaishou 快手",
}
# yt-dlp engine သုံးမယ့် domain တွေ
YTDLP_ENGINE = {
    "tiktok.com": "TikTok",
    "vt.tiktok.com": "TikTok",
    "vm.tiktok.com": "TikTok",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "facebook.com": "Facebook",
    "fb.watch": "Facebook",
    "fb.com": "Facebook",
    "instagram.com": "Instagram",
    "x.com": "X (Twitter)",
    "twitter.com": "X (Twitter)",
    "pinterest.com": "Pinterest",
    "pin.it": "Pinterest",
}
KNOWN = {**API_ENGINE, **YTDLP_ENGINE}

YT_DOMAINS = {"youtube.com", "youtu.be"}
# YouTube က datacenter IP ကို bot-check လုပ်လို့ android/ios client နဲ့မှ ရတယ်
YT_ARGS = ["--extractor-args", "youtube:player_client=android,ios,mweb"]

ERR = {
    "bad_url": "link မမှန်ဘူး — app ထဲက Copy Link နဲ့ အပြည့်အစုံ ကူးလာပါ",
    "unsupported": "ဒီ site ကို မထောက်ပံ့သေးဘူး",
    "not_found": "video ရှာမတွေ့ဘူး — link က public video ဟုတ်မဟုတ် စစ်ကြည့်ပါ",
    "private": "private/deleted video မို့ ယူမရဘူး",
    "bot": "YouTube က server ကို ခဏ block ထားတယ် — ၁ မိနစ်နေပြန်နှိပ်",
    "api_down": "parse server ချိတ်မရဘူး — ခဏနေပြန်နှိပ်",
    "timeout": "ကြာလွန်းလို့ ရပ်လိုက်တယ် — ခဏနေပြန်နှိပ်",
    "too_big": f"file ကြီးလွန်းတယ် ({MAX_MB}MB အထိပဲရတယ်)",
    "parse_fail": "parse မရဘူး — link အသစ်ကူးပြီး ပြန်စမ်းကြည့်ပါ",
}


# ---------------------------------------------------------------- helpers
def check_token():
    if DL_TOKEN:
        tok = request.args.get("token", "") or (request.get_json(silent=True) or {}).get("token", "")
        if tok != DL_TOKEN:
            return jsonify(ok=False, error="token မှားနေတယ်"), 403
    return None


def host_of(url):
    try:
        return urlparse(url).netloc.lower().split(":")[0]
    except Exception:
        return ""


def base_domain(host):
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def valid_url(url):
    if not url or not isinstance(url, str):
        return False
    p = urlparse(url.strip())
    return p.scheme in ("http", "https") and bool(p.netloc)


def resolve_url(url):
    """short link (xhslink.com, vt.tiktok.com, b23.tv...) တွေကို final URL ထိ follow လုပ်."""
    try:
        r = requests.head(url, allow_redirects=True, timeout=15,
                          headers={"User-Agent": UA})
        if r.url and r.url != url:
            return r.url
    except Exception:
        pass
    try:
        r = requests.get(url, allow_redirects=True, timeout=20, stream=True,
                         headers={"User-Agent": UA})
        final = r.url
        r.close()
        return final
    except Exception:
        return url


def safe_filename(title, ext="mp4"):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", (title or "video").strip())
    name = re.sub(r"\s+", " ", name).strip()[:60] or "video"
    return f"{name}.{ext}"


def pick(d, *keys):
    for k in keys:
        v = d.get(k)
        if v:
            return v
    return None


def ytdlp_extra():
    extra = os.environ.get("YTDLP_EXTRA_ARGS", "").strip()
    return extra.split() if extra else []


# ---------------------------------------------------------------- parse-API engine
def api_parse(url):
    """ပြင်ပ 解析 API ကို ခေါ် → (info|None, status, api_msg)."""
    try:
        r = requests.get(PARSE_API + quote(url, safe=""),
                         timeout=RESOLVE_TIMEOUT,
                         headers={"User-Agent": UA})
        j = r.json()
    except Exception:
        return None, "unreachable", ""
    code = j.get("code")
    msg = str(j.get("msg") or j.get("message") or "")
    data = j.get("data")
    if code not in (0, 200) or not data or isinstance(data, list):
        return None, "api_fail", msg
    if isinstance(data, dict):
        video_url = pick(data, "url", "video_url", "play_url", "videoUrl",
                         "nwm_url", "download_url")
        backups = data.get("video_backup") or data.get("videos") or []
        if isinstance(backups, dict):
            backups = list(backups.values())
        images = data.get("images") or data.get("image_list") or data.get("pics") or []
        info = {
            "title": pick(data, "title", "desc", "description") or "video",
            "author": pick(data, "author", "nickname", "uploader") or "",
            "cover": pick(data, "cover", "cover_url", "thumbnail", "pic") or "",
            "duration": data.get("duration") or 0,
            "video_url": video_url,
            "backups": [b for b in backups if isinstance(b, str)][:4],
            "images": [i if isinstance(i, str) else pick(i, "url", "src")
                       for i in images if isinstance(i, (str, dict))][:20],
        }
        if not info["video_url"] and not info["images"]:
            return None, "api_fail", msg
        return info, "ok", msg
    return None, "api_fail", msg


def api_parse_retry(url, resolved_url):
    """resolved URL နဲ့မရရင် မူရင်း URL နဲ့ တစ်ခါထပ်စမ်း."""
    info, status, msg = api_parse(resolved_url)
    if info:
        return info, status, msg, resolved_url
    if resolved_url != url:
        info2, status2, msg2 = api_parse(url)
        if info2:
            return info2, status2, msg2, url
    return None, status, msg, resolved_url


# ---------------------------------------------------------------- yt-dlp engine
def ytdlp_json(url):
    cmd = (["yt-dlp"] + ytdlp_extra()
           + ["--no-playlist", "--no-warnings", "--skip-download",
              "--socket-timeout", "25", "--extractor-retries", "2",
              "--dump-json", url])
    if base_domain(host_of(url)) in YT_DOMAINS:
        cmd[1:1] = YT_ARGS
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=RESOLVE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    if p.returncode != 0:
        msg = (p.stderr or "").lower()
        if "not a bot" in msg or "sign in to confirm" in msg:
            return None, "bot"
        if "private" in msg or "login" in msg or "sign in" in msg:
            return None, "private"
        if "unsupported url" in msg:
            return None, "unsupported"
        return None, "not_found"
    try:
        return json.loads(p.stdout), None
    except Exception:
        return None, "not_found"


def ytdlp_qualities(info):
    quals = []
    seen = set()
    for f in info.get("formats") or []:
        if f.get("vcodec") in (None, "none"):
            continue
        h = f.get("height")
        if not h or h in seen:
            continue
        seen.add(h)
        size = f.get("filesize") or f.get("filesize_approx")
        quals.append({"id": str(h), "label": f"{h}p",
                      "size": size or 0})
    quals.sort(key=lambda q: int(q["id"]), reverse=True)
    return quals[:5]


def ytdlp_download(url, quality, tmpdir):
    if quality and quality != "best":
        fmt = f"b[height<={quality}]/b"
    else:
        fmt = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"
    out = os.path.join(tmpdir, "video.%(ext)s")
    cmd = (["yt-dlp"] + ytdlp_extra()
           + ["--no-playlist", "--no-warnings",
              "--socket-timeout", "25", "--extractor-retries", "2",
              "--max-filesize", f"{MAX_MB}M",
              "-f", fmt, "--merge-output-format", "mp4",
              "-o", out, url])
    if base_domain(host_of(url)) in YT_DOMAINS:
        cmd[1:1] = YT_ARGS
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    if p.returncode != 0:
        if "too large" in (p.stderr or "").lower() or "max-filesize" in (p.stderr or "").lower():
            return None, "too_big"
        return None, "parse_fail"
    files = [f for f in os.listdir(tmpdir) if f.startswith("video.")]
    if not files:
        return None, "parse_fail"
    return os.path.join(tmpdir, files[0]), None


# ---------------------------------------------------------------- routes
@app.get("/health")
def health():
    return jsonify(ok=True)


@app.get("/")
def index():
    return send_file("index.html")


@app.post("/api/resolve")
def resolve():
    denied = check_token()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    orig_url = (body.get("url") or "").strip()
    debug = request.args.get("debug") == "1"
    if not valid_url(orig_url):
        return jsonify(ok=False, error=ERR["bad_url"])

    url = resolve_url(orig_url)
    host = host_of(url)
    domain = base_domain(host)
    engine = "api" if domain in API_ENGINE else ("ytdlp" if domain in YTDLP_ENGINE else None)
    if not engine:
        # မသိတဲ့ domain — yt-dlp နဲ့ အရင်စမ်းကြည့်
        engine = "ytdlp"
    platform = KNOWN.get(domain, domain or "unknown")
    dbg = {"resolved": url} if debug else None

    if engine == "api":
        info, status, api_msg, used = api_parse_retry(orig_url, url)
        if dbg is not None:
            dbg.update(api_status=status, api_msg=api_msg[:120], via=used)
        if not info:
            err_key = "api_down" if status == "unreachable" else "not_found"
            resp = jsonify(ok=False, error=ERR[err_key], platform=platform)
            if dbg is not None:
                resp = jsonify(ok=False, error=ERR[err_key], platform=platform, debug=dbg)
            return resp
        kind = "video" if info["video_url"] else "images"
        quals = []
        if kind == "video":
            quals = [{"id": "best", "label": "အကောင်းဆုံး", "size": 0}]
            for i, b in enumerate(info["backups"][:3]):
                quals.append({"id": f"alt{i}", "label": f"ရွေးချယ်စရာ {i+1}", "size": 0})
        out = dict(ok=True, engine="api", platform=platform, kind=kind,
                   title=info["title"], author=info["author"],
                   cover=info["cover"], duration=info["duration"],
                   qualities=quals, image_count=len(info["images"]),
                   url=used)
        if dbg is not None:
            out["debug"] = dbg
        return jsonify(out)

    info, err = ytdlp_json(url)
    if err and domain in YT_DOMAINS:
        # YouTube fallback — parse API ကနေတစ်ဆင့်
        ainfo, status, api_msg, used = api_parse_retry(orig_url, url)
        if dbg is not None:
            dbg.update(ytdlp_err=err, api_status=status, api_msg=api_msg[:120])
        if ainfo and ainfo["video_url"]:
            out = dict(ok=True, engine="api", platform=platform, kind="video",
                       title=ainfo["title"], author=ainfo["author"],
                       cover=ainfo["cover"], duration=ainfo["duration"],
                       qualities=[{"id": "best", "label": "အကောင်းဆုံး", "size": 0}],
                       image_count=0, url=used)
            if dbg is not None:
                out["debug"] = dbg
            return jsonify(out)
    if err:
        out = dict(ok=False, error=ERR.get(err, ERR["parse_fail"]), platform=platform)
        if dbg is not None:
            out["debug"] = dbg
        return jsonify(out)
    quals = ytdlp_qualities(info)
    if not quals:
        quals = [{"id": "best", "label": "အကောင်းဆုံး", "size": 0}]
    out = dict(ok=True, engine="ytdlp", platform=platform, kind="video",
               title=info.get("title") or "video",
               author=info.get("uploader") or info.get("channel") or "",
               cover=info.get("thumbnail") or "",
               duration=info.get("duration") or 0,
               qualities=quals, url=url)
    if dbg is not None:
        out["debug"] = dbg
    return jsonify(out)


def stream_url(url, referer=""):
    headers = {"User-Agent": UA, "Referer": referer or url}
    r = requests.get(url, stream=True, timeout=60, headers=headers)
    r.raise_for_status()
    return r


def stream_api_video(vurl, title, referer):
    """parse-API က ပေးတဲ့直链 ကို client ဆီ stream လုပ်."""
    try:
        r = stream_url(vurl, referer=referer)
    except Exception:
        return jsonify(ok=False, error=ERR["timeout"]), 502
    length = r.headers.get("Content-Length")
    if length and int(length) > MAX_MB * 1024 * 1024:
        r.close()
        return jsonify(ok=False, error=ERR["too_big"]), 413
    fname = safe_filename(title)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"}
    if length:
        headers["Content-Length"] = length
    return Response(r.iter_content(chunk_size=1024 * 256),
                    mimetype="video/mp4", headers=headers,
                    direct_passthrough=True)


@app.get("/api/dl")
def dl():
    denied = check_token()
    if denied:
        return denied
    url = (request.args.get("url") or "").strip()
    q = (request.args.get("q") or "best").strip()
    title = (request.args.get("t") or "video").strip()
    if not valid_url(url):
        return jsonify(ok=False, error=ERR["bad_url"]), 400

    domain = base_domain(host_of(url))
    if domain in API_ENGINE:
        info, status, _msg = api_parse(url)
        if status == "unreachable":
            return jsonify(ok=False, error=ERR["api_down"]), 502
        if not info or not info["video_url"]:
            return jsonify(ok=False, error=ERR["not_found"]), 502
        vurl = info["video_url"]
        if q.startswith("alt"):
            try:
                vurl = info["backups"][int(q[3:])] or vurl
            except (IndexError, ValueError):
                pass
        return stream_api_video(vurl, title or info["title"], url)

    # yt-dlp engine — file ဒေါင်းပြီးမှ ပြန် serve လုပ်
    tmpdir = tempfile.mkdtemp(prefix="vddl_")
    path, err = ytdlp_download(url, q, tmpdir)
    if err and domain in YT_DOMAINS:
        # YouTube fallback — parse API直链 ကို stream လုပ်
        info, status, _msg = api_parse(url)
        if info and info["video_url"]:
            return stream_api_video(info["video_url"], title, url)
    if err:
        return jsonify(ok=False, error=ERR.get(err, ERR["parse_fail"])), 502
    fname = safe_filename(title)
    resp = send_file(path, mimetype="video/mp4", as_attachment=True,
                     download_name=fname)
    resp.headers["Access-Control-Allow-Origin"] = "*"

    @resp.call_on_close
    def _clean():
        try:
            os.remove(path)
            os.rmdir(tmpdir)
        except OSError:
            pass
    return resp


@app.get("/api/zip")
def zip_images():
    """photo-note image တွေကို zip တစ်ဖိုင်တည်း ဒေါင်းလုဒ်."""
    denied = check_token()
    if denied:
        return denied
    url = (request.args.get("url") or "").strip()
    title = (request.args.get("t") or "images").strip()
    if not valid_url(url):
        return jsonify(ok=False, error=ERR["bad_url"]), 400
    info = api_parse(url)
    if not info or not info["images"]:
        return jsonify(ok=False, error=ERR["not_found"]), 502
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, img in enumerate(info["images"][:20], 1):
            try:
                r = requests.get(img, timeout=30, headers={"User-Agent": UA,
                                                           "Referer": url})
                r.raise_for_status()
                ext = ".jpg"
                ct = r.headers.get("Content-Type", "")
                if "png" in ct:
                    ext = ".png"
                elif "webp" in ct:
                    ext = ".webp"
                z.writestr(f"img_{i:02d}{ext}", r.content)
            except Exception:
                continue
    buf.seek(0)
    fname = safe_filename(title, ext="zip")
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=fname)


@app.after_request
def cors(resp):
    resp.headers.setdefault("Access-Control-Allow-Origin", "*")
    return resp


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
