"""
Gmail Cookie & Session API Server
=================================
Linux (Render / Railway) এবং Windows উভয় প্ল্যাটফর্মে স্বয়ংক্রিয়ভাবে কাজ করে।
- Session valid থাকলে: requests-only (কোনো ব্রাউজার নেই, নো মেমোরি খরচ)
- Session expired হলে: Chromium/Chrome কে headless মোডে CDP চালু করে নতুন cookies সংগ্রহ করে
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
SESSION_FILE = os.path.join(BASE_DIR, "gmail_session_data.json")
PROFILE_PATH = os.path.join(BASE_DIR, "chrome_gmail_profile")
ZIP_PROFILE = os.path.join(BASE_DIR, "chrome_profile.zip")
CDP_PORT = 9222
GMAIL_URL = "https://mail.google.com/"
GMAIL_FEED = "https://mail.google.com/mail/feed/atom"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# Auto extract zip on server startup
if not os.path.exists(PROFILE_PATH) and os.path.exists(ZIP_PROFILE):
    print("[*] Extracting chrome_profile.zip...")
    import zipfile
    with zipfile.ZipFile(ZIP_PROFILE, 'r') as zip_ref:
        zip_ref.extractall(BASE_DIR)
    print(f"[+] chrome_profile extracted to {PROFILE_PATH}!")
# ==========================================================


def find_chrome_binary():
    """OS অনুযায়ী উপযুক্ত Chrome/Chromium বাইনারি বের করো।"""
    # 1. Custom ENV Path
    if os.environ.get("CHROME_PATH"):
        return os.environ.get("CHROME_PATH")

    # 2. Windows paths
    if sys.platform.startswith("win"):
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")
        ]
        for path in candidates:
            if os.path.exists(path):
                return path

    # 3. Linux / Docker / Railway / Render paths
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

    raise FileNotFoundError("Chrome/Chromium binary not found on this system. Please check CHROME_PATH environment variable.")


# ─────────────────────────────────────────────────────────
#  PART 1 — Requests Session Management (No Browser)
# ─────────────────────────────────────────────────────────

def load_session_file():
    """gmail_session_data.json থেকে cookies লোড করো।"""
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[!] Error loading {SESSION_FILE}: {e}")
        return None


def build_requests_session(cookies: list) -> requests.Session:
    """Cookie list থেকে requests.Session প্রস্তুত করো।"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    for c in cookies:
        domain = c.get("domain", ".google.com")
        s.cookies.set(c["name"], c["value"], domain=domain)
    return s


def is_session_valid(s: requests.Session) -> bool:
    """Gmail feed দিয়ে সেশন ভ্যালিডেশন চেক করো।"""
    try:
        r = s.get(GMAIL_FEED, timeout=8, allow_redirects=False)
        return r.status_code == 200
    except Exception as e:
        print(f"  [!] Session check error: {e}")
        return False


