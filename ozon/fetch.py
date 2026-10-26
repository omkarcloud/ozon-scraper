"""Ozon transport: curl_cffi with an "Antibot" pass token minted on the
Windows browser box (recipes/ozon.py), replayed on the SAME sticky exit.

Ozon's own antibot answers every path, the /api/ JSON gateway included, with
one of three bodies chosen by the exit IP's reputation (parsers.antibot_kind):
a JavaScript proof-of-work challenge that a real Chrome clears in ~6 s, a
slider captcha (not solvable here) or a hard "нет соединения" block. A bare
curl never gets data. The identity minted after the challenge (cookie jar +
UA; `abt_data` is the token) makes plain curl_cffi pass every surface this
scraper uses — proven from the pod 2026-10-24: product + its second layout
page, search, category, brand, seller page, seller info modal, reviews,
questions, suggestions and the catalog page, 33/33 and 110/110 replays on
one identity (config's "--- ozon ---" block has the tables).

Exit choice: only an exit that shows the challenge variant can mint, so
_pick_exit() screens fresh sticky ports with one ~9 KB curl GET of the
mint's seed before the box ever launches a browser (datacenter proxy pool
2026-10-24: 2 of 16 ports in the variant census, the first or second port
in every live mint). The box receives that exact proxy URL; a sticky proxy
port is the same exit IP for the pod and the box.

Identity model (allegro pattern): config.OZON_IDENTITIES slots, each one
identity on its own exit, process-wide, minted lazily and shared by every
worker thread (requests round-robin over the slots); thread-local curl
sessions rebuild onto a slot's exit through a generation counter. Any
antibot body drops the slot's identity and the retry mints a new one on a
freshly screened exit.

Every request also sends adult_user_birthdate (an 18+ birth date): Ozon
answers age-restricted products with a userAdultModal instead of the page
until that cookie exists (2026-10-24: socks 1574782712 needed it).

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  OzonUpstreamError  transport failure / 5xx / non-JSON body   — retryable
  OzonBoxDown        browser box down / busy                   — fails at once
  OzonBlocked        antibot challenge / captcha / block        — retryable after a re-mint
  OzonBadRequest     upstream 400                               — never retried
  OzonNotFound       unknown product / category / brand / seller — never retried
"""
import itertools
import json
import os
import sys
import threading
import time
from urllib.parse import quote, urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import browser_client
import config
from browser_client import BoxRefused, BoxUnavailable, RemintBudgetExceeded
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from ozon import parsers
from ozon.refs import SITE

BOX_SITE = "ozon"                        # recipes/ozon.py
IMPERSONATE = "chrome"                   # passes every surface from the pod (2026-10-24)
ENTRYPOINT = f"{SITE}/api/entrypoint-api.bx/page/json/v2?url="
FILTER_ACTION = f"{SITE}/api/composer-api.bx/_action/getCatalogFilterValues"
SCREEN_URL = f"{SITE}/api/composer-api.bx/_action/summaryV2"    # the recipe's seed
ADULT_COOKIE = "adult_user_birthdate=1990-01-01"
PAGE_TIMEOUT = 30                        # product / listing JSON is 150-330 KB
SCREEN_TIMEOUT = 10                      # a healthy exit answers the screen in < 2 s; dead ports just time out
MINT_ATTEMPTS = 3                        # screened exits per mint before giving up
PDP_PAGE2 = "layout_container=pdpPage2column&layout_page_index=2"


class OzonUpstreamError(UpstreamError):
    """Transport failure / 5xx / unexpected body — retryable."""


class OzonBoxDown(OzonUpstreamError):
    """The browser box is down, draining or full: fail the request at once."""


class OzonBlocked(OzonUpstreamError, Blocked):
    """Antibot challenge / captcha / hard block — retryable after a fresh identity."""


class OzonBadRequest(BadRequest):
    """Upstream 400 — never retried."""


class OzonNotFound(NotFound):
    """Product / category / brand / seller does not exist — never retried."""


# ---- identity slots ----------------------------------------------------------------
_slots = {}              # index -> {"ident", "proxy", "cookie", "gen"}
_slot_gen = {}
_slot_locks = {}
_slots_guard = threading.Lock()
_rr = itertools.count()
_local = threading.local()


