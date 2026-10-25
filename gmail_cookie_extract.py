"""
Gmail Smart Session Manager
============================
- যদি gmail_session_data.json এ valid cookies থাকে:
    শুধু `requests` দিয়ে কাজ করে — কোনো browser খোলে না।
- যদি cookies না থাকে বা expired:
    Chrome কে subprocess দিয়ে CDP mode-এ চালু করে
    raw WebSocket দিয়ে cookies নেয় — Selenium/Playwright নেই।
"""

import subprocess
import requests
import asyncio
import websockets
import json
import os
import time

# ========================= CONFIG =========================
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
PROFILE_PATH = os.path.join(BASE_DIR, "chrome_gmail_profile")
SESSION_FILE = os.path.join(BASE_DIR, "gmail_session_data.json")
CHROME_EXE   = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
CDP_PORT     = 9222
GMAIL_URL    = "https://mail.google.com/"
GMAIL_FEED   = "https://mail.google.com/mail/feed/atom"
UA           = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
# ==========================================================


# ─────────────────────────────────────────────────────────
#  PART 1 — Requests Only (No Browser)
# ─────────────────────────────────────────────────────────

def load_session_file():
    """gmail_session_data.json থেকে cookies লোড করো।"""
    if not os.path.exists(SESSION_FILE):
        return None
    with open(SESSION_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_requests_session(cookies: list) -> requests.Session:
    """Cookie list থেকে একটি ready requests.Session তৈরি করো।"""
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
    """cookies দিয়ে Gmail feed request পাঠিয়ে সেশন live আছে কিনা চেক করো।"""
    try:
        r = s.get(GMAIL_FEED, timeout=8, allow_redirects=False)
        print(f"  [*] Auth check → HTTP {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        print(f"  [!] Auth check failed: {e}")
        return False


def refresh_cookies_via_request(s: requests.Session, old_data: dict) -> dict:
    """
    Gmail/Google-এ authenticated request পাঠাও।
    Google নিজেই Set-Cookie দিয়ে SIDTS রোটেট করে দেবে।
    নতুন cookies merge করে JSON-এ save করো।
    """
    print("[*] Google-এর কাছ থেকে fresh cookies নেওয়া হচ্ছে (request-only)...")

    endpoints = [
        "https://accounts.google.com/ListAccounts?gpsia=1&source=ChromiumBrowser",
        "https://mail.google.com/mail/u/0/",
        GMAIL_FEED,
    ]

    for url in endpoints:
        try:
            r = s.get(url, timeout=8, allow_redirects=True)
            new_cookies = r.cookies
            if new_cookies:
                print(f"  [+] {url[:55]} → {len(new_cookies)} নতুন Set-Cookie পেয়েছি")
        except Exception:
            pass

    # requests.Session এ নতুন cookies auto-merge হয়ে যায়
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

    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(old_data, f, indent=4, ensure_ascii=False)

    print(f"  [+] {len(updated_cookies)} cookies save হয়েছে (কোনো browser ছাড়াই!)")
    return old_data


# ─────────────────────────────────────────────────────────
#  PART 2 — Chrome CDP (No Selenium/Playwright)
# ─────────────────────────────────────────────────────────

def kill_existing_chrome_on_profile():
    """Profile-এ চলমান Chrome process বন্ধ করো।"""
    result = subprocess.run(
        ["powershell", "-Command",
         "Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\" | "
         "Where-Object { $_.CommandLine -like '*chrome_gmail_profile*' } | "
         "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
        capture_output=True, text=True
    )
    time.sleep(2)
    print("[*] আগের Chrome session বন্ধ করা হয়েছে।")


def launch_chrome_cdp() -> subprocess.Popen:
    """Chrome কে CDP debug mode-এ চালু করো।"""
    print(f"[*] Chrome চালু হচ্ছে (CDP port {CDP_PORT}) — Selenium/Playwright নেই!")
    proc = subprocess.Popen([
        CHROME_EXE,
        f"--user-data-dir={PROFILE_PATH}",
        f"--remote-debugging-port={CDP_PORT}",
        "--no-first-run",
        "--no-default-browser-check",
        GMAIL_URL
    ])
    print(f"    Chrome PID: {proc.pid}")
    return proc


def wait_for_cdp(timeout=20) -> list:
    """CDP ready হওয়া পর্যন্ত অপেক্ষা করো।"""
    print("[*] Chrome CDP ready হওয়ার জন্য অপেক্ষা করছি...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"http://localhost:{CDP_PORT}/json", timeout=2)
            if r.status_code == 200:
                tabs = r.json()
                print(f"[+] CDP ready! {len(tabs)} tab পাওয়া গেছে।")
                return tabs
        except Exception:
            pass
        time.sleep(0.8)
    raise TimeoutError("Chrome CDP চালু হয়নি।")


async def _cdp_get_cookies(ws_url: str) -> list:
    """CDP WebSocket দিয়ে সব cookies নাও।"""
    async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
        # Gmail লোড হওয়ার জন্য কিছুটা অপেক্ষা
        await asyncio.sleep(3)

        # Network domain enable
        await ws.send(json.dumps({"id": 1, "method": "Network.enable", "params": {}}))
        await ws.recv()

        # সব domain-এর cookies নাও (accounts.google.com + mail.google.com + .google.com)
        await ws.send(json.dumps({"id": 2, "method": "Network.getAllCookies", "params": {}}))
        resp = json.loads(await ws.recv())
        cookies = resp.get("result", {}).get("cookies", [])
        return cookies


def extract_cookies_via_cdp() -> list:
    """CDP WebSocket থেকে cookies বের করো।"""
    tabs = wait_for_cdp()

    # Gmail page tab খোঁজো
    target = next(
        (t for t in tabs if t.get("type") == "page" and "google" in t.get("url", "")),
        next((t for t in tabs if t.get("type") == "page"), None)
    )

    if not target:
        raise RuntimeError("Gmail page tab পাওয়া যায়নি।")

    ws_url = target.get("webSocketDebuggerUrl")
    print(f"[*] Tab: {target.get('url', '')[:60]}")
    print(f"[*] WebSocket CDP-এ connect হচ্ছে...")

    cookies = asyncio.run(_cdp_get_cookies(ws_url))
    print(f"[+] CDP থেকে {len(cookies)} cookies পাওয়া গেছে!")
    return cookies


def save_cookies_from_cdp(cookies: list, current_url: str):
    """CDP থেকে পাওয়া cookies JSON-এ save করো।"""
    payload = {
        "profile_path": PROFILE_PATH,
        "current_url": current_url,
        "cookies_count": len(cookies),
        "cookies": cookies,
        "local_storage": {},
        "session_storage": {},
        "timestamp": time.time(),
        "source": "cdp_no_selenium_no_playwright"
    }
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)
    print(f"[+] {len(cookies)} cookies → {SESSION_FILE}")


# ─────────────────────────────────────────────────────────
#  MAIN ENTRY
# ─────────────────────────────────────────────────────────

def get_valid_gmail_session() -> requests.Session:
    """
    যেকোনো পরিস্থিতিতে valid Gmail session return করে।
    ── Cookies valid থাকলে: শুধু requests, browser নেই
    ── Expired হলে: Chrome (CDP) দিয়ে refresh, Selenium নেই
    """

    print("=" * 58)
    print("  Gmail Smart Session — No Selenium / No Playwright")
    print("=" * 58)

    # ── Step 1: Existing JSON চেক ──────────────────────────
    data = load_session_file()
    if data:
        print(f"\n[1] JSON-এ {data.get('cookies_count', 0)} cookies পেলাম।")
        s = build_requests_session(data["cookies"])

        print("[2] সেশন valid কিনা চেক হচ্ছে (no browser)...")
        if is_session_valid(s):
            print("[+] ✅ সেশন LIVE আছে — browser লাগবে না!")
            print("[*] Google-এর কাছ থেকে fresh cookies রিফ্রেশ করা হচ্ছে...")
            refresh_cookies_via_request(s, data)
            return s

    # ── Step 2: Expired — Chrome CDP দিয়ে refresh ──────────
    print("\n[!] সেশন নেই বা expired। Chrome CDP দিয়ে নতুন cookies নেওয়া হচ্ছে...")
    kill_existing_chrome_on_profile()
    proc = launch_chrome_cdp()

    try:
        time.sleep(6)  # Gmail লোড হওয়ার সময়
        cookies = extract_cookies_via_cdp()
        current_url = GMAIL_URL
        save_cookies_from_cdp(cookies, current_url)

        # নতুন session তৈরি করো
        s = build_requests_session(cookies)
        if is_session_valid(s):
            print("\n[+] ✅ সফল! CDP দিয়ে cookies নেওয়া হয়েছে (Selenium/Playwright নেই)!")
        return s
    finally:
        time.sleep(2)
        proc.terminate()
        print("[*] Chrome বন্ধ করা হয়েছে।")


if __name__ == "__main__":
    session = get_valid_gmail_session()

    print("\n[*] Test: Gmail Feed request...")
    r = session.get(GMAIL_FEED)
    print(f"    Status: {r.status_code}")
    if r.status_code == 200:
        print("    [+] ✅ Gmail access confirmed! Pure Python requests কাজ করছে।")
