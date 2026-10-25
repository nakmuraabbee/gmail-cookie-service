"""
Remote Interactive Browser Controller (Web-RDP Style)
=====================================================
User can click, type, press Enter/keys, navigate, and solve Google Captcha/2FA manually.
"""

import os
import sys
import json
import base64
import asyncio
from playwright.async_api import async_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "linux_chrome_profile")
SESSION_FILE = os.path.join(BASE_DIR, "session_data.json")

# Global session holder
_playwright_instance = None
_browser_context = None
_active_page = None
_lock = asyncio.Lock()


async def get_or_create_page():
    global _playwright_instance, _browser_context, _active_page

    async with _lock:
        if _active_page and not _active_page.is_closed():
            return _active_page

        if not _playwright_instance:
            _playwright_instance = await async_playwright().start()

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
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "viewport": {"width": 1280, "height": 800}
        }
        if chrome_bin and os.path.exists(chrome_bin):
            launch_kwargs["executable_path"] = chrome_bin

        _browser_context = await _playwright_instance.chromium.launch_persistent_context(**launch_kwargs)
        _active_page = await _browser_context.new_page()

        # Start on Google Accounts
        try:
            await _active_page.goto("https://accounts.google.com/signin/v2/identifier?flowName=GlifWebSignIn&flowEntry=ServiceLogin", wait_until="networkidle", timeout=15000)
        except Exception:
            pass

        return _active_page


async def handle_remote_action(action: str, params: dict):
    """
    Actions:
    - screenshot: returns base64 image and url
    - click: params: x, y
    - type: params: text
    - key: params: key (Enter, Backspace, Tab, etc.)
    - navigate: params: url
    - save: saves cookies to session_data.json
    """
    page = await get_or_create_page()

    if action == "click":
        x = float(params.get("x", 0))
        y = float(params.get("y", 0))
        await page.mouse.click(x, y)
        await page.wait_for_timeout(1000)

    elif action == "fill":
        text = params.get("text", "")
        # Directly fill whatever input box is active on the screen (Email or Password)
        try:
            if await page.locator('input[type="email"]').is_visible():
                await page.fill('input[type="email"]', text)
            elif await page.locator('input[type="password"]').is_visible():
                await page.fill('input[type="password"]', text)
            elif await page.locator('input:visible').count() > 0:
                await page.fill('input:visible', text)
            else:
                await page.keyboard.type(text, delay=30)
        except Exception as e:
            print(f"[!] Direct fill error: {e}")
            await page.keyboard.type(text, delay=30)
        await page.wait_for_timeout(800)

    elif action == "key":
        key = params.get("key", "Enter")
        await page.keyboard.press(key)
        await page.wait_for_timeout(2000)

    elif action == "navigate":
        url = params.get("url", "https://accounts.google.com")
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)

    elif action == "save":
        # Navigate to Gemini to ensure cookies are populated
        try:
            await page.goto("https://gemini.google.com/app", wait_until="networkidle", timeout=15000)
            await page.wait_for_timeout(2000)
        except Exception:
            pass

        cookies = await _browser_context.cookies()
        payload = {
            "cookies_count": len(cookies),
            "cookies": cookies,
            "source": "remote_rdp_interactive_login"
        }
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
        return {"saved": True, "cookies_count": len(cookies), "url": page.url}

    # Take fresh screenshot after action
    img_bytes = await page.screenshot(full_page=False)
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")

    return {
        "url": page.url,
        "screenshot": img_b64
    }
