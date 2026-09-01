"""
Per-thread browser instances for Playwright.

Playwright's sync API uses greenlets internally which are thread-affine.
Sharing browser instances across threads causes "Cannot switch to a different thread" errors.

SOLUTION: Each thread gets its OWN Playwright + browser instance.
Memory is controlled by limiting max_workers in ThreadPoolExecutor (default: 2).
Peak RAM: ~200MB per thread × max_workers (e.g., 2 workers = 400MB max).

Includes cookie persistence for anti-detection.
"""
import random
import json
import threading
import os
from contextlib import contextmanager
from playwright.sync_api import sync_playwright

BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-blink-features=AutomationControlled",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15",
]

_thread_local = threading.local()

SYSTEM_BROWSER_PATHS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)


def _get_or_create_browser():
    """Create a browser instance for the current thread if one doesn't exist."""
    if not hasattr(_thread_local, 'browser'):
        p = sync_playwright().start()
        launch_options = {"headless": True, "args": BROWSER_ARGS}
        if not os.path.isfile(p.chromium.executable_path):
            installed_browser = next(
                (path for path in SYSTEM_BROWSER_PATHS if os.path.isfile(path)),
                None,
            )
            if not installed_browser:
                p.stop()
                raise RuntimeError(
                    "No Chromium browser found. Run 'playwright install chromium' "
                    "or install Chrome/Edge."
                )
            launch_options["executable_path"] = installed_browser
        browser = p.chromium.launch(**launch_options)
        _thread_local.playwright = p
        _thread_local.browser = browser
    return _thread_local.browser


@contextmanager
def get_browser():
    """Get the current thread's browser. Creates one if needed."""
    yield _get_or_create_browser()


def new_context(extra_headers=None, ignore_https_errors=False,
                device_scale_factor=1):
    """Create a new isolated browser context (tab) in the current thread.

    Each call creates a fresh context with a random User-Agent.
    Contexts are lightweight (~5MB) unlike browsers (~200MB).
    """
    browser = _get_or_create_browser()
    headers = {
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Upgrade-Insecure-Requests": "1",
    }
    if extra_headers:
        headers.update(extra_headers)

    context = browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport={"width": 1920, "height": 1080},
        extra_http_headers=headers,
        ignore_https_errors=ignore_https_errors,
        device_scale_factor=device_scale_factor,
    )
    return context


def save_cookies(context, cookie_file='cookies.json'):
    """Persist browser cookies for anti-detection."""
    try:
        cookies = context.cookies()
        cookies_path = os.path.join(os.path.dirname(__file__), cookie_file)
        with open(cookies_path, 'w') as f:
            json.dump(cookies, f)
    except Exception:
        pass


def load_cookies(context, cookie_file='cookies.json'):
    """Load previously saved cookies."""
    try:
        cookies_path = os.path.join(os.path.dirname(__file__), cookie_file)
        if os.path.exists(cookies_path):
            with open(cookies_path) as f:
                cookies = json.load(f)
            if cookies:
                context.add_cookies(cookies)
    except Exception:
        pass


def cleanup_thread():
    """Clean up the current thread's browser. Call on thread exit."""
    if hasattr(_thread_local, 'browser'):
        try:
            _thread_local.browser.close()
        except Exception:
            pass
        del _thread_local.browser
    if hasattr(_thread_local, 'playwright'):
        try:
            _thread_local.playwright.stop()
        except Exception:
            pass
        del _thread_local.playwright
