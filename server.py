"""
Multi-Service Cookie API Server (Gemini & YouTube)
===================================================
- /get?cookies=gemini   -> Gemini (https://gemini.google.com/) cookies
- /get?cookies=youtube  -> YouTube (https://www.youtube.com/) cookies

লজিক:
1. প্রথমে সেভ থাকা cookies দিয়ে ভ্যালিডিটি চেক করা হয় (কোনো ব্রাউজার খোলে না)
2. সেশন ভ্যালিড থাকলে ফ্রেশ রিকোয়েস্ট চালিয়ে নতুন cookies merge করে রিটার্ন করে
3. যদি এক্সপায়ার হয়, কেবল তখনই headless Chromium চালু করে লাইভ cookies রিফ্রেশ করে
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
SESSION_FILE = os.path.join(BASE_DIR, "session_data.json")
SEED_FILE = os.path.join(BASE_DIR, "seed_cookies.json")
PROFILE_PATH = os.path.join(BASE_DIR, "chrome_profile")
ZIP_PROFILE = os.path.join(BASE_DIR, "chrome_profile.zip")
CDP_PORT = 9222

GEMINI_URL = "https://gemini.google.com/app"
YOUTUBE_URL = "https://www.youtube.com/"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# Auto extract zip on server startup if needed
if not os.path.exists(PROFILE_PATH) and os.path.exists(ZIP_PROFILE):
    print("[*] Extracting chrome_profile.zip...")
    import zipfile
    try:
        with zipfile.ZipFile(ZIP_PROFILE, 'r') as zip_ref:
            zip_ref.extractall(BASE_DIR)
        print(f"[+] Profile extracted to {PROFILE_PATH}!")
    except Exception as e:
        print(f"[!] Zip extract error: {e}")
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

    raise FileNotFoundError("Chrome/Chromium binary not found on this system.")


# ─────────────────────────────────────────────────────────
#  PART 1 — Session & Cookie Helpers
# ─────────────────────────────────────────────────────────

def load_session_file():
    """session_data.json অথবা seed_cookies.json থেকে cookies লোড করো।"""
    # 1. Try session_data.json
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data and data.get("cookies"):
                    return data
        except Exception as e:
            print(f"[!] Error loading {SESSION_FILE}: {e}")

    # 2. Try seed_cookies.json
    if os.path.exists(SEED_FILE):
        try:
            with open(SEED_FILE, "r", encoding="utf-8") as f:
                seed_data = json.load(f)
                if seed_data and seed_data.get("cookies"):
                    return seed_data
        except Exception as e:
            print(f"[!] Error loading {SEED_FILE}: {e}")

    return None


def build_requests_session(cookies: list) -> requests.Session:
    """Cookie list থেকে requests.Session প্রস্তুত করো।"""
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


def is_service_valid(s: requests.Session, target: str) -> bool:
    """সার্ভিস ভিত্তিক সেশন ভ্যালিডেশন চেক করো।"""
    try:
        if target == "gemini":
            r = s.get(GEMINI_URL, timeout=10, allow_redirects=True)
            # Gemini-তে লগইন থাকলে URL 'gemini.google.com/app' থাকবে, লগইন না থাকলে accounts.google.com-এ রিডাইরেক্ট হবে
            return "accounts.google.com" not in r.url and r.status_code == 200
        elif target == "youtube":
            r = s.get("https://www.youtube.com/feed/library", timeout=10, allow_redirects=True)
            return "accounts.google.com" not in r.url and r.status_code == 200
        else:
            r = s.get("https://accounts.google.com/ListAccounts?gpsia=1&source=ChromiumBrowser", timeout=8)
            return r.status_code == 200
    except Exception as e:
        print(f"  [!] Session check error for {target}: {e}")
        return False


def refresh_service_cookies(s: requests.Session, target: str, old_data: dict) -> dict:
    """Requests দিয়ে সার্ভিস হিট করে নতুন rotate হওয়া cookies সেভ করো।"""
    urls = []
    if target == "gemini":
        urls = [
            GEMINI_URL,
            "https://gemini.google.com/_/BardChatUi/data/batchexecute",
            "https://accounts.google.com/ListAccounts?gpsia=1&source=ChromiumBrowser"
        ]
    elif target == "youtube":
        urls = [
            YOUTUBE_URL,
            "https://www.youtube.com/feed/subscriptions",
            "https://accounts.google.com/ListAccounts?gpsia=1&source=ChromiumBrowser"
        ]

    for url in urls:
        try:
            s.get(url, timeout=8, allow_redirects=True)
        except Exception:
            pass

    # Merge newly received cookies
    existing_cookie_map = {f"{c.get('domain', '')}:{c.get('name', '')}": c for c in old_data.get("cookies", [])}

    for c in s.cookies:
        key = f"{c.domain or '.google.com'}:{c.name}"
        existing_cookie_map[key] = {
            "name": c.name,
            "value": c.value,
            "domain": c.domain or ".google.com",
            "path": c.path or "/",
            "secure": bool(c.secure),
            "httpOnly": False,
            "expiry": int(c.expires) if c.expires else int(time.time()) + 86400 * 30
        }

    merged_cookies = list(existing_cookie_map.values())
    old_data["cookies"] = merged_cookies
    old_data["cookies_count"] = len(merged_cookies)
    old_data["timestamp"] = time.time()
    old_data["source"] = f"requests_refresh_{target}"

    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(old_data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Error writing session file: {e}")

    return old_data


# ─────────────────────────────────────────────────────────
#  PART 2 — CDP Headless Extraction (Fallback for Expired)
# ─────────────────────────────────────────────────────────

def launch_chrome_cdp(target_url: str):
    """Headless Chromium/Chrome চালু করো।"""
    chrome_bin = find_chrome_binary()
    print(f"[*] Starting Chrome via CDP for {target_url}...")

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
        target_url
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc


def wait_for_cdp(timeout=20):
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
    async with websockets.connect(ws_url) as ws:
        msg = json.dumps({"id": 1, "method": "Network.getAllCookies", "params": {}})
        await ws.send(msg)
        resp = await ws.recv()
        data = json.loads(resp)
        return data.get("result", {}).get("cookies", [])


async def _cdp_inject_and_load(ws_url, seed_cookies, target_url):
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
        await ws.recv()
        await ws.send(json.dumps({"id": 2, "method": "Page.enable"}))
        await ws.recv()

        if seed_cookies:
            clean_cookies = []
            for c in seed_cookies:
                clean_cookies.append({
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c.get("domain", ".google.com"),
                    "path": c.get("path", "/")
                })
            await ws.send(json.dumps({"id": 3, "method": "Network.setCookies", "params": {"cookies": clean_cookies}}))
            await ws.recv()

        await ws.send(json.dumps({"id": 4, "method": "Page.navigate", "params": {"url": target_url}}))
        await ws.recv()


def extract_cookies_via_cdp(target_url: str):
    tabs = wait_for_cdp()
    page_tab = next((t for t in tabs if t.get("type") == "page"), tabs[0])
    ws_url = page_tab["webSocketDebuggerUrl"]

    seed_data = load_session_file() or {}
    seed_cookies = seed_data.get("cookies", [])

    asyncio.run(_cdp_inject_and_load(ws_url, seed_cookies, target_url))
    time.sleep(10)

    try:
        r = requests.get(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=3)
        if r.status_code == 200:
            browser_ws = r.json().get("webSocketDebuggerUrl")
            if browser_ws:
                cookies = asyncio.run(_cdp_get_cookies(browser_ws))
                if len(cookies) > 5:
                    return cookies
    except Exception:
        pass

    return asyncio.run(_cdp_get_cookies(ws_url))


def get_active_session_for_target(target: str):
    """ভ্যালিড requests.Session রিটার্ন করে নির্দিষ্ট সার্ভিসের জন্য।"""
    target_url = GEMINI_URL if target == "gemini" else YOUTUBE_URL
    data = load_session_file()

    if data and data.get("cookies"):
        s = build_requests_session(data["cookies"])
        if is_service_valid(s, target):
            print(f"[+] {target} session is valid! Refreshing via requests...")
            updated_data = refresh_service_cookies(s, target, data)
            return s, "requests_existing", updated_data

    # Expired or missing -> Launch Headless CDP
    print(f"[!] {target} session expired/missing. Launching Chromium CDP...")
    proc = launch_chrome_cdp(target_url)
    try:
        time.sleep(6)
        cookies = extract_cookies_via_cdp(target_url)
        payload = {
            "target": target,
            "cookies_count": len(cookies),
            "cookies": cookies,
            "timestamp": time.time(),
            "source": f"cdp_headless_{target}"
        }
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
        s = build_requests_session(cookies)
        return s, "cdp_refreshed", payload
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


def filter_cookies_for_service(cookies: list, service: str):
    """নির্দিষ্ট সার্ভিসের জন্য দরকারি cookies ফিল্টার করো।"""
    result = []
    for c in cookies:
        d = c.get("domain", "").lower()
        if service == "gemini":
            # Gemini needs google.com, gemini.google.com, accounts.google.com
            if "google.com" in d and "youtube" not in d:
                result.append(c)
        elif service == "youtube":
            # YouTube needs youtube.com and google.com auth tokens
            if "youtube.com" in d or "google.com" in d:
                result.append(c)
    return result


# ─────────────────────────────────────────────────────────
#  PART 3 — Unified Query Endpoint: /get?cookies=...
# ─────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "service": "Google Services Cookie API",
        "endpoints": {
            "/get?cookies=gemini": "Get active Gemini cookies (https://gemini.google.com)",
            "/get?cookies=youtube": "Get active YouTube cookies (https://www.youtube.com)"
        }
    })


@app.route("/get", methods=["GET"])
def api_get():
    service = request.args.get("cookies", "").strip().lower()

    if service not in ["gemini", "youtube"]:
        return jsonify({
            "success": False,
            "error": "Invalid service parameter. Use ?cookies=gemini or ?cookies=youtube"
        }), 400

    try:
        session, method, data = get_active_session_for_target(service)
        all_cookies = data.get("cookies", [])
        service_cookies = filter_cookies_for_service(all_cookies, service)

        return jsonify({
            "success": True,
            "service": service,
            "method": method,
            "cookies_count": len(service_cookies),
            "timestamp": data.get("timestamp"),
            "cookies": service_cookies
        })
    except Exception as e:
        return jsonify({"success": False, "service": service, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
