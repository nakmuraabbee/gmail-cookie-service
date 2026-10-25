"""
Universal Google Services Cookie API (Gemini & YouTube)
========================================================
- /get?cookies=gemini   -> Gemini (https://gemini.google.com/) authenticated cookies
- /get?cookies=youtube  -> YouTube (https://www.youtube.com/) authenticated cookies

Strategy:
1. Always maintains genuine logged-in session (SID, HSID, SSID, APISID, SAPISID, OSID)
2. Auto-rotates security tokens via Google internal Keep-Alive endpoints
3. If session needs refresh, launches Playwright/CDP with master tokens injected into the browser context
"""

import os
import sys
import time
import json
import asyncio
import subprocess
import requests
import websockets
from flask import Flask, jsonify, request

app = Flask(__name__)

# ========================= CONFIG =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUTH_TOKENS_FILE = os.path.join(BASE_DIR, "auth_tokens.json")
SESSION_FILE = os.path.join(BASE_DIR, "session_data.json")
CDP_PORT = 9222

GEMINI_URL = "https://gemini.google.com/app"
YOUTUBE_URL = "https://www.youtube.com/"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
# ==========================================================


def find_chrome_binary():
    """OS অনুযায়ী উপযুক্ত Chrome/Chromium বাইনারি বের করো।"""
    if os.environ.get("CHROME_PATH"):
        return os.environ.get("CHROME_PATH")

    if sys.platform.startswith("win"):
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")
        ]
        for path in candidates:
            if os.path.exists(path):
                return path

    linux_candidates = [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/snap/bin/chromium"
    ]
    for path in linux_candidates:
        if os.path.exists(path):
            return path

    import shutil
    found = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if found:
        return found

    return "chromium"