def _slot_count():
    return max(1, int(getattr(config, "OZON_IDENTITIES", 1) or 1))


def _screen(proxy):
    """'challenge' | 'captcha' | 'block' | 'open' | 'error' for one exit: one
    GET of the mint's seed (the antibot answers it like any page)."""
    from curl_cffi import requests as curl_requests
    sess = curl_requests.Session(impersonate=IMPERSONATE)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    try:
        resp = sess.get(SCREEN_URL, headers={"accept-language": "ru-RU,ru;q=0.9", "accept": "application/json"},
                        timeout=SCREEN_TIMEOUT)
    except Exception as e:
        print(f"ozon: exit screen failed ({type(e).__name__}: {str(e)[:80]})")
        return "error"
    finally:
        try:
            sess.close()
        except Exception:
            pass
    kind = parsers.antibot_kind(resp.status_code, resp.text)
    if kind:
        return kind
    return "open" if resp.status_code == 200 else "error"


def _pick_exit():
    """A fresh sticky exit whose antibot variant is the clearable challenge
    (or that is not challenged at all)."""
    seen = []
    for _ in range(max(1, int(getattr(config, "OZON_EXIT_SCREEN", 12)))):
        proxy = config.ozon_proxy()
        verdict = _screen(proxy)
        seen.append(verdict)
        if verdict in ("challenge", "open"):
            return proxy
    raise OzonBlocked(f"no exit with the clearable challenge in {len(seen)} screened ports ({', '.join(seen)})")


def _mint():
    """One identity on a screened exit; MINT_ATTEMPTS exits."""
    last = None
    for attempt in range(1, MINT_ATTEMPTS + 1):
        proxy = _pick_exit()
        port = proxy.rsplit(":", 1)[-1] if proxy else "own IP"
        try:
            print(f"ozon: minting the antibot identity on the browser box (exit port {port}, "
                  f"attempt {attempt}/{MINT_ATTEMPTS})...")
            ident = browser_client.identity(BOX_SITE, proxy=proxy)
        except BoxUnavailable as e:
            raise OzonBoxDown(f"browser box unavailable for the identity mint: {e}")
        except RemintBudgetExceeded as e:
            raise OzonBlocked(f"identity re-mint budget exhausted: {e}")
        except BoxRefused as e:
            last = e
            print(f"ozon: mint attempt {attempt} refused: {e}")
            continue
        jar = {c["name"]: c["value"] for c in ident.get("cookies") or []}
        if "abt_data" not in jar or not ident.get("user_agent"):
            browser_client.invalidate(BOX_SITE, proxy=proxy)
            last = RuntimeError("the box answered without an abt_data cookie / user agent")
            continue
        cookie = "; ".join([f"{k}={v}" for k, v in jar.items()] + [ADULT_COOKIE])
        print(f"ozon: identity minted (exit {ident.get('exit_ip')}, ua={ident['user_agent'][:40]}...)")
        return {"ident": ident, "proxy": proxy, "cookie": cookie}
    raise OzonBlocked(f"identity mint failed after {MINT_ATTEMPTS} attempts (last: {last})")


def _slot_lock(index):
    with _slots_guard:
        return _slot_locks.setdefault(index, threading.Lock())


def _identity(index):
    entry = _slots.get(index)
    if entry is not None:
        return entry
    with _slot_lock(index):
        entry = _slots.get(index)
        if entry is not None:
            return entry
        entry = _mint()
        _slot_gen[index] = _slot_gen.get(index, 0) + 1
        entry["gen"] = _slot_gen[index]
        entry["slot"] = index
        _slots[index] = entry
        return entry


def _invalidate(entry):
    """Drop a slot's identity iff it is still the one that got blocked
    (another thread may already have re-minted it)."""
    with _slot_lock(entry["slot"]):
        if _slots.get(entry["slot"]) is entry:
            del _slots[entry["slot"]]
            browser_client.invalidate(BOX_SITE, proxy=entry["proxy"])


