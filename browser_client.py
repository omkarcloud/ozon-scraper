"""Gets Ozon's Antibot pass on THIS machine.

Ozon answers every request — its JSON API included — with an "Antibot"
page until the visitor has solved a JavaScript proof of work. ozon/fetch.py
asks this module for that pass (`identity()`); here a real Google Chrome
(patchright, headed) opens one tiny Ozon JSON URL, lets the challenge run
(~5–10 s), and hands back the browser's cookies and user agent. From then on
every request is plain HTTP with that pass, on the same connection
(OZON_PROXY, or your own IP when it is unset).

Needs Google Chrome installed (patchright drives it). Ozon refuses the pass
to headless Chrome, so a window opens briefly. If Ozon shows your IP its
slider captcha or a "нет соединения" block instead of the challenge, the pass
cannot be earned there: set OZON_PROXY to another (sticky) proxy.

Same interface as the hosted service's client for its browser servers:
identity(), invalidate() and the three exception classes."""
import threading
import time

from ozon.parsers import antibot_kind

SEED = "https://www.ozon.ru/api/composer-api.bx/_action/summaryV2"
ORIGIN = "https://www.ozon.ru"
COOKIE = "abt_data"
TIMEOUT = 45          # seconds to wait for the proof of work
POLL = 1.0


class BoxUnavailable(Exception):
    """Chrome could not be started on this machine."""


class BoxRefused(Exception):
    """Ozon did not hand out a pass (captcha / block / timeout) on this connection."""


class RemintBudgetExceeded(Exception):
    """Kept for interface parity with the hosted service; never raised here."""


_lock = threading.Lock()


def identity(site="ozon", proxy=None, variant="", force=False):
    """Solve Ozon's challenge in a real Chrome -> {cookies, user_agent, ...}."""
    with _lock:                                   # one Chrome at a time
        return _mint(proxy)


def invalidate(site="ozon", proxy=None, variant=""):
    """Nothing is cached here: the next identity() call opens Chrome again."""


def _mint(proxy):
    try:
        from chrome_manager import create_scope
        from patchright_driver import PatchrightDriver
        with create_scope():
            driver = PatchrightDriver(proxy_url=proxy, headless=False,
                                      block_resources=("image", "font", "media", "stylesheet"))
    except Exception as e:
        raise BoxUnavailable(f"could not start Google Chrome: {type(e).__name__}: {e}")
    where = proxy.rsplit("@", 1)[-1] if proxy else "your own IP"
    print(f"ozon: solving the Antibot challenge in Chrome ({where})...")
    started = time.monotonic()
    try:
        driver.goto(SEED, referer=ORIGIN + "/")
        while True:
            try:
                html = driver.content() or ""
            except Exception:
                html = ""                          # the page is reloading after the proof of work
            kind = antibot_kind(200, html) if html else "challenge"
            if kind in ("captcha", "block"):
                raise BoxRefused(f"Ozon answered its {kind} page on {where}; "
                                 "set OZON_PROXY to another (sticky) proxy")
            cookies = driver.call(lambda page: page.context.cookies(ORIGIN))
            if kind is None and "<pre" in html.lower() and any(c["name"] == COOKIE for c in cookies):
                ua = driver.evaluate("navigator.userAgent")
                print(f"ozon: Antibot pass ready in {time.monotonic() - started:.0f}s")
                return {"cookies": [{k: c[k] for k in ("name", "value", "domain", "path") if k in c}
                                    for c in cookies],
                        "user_agent": ua, "exit_ip": None}
            if time.monotonic() - started > TIMEOUT:
                raise BoxRefused(f"the Antibot challenge did not clear in {TIMEOUT}s on {where}")
            time.sleep(POLL)
    finally:
        try:
            driver.close()
        except Exception:
            pass