def refresh_cookies_via_request(s: requests.Session, old_data: dict) -> dict:
    """Requests দিয়ে সেশন রিফ্রেশ করে নতুন cookies সেভ করো।"""
    endpoints = [
        "https://accounts.google.com/ListAccounts?gpsia=1&source=ChromiumBrowser",
        "https://mail.google.com/mail/u/0/",
        GMAIL_FEED,
    ]
    for url in endpoints:
        try:
            s.get(url, timeout=8, allow_redirects=True)
        except Exception:
            pass

    updated_cookies = [
        {
            "name": c.name,
            "value": c.value,
            "domain": c.domain or ".google.com",
            "path": c.path or "/",
            "secure": bool(c.secure),
            "httpOnly": False,
            "expiry": int(c.expires) if c.expires else int(time.time()) + 86400 * 30
        }
        for c in s.cookies
    ]

    old_data["cookies"] = updated_cookies
    old_data["cookies_count"] = len(updated_cookies)
    old_data["timestamp"] = time.time()
    old_data["source"] = "requests_refresh_no_browser"

    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(old_data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Error writing session file: {e}")

    return old_data


# ─────────────────────────────────────────────────────────
#  PART 2 — CDP Headless Extraction (No Selenium/Playwright)
# ─────────────────────────────────────────────────────────

def launch_chrome_cdp():
    """Headless Chromium/Chrome চালু করো।"""
    chrome_bin = find_chrome_binary()
    print(f"[*] Starting Chrome via CDP ({chrome_bin})...")

    cmd = [
        chrome_bin,
        f"--user-data-dir={PROFILE_PATH}",
        f"--remote-debugging-port={CDP_PORT}",
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        GMAIL_URL
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc


def wait_for_cdp(timeout=20):
    """CDP WebSocket endpoint প্রস্তুত হওয়া পর্যন্ত অপেক্ষা করো।"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"http://127.0.0.1:{CDP_PORT}/json", timeout=2)
            if r.status_code == 200:
                tabs = r.json()
                if tabs:
                    return tabs
        except Exception:
            pass
        time.sleep(0.8)
    raise TimeoutError("Chrome CDP ready timeout.")


async def _cdp_get_cookies(ws_url):
    """Raw WebSocket দিয়ে Network.getAllCookies কল করো।"""
    async with websockets.connect(ws_url) as ws:
        msg = json.dumps({"id": 1, "method": "Network.getAllCookies", "params": {}})
        await ws.send(msg)
        resp = await ws.recv()
        data = json.loads(resp)
        return data.get("result", {}).get("cookies", [])


async def _cdp_inject_and_load(ws_url, seed_cookies):
    """Seed cookies ইনজেক্ট করে Gmail পেজ রিফ্রেশ করো।"""
    async with websockets.connect(ws_url) as ws:
        # Enable Network and Page
        await ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
        await ws.recv()
        await ws.send(json.dumps({"id": 2, "method": "Page.enable"}))
        await ws.recv()

        # Inject existing seed cookies
        if seed_cookies:
            clean_cookies = []
            for c in seed_cookies:
                item = {
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c.get("domain", ".google.com"),
                    "path": c.get("path", "/")
                }
                clean_cookies.append(item)
            await ws.send(json.dumps({"id": 3, "method": "Network.setCookies", "params": {"cookies": clean_cookies}}))
            await ws.recv()
            print(f"[+] Injected {len(clean_cookies)} seed cookies into Chromium!")

        # Navigate to Gmail
        await ws.send(json.dumps({"id": 4, "method": "Page.navigate", "params": {"url": GMAIL_URL}}))
        await ws.recv()


def extract_cookies_via_cdp():
    """Wait for page load and extract all browser cookies via CDP."""
    tabs = wait_for_cdp()
    page_tab = next((t for t in tabs if t.get("type") == "page"), tabs[0])
    ws_url = page_tab["webSocketDebuggerUrl"]

    # Load seed cookies if available
    seed_file = os.path.join(BASE_DIR, "seed_cookies.json")
    seed_cookies = []
    if os.path.exists(seed_file):
        try:
            with open(seed_file, "r", encoding="utf-8") as f:
                seed_data = json.load(f)
                seed_cookies = seed_data.get("cookies", [])
        except Exception:
            pass

    # Inject and reload
    asyncio.run(_cdp_inject_and_load(ws_url, seed_cookies))
    time.sleep(10)  # Wait for Google login refresh and token rotation

    # Try browser target first
    try:
        r = requests.get(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=3)
        if r.status_code == 200:
            browser_ws = r.json().get("webSocketDebuggerUrl")
            if browser_ws:
                cookies = asyncio.run(_cdp_get_cookies(browser_ws))
                if len(cookies) > 5:
                    return cookies
    except Exception as e:
        print(f"[!] Browser target cookie fetch error: {e}")

    # Fallback to page tab target
    return asyncio.run(_cdp_get_cookies(ws_url))


def get_active_session():
    """ভ্যালিড requests.Session রিটার্ন করে।"""
    data = load_session_file()
    if data and data.get("cookies"):
        s = build_requests_session(data["cookies"])
        if is_session_valid(s):
            refresh_cookies_via_request(s, data)
            return s, "requests_existing"

    # Cookies expired or missing -> launch headless CDP
    proc = launch_chrome_cdp()
    try:
        time.sleep(6)
        cookies = extract_cookies_via_cdp()
        payload = {
            "profile_path": PROFILE_PATH,
            "cookies_count": len(cookies),
            "cookies": cookies,
            "timestamp": time.time(),
            "source": "cdp_headless"
        }
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
        s = build_requests_session(cookies)
        return s, "cdp_refreshed"
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────
#  PART 3 — HTTP API Endpoints
# ─────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "service": "Gmail Cookie & Session API",
        "endpoints": {
            "/cookies": "Get active Gmail cookies (JSON)",
            "/check": "Check Gmail session validity",
            "/feed": "Get Gmail inbox feed / unread summary"
        }
    })


@app.route("/cookies", methods=["GET"])
def api_get_cookies():
    try:
        session, method = get_active_session()
        data = load_session_file() or {}
        return jsonify({
            "success": True,
            "method": method,
            "cookies_count": data.get("cookies_count", 0),
            "timestamp": data.get("timestamp"),
            "cookies": data.get("cookies", [])
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/check", methods=["GET"])
def api_check_session():
    try:
        session, method = get_active_session()
        valid = is_session_valid(session)
        return jsonify({
            "success": True,
            "is_valid": valid,
            "method": method
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/feed", methods=["GET"])
def api_gmail_feed():
    try:
        session, _ = get_active_session()
        r = session.get(GMAIL_FEED, timeout=10)
        return jsonify({
            "success": r.status_code == 200,
            "status_code": r.status_code,
            "xml_preview": r.text[:500] if r.status_code == 200 else None
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
