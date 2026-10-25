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


@app.route("/rdp", methods=["GET"])
def remote_desktop_ui():
    """Interactive Web-RDP Interface: Click, Type, solve Captcha, and Save Session directly."""
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Cloud Browser Remote Controller (Web-RDP)</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { background: #0f172a; color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; flex-direction: column; align-items: center; min-height: 100vh; padding: 15px; }
            .header { width: 100%; max-width: 1280px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
            .title { font-size: 1.1rem; font-weight: 600; color: #38bdf8; display: flex; align-items: center; gap: 8px; }
            .controls { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
            input[type="text"] { background: #1e293b; border: 1px solid #334155; color: #fff; padding: 8px 12px; border-radius: 6px; font-size: 0.9rem; outline: none; width: 260px; }
            input[type="text"]:focus { border-color: #38bdf8; }
            button { background: #2563eb; color: #fff; border: none; padding: 8px 14px; border-radius: 6px; font-weight: 500; cursor: pointer; transition: 0.2s; font-size: 0.85rem; }
            button:hover { background: #1d4ed8; }
            button.success { background: #16a34a; }
            button.success:hover { background: #15803d; }
            button.warning { background: #ea580c; }
            button.warning:hover { background: #c2410c; }
            .screen-wrapper { position: relative; border: 2px solid #334155; border-radius: 8px; overflow: hidden; background: #000; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.5); cursor: crosshair; }
            #browser-screen { display: block; max-width: 100%; height: auto; }
            .status-bar { width: 100%; max-width: 1280px; margin-top: 8px; font-size: 0.8rem; color: #94a3b8; display: flex; justify-content: space-between; }
            .loading { position: absolute; top: 10px; right: 10px; background: rgba(0,0,0,0.7); padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; color: #38bdf8; display: none; }
        </style>
    </head>
    <body>
        <div class="header">
            <div class="title">🖥️ Google Cloud Browser (Web-RDP)</div>
            <div class="controls">
                <input type="text" id="type-input" placeholder="Type text here..." />
                <button onclick="sendType()">Type Text</button>
                <button onclick="smartFill()" class="warning">⚡ Fill Input Box</button>
                <button onclick="sendKey('Enter')" class="warning">Press Enter</button>
                <button onclick="sendKey('Tab')">Tab</button>
                <button onclick="sendKey('Backspace')">Backspace</button>
                <button onclick="refreshScreen()">🔄 Refresh</button>
                <button onclick="saveSession()" class="success">💾 Save Login Session</button>
            </div>
        </div>

        <div class="screen-wrapper" onclick="handleScreenClick(event)">
            <img id="browser-screen" src="" alt="Loading remote screen..." />
            <div id="loading" class="loading">Processing...</div>
        </div>

        <div class="status-bar">
            <span id="current-url">URL: Loading...</span>
            <span>💡 <b>টিপস:</b> ইনপুট বক্সে লেখা বসাতে উপরে লেখা টাইপ করে <b>"⚡ Fill Input Box"</b> অথবা <b>"Type Text"</b> বাটনে চাপুন।</span>
        </div>

        <script>
            const img = document.getElementById('browser-screen');
            const urlSpan = document.getElementById('current-url');
            const loading = document.getElementById('loading');
            const typeInput = document.getElementById('type-input');

            typeInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    sendType();
                }
            });

            async function apiAction(action, params = {}) {
                loading.style.display = 'block';
                try {
                    const res = await fetch('/rdp/action', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ action, ...params })
                    });
                    const data = await res.json();
                    if (data.screenshot) {
                        img.src = 'data:image/png;base64,' + data.screenshot;
                    }
                    if (data.url) {
                        urlSpan.innerText = 'URL: ' + data.url;
                    }
                    if (data.saved) {
                        alert('🎉 Login Session Saved Successfully! Total cookies: ' + data.cookies_count);
                    }
                } catch(err) {
                    console.error(err);
                } finally {
                    loading.style.display = 'none';
                }
            }

            function handleScreenClick(e) {
                const rect = img.getBoundingClientRect();
                const scaleX = (img.naturalWidth || 1280) / rect.width;
                const scaleY = (img.naturalHeight || 800) / rect.height;
                const x = (e.clientX - rect.left) * scaleX;
                const y = (e.clientY - rect.top) * scaleY;
                apiAction('click', { x, y });
            }

            function sendType() {
                const text = typeInput.value;
                if (!text) return;
                apiAction('type', { text });
            }

            function smartFill() {
                const text = typeInput.value;
                if (!text) return;
                apiAction('fill', { text });
            }

            function sendKey(key) {
                apiAction('key', { key });
            }

            function refreshScreen() {
                apiAction('screenshot');
            }

            function saveSession() {
                apiAction('save');
            }

            // Initial load
            refreshScreen();
        </script>
    </body>
    </html>
    """
    return html, 200


@app.route("/rdp/action", methods=["POST"])
def remote_desktop_action():
    body = request.json or {}
    action = body.get("action", "screenshot")
    try:
        from remote_browser import handle_remote_action
        result = asyncio.run(handle_remote_action(action, body))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
