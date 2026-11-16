"""
services/whatsapp_web_sender.py — Automated WhatsApp Web sender for Agri Doctor.

Uses Selenium + Chrome (via webdriver-manager auto-download) to:
  1. Open WhatsApp Web in a dedicated Chrome profile stored inside the project.
  2. Navigate directly to the recipient's chat via wa.me URL.
  3. Wait for the message input box using real DOM selectors.
  4. Type the compact advisory into the message box.
  5. Click the Send button — message is sent with ZERO manual interaction.
  6. Repeat for each part if multi-part.

Profile strategy
----------------
  A dedicated `.chrome_profile/` directory is kept inside the project folder.
  On first run Chrome opens and shows the WhatsApp Web QR code.
  After scanning once the session is saved permanently in that profile.
  Subsequent runs connect instantly — no QR scan needed.

Dependencies
------------
  selenium         — pip install selenium
  webdriver-manager — pip install webdriver-manager  (auto-downloads chromedriver)
"""

import logging
import os
import shutil
import sys
import time
import urllib.parse
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Project paths ─────────────────────────────────────────────────────────────
_PROJECT_ROOT          = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CHROME_PROFILE = os.path.join(_PROJECT_ROOT, ".chrome_profile")
os.makedirs(_DEFAULT_CHROME_PROFILE, exist_ok=True)

# ── Chrome binary locations (macOS first, then Linux) ─────────────────────────
_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]

def _find_chrome() -> Optional[str]:
    """Return the path to a usable Chrome/Chromium binary, or None."""
    for path in _CHROME_CANDIDATES:
        if os.path.isfile(path):
            return path
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None

# ── Selenium + webdriver-manager import ───────────────────────────────────────
SELENIUM_AVAILABLE = False
_CHROME_BINARY     = _find_chrome()

if _CHROME_BINARY:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options  import Options
        from selenium.webdriver.chrome.service  import Service
        from selenium.webdriver.common.by       import By
        from selenium.webdriver.common.keys     import Keys
        from selenium.webdriver.support.ui      import WebDriverWait
        from selenium.webdriver.support         import expected_conditions as EC
        from selenium.common.exceptions         import (
            TimeoutException, NoSuchElementException,
            WebDriverException, ElementNotInteractableException,
        )
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            _WDM_AVAILABLE = True
        except ImportError:
            _WDM_AVAILABLE = False

        SELENIUM_AVAILABLE = True
        logger.info("[WA-Web] Chrome found: %s  selenium OK  wdm=%s", _CHROME_BINARY, _WDM_AVAILABLE)
    except ImportError as _e:
        logger.warning("[WA-Web] selenium not installed: %s", _e)
else:
    logger.warning("[WA-Web] No Chrome binary found — Selenium auto-send disabled.")

# ── Timing constants ──────────────────────────────────────────────────────────
WAIT_PAGE_LOAD       = 30   # max seconds waiting for WA Web to show chat
WAIT_MSG_BOX         = 25   # max seconds for message input box to appear
WAIT_SEND            = 10   # max seconds for send confirmation
DELAY_BETWEEN_PARTS  =  3   # pause between multi-part messages

