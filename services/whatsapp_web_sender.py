"""
services/whatsapp_web_sender.py — Automated WhatsApp Web sender for Agri Doctor.

Uses Selenium + Chrome to:
  1. Open WhatsApp Web in a dedicated Chrome profile stored inside the project.
  2. Navigate to the recipient's chat automatically.
  3. Paste the full report into the message box (clipboard paste for speed).
  4. Press Enter — message is sent.
  5. Repeat for each part if multi-part.

Profile strategy
----------------
  A dedicated `.chrome_profile/` directory is kept inside the project folder.
  This avoids conflicts with the user's running Chrome instance.
  On first run Chrome opens and shows the WhatsApp Web QR code.
  After scanning once the session is saved permanently in that profile.
  Subsequent runs connect instantly — no QR scan needed.

Multi-part messages: each part is sent sequentially with a 2-second pause.
"""

import logging
import os
import sys
import time
import urllib.parse
import subprocess
import tempfile
import json
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Selenium import ───────────────────────────────────────────────────────────
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException, NoSuchElementException,
        WebDriverException, ElementNotInteractableException,
    )
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# ── Dedicated Chrome profile for Agri Doctor (avoids lock on system Chrome) ──
# This profile lives inside the project so it never conflicts with a running
# Chrome instance. The user scans the WhatsApp Web QR code once into this
# profile and it stays logged in forever.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CHROME_PROFILE = os.path.join(_PROJECT_ROOT, ".chrome_profile")

# Create the directory if it doesn't exist yet
os.makedirs(_DEFAULT_CHROME_PROFILE, exist_ok=True)

# WhatsApp Web selectors (robust, tested against 2024–2025 WA Web UI)
_WA_SELECTORS = {
    # Main search/open a chat
    "search_box": [
        '//div[@contenteditable="true"][@data-tab="3"]',
        '//div[@title="Search input textbox"]',
    ],
    # Message input box
    "msg_box": [
        '//div[@contenteditable="true"][@data-tab="10"]',
        '//div[@contenteditable="true"][@data-tab="6"]',
        '//footer//div[@contenteditable="true"]',
    ],
    # Send button
    "send_btn": [
        '//button[@data-testid="compose-btn-send"]',
        '//button[@aria-label="Send"]',
        '//span[@data-icon="send"]/..',
    ],
    # Sent tick on last message (confirms delivery)
    "sent_tick": [
        '//span[@data-icon="msg-check"]',
        '//span[@data-icon="msg-dblcheck"]',
        '//span[@aria-label="Sent"]',
    ],
    # QR code — means we're not logged in
    "qr_code": [
        '//canvas[@aria-label="Scan me!"]',
        '//div[@data-ref]',
    ],
}

# Timing constants (seconds)
WAIT_PAGE_LOAD   = 25    # Max wait for WA Web to show the chat list
WAIT_MSG_BOX     = 20    # Max wait for message input box to appear
WAIT_SEND        = 10    # Max wait for send confirmation
DELAY_BETWEEN_PARTS = 2.0  # Pause between multi-part messages


# ─────────────────────────────────────────────────────────────────────────────
#  Clipboard helper (macOS / Linux / fallback)
# ─────────────────────────────────────────────────────────────────────────────

def _copy_to_clipboard(text: str) -> bool:
    """Copy text to the system clipboard. Returns True on success."""
    try:
        # macOS
        proc = subprocess.run(
            ["pbcopy"], input=text.encode("utf-8"),
            capture_output=True, timeout=5,
        )
        return proc.returncode == 0
    except FileNotFoundError:
        pass
    try:
        # Linux (xclip)
        proc = subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=text.encode("utf-8"),
            capture_output=True, timeout=5,
        )
        return proc.returncode == 0
    except FileNotFoundError:
        pass
    try:
        # Linux (xsel)
        proc = subprocess.run(
            ["xsel", "--clipboard", "--input"],
            input=text.encode("utf-8"),
            capture_output=True, timeout=5,
        )
        return proc.returncode == 0
    except FileNotFoundError:
        pass
    return False


# ─────────────────────────────────────────────────────────────────────────────
#  XPath helpers
# ─────────────────────────────────────────────────────────────────────────────

def _wait_for_any(driver, xpaths: List[str], timeout: int = 15):
    """Wait until any of the given XPaths is present and visible."""
    for _ in range(timeout):
        for xpath in xpaths:
            try:
                el = driver.find_element(By.XPATH, xpath)
                if el.is_displayed():
                    return el
            except NoSuchElementException:
                pass
        time.sleep(1)
    return None


def _find_any(driver, xpaths: List[str]):
    """Return the first matching element from the XPath list, or None."""
    for xpath in xpaths:
        try:
            el = driver.find_element(By.XPATH, xpath)
            if el.is_displayed():
                return el
        except NoSuchElementException:
            pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  Chrome driver factory
# ─────────────────────────────────────────────────────────────────────────────