def get_master_cookies():
    """Master auth tokens লোড করো।"""
    # 1. Try session_data.json if exists and valid
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data and data.get("cookies"):
                    return data.get("cookies")
        except Exception:
            pass

    # 2. Try auth_tokens.json
    if os.path.exists(AUTH_TOKENS_FILE):
        try:
            with open(AUTH_TOKENS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data and data.get("cookies"):
                    return data.get("cookies")
        except Exception:
            pass

    return []


def build_requests_session(cookies: list) -> requests.Session:
    """Session প্রস্তুত করো।"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    for c in cookies:
        domain = c.get("domain", ".google.com")
        s.cookies.set(c["name"], c["value"], domain=domain)
    return s


def is_service_logged_in(s: requests.Session, target: str) -> bool:
    """যাচাই করো ইউজার আসলেই লগইন অবস্থায় আছে কিনা।"""
    try:
        if target == "gemini":
            r = s.get(GEMINI_URL, timeout=10, allow_redirects=True)
            return "accounts.google.com" not in r.url and r.status_code == 200
        elif target == "youtube":
            r = s.get("https://www.youtube.com/", timeout=10, allow_redirects=True)
            # Check if user has auth cookies in session
            yt_auth = any(c.name in ["SAPISID", "APISID", "LOGIN_INFO"] for c in s.cookies)
            return yt_auth and r.status_code == 200
        return True
    except Exception as e:
        print(f"[!] Login check failed for {target}: {e}")
        return False


def refresh_and_sync_cookies(s: requests.Session, target: str):
    """Google-এর সাথে হ্যান্ডশেক করে নতুন Set-Cookie সংগ্রহ ও সেভ করো।"""
    endpoints = [
        "https://accounts.google.com/ListAccounts?gpsia=1&source=ChromiumBrowser",
        GEMINI_URL if target == "gemini" else YOUTUBE_URL,
    ]
    for url in endpoints:
        try:
            s.get(url, timeout=8, allow_redirects=True)
        except Exception:
            pass

    # Merge all cookies
    all_cookies = []
    for c in s.cookies:
        all_cookies.append({
            "name": c.name,
            "value": c.value,
            "domain": c.domain or ".google.com",
            "path": c.path or "/",
            "secure": bool(c.secure),
            "httpOnly": False,
            "expiry": int(c.expires) if c.expires else int(time.time()) + 86400 * 30
        })

    # Save to session_data.json
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump({"cookies": all_cookies, "timestamp": time.time(), "target": target}, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Session file write error: {e}")

    return all_cookies


# ─────────────────────────────────────────────────────────
#  PART 2 — Browser Automation (CDP Injected Fallback)
# ─────────────────────────────────────────────────────────

def launch_browser_cdp(target_url: str):
    chrome_bin = find_chrome_binary()
    cmd = [
        chrome_bin,
        f"--remote-debugging-port={CDP_PORT}",
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        target_url
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def _browser_inject_and_extract(target_url: str, cookies: list):
    # Wait for CDP endpoint
    for _ in range(25):
        try:
            r = requests.get(f"http://127.0.0.1:{CDP_PORT}/json", timeout=2)
            if r.status_code == 200 and r.json():
                break
        except Exception:
            pass
        await asyncio.sleep(0.8)

    r = requests.get(f"http://127.0.0.1:{CDP_PORT}/json")
    tabs = r.json()
    page_tab = next((t for t in tabs if t.get("type") == "page"), tabs[0])
    ws_url = page_tab["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
        await ws.recv()

        # Inject Master Authentication Cookies
        formatted = []
        for c in cookies:
            formatted.append({
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ".google.com"),
                "path": c.get("path", "/")
            })
        await ws.send(json.dumps({"id": 2, "method": "Network.setCookies", "params": {"cookies": formatted}}))
        await ws.recv()

        # Navigate to target
        await ws.send(json.dumps({"id": 3, "method": "Page.navigate", "params": {"url": target_url}}))
        await ws.recv()

        # Give browser time to load Google auth
        await asyncio.sleep(8)

        # Extract all cookies
        await ws.send(json.dumps({"id": 4, "method": "Network.getAllCookies"}))
        resp = await ws.recv()
        data = json.loads(resp)
        return data.get("result", {}).get("cookies", [])


def extract_via_browser_automation(target_url: str, master_cookies: list):
    proc = launch_browser_cdp(target_url)
    try:
        return asyncio.run(_browser_inject_and_extract(target_url, master_cookies))
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────
#  PART 3 — Cookie Filtering & Endpoint Dispatcher
# ─────────────────────────────────────────────────────────

def filter_service_cookies(cookies: list, service: str):
    """সার্ভিস ভিত্তিক ফিল্টারিং: নিশ্চিত করে লগইন টোকেন যেন অবশ্যই থাকে।"""
    result = []
    for c in cookies:
        d = c.get("domain", "").lower()
        if service == "gemini":
            # Gemini requires google.com, gemini.google.com, accounts.google.com
            if "google.com" in d and "youtube" not in d:
                result.append(c)
        elif service == "youtube":
            # YouTube requires youtube.com and root google.com auth
            if "youtube.com" in d or "google.com" in d:
                result.append(c)
    return result


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "service": "Google Authenticated Cookie Provider",
        "endpoints": {
            "/get?cookies=gemini": "Live Gemini login cookies (SID, HSID, SSID, etc.)",
            "/get?cookies=youtube": "Live YouTube login cookies (SID, HSID, SSID, etc.)",
            "/login": "One-time direct cloud login (POST {email, password})"
        }
    })


@app.route("/login", methods=["POST", "GET"])
def api_login():
    """সার্ভারে সরাসরি একবার Google অ্যাকাউন্টে লগইন করে পার্মানেন্ট লিনাক্স প্রোফাইল বানানোর এন্ডপয়েন্ট।"""
    email = request.args.get("email") or (request.json or {}).get("email") or "illukailluma@gmail.com"
    password = request.args.get("password") or (request.json or {}).get("password")

    if not password:
        return jsonify({
            "success": False,
            "message": "Password is required for first-time cloud authorization.",
            "usage": "POST /login with JSON {'email': '...', 'password': '...'}"
        }), 400

    try:
        from cloud_login import perform_login
        asyncio.run(perform_login(email, password))
        return jsonify({
            "success": True,
            "message": f"Successfully authenticated {email} directly on Linux cloud server!"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/get", methods=["GET"])
def api_get():
    service = request.args.get("cookies", "").strip().lower()
    if service not in ["gemini", "youtube"]:
        return jsonify({
            "success": False,
            "error": "Invalid parameter. Please use ?cookies=gemini or ?cookies=youtube"
        }), 400

    master_cookies = get_master_cookies()
    if not master_cookies:
        return jsonify({"success": False, "error": "No master auth tokens found."}), 500

    target_url = GEMINI_URL if service == "gemini" else YOUTUBE_URL

    # Step 1: Check session with master cookies
    session = build_requests_session(master_cookies)
    
    if is_service_logged_in(session, service):
        all_cookies = refresh_and_sync_cookies(session, service)
        service_cookies = filter_service_cookies(all_cookies, service)
        method = "requests_authenticated"
    else:
        # Step 2: Fallback to full browser automation
        raw_cookies = extract_via_browser_automation(target_url, master_cookies)
        service_cookies = filter_service_cookies(raw_cookies, service)
        method = "browser_cdp_authenticated"

    return jsonify({
        "success": True,
        "service": service,
        "method": method,
        "cookies_count": len(service_cookies),
        "timestamp": time.time(),
        "cookies": service_cookies
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