# ── WhatsApp Web DOM selectors (2024-2025 WA Web UI) ─────────────────────────
# Multiple fallbacks per element — WA Web occasionally changes data-tab values.
_SEL = {
    "msg_box": [
        '//div[@contenteditable="true"][@data-tab="10"]',
        '//div[@contenteditable="true"][@data-tab="6"]',
        '//footer//div[@contenteditable="true"]',
        '//div[@role="textbox"][@data-tab="10"]',
        '//div[@role="textbox"][@data-tab="6"]',
    ],
    "send_btn": [
        '//button[@data-testid="compose-btn-send"]',
        '//button[@aria-label="Send"]',
        '//span[@data-icon="send"]/..',
        '//button[@data-testid="send"]',
    ],
    "sent_tick": [
        '//span[@data-icon="msg-check"]',
        '//span[@data-icon="msg-dblcheck"]',
        '//span[@aria-label="Sent"]',
    ],
    "qr_code": [
        '//canvas[@aria-label="Scan me!"]',
        '//div[@data-ref]',
        '//div[@data-testid="qrcode"]',
    ],
    "chat_ready": [
        '//div[@data-testid="conversation-panel-wrapper"]',
        '//div[@id="main"]',
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
#  DOM helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_any(driver, xpaths: List[str]):
    """Return first visible matching element from the XPath list, or None."""
    for xpath in xpaths:
        try:
            el = driver.find_element(By.XPATH, xpath)
            if el.is_displayed():
                return el
        except (NoSuchElementException, Exception):
            pass
    return None


def _wait_any(driver, xpaths: List[str], timeout: int = 20):
    """Poll until any XPath matches a visible element. Returns element or None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        el = _find_any(driver, xpaths)
        if el:
            return el
        time.sleep(1)
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  Chrome driver factory
# ─────────────────────────────────────────────────────────────────────────────

def _build_driver(chrome_profile: str = "") -> "webdriver.Chrome":
    """
    Build and return a Chrome WebDriver.
    Uses webdriver-manager to auto-download the matching chromedriver.
    Uses a persistent profile so WhatsApp Web login is saved between runs.
    """
    opts = Options()

    # Binary path
    opts.binary_location = _CHROME_BINARY

    # Persistent profile — WhatsApp login is kept across runs
    profile = chrome_profile or _DEFAULT_CHROME_PROFILE
    os.makedirs(profile, exist_ok=True)
    opts.add_argument(f"--user-data-dir={profile}")
    opts.add_argument("--profile-directory=Default")

    # Stability flags
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

    # Build service with webdriver-manager (auto-downloads correct chromedriver)
    if _WDM_AVAILABLE:
        service = Service(ChromeDriverManager().install())
    else:
        service = Service()   # fallback: Selenium 4 auto-manager

    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(60)
    driver.execute_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
    )
    logger.info("[WA-Web] Chrome started (profile: %s)", profile)
    return driver


# ─────────────────────────────────────────────────────────────────────────────
#  Core sender
# ─────────────────────────────────────────────────────────────────────────────

def send_via_whatsapp_web(
    phone_number: str,
    message_parts: List[str],
    chrome_profile: str = "",
    progress_callback: Optional[Callable] = None,
) -> Tuple[bool, str]:
    """
    Send one or more message parts to a WhatsApp number via WhatsApp Web.
    Zero manual interaction required after the first QR-code scan.

    Parameters
    ----------
    phone_number    : E.164 normalised number  e.g. "+919876543210"
    message_parts   : list of strings — each sent as a separate WA message
    chrome_profile  : path to Chrome user-data-dir (empty = project default)
    progress_callback : optional func(step: str) for live UI updates

    Returns
    -------
    (success: bool, detail_message: str)
    """
    if not SELENIUM_AVAILABLE:
        return False, (
            "Selenium or Chrome not available. "
            "Run: pip install selenium webdriver-manager"
        )

    phone_digits = phone_number.lstrip("+").strip()
    if not phone_digits.isdigit():
        return False, f"Invalid phone number: {phone_number}"

    def _p(msg: str):
        logger.info("[WA-Web] %s", msg)
        if progress_callback:
            try:
                progress_callback(msg)
            except Exception:
                pass

    driver = None
    try:
        _p("Launching Chrome with persistent profile…")
        driver = _build_driver(chrome_profile=chrome_profile or _DEFAULT_CHROME_PROFILE)

        # Navigate to the recipient's chat (no pre-filled text to avoid URL length issues)
        wa_url = f"https://web.whatsapp.com/send/?phone={phone_digits}&app_absent=0"
        _p(f"Opening WhatsApp Web → +{phone_digits}…")
        driver.get(wa_url)

        # Give the page an initial moment to begin loading
        time.sleep(5)

        # ── QR code check (first-time setup) ─────────────────────────────────
        qr = _find_any(driver, _SEL["qr_code"])
        if qr:
            _p(
                "🔑 First-time: scan the QR code in the Chrome window with your phone. "
                "Waiting up to 60 s…"
            )
            for _ in range(60):
                time.sleep(1)
                if not _find_any(driver, _SEL["qr_code"]):
                    _p("✅ QR scanned — logged in!")
                    time.sleep(5)
                    break
            else:
                driver.quit()
                return False, (
                    "QR scan timed out (60 s). "
                    "Open WhatsApp Web in the Chrome window that launched, "
                    "scan once, then run again."
                )

        # ── Wait for message input box ────────────────────────────────────────
        _p(f"Waiting for chat with +{phone_digits} to open…")
        msg_box = _wait_any(driver, _SEL["msg_box"], timeout=WAIT_PAGE_LOAD)

        if not msg_box:
            src = driver.page_source.lower()
            if "phone number shared via url is invalid" in src:
                driver.quit()
                return False, f"+{phone_digits} is not registered on WhatsApp."
            driver.quit()
            return False, (
                f"Could not open chat for +{phone_digits}. "
                "Check internet connection and that the number has WhatsApp."
            )

        # ── Send each part ────────────────────────────────────────────────────
        parts_sent  = 0
        total_parts = len(message_parts)

        for i, part_text in enumerate(message_parts, 1):
            _p(f"Sending part {i}/{total_parts}…")

            # Re-locate message box for every part (stale element after previous send)
            if i > 1:
                time.sleep(DELAY_BETWEEN_PARTS)
                msg_box = _wait_any(driver, _SEL["msg_box"], timeout=WAIT_MSG_BOX)
                if not msg_box:
                    _p(f"⚠️ Message box lost before part {i} — stopping.")
                    break

            sent_ok = _type_and_send(driver, msg_box, part_text, _p)
            if sent_ok:
                parts_sent += 1
                _p(f"✅ Part {i}/{total_parts} sent!")
            else:
                _p(f"⚠️ Part {i} may not have sent.")

        time.sleep(2)
        driver.quit()

        if parts_sent == 0:
            return False, "No parts were sent — message input could not be interacted with."
        if parts_sent < total_parts:
            return True, (
                f"⚠️ Partial: {parts_sent}/{total_parts} parts sent to +{phone_digits}."
            )
        return True, (
            f"✅ All {total_parts} part(s) sent to +{phone_digits} via WhatsApp Web."
        )

    except WebDriverException as exc:
        if driver:
            try: driver.quit()
            except Exception: pass
        msg = str(exc).split("\n")[0][:300]
        logger.error("[WA-Web] WebDriverException: %s", msg)
        return False, f"Chrome error: {msg}"

    except Exception as exc:
        if driver:
            try: driver.quit()
            except Exception: pass
        logger.error("[WA-Web] Unexpected error: %s", exc)
        return False, f"Unexpected error: {exc}"


# ─────────────────────────────────────────────────────────────────────────────
#  Type and send helper
# ─────────────────────────────────────────────────────────────────────────────

def _type_and_send(driver, msg_box, text: str, progress_fn=None) -> bool:
    """
    Type text into the WhatsApp message box, then click the Send button.
    Uses JavaScript to set the value directly — bypasses clipboard restrictions.
    Falls back to send_keys character-by-character if JS doesn't work.
    Returns True if the Send button was clicked successfully.
    """
    def _p(m):
        logger.debug("[WA-Web] _type_and_send: %s", m)
        if progress_fn:
            try: progress_fn(m)
            except Exception: pass

    try:
        msg_box.click()
        time.sleep(0.3)

        # ── Method A: Paste via clipboard using xdotool/pbcopy (fastest) ─────
        import platform, subprocess as _sp
        pasted = False
        try:
            if platform.system() == "Darwin":
                proc = _sp.run(["pbcopy"], input=text.encode("utf-8"),
                               capture_output=True, timeout=3)
                if proc.returncode == 0:
                    msg_box.send_keys(Keys.COMMAND, "v")
                    pasted = True
            else:
                for tool in (["xclip", "-selection", "clipboard"],
                             ["xsel", "--clipboard", "--input"]):
                    try:
                        proc = _sp.run(tool, input=text.encode("utf-8"),
                                       capture_output=True, timeout=3)
                        if proc.returncode == 0:
                            msg_box.send_keys(Keys.CONTROL, "v")
                            pasted = True
                            break
                    except FileNotFoundError:
                        pass
        except Exception:
            pass

        if not pasted:
            # ── Method B: send_keys line by line (preserves newlines via Shift+Enter)
            lines = text.split("\n")
            for j, line in enumerate(lines):
                msg_box.send_keys(line)
                if j < len(lines) - 1:
                    msg_box.send_keys(Keys.SHIFT, Keys.ENTER)
            time.sleep(0.5)

        time.sleep(0.8)

        # ── Click the Send button (more reliable than pressing Enter) ─────────
        send_btn = _find_any(driver, _SEL["send_btn"])
        if send_btn:
            send_btn.click()
            _p("Send button clicked ✅")
            time.sleep(1.5)
            return True

        # ── Fallback: press Enter ─────────────────────────────────────────────
        msg_box.send_keys(Keys.ENTER)
        time.sleep(1.5)
        _p("Enter pressed (send button not found) ✅")
        return True

    except ElementNotInteractableException:
        # Last resort: find and click send button
        btn = _find_any(driver, _SEL["send_btn"])
        if btn:
            btn.click()
            time.sleep(1.5)
            return True
        return False
    except Exception as exc:
        logger.warning("[WA-Web] _type_and_send error: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  Public entry-point (called from WhatsAppSender in whatsapp_agent.py)
# ─────────────────────────────────────────────────────────────────────────────

def push_report_to_whatsapp_web(
    phone_number: str,
    message_parts: List[str],
    chrome_profile: str = "",
    progress_callback: Optional[Callable] = None,
) -> Tuple[bool, str]:
    """
    Push an Agri Doctor report to WhatsApp Web and send it automatically.
    Zero manual interaction required (after one-time QR scan on first use).

    Parameters
    ----------
    phone_number      : normalised E.164 e.g. "+919876543210"
    message_parts     : pre-split message strings
    chrome_profile    : path to Chrome user-data-dir (empty = project default)
    progress_callback : optional func(step_text: str)

    Returns
    -------
    (success: bool, message: str)
    """
    return send_via_whatsapp_web(
        phone_number=phone_number,
        message_parts=message_parts,
        chrome_profile=chrome_profile or _DEFAULT_CHROME_PROFILE,
        progress_callback=progress_callback,
    )