def _session(entry):
    """Thread-local curl session on the slot's exit, rebuilt when the slot
    was re-minted (new exit)."""
    store = getattr(_local, "sessions", None)
    if store is None:
        store = _local.sessions = {}
    key = entry["slot"]
    sess, gen = store.get(key, (None, None))
    if sess is not None and gen != entry["gen"]:
        _close(sess)
        sess = None
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        if entry["proxy"]:
            sess.proxies = {"http": entry["proxy"], "https": entry["proxy"]}
        store[key] = (sess, entry["gen"])
    return sess


def _close(sess):
    try:
        sess.close()
    except Exception:
        pass


def _drop_sessions():
    store = getattr(_local, "sessions", None) or {}
    for key in list(store):
        sess, _ = store.pop(key)
        _close(sess)


def _headers(entry, content_type=None):
    out = {
        "user-agent": entry["ident"]["user_agent"],
        "accept": "application/json",
        "accept-language": "ru-RU,ru;q=0.9,en;q=0.8",
        "referer": f"{SITE}/",
        "cookie": entry["cookie"],
    }
    if content_type:
        out["content-type"] = content_type
    return out


def _once(method, url, body=None, what=None):
    """One request through the next identity slot -> (status, text)."""
    entry = _identity(next(_rr) % _slot_count())
    try:
        if method == "POST":
            resp = _session(entry).post(url, data=json.dumps(body), headers=_headers(entry, "application/json"),
                                        timeout=PAGE_TIMEOUT)
        else:
            resp = _session(entry).get(url, headers=_headers(entry), timeout=PAGE_TIMEOUT)
    except Exception as e:
        raise OzonUpstreamError(f"request failed: {type(e).__name__}: {str(e)[:160]}")
    text = resp.text or ""
    status = resp.status_code
    kind = parsers.antibot_kind(status, text)
    if kind:
        _invalidate(entry)
        raise OzonBlocked(f"antibot {kind} (HTTP {status}) for {what or url[:120]}")
    if status in (403, 429):
        _invalidate(entry)
        raise OzonBlocked(f"HTTP {status} for {what or url[:120]}")
    if status >= 500:
        raise OzonUpstreamError(f"HTTP {status} for {what or url[:120]}")
    return status, text


def _retrying(fn):
    """config.MAX_RETRIES attempts; a retryable failure drops the thread's
    sessions (a block already dropped the identity, so the retry mints a
    new one on a freshly screened exit). NotFound / BadRequest surface at once."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except OzonBoxDown:
            raise
        except OzonUpstreamError as e:
            last = e
            _drop_sessions()
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def entrypoint_url(path):
    """The page JSON URL for a site path; the path is encoded whole, as the
    web app does (its own ?/&/; must reach Ozon intact)."""
    return ENTRYPOINT + quote(path, safe="")


def fetch_page(path, what=None):
    """GET one site page's JSON -> the page dict. A 404 with a page body is
    returned (callers read the not-found widgets); 400 is a BadRequest."""
    def go():
        status, text = _once("GET", entrypoint_url(path), what=what)
        page = parsers.load_page(text)
        if page is None:
            if status == 404:
                raise OzonNotFound(f"{what or path} not found")
            if status == 400:
                raise OzonBadRequest(text[:200])
            raise OzonUpstreamError(f"HTTP {status}, non-JSON body for {what or path}: {text[:120]!r}")
        if parsers.is_adult_gate(page):
            raise OzonUpstreamError(f"age gate on {what or path} despite the birth-date cookie")
        return page
    return _retrying(go)


# ---- URL builders -----------------------------------------------------------------

def _price_param(min_price, max_price):
    if min_price is None and max_price is None:
        return None
    lo = 0 if min_price is None else min_price
    hi = 1_000_000_000 if max_price is None else max_price
    return f"{float(lo):.3f};{float(hi):.3f}"     # filtersDesktop currency_price keys: "129.000;20000.000"


def listing_path(base, page=1, sort=None, min_price=None, max_price=None, text=None, extra=None):
    """A listing path with Ozon's own query params (sorting / currency_price
    / page / text), in the web app's order."""
    params = list(extra or [])
    if text:
        params.append(("text", text))
    if sort and sort != "score":
        params.append(("sorting", sort))
    price = _price_param(min_price, max_price)
    if price:
        params.append(("currency_price", price))
    if page and page > 1:
        params.append(("page", page))
    return base + ("?" + urlencode(params, safe=";") if params else "")