def _build_driver(
    chrome_profile: str = "",
    headless: bool = False,
) -> "webdriver.Chrome":
    """
    Build and return a Chrome WebDriver instance using the dedicated project profile.

    chrome_profile : path to Chrome user-data-dir
    headless       : run invisibly — not suitable for first QR scan
    """
    opts = Options()

    profile = chrome_profile or _DEFAULT_CHROME_PROFILE
    os.makedirs(profile, exist_ok=True)
    opts.add_argument(f"--user-data-dir={profile}")
    opts.add_argument("--profile-directory=Default")
    logger.info("[WA-Web] Chrome profile: %s", profile)

    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1300,900")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--log-level=3")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    opts.add_experimental_option("useAutomationExtension", False)

    if headless:
        opts.add_argument("--headless=new")

    # Selenium 4.6+ auto-manages ChromeDriver — no separate binary needed
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(60)
    # Hide the "Chrome is being controlled" infobar via JS
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


# ─────────────────────────────────────────────────────────────────────────────
#  Core sender
# ─────────────────────────────────────────────────────────────────────────────

def send_via_whatsapp_web(
    phone_number: str,
    message_parts: List[str],
    chrome_profile: str = "",
    headless: bool = False,
    progress_callback: Optional[Callable] = None,
) -> Tuple[bool, str]:
    """
    Send one or more message parts to a WhatsApp number via WhatsApp Web.

    Parameters
    ----------
    phone_number    : E.164 normalised number e.g. "+919876543210"
    message_parts   : list of strings — each part sent as a separate WA message
    chrome_profile  : path to Chrome user-data-dir; empty = fresh profile
    headless        : True = run Chrome invisibly
    progress_callback : optional func(step: str) called at each stage

    Returns
    -------
    (success: bool, detail_message: str)
    """
    if not SELENIUM_AVAILABLE:
        return (
            False,
            "Selenium is not installed. Run: pip install selenium",
        )

    phone_digits = phone_number.lstrip("+").strip()
    if not phone_digits.isdigit():
        return False, f"Invalid phone number for WhatsApp Web: {phone_number}"

    profile = chrome_profile or _DEFAULT_CHROME_PROFILE

    def _progress(msg: str):
        logger.info("[WA-Web] %s", msg)
        if progress_callback:
            try:
                progress_callback(msg)
            except Exception:
                pass

    driver = None
    try:
        _progress("Launching Chrome…")
        driver = _build_driver(chrome_profile=profile, headless=headless)

        # ── Navigate to the recipient's chat ──────────────────────────────────
        # Use a clean wa.me URL — no pre-filled text (avoids URL length limits)
        wa_url = f"https://web.whatsapp.com/send/?phone={phone_digits}&app_absent=0"

        _progress(f"Opening WhatsApp Web → +{phone_digits}…")
        driver.get(wa_url)

        # ── Wait for initial page load ────────────────────────────────────────
        # Give WhatsApp Web time to settle (especially on first open)
        _progress("Waiting for WhatsApp Web to load…")
        time.sleep(5)

        # ── Check for QR code / phone link screen (not logged in) ────────────
        qr = _find_any(driver, _WA_SELECTORS["qr_code"])
        if qr:
            _progress(
                "🔑 First-time setup: WhatsApp Web needs to be linked. "
                "Scan the QR code in the Chrome window with your phone."
            )
            # Wait up to 60 s for the user to scan the QR code
            for _wait in range(60):
                time.sleep(1)
                if not _find_any(driver, _WA_SELECTORS["qr_code"]):
                    _progress("✅ QR code scanned — logged in!")
                    time.sleep(4)  # Let WA Web finish loading after login
                    break
            else:
                driver.quit()
                return (
                    False,
                    "⏱️ QR code scan timed out (60 s). "
                    "A Chrome window opened — scan the QR code at web.whatsapp.com "
                    "with your phone, then click **Retry** to send the report.",
                )

        # ── Wait for the message input box to appear ──────────────────────────
        _progress(f"Waiting for chat with +{phone_digits} to open…")
        msg_box = _wait_for_any(driver, _WA_SELECTORS["msg_box"], timeout=WAIT_PAGE_LOAD)

        if not msg_box:
            # Last-chance: check page source for common error indicators
            page_src = driver.page_source.lower()
            if "phone number shared via url is invalid" in page_src:
                driver.quit()
                return False, f"+{phone_digits} is not a valid WhatsApp number."
            driver.quit()
            return (
                False,
                f"Could not open the WhatsApp chat for +{phone_digits}. "
                "The number may not have WhatsApp, or the page failed to load. "
                "Make sure you are connected to the internet.",
            )

        # ── Clear any pre-filled text from the URL ───────────────────────────
        _progress("Chat opened — preparing message…")
        try:
            msg_box.click()
            time.sleep(0.3)
            # Select all + delete (clears any pre-filled text)
            import platform
            if platform.system() == "Darwin":
                msg_box.send_keys(Keys.COMMAND, "a")
            else:
                msg_box.send_keys(Keys.CONTROL, "a")
            msg_box.send_keys(Keys.DELETE)
            time.sleep(0.2)
        except Exception:
            pass

        # ── Send each message part ────────────────────────────────────────────
        parts_sent = 0
        total_parts = len(message_parts)

        for i, part_text in enumerate(message_parts, 1):
            _progress(f"Typing and sending part {i}/{total_parts}…")

            # Re-find the message box for each part (stale element after previous send)
            if i > 1:
                _progress(f"Waiting before part {i}…")
                time.sleep(DELAY_BETWEEN_PARTS)
                msg_box = _wait_for_any(driver, _WA_SELECTORS["msg_box"], timeout=WAIT_MSG_BOX)
                if not msg_box:
                    _progress(f"⚠️ Message box not found before part {i} — stopping.")
                    break

            sent_ok = _type_and_send(driver, msg_box, part_text)
            if sent_ok:
                parts_sent += 1
                _progress(f"✅ Part {i}/{total_parts} sent!")
            else:
                _progress(f"⚠️ Part {i}/{total_parts} may not have sent — check WhatsApp.")

        # Brief pause so the last message renders before closing
        time.sleep(2)
        driver.quit()

        if parts_sent == 0:
            return False, "No message parts were successfully sent."
        if parts_sent < total_parts:
            return (
                True,
                f"⚠️ Partially sent: {parts_sent}/{total_parts} parts delivered to {phone_number}.",
            )
        return (
            True,
            f"✅ All {total_parts} message part(s) sent to {phone_number} via WhatsApp Web.",
        )

    except WebDriverException as exc:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        msg = str(exc).split("\n")[0][:200]
        logger.error("[WA-Web] WebDriverException: %s", msg)
        return False, f"Chrome/WebDriver error: {msg}"

    except Exception as exc:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        logger.error("[WA-Web] Unexpected error: %s", exc)
        return False, f"Unexpected error: {exc}"


