"""
Production Cookie Server for Gemini & YouTube
=============================================
Endpoints:
- /get?cookies=gemini   -> Gemini login cookies
- /get?cookies=youtube  -> YouTube login cookies
- /login                -> Trigger cloud login engine
"""

import os
import sys
import time
import json
import asyncio
import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(BASE_DIR, "session_data.json")

GEMINI_URL = "https://gemini.google.com/app"
YOUTUBE_URL = "https://www.youtube.com/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def load_session():
    """session_data.json থেকে সেভ থাকা cookies লোড করো।"""
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data and data.get("cookies"):
                    return data
        except Exception:
            pass
    return None


def build_requests_session(cookies: list) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    for c in cookies:
        domain = c.get("domain", ".google.com")
        s.cookies.set(c["name"], c["value"], domain=domain)
    return s


def is_service_logged_in(s: requests.Session, target: str) -> bool:
    try:
        if target == "gemini":
            r = s.get(GEMINI_URL, timeout=10, allow_redirects=True)
            return "accounts.google.com" not in r.url and r.status_code == 200
        elif target == "youtube":
            r = s.get("https://www.youtube.com/", timeout=10, allow_redirects=True)
            return any(c.name in ["SAPISID", "APISID", "LOGIN_INFO", "SID"] for c in s.cookies)
        return True
    except Exception:
        return False


def refresh_live_cookies(s: requests.Session, target: str):
    """Google Endpoints হিট করে Set-Cookie রোটেট ও সেভ করো।"""
    urls = [
        "https://accounts.google.com/ListAccounts?gpsia=1&source=ChromiumBrowser",
        GEMINI_URL if target == "gemini" else YOUTUBE_URL
    ]
    for u in urls:
        try:
            s.get(u, timeout=8, allow_redirects=True)
        except Exception:
            pass

    updated = []
    for c in s.cookies:
        updated.append({
            "name": c.name,
            "value": c.value,
            "domain": c.domain or ".google.com",
            "path": c.path or "/",
            "secure": bool(c.secure),
            "httpOnly": False,
            "expiry": int(c.expires) if c.expires else int(time.time()) + 86400 * 30
        })

    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump({"cookies": updated, "timestamp": time.time(), "target": target}, f, indent=4, ensure_ascii=False)
    except Exception:
        pass

    return updated


def filter_cookies(cookies: list, service: str):
    res = []
    for c in cookies:
        d = c.get("domain", "").lower()
        if service == "gemini":
            if "google.com" in d and "youtube" not in d:
                res.append(c)
        elif service == "youtube":
            if "youtube.com" in d or "google.com" in d:
                res.append(c)
    return res


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "service": "Google Cookies API (Playwright Cloud Engine)",
        "endpoints": {
            "/get?cookies=gemini": "Get active Gemini login cookies",
            "/get?cookies=youtube": "Get active YouTube login cookies",
            "/login": "Trigger direct Google login"
        }
    })


@app.route("/login", methods=["POST", "GET"])
def trigger_login():
    email = request.args.get("email") or "illukailluma@gmail.com"
    password = request.args.get("password") or "marasudo15"

    try:
        from cloud_login import perform_login
        data = asyncio.run(perform_login(email, password))
        
        # If Google presented a challenge (2FA or Captcha), show diagnosis
        if not data.get("logged_in") and data.get("screenshot_base64"):
            html = f"""
            <html>
                <body style="font-family:sans-serif; background:#121212; color:#fff; text-align:center; padding:20px;">
                    <h2>⚠️ Google Login Challenge / 2FA Verification Needed</h2>
                    <p>Current Page URL: <code>{data.get('current_url')}</code></p>
                    <p>Google is displaying the following screen on the server. If this is a 2-Step Verification prompt, please approve it on your phone!</p>
                    <img style="border:2px solid #555; max-width:90%; border-radius:8px;" src="data:image/png;base64,{data.get('screenshot_base64')}" />
                </body>
            </html>
            """
            return html, 200

        return jsonify({
            "success": True,
            "logged_in": data.get("logged_in", False),
            "cookies_count": data.get("cookies_count", 0),
            "current_url": data.get("current_url")
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/get", methods=["GET"])
def api_get():
    service = request.args.get("cookies", "").strip().lower()
    if service not in ["gemini", "youtube"]:
        return jsonify({"success": False, "error": "Use ?cookies=gemini or ?cookies=youtube"}), 400

    session_data = load_session()

    # If no session or invalid, trigger auto-login
    if not session_data:
        try:
            from cloud_login import perform_login
            session_data = asyncio.run(perform_login())
        except Exception as e:
            return jsonify({"success": False, "error": f"Initial login error: {e}"}), 500

    cookies = session_data.get("cookies", [])
    s = build_requests_session(cookies)

    if not is_service_logged_in(s, service):
        try:
            from cloud_login import perform_login
            session_data = asyncio.run(perform_login())
            cookies = session_data.get("cookies", [])
            s = build_requests_session(cookies)
        except Exception:
            pass

    fresh_cookies = refresh_live_cookies(s, service)
    filtered = filter_cookies(fresh_cookies, service)

    return jsonify({
        "success": True,
        "service": service,
        "cookies_count": len(filtered),
        "timestamp": time.time(),
        "cookies": filtered
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