# ---- surfaces ----------------------------------------------------------------------

def fetch_product(sku):
    """(page1, page2) for one SKU. oos_search=false keeps an out-of-stock
    product on its own page (without it Ozon swaps in a search page). The
    second layout page carries the full characteristics and description;
    when it fails the record is built from page 1 alone (page2 None)."""
    page1 = fetch_page(f"/product/{sku}/?oos_search=false", what=f"product {sku}")
    if parsers.product_not_found(page1):
        raise OzonNotFound(f"product {sku} not found")
    if parsers.page_type(page1) != "pdp":
        raise OzonUpstreamError(f"product {sku}: unexpected page type {parsers.page_type(page1)!r}")
    try:
        page2 = fetch_page(f"/product/{sku}/?oos_search=false&{PDP_PAGE2}", what=f"product {sku} (details)")
    except OzonBoxDown:
        raise
    except (OzonUpstreamError, OzonBadRequest, OzonNotFound) as e:
        print(f"ozon: product {sku} second layout page failed, serving page 1 only: {e}")
        page2 = None
    return page1, page2


def fetch_search(query, page=1, sort=None, min_price=None, max_price=None, category=None):
    base = category or "/search/"
    extra = [] if category else [("from_global", "true")]
    return fetch_page(listing_path(base, page, sort, min_price, max_price, text=query, extra=extra),
                      what=f"search {query!r}")


def fetch_category(category, page=1, sort=None, min_price=None, max_price=None):
    return fetch_page(listing_path(category, page, sort, min_price, max_price), what=f"category {category}")


def fetch_brand(brand_id, page=1, sort=None):
    return fetch_page(listing_path(f"/brand/{brand_id}/", page, sort), what=f"brand {brand_id}")


def fetch_seller_page(seller):
    return fetch_page(f"/seller/{seller}/", what=f"seller {seller}")


def fetch_seller_products(seller, page=1, sort=None, query=None):
    return fetch_page(listing_path(f"/seller/{seller}/products/", page, sort, text=query), what=f"seller {seller}")


def fetch_seller_modal(seller_id):
    return fetch_page(f"/modal/shop-in-shop-info?seller_id={seller_id}", what=f"seller {seller_id}")


def fetch_reviews(sku, page=1, sort=None):
    params = []
    if page and page > 1:
        params.append(("page", page))
    if sort:
        params.append(("sort", sort))
    path = f"/product/{sku}/reviews/" + ("?" + urlencode(params) if params else "")
    return fetch_page(path, what=f"product {sku} reviews")


def fetch_questions(sku, sort=None, cursor=None):
    """The first questions page, or the page a previous page's `next`
    cursor path points at (sort travels in the base page's URL)."""
    if cursor:
        return fetch_page(cursor, what=f"product {sku} questions")
    path = f"/product/{sku}/questions/" + (f"?qsort={sort}" if sort else "")
    return fetch_page(path, what=f"product {sku} questions")


def fetch_suggestions(query):
    return fetch_page(f"/searchSuggestions/search/?{urlencode({'text': query, 'from_global': 'true'})}",
                      what=f"suggestions {query!r}")


def fetch_catalog():
    """/category/ — the catalog page; its catalogMenu lists the roots."""
    return fetch_page("/category/", what="catalog")


def fetch_category_children(category):
    """The category filter's "show all" composer action: ancestors (level 0)
    + every child category (level 1). Accepts /category/<id>/ and slugged
    paths; an unknown category answers HTTP 400 (rpc Internal)."""
    body = {"baseLink": category.split("?")[0], "isOpened": "true", "key": "category", "pageType": "category"}

    def go():
        status, text = _once("POST", FILTER_ACTION, body=body, what=f"category {category}")
        if status == 400:
            raise OzonNotFound(f"category {category} not found")
        try:
            payload = json.loads(text)
        except ValueError:
            raise OzonUpstreamError(f"HTTP {status}, non-JSON category children for {category}: {text[:120]!r}")
        if status != 200 or not isinstance(payload, dict):
            raise OzonUpstreamError(f"HTTP {status} for category children of {category}")
        return payload
    return _retrying(go)


def _reset_for_tests():
    with _slots_guard:
        _slots.clear()
        _slot_gen.clear()
    _drop_sessions()