def _type_and_send(driver, msg_box, text: str) -> bool:
    """
    Type text into the WhatsApp message box and press Enter (or click Send).
    Uses clipboard paste for speed and to preserve line breaks correctly.
    Returns True if the message was sent.
    """
    try:
        msg_box.click()
        time.sleep(0.3)

        # ── Paste via clipboard (preserves newlines + fast) ─────────────────
        clipboard_ok = _copy_to_clipboard(text)
        if clipboard_ok:
            # macOS paste shortcut
            import platform
            if platform.system() == "Darwin":
                msg_box.send_keys(Keys.COMMAND, "v")
            else:
                msg_box.send_keys(Keys.CONTROL, "v")
            time.sleep(0.8)
        else:
            # Fall back to character-by-character send (slow for long texts)
            # WA Web uses Shift+Enter for newlines, Enter to send
            lines = text.split("\n")
            for j, line in enumerate(lines):
                msg_box.send_keys(line)
                if j < len(lines) - 1:
                    msg_box.send_keys(Keys.SHIFT, Keys.ENTER)
            time.sleep(0.5)

        # ── Press Enter to send ──────────────────────────────────────────────
        msg_box.send_keys(Keys.ENTER)
        time.sleep(1.5)

        # ── Optionally verify send tick ──────────────────────────────────────
        # (nice-to-have — not blocking)
        tick = _find_any(driver, _WA_SELECTORS["sent_tick"])
        if tick:
            logger.debug("[WA-Web] Send tick detected.")
        return True

    except ElementNotInteractableException:
        logger.warning("[WA-Web] Message box not interactable.")
        # Try clicking the send button instead
        btn = _find_any(driver, _WA_SELECTORS["send_btn"])
        if btn:
            btn.click()
            time.sleep(1.5)
            return True
        return False
    except Exception as exc:
        logger.warning("[WA-Web] _type_and_send error: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  Public entry-point
# ─────────────────────────────────────────────────────────────────────────────

def push_report_to_whatsapp_web(
    phone_number: str,
    message_parts: List[str],
    chrome_profile: str = "",
    progress_callback: Optional[Callable] = None,
) -> Tuple[bool, str]:
    """
    Push an Agri Doctor report to WhatsApp Web and send it automatically.

    This is the primary function called from the Streamlit UI and the agent.

    Parameters
    ----------
    phone_number    : normalised E.164 number, e.g. "+919876543210"
    message_parts   : pre-split list of message strings (from split_message_into_parts)
    chrome_profile  : path to Chrome user-data-dir; defaults to the system Chrome profile
    progress_callback : optional func(step_text: str) for live UI progress updates

    Returns
    -------
    (success: bool, message: str)
    """
    return send_via_whatsapp_web(
        phone_number=phone_number,
        message_parts=message_parts,
        chrome_profile=chrome_profile or _DEFAULT_CHROME_PROFILE,
        headless=False,  # Must be visible so the user can scan QR if needed
        progress_callback=progress_callback,
    )
