"""
Cloud Auto-Login Engine (Playwright Linux)
=========================================
সার্ভারে স্বয়ংক্রিয়ভাবে Google অ্যাকাউন্টে লগইন করে পার্মানেন্ট লিনাক্স সেশন ও কুকিজ তৈরি করে।
"""

import os
import sys
import json
import asyncio
from playwright.async_api import async_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "linux_chrome_profile")
SESSION_FILE = os.path.join(BASE_DIR, "session_data.json")

DEFAULT_EMAIL = "illukailluma@gmail.com"
DEFAULT_PASSWORD = os.environ.get("GOOGLE_PASSWORD", "marasudo15")


async def perform_login(email: str = DEFAULT_EMAIL, password: str = DEFAULT_PASSWORD):
    print("=" * 60)
    print(f"[*] Starting Direct Cloud Authentication for {email}...")
    print("=" * 60)

    async with async_playwright() as p:
        # Determine executable path (system chromium)
        chrome_bin = os.environ.get("CHROME_PATH") or "/usr/bin/chromium"
        if not os.path.exists(chrome_bin):
            import shutil
            chrome_bin = shutil.which("chromium") or shutil.which("google-chrome")

        launch_kwargs = {
            "user_data_dir": PROFILE_DIR,
            "headless": True,
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ],
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        }
        if chrome_bin and os.path.exists(chrome_bin):
            launch_kwargs["executable_path"] = chrome_bin

        context = await p.chromium.launch_persistent_context(**launch_kwargs)
        page = await context.new_page()

        # Step 1: Navigate to Google Login
        print("[*] Loading Google Accounts...")
        await page.goto("https://accounts.google.com/signin/v2/identifier?flowName=GlifWebSignIn&flowEntry=ServiceLogin", wait_until="networkidle")
        await page.wait_for_timeout(2000)

        # Step 2: Fill Email
        print(f"[*] Submitting email: {email}...")
        try:
            await page.fill('input[type="email"]', email)
            await page.click('#identifierNext')
            await page.wait_for_timeout(4000)
        except Exception as e:
            print(f"[!] Email submission error: {e}")

        # Step 3: Fill Password
        print("[*] Submitting password...")
        try:
            await page.fill('input[type="password"]', password)
            await page.click('#passwordNext')
            await page.wait_for_timeout(6000)
        except Exception as e:
            print(f"[!] Password submission error: {e}")

        # Step 4: Handle 2FA or Wait for Login completion
        print(f"[*] Post-login URL: {page.url}")
        for sec in range(15):
            curr = page.url.lower()
            if "myaccount.google.com" in curr or "mail.google.com" in curr or "gemini.google.com" in curr:
                print(f"[+] Confirmed login at: {curr}")
                break
            await page.wait_for_timeout(2000)

        # Step 5: Navigate to Gemini & YouTube to populate cookies
        print("[*] Loading Gemini to register session...")
        try:
            await page.goto("https://gemini.google.com/app", wait_until="networkidle", timeout=15000)
            await page.wait_for_timeout(3000)
        except Exception:
            pass

        # Step 6: Extract all genuine Linux cookies
        cookies = await context.cookies()
        auth_names = [c["name"] for c in cookies]
        print(f"[+] Acquired {len(cookies)} cookies!")
        print(f"[+] Key auth tokens: {[k for k in ['SID', 'HSID', 'SSID', 'APISID', 'SAPISID', 'COMPASS'] if k in auth_names]}")

        payload = {
            "account": email,
            "cookies_count": len(cookies),
            "cookies": cookies,
            "source": "playwright_linux_direct_login"
        }

        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)

        print(f"[+] Session saved to {SESSION_FILE}!")
        await context.close()
        return payload


if __name__ == "__main__":
    em = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EMAIL
    pw = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PASSWORD
    asyncio.run(perform_login(em, pw))
