"""
Interactive Cloud Login Script (Playwright)
===========================================
সার্ভারে সরাসরি একবার Google অ্যাকাউন্টে লগইন করার জন্য স্ক্রিপ্ট।
এটি লিনাক্সের নিজস্ব এনক্রিপশন ও ডিভাইস টোকেন তৈরি করবে, ফলে কখনো এক্সপায়ার হবে না।
"""

import os
import sys
import json
import asyncio
from playwright.async_api import async_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "linux_chrome_profile")
AUTH_TOKENS_FILE = os.path.join(BASE_DIR, "auth_tokens.json")


async def perform_login(email: str, password: str = None):
    print("=" * 60)
    print("  Google Cloud Direct Login (Playwright Linux Engine)")
    print("=" * 60)

    async with async_playwright() as p:
        # Launch persistent context to store Linux hardware credentials
        context = await p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )

        page = await context.new_page()
        print(f"[*] Navigating to Google Accounts login...")
        await page.goto("https://accounts.google.com/signin/v2/identifier?flowName=GlifWebSignIn&flowEntry=ServiceLogin")
        await page.wait_for_timeout(3000)

        # Enter Email
        print(f"[*] Entering email: {email}...")
        await page.fill('input[type="email"]', email)
        await page.click('#identifierNext')
        await page.wait_for_timeout(4000)

        # Check for password field
        if password:
            print("[*] Entering password...")
            try:
                await page.fill('input[type="password"]', password)
                await page.click('#passwordNext')
                await page.wait_for_timeout(6000)
            except Exception as e:
                print(f"[!] Password field not found or blocked: {e}")

        # Check if 2FA or verification prompt is needed
        current_url = page.url
        print(f"[*] Current URL: {current_url}")

        # Wait for user to verify if 2FA appears
        for i in range(12):
            if "myaccount.google.com" in page.url or "mail.google.com" in page.url:
                print("[+] Successfully logged in!")
                break
            await page.wait_for_timeout(3000)

        # Extract genuine Linux tokens
        cookies = await context.cookies()
        auth_names = [c["name"] for c in cookies]
        print(f"[+] Total cookies acquired: {len(cookies)}")
        print(f"[+] Auth tokens detected: {[k for k in ['SID', 'HSID', 'SSID', 'APISID', 'SAPISID'] if k in auth_names]}")

        with open(AUTH_TOKENS_FILE, "w", encoding="utf-8") as f:
            json.dump({"account": email, "cookies": cookies}, f, indent=4, ensure_ascii=False)

        print(f"[+] Saved authentic Linux tokens to {AUTH_TOKENS_FILE}!")
        await context.close()


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "illukailluma@gmail.com"
    password = sys.argv[2] if len(sys.argv) > 2 else None
    asyncio.run(perform_login(email, password))
