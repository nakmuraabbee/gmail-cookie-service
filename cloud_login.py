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
            # Wait for email input
            email_input = await page.wait_for_selector('input[type="email"], #identifierId', timeout=10000)
            await email_input.click()
            await email_input.fill("")
            await page.keyboard.type(email, delay=50)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(4000)
        except Exception as e:
            print(f"[!] Email submission error: {e}")

        # Step 3: Fill Password
        print("[*] Submitting password...")
        try:
            pw_input = await page.wait_for_selector('input[type="password"], input[name="Passwd"]', timeout=8000)
            await pw_input.click()
            await page.keyboard.type(password, delay=50)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(6000)
        except Exception as e:
            print(f"[!] Password submission error: {e}")

        # Step 4: Check what Google screen is displaying
        print(f"[*] Post-login URL: {page.url}")
        logged_in = False
        for sec in range(15):
            curr = page.url.lower()
            if "myaccount.google.com" in curr or "mail.google.com" in curr or "gemini.google.com" in curr:
                print(f"[+] Confirmed login at: {curr}")
                logged_in = True
                break
            await page.wait_for_timeout(2000)

        # Take screenshot for diagnosis if not logged in
        screenshot_base64 = None
        if not logged_in:
            try:
                import base64
                img_bytes = await page.screenshot(full_page=True)
                screenshot_base64 = base64.b64encode(img_bytes).decode("utf-8")
                print(f"[!] Login pending or challenge displayed! Captured screenshot ({len(img_bytes)} bytes)")
            except Exception as e:
                print(f"[!] Screenshot error: {e}")

        # Step 5: Navigate to Gemini & YouTube to populate cookies
        if logged_in:
            try:
                await page.goto("https://gemini.google.com/app", wait_until="networkidle", timeout=15000)
                await page.wait_for_timeout(3000)
            except Exception:
                pass

        # Step 6: Extract all genuine Linux cookies
        cookies = await context.cookies()
        auth_names = [c["name"] for c in cookies]
        has_auth = any(k in auth_names for k in ["SID", "HSID", "SSID", "APISID", "SAPISID"])

        payload = {
            "account": email,
            "logged_in": logged_in,
            "has_auth_tokens": has_auth,
            "cookies_count": len(cookies),
            "cookies": cookies,
            "current_url": page.url,
            "screenshot_base64": screenshot_base64,
            "source": "playwright_linux_direct_login"
        }

        if logged_in or has_auth:
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=4, ensure_ascii=False)
            print(f"[+] Session saved to {SESSION_FILE}!")

        await context.close()
        return payload


if __name__ == "__main__":
    em = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EMAIL
    pw = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PASSWORD
    asyncio.run(perform_login(em, pw))
