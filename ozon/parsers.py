"""Ozon parsers: the entrypoint-api.bx page JSON (and two composer actions)
-> clean dicts. Pure functions, no I/O; every parser tolerates partial
payloads (missing widgets give nulls / empty lists, never a crash).

Every page Ozon's web app renders is one JSON document from
`/api/entrypoint-api.bx/page/json/v2?url=<site path>`:
    {layout, widgetStates: {"<widget>-<id>-<container>-<n>": "<JSON string>"},
     pageInfo: {url, pageType, analyticsInfo}, seo: {title, link, meta, script},
     nextPage, ...}
The widgets read here (captured 2026-10-24, ozon/fixtures/, from the GKE pod
through a box-minted identity on a datacenter exit):

  product page    webProductHeading, webPrice, webGallery, webAspects,
                  webReviewProductScore, webQuestionCount, webCurrentSeller,
                  webBrand, webShortCharacteristics, breadCrumbs,
                  webMarketingLabels, webBestSeller, webIconWithText,
                  webModelParams, the seo JSON-LD Product block; the second
                  layout page (layout_container=pdpPage2column) adds
                  webCharacteristics, webDescription, webHashtags
  listings        tileGridDesktop items (search, category, brand, seller),
                  infiniteVirtualPaginator, filtersDesktop, breadCrumbs,
                  resultsHeader, categoryBrandList
  reviews         webListReviews, webReviewProductScore, reviewsTitle
  questions       webPDPListQuestions + the paginator / root nextPage cursor
  seller          sellerTransparency (storefront header) + the
                  /modal/shop-in-shop-info cells and legal text
  brand           sellerTransparency (brand header)
  suggestions     webSuggestions
  categories      catalogMenu (roots) and the getCatalogFilterValues action

Not-found shapes: product / reviews / questions pages of an unknown SKU answer
HTTP 200 with an `error` widget "Такой страницы не существует" (a product
with no reviews gets the same widget plus "потому что у товара нет отзывов",
which is an empty list, not a 404); an unknown seller or brand answers 200
with a `statusWidget` and no seo title; an unknown category id makes the
filter action answer HTTP 400.

Fields skipped on purpose: tracking keys/tokens (trackingInfo, advert,
cellTrackingInfo, widgetToken, sliceKey), presentation (colours, typography,
paddings, icons, button labels, popover texts), cart / favourite / compare /
share / chat actions, installment promos ("без % до 10 января"), bank logos,
recommendation shelves (tileScrollDesktop, "Рекомендуем также"), SEO tag
clouds (tagListModal / tagList) and the gallery tips.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

from ozon.shared import as_dict, as_list, g, html_to_text, multiline, num, text, to_int
from ozon import refs

CURRENCY = refs.CURRENCY
REVIEWS_PER_PAGE = 30            # webListReviews.paging.perPage on every captured page

# antibot bodies (recipes/ozon.py uses the same tells)
_CHALLENGE = ("abt-challenge/script_", "Antibot Challenge Page")
_CAPTCHA = ("abt-challenge/captcha_", "Antibot Captcha")
_BLOCK = ("abt-challenge/incidents/images/warn", "нет соединения")

_RU_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7,
    "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}


# ---- envelope ------------------------------------------------------------------------

def load_page(raw):
    """Raw response text (or an already-parsed dict) -> the page dict, or None."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.lstrip().startswith("{"):
        return None
    try:
        out = json.loads(raw)
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


def antibot_kind(status, raw):
    """'challenge' | 'captcha' | 'block' when the body is Ozon's antibot
    answer (HTML interstitial or the JSON incident the /api/ paths return),
    else None."""
    body = raw if isinstance(raw, str) else ""
    head = body[:3000]
    if '"incidentId"' in head:
        if "challengeURL" in head:
            return "challenge"
        if "captchaURL" in head:
            return "captcha"
        return "block"
    if "<html" in head.lower() or "<!doctype" in head.lower():
        if any(m in body for m in _CAPTCHA):
            return "captcha"
        if any(m in body for m in _CHALLENGE):
            return "challenge"
        if any(m in body for m in _BLOCK):
            return "block"
        if status in (403, 429):
            return "block"
    return None


def _decode(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            out = json.loads(value)
        except ValueError:
            return None
        return out if isinstance(out, dict) else None
    return None


def widgets(page, name):
    """Every decoded state of widget `name` (key prefix before the first '-')."""
    out = []
    for key, value in as_dict((page or {}).get("widgetStates")).items():
        if key.split("-", 1)[0] == name:
            state = _decode(value)
            if state is not None:
                out.append(state)
    return out


def widget(page, name):
    """The first non-empty state of widget `name`, else {}."""
    for state in widgets(page, name):
        if state:
            return state
    return {}


def page_type(page):
    return g(page, "pageInfo", "pageType")


def page_url(page):
    return g(page, "pageInfo", "url")


def analytics(page):
    return as_dict(g(page, "pageInfo", "analyticsInfo"))


def is_adult_gate(page):
    return bool(widgets(page, "userAdultModal"))


def error_widget(page):
    """The `error` widget's (title, subtitle), or (None, None)."""
    state = widget(page, "error")
    return text(state.get("title")), text(state.get("subtitle"))


def _seo_title(page):
    return text(g(page, "seo", "title"))


def json_ld(page):
    """The seo block's schema.org Product JSON-LD, or {}."""
    for script in as_list(g(page, "seo", "script")):
        blob = _decode(as_dict(script).get("innerHTML"))
        if blob and blob.get("@type") == "Product":
            return blob
    return {}


def canonical_link(page):
    for link in as_list(g(page, "seo", "link")):
        if as_dict(link).get("rel") == "canonical":
            return link.get("href")
    return None


# ---- values ------------------------------------------------------------------------

def _digits_text(value):
    return re.sub(r"[\s   ]", "", str(value))


def money(value):
    """'165 079 ₽' / '193 ₽' / '1 234,50 ₽' -> 165079 / 193 / 1234.5; junk -> None."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value) if float(value).is_integer() else round(float(value), 2)
    match = re.search(r"\d[\d\s   ]*(?:[.,]\d{1,2})?", str(value))
    if not match:
        return None
    out = num(_digits_text(match.group(0)).replace(",", "."))
    if out is None:
        return None
    return int(out) if out.is_integer() else round(out, 2)


def count(value):
    """'41 786 отзывов' / '440 K' / '1,3 M' / '77,3 K' / '2 077 заказов' -> int; junk -> None."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    s = str(value).replace(" ", " ").replace(" ", " ").replace(" ", " ")
    match = re.search(r"(\d[\d ]*(?:[.,]\d+)?)\s*([KkКкMmМм])?(?![a-zа-я])", s)
    if not match:
        return None
    number = num(match.group(1).replace(" ", "").replace(",", "."))
    if number is None:
        return None
    unit = (match.group(2) or "").lower()
    if unit in ("k", "к"):
        number *= 1000
    elif unit in ("m", "м"):
        number *= 1_000_000
    return int(round(number))


def rating_value(value):
    out = num(str(value).replace(",", ".")) if value is not None else None
    if out is None or out <= 0 or out > 5:
        return None
    return round(out, 2)


def percent(value):
    """'−49%' / '-49%' -> 49; junk -> None."""
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", str(value or ""))
    return to_int(match.group(1).replace(",", ".")) if match else None


def epoch_iso(value):
    """1788842612 -> '2026-09-07T04:43:32Z' (UTC); junk -> None."""
    seconds = num(value)
    if seconds is None or seconds <= 0:
        return None
    if seconds > 10_000_000_000:
        seconds /= 1000
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def ru_date(value):
    """'3 декабря 2025' -> '2025-12-03'; anything else -> None."""
    match = re.search(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", (text(value) or "").lower())
    if not match or match.group(2) not in _RU_MONTHS:
        return None
    try:
        return date(int(match.group(3)), _RU_MONTHS[match.group(2)], int(match.group(1))).isoformat()
    except ValueError:
        return None


def delivery_date(value, today=None):
    """A tile's delivery label ('26 октября', 'завтра', 'сегодня',
    'послезавтра') -> ISO date; the year is the next occurrence from today
    (Moscow calendar). Anything else -> None."""
    label = (text(value) or "").lower()
    if not label:
        return None
    today = today or (datetime.now(timezone.utc) + timedelta(hours=3)).date()
    for word, days in (("послезавтра", 2), ("завтра", 1), ("сегодня", 0)):
        if word in label:
            return (today + timedelta(days=days)).isoformat()
    match = re.search(r"(\d{1,2})\s+([а-яё]+)", label)
    if not match or match.group(2) not in _RU_MONTHS:
        return None
    day, month = int(match.group(1)), _RU_MONTHS[match.group(2)]
    for year in (today.year, today.year + 1):
        try:
            when = date(year, month, day)
        except ValueError:
            return None
        if when >= today - timedelta(days=1):
            return when.isoformat()
    return None


def _strip_html(value):
    out = html_to_text(value) if isinstance(value, str) and "<" in value else multiline(value)
    return out or None


def _rich_text(items):
    """[{type: text, content}, {type: br}, ...] -> text with line breaks."""
    parts = []
    for item in as_list(items):
        kind = as_dict(item).get("type")
        if kind in ("br", "newLine"):
            parts.append("\n")
        elif "content" in item:
            parts.append(str(item.get("content") or ""))
    return multiline("".join(parts).replace("\r", ""))


def _uniq(values):
    out = []
    for v in values:
        if v and v not in out:
            out.append(v)
    return out


# ---- listings (search / category / brand / seller products) -------------------------

def _tile_price(state):
    prices = as_list(g(state, "priceV2", "price"))
    current = next((p.get("text") for p in prices if as_dict(p).get("textStyle") == "PRICE"), None)
    original = next((p.get("text") for p in prices if as_dict(p).get("textStyle") == "ORIGINAL_PRICE"), None)
    return {
        # tiles always show the Ozon-card price (webPrice.cardPrice on the product page)
        "amount": money(current),
        "original_amount": money(original),
        "discount_percent": percent(g(state, "priceV2", "discount")),
        "currency": CURRENCY,
    }


def _label_items(state):
    """labelListV2 -> [(icon name or None, text or None), ...]."""
    out = []
    pending_icon = None
    for item in as_list(g(state, "labelListV2", "items")):
        kind = as_dict(item).get("type")
        if kind == "icon":
            pending_icon = g(item, "icon", "icon", "icon")
        elif kind == "text":
            out.append((pending_icon, text(g(item, "text", "text"))))
            pending_icon = None
    return out


def parse_tile(item):
    """One tileGrid item -> a product row."""
    item = as_dict(item)
    sku = to_int(item.get("sku") or item.get("id"))
    row = {
        "sku": sku,
        "name": None,
        "link": refs.product_link(sku, g(item, "action", "link")) if sku else None,
        "image": None,
        "images": _uniq(g(m, "image", "link") for m in as_list(g(item, "tileImage", "items"))
                        if as_dict(m).get("type") == "image"),
        "price": {"amount": None, "original_amount": None, "discount_percent": None, "currency": CURRENCY},
        "rating": None,
        "reviews_count": None,
        "brand": None,
        "stock_left": None,
        "delivery_date": None,
        "is_sold_by_ozon": False,
        "has_express_delivery": False,
        "is_premium_seller": False,
        "has_price_drop": False,
        "is_adult": bool(item.get("isAdult")),
        "labels": [],
    }
    row["image"] = row["images"][0] if row["images"] else None
    brand_name, brand_verified = None, False
    for state in as_list(item.get("mainState")):
        kind = as_dict(state).get("type")
        if kind == "priceV2":
            row["price"] = _tile_price(state)
        elif kind == "textDS":
            body = as_dict(state.get("textDS"))
            if state.get("id") == "name":
                row["name"] = text(body.get("text"))
            elif "осталось" in (body.get("text") or ""):
                row["stock_left"] = count(body.get("text"))
            elif text(body.get("text")):
                row["labels"].append(text(body.get("text")))
        elif kind == "labelListV2":
            for icon, label in _label_items(state):
                if icon == "ic_s_star_filled_compact":
                    row["rating"] = rating_value(label)
                elif icon == "ic_s_dialog_filled_compact":
                    row["reviews_count"] = count(label)
                elif icon == "ic_s_ozon_circle_filled_compact":
                    row["is_sold_by_ozon"] = True
                elif label == "Стало дешевле":
                    row["has_price_drop"] = True
                elif label == "Бренд проверен":
                    brand_verified = True
                elif icon == "ic_s_confirmed_filled_compact" and label:
                    brand_name, brand_verified = label, True
                elif icon is None and label and not brand_name and not any(ch.isdigit() for ch in label):
                    brand_name = label
                elif label:
                    row["labels"].append(label)
    logo = g(item, "brandLogo", "logo")
    if brand_name or logo or brand_verified:
        row["brand"] = {"name": brand_name, "logo": logo, "is_verified": brand_verified}
    buttons = as_dict(item.get("multiButton"))
    button = as_dict(buttons.get("ozonButton") or buttons.get("expressButton"))
    cart = as_dict(button.get("addToCart"))
    action = as_dict(cart.get("actionButton"))
    row["delivery_date"] = delivery_date(action.get("title") or cart.get("title"))   # "27 октября"
    row["has_express_delivery"] = "expressButton" in buttons
    seller_icon = as_dict(action.get("sellerIcon") or cart.get("sellerIcon"))
    row["is_premium_seller"] = "premium" in (g(seller_icon, "testInfo", "automatizationId") or "")
    return row


def tiles(page):
    """The listing's own products. A grid with a `header` is a
    recommendation shelf ("Возможно, вам понравится" under brand pages and
    unknown brands, 2026-10-24) and is skipped."""
    out = []
    for state in widgets(page, "tileGridDesktop") + widgets(page, "tileGridMobile"):
        if state.get("header"):
            continue
        out.extend(parse_tile(item) for item in as_list(state.get("items"))
                   if as_dict(item).get("sku") or as_dict(item).get("id"))
    return out


def next_page_link(page):
    """The infinite paginator's next link (listings), else the paginator's
    (questions), else the document-level nextPage (layout follow-ups)."""
    for name in ("infiniteVirtualPaginator", "paginator"):
        nxt = widget(page, name).get("nextPage")
        if nxt:
            return nxt
    return (page or {}).get("nextPage")


def breadcrumbs(page):
    """Category trail. A trailing brand-filter crumb
    (/category/<cat>-<id>/<brand>-<brand id>/) is not a category and is
    dropped (the product's brand carries it)."""
    out = []
    for crumb in as_list(widget(page, "breadCrumbs").get("breadcrumbs")):
        link = as_dict(crumb).get("link") or ""
        if re.search(r"/category/[^/]+/[^/?#]+", link):
            continue
        out.append({"id": refs.category_id_from_path(link), "name": text(crumb.get("text")),
                    "link": refs.category_link(link) if link else None})
    return out


def full_image(url):
    """Ozon resizes images by path segment (/wc140/, /c100/, /c600/); without
    it the CDN serves the original."""
    if not isinstance(url, str) or not url:
        return None
    return re.sub(r"/(?:wc|c)\d+(?=/)", "", url)


def _filters(page):
    """filtersDesktop -> {key: filter dict} for the filter keys used below."""
    out = {}
    for section in as_list(widget(page, "filtersDesktop").get("sections")):
        for flt in as_list(as_dict(section).get("filters")):
            if as_dict(flt).get("key"):
                out[flt["key"]] = flt
    return out


def _checkbox_values(flt):
    body = as_dict(flt.get(flt.get("type") or "")) if flt else {}
    out = []
    for section in as_list(body.get("sections")):
        for item in as_list(as_dict(section).get("items")):
            out.append({"id": to_int(item.get("key")) if str(item.get("key") or "").isdigit() else item.get("key"),
                        "name": text(g(item, "title", "text")), "image": item.get("image")})
    return out


def _category_filter_entries(page):
    flt = _filters(page).get("category")
    out = []
    for cat in as_list(g(flt, "categoryFilter", "categories")):
        url = (as_dict(cat).get("urlValue") or "").split("?")[0]
        match = re.match(r"/category/[^/]+/", url)
        if not match:
            continue
        url = match.group(0)          # drop a brand-filter sub-segment (/category/smartfony-15502/apple-26303000/)
        out.append({"id": refs.category_id_from_path(url), "name": text(cat.get("title")),
                    "link": refs.category_link(url), "level": cat.get("level"), "is_current": bool(cat.get("isActive"))})
    return out


def category_path(page):
    """On a category page the categoryFilter's level-0 entries are the trail
    (ancestors + the active category). On a plain search page they are the
    categories the results fall into, not a trail: see facets()."""
    if page_type(page) == "search":
        return []
    return [c for c in _category_filter_entries(page) if c["level"] == 0]


def facets(page):
    """What the listing can be narrowed by: price range (Ozon-card price),
    categories (child categories, or the matching categories on a plain
    search page), brands, sellers (filtersDesktop; values Ozon shows first)."""
    flts = _filters(page)
    price = as_dict(g(flts.get("currency_price"), "multipleRangesFilter", "rangeFilter"))
    entries = _category_filter_entries(page)
    if page_type(page) == "search":
        cats = entries
    else:
        cats = [c for c in entries if c["level"] and c["level"] > 0]
    return {
        "price_range": {"min": money(price.get("minValue")), "max": money(price.get("maxValue")), "currency": CURRENCY}
        if price else None,
        "categories": [{k: c[k] for k in ("id", "name", "link")} for c in cats],
        "brands": _checkbox_values(flts.get("brand")),
        "sellers": _checkbox_values(flts.get("seller")),
    }


def parse_listing(page):
    """Any tile listing page -> {results, has_next, context...}."""
    results = tiles(page)
    info = analytics(page)
    path = category_path(page)
    current = next((c for c in path if c["is_current"]), None)
    header = text(widget(page, "resultsHeader").get("title"))
    return {
        "page_type": page_type(page),
        "title": header or text(g(page, "seo", "h1")),
        "category": {"id": current["id"] if current else to_int(info.get("categoryId")),
                     "name": current["name"] if current else (header if page_type(page) == "category" else None),
                     "link": current["link"] if current else
                     (refs.category_link(int(info["categoryId"])) if to_int(info.get("categoryId")) else None)}
        if (current or info.get("categoryId")) else None,
        "category_path": [{k: c[k] for k in ("id", "name", "link")} for c in path],
        "brand_id": to_int(info.get("brandId")),
        "results": results,
        "has_next": bool(results) and bool(next_page_link(page)),
        "facets": facets(page),
        "url": page_url(page),
    }


def listing_not_found(page):
    """An unknown category / brand / seller listing: Ozon answers 200 with a
    statusWidget and no seo title, or (a search scoped to an unknown
    category, whose seo title comes from the query) the statusWidget's
    sign-error image."""
    status = widgets(page, "statusWidget")
    if not status:
        return False
    if not _seo_title(page):
        return True
    return any("sign-error" in (g(s, "imageAtom", "image") or "") for s in status)


# ---- product -------------------------------------------------------------------------

def _seller(page):
    state = widget(page, "webCurrentSeller")
    sticky = as_dict(widget(page, "webStickyProducts").get("seller"))
    out = {"id": None, "name": None, "link": None, "slug": None, "logo": sticky.get("logoImageUrl"),
           "rating": None, "orders_count": None, "is_premium": None, "legal_name": None, "legal_address": None,
           "registration_number": None, "country_code": None, "is_honest_sign_registered": None,
           "working_hours": None}
    if not state:
        if not sticky:
            return None
        link = refs.absolute(sticky.get("link"))
        out.update(name=text(sticky.get("name")), link=link, slug=_seller_slug(link))
        return out
    cell = as_dict(state.get("sellerCell"))
    link = refs.absolute(g(cell, "common", "action", "link")) or refs.absolute(sticky.get("link"))
    seller_id = to_int(g(state, "header", "badge", "subscribed", "common", "action", "params", "sellerId"))
    if seller_id is None:
        match = re.search(r"[?&]user_id=(\d+)", g(state, "chat", "action", "link") or "")
        seller_id = to_int(match.group(1)) if match else None
    out.update({
        "id": seller_id,
        "name": text(g(cell, "centerBlock", "title", "text")) or text(sticky.get("name")),
        "link": link,
        "slug": _seller_slug(link),
        "logo": g(cell, "leftBlock", "icon", "backgroundImage") or sticky.get("logoImageUrl"),
        "rating": rating_value(g(state, "rating", "title", "text")),
        "is_premium": "premium" in (g(cell, "centerBlock", "titleIcon", "icon") or ""),
    })
    for factor in as_list(state.get("trustFactors")):
        title = text(g(factor, "title", "text")) or ""
        if title == "Заказы":
            out["orders_count"] = count(g(factor, "badge", "text"))
        elif title == "О магазине":
            lines = [text(x.get("content")) for x in as_list(g(factor, "tooltip", "subtitle"))
                     if as_dict(x).get("type") == "text" and text(x.get("content"))]
            legal, hours = _split_legal(lines)
            out.update(legal)
            out["working_hours"] = hours
    return out


def _seller_slug(link):
    match = re.search(r"/seller/([^/?#]+)", link or "")
    return match.group(1) if match else None


_LEGAL_ID_RE = re.compile(r"^\d{13,15}$")          # ОГРН (13) / ОГРНИП (15)
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _split_legal(lines):
    """The seller's "О магазине" lines -> ({legal_name, legal_address,
    registration_number, country_code, is_honest_sign_registered},
    working_hours). Ozon lists: legal name, address (optional), ОГРН /
    ОГРНИП, a country code (foreign sellers), the working hours and
    "Продавец зарегистрирован в системе Честный знак" (Russia's mandatory
    goods-marking system)."""
    legal = {"legal_name": None, "legal_address": None, "registration_number": None, "country_code": None,
             "is_honest_sign_registered": False}
    hours = None
    rest = []
    for line in lines:
        if line.lower().startswith("режим работы"):
            hours = re.sub(r"^режим работы\s*[—–-]\s*", "", line, flags=re.I) or line
        elif "честный знак" in line.lower():
            legal["is_honest_sign_registered"] = True
        elif _LEGAL_ID_RE.match(line):
            legal["registration_number"] = line
        elif _COUNTRY_RE.match(line):
            legal["country_code"] = line
        else:
            rest.append(line)
    if rest:
        legal["legal_name"] = rest[0]
    if len(rest) > 1:
        legal["legal_address"] = ", ".join(rest[1:])
    return legal, hours


def _variants(page):
    out = []
    for aspect in as_list(widget(page, "webAspects").get("aspects")):
        options = []
        for v in as_list(as_dict(aspect).get("variants")):
            data = as_dict(v.get("data"))
            sku = to_int(v.get("sku"))
            options.append({
                "sku": sku,
                "value": text(data.get("searchableText")) or _rich_text(data.get("textRs")),
                "name": text(data.get("title")),
                "link": refs.product_link(sku, v.get("link")) if sku else None,
                "price": money(v.get("price")) if v.get("price") is not None else money(data.get("price")),
                "original_price": money(data.get("originalPrice")),
                "image": full_image(data.get("coverImage")),
                "colors": as_list(data.get("colors")) or None,
                "is_available": v.get("availability") == "inStock" if v.get("availability") else None,
                "is_selected": bool(v.get("active")),
            })
        out.append({"name": text(aspect.get("aspectName")), "key": aspect.get("aspectKey"),
                    "options_count": to_int(g(aspect, "aspectModalInfo", "realNumberOfVariants")) or len(options),
                    "options": options})
    return out


def _characteristics(page1, page2):
    """Full list from the second layout page (webCharacteristics: short +
    long groups); the first page's short list when page 2 is missing."""
    out = []
    for state in widgets(page2, "webCharacteristics") if page2 else []:
        for group in as_list(state.get("characteristics")):
            group_title = text(as_dict(group).get("title"))
            for kind in ("short", "long"):
                for item in as_list(group.get(kind)):
                    out.append({
                        "key": item.get("key"),
                        "name": text(item.get("name")),
                        "values": [text(v.get("text")) for v in as_list(item.get("values")) if text(v.get("text"))],
                        "group": group_title,
                    })
    if out:
        return out
    for item in as_list(widget(page1, "webShortCharacteristics").get("characteristics")):
        values = [re.sub(r",\s*$", "", text(v.get("text")) or "") for v in as_list(item.get("values"))]
        out.append({"key": re.sub(r"_\d+$", "", item.get("id") or "") or None,
                    "name": _rich_text(g(item, "title", "textRs")),
                    "values": [v for v in values if v], "group": None})
    return out


def _description(page2, ld):
    """(description text, description images, extra sections) from the
    second layout page's webDescription widgets; JSON-LD as the fallback."""
    body, images, sections = None, [], []
    for state in widgets(page2, "webDescription") if page2 else []:
        if state.get("richAnnotation"):
            body = body or _strip_html(state["richAnnotation"])
        rich = as_dict(state.get("richAnnotationJson"))
        if rich:
            parts = []
            for block_group in as_list(rich.get("content")):
                for block in as_list(as_dict(block_group).get("blocks")):
                    title = _rich_text(g(block, "title", "items"))
                    content = _rich_text(g(block, "text", "items"))
                    if title:
                        parts.append(title)
                    if content:
                        parts.append(content)
                    src = g(block, "img", "src")
                    if src:
                        images.append(src)
            if parts:
                body = body or "\n\n".join(parts)
        for section in as_list(state.get("characteristics")):
            title, content = text(as_dict(section).get("title")), multiline(section.get("content"))
            if title or content:
                sections.append({"title": title, "content": content})
    if not body:
        body = multiline(ld.get("description"))
    return body or None, _uniq(images), sections


def _price(page, ld):
    state = widget(page, "webPrice")
    card = money(state.get("cardPrice"))
    regular = money(state.get("price"))
    original = money(state.get("originalPrice"))
    if regular is None:
        regular = money(g(ld, "offers", "price"))
    lowest = card if card is not None else regular
    return {
        "amount": regular,                    # without an Ozon card
        "card_amount": card,                  # with an Ozon card (what listings show)
        "original_amount": original,          # before discount
        # floored like Ozon's own "−49%" badge (card price vs original)
        "discount_percent": int((original - lowest) * 100 / original) if (lowest and original and original > lowest) else None,
        "currency": g(ld, "offers", "priceCurrency") or CURRENCY,
    }


def _available(page, ld):
    state = widget(page, "webPrice")
    if "isAvailable" in state:
        return bool(state.get("isAvailable"))
    offer = g(widget(page, "webSale"), "offer")
    if isinstance(offer, dict) and "isAvailable" in offer:
        return bool(offer.get("isAvailable"))
    avail = g(ld, "offers", "availability") or ""
    if avail:
        return avail.endswith("InStock")
    if widgets(page, "webOutOfStock"):
        return False
    return None


def _videos(page):
    out = []
    for v in as_list(widget(page, "webGallery").get("videos")):
        if as_dict(v).get("url"):
            out.append({"link": v["url"], "cover": v.get("coverUrl"), "name": text(v.get("name"))})
    return out


def _brand(page, ld):
    """Brand name (JSON-LD), its id from a brand breadcrumb
    (/category/<cat>-<id>/<brand>-<brand id>/), and webBrand's trust flags."""
    name = text(ld.get("brand")) or None
    state = widget(page, "webBrand")
    verified = None
    for item in as_list(g(state, "content", "description", "content", "text")):
        if text(as_dict(item).get("content")) == "Бренд проверен":
            verified = True
    brand_id = None
    for crumb in as_list(widget(page, "breadCrumbs").get("breadcrumbs")):     # raw: breadcrumbs() drops this one
        match = re.search(r"/category/[^/]+/[^/?#]*-(\d+)/?$", as_dict(crumb).get("link") or "")
        label = text(crumb.get("text"))
        if match and label and name and label.lower() == name.lower():
            brand_id = int(match.group(1))
    if not (name or state):
        return None
    return {"name": name, "id": brand_id, "link": refs.brand_link(brand_id) if brand_id else None,
            "is_verified": verified,
            "is_original": (text(g(state, "params", "title")) == "Оригинал") if state else None}


def parse_product(page1, page2=None):
    """The product page (+ its second layout page) -> the product record."""
    ld = json_ld(page1)
    crumbs = breadcrumbs(page1)
    sku = to_int(analytics(page1).get("sku")) or to_int(ld.get("sku")) or to_int(widget(page1, "webDetailSKU").get("copyText"))
    link = canonical_link(page1) or widget(page1, "webProductMainWidget").get("url")
    score = widget(page1, "webReviewProductScore")
    questions = text(widget(page1, "webQuestionCount").get("text"))
    description, description_images, sections = _description(page2, ld)
    best = widget(page1, "webBestSeller")
    duty = widget(page1, "webIconWithText")
    duty_amount = None
    if g(duty, "params", "mode") == "customsDuty":
        duty_amount = money(_rich_text(duty.get("textRs")))
    hashtags = []
    for state in widgets(page2, "webHashtags") if page2 else []:
        hashtags += [text(b.get("text")) for b in as_list(state.get("badges")) if text(as_dict(b).get("text"))]
    images = _uniq(as_dict(i).get("src") for i in as_list(widget(page1, "webGallery").get("images")))
    reviews_count = to_int(score.get("reviewsCount"))
    if reviews_count is None and score:
        reviews_count = count(g(score, "constants", "reviewsTextExist"))
    record = {
        "sku": sku,
        "name": text(widget(page1, "webProductHeading").get("title")) or text(ld.get("name")),
        "link": refs.product_link(sku, link) if sku else refs.absolute(link),
        "brand": _brand(page1, ld),
        "category": crumbs[-1] if crumbs else None,
        "breadcrumbs": crumbs,
        "price": _price(page1, ld),
        "is_available": _available(page1, ld),
        "rating": rating_value(score.get("totalScore")) or rating_value(g(ld, "aggregateRating", "ratingValue")),
        "reviews_count": reviews_count if reviews_count is not None else to_int(g(ld, "aggregateRating", "reviewCount")),
        "questions_count": count(questions) if questions and any(ch.isdigit() for ch in questions) else (0 if questions else None),
        "image": images[0] if images else (ld.get("image") or None),
        "images": images or ([ld["image"]] if ld.get("image") else []),
        "videos": _videos(page1),
        "description": description,
        "description_images": description_images,
        "description_sections": sections,
        "characteristics": _characteristics(page1, page2),
        "variants": _variants(page1),
        "seller": _seller(page1),
        "other_offers": {"count": to_int(best.get("count")), "lowest_price": money(_rich_text(best.get("textRs")))}
        if best else None,
        "customs_duty_estimate": duty_amount,
        "model_info": _rich_text(widget(page1, "webModelParams").get("textRs")),
        "labels": [text(g(lab, "badge", "text")) for lab in as_list(widget(page1, "webMarketingLabels").get("labels"))
                   if text(g(lab, "badge", "text"))],
        "has_price_drop": bool(widgets(page1, "webPriceDecreasedCompact")),
        "hashtags": hashtags,
    }
    return record


def product_not_found(page):
    """Unknown SKU: the pdp page answers its `error` widget instead of the product."""
    title, _ = error_widget(page)
    return page_type(page) == "pdp" and bool(title) and not widgets(page, "webProductHeading")


def is_out_of_stock_redirect(page):
    """Without oos_search=false Ozon swaps an out-of-stock PDP for a search
    page pinning the product (webOutOfStock); fetch.py always asks with it."""
    return page_type(page) == "search" and bool(widgets(page, "webOutOfStock"))


# ---- reviews -------------------------------------------------------------------------

def _review(r, products):
    r = as_dict(r)
    content = as_dict(r.get("content"))
    author = as_dict(r.get("author"))
    variant_sku = to_int(r.get("itemId"))
    variant = as_dict(products.get(str(r.get("itemId")))) if r.get("itemId") is not None else {}
    replies = []
    for c in as_list(g(r, "comments", "list")):
        c = as_dict(c)
        replies.append({
            "id": c.get("uuid") or c.get("id"),
            "text": multiline(c.get("text") or c.get("comment") or g(c, "content", "comment")),
            "author": text(g(c, "author", "firstName") or g(c, "author", "name")
                           or g(c, "author", "clientOfficial", "name")),
            "is_official": bool(g(c, "author", "clientOfficial", "name") or g(c, "author", "officialUser")),
            "published_at": epoch_iso(c.get("publishedAt") or c.get("createdAt")),
        })
    is_anonymous = bool(r.get("isAnonymous"))
    return {
        "id": r.get("uuid"),
        "rating": to_int(content.get("score")),
        "text": multiline(content.get("comment")),
        "pros": multiline(content.get("positive")),
        "cons": multiline(content.get("negative")),
        "published_at": epoch_iso(r.get("publishedAt") or r.get("createdAt")),
        "updated_at": epoch_iso(r.get("updatedAt")),
        "author": {
            "name": None if is_anonymous else text(author.get("firstName")) or text(author.get("fio")),
            "avatar": author.get("avatarUrl") or None,
            "is_anonymous": is_anonymous,
        },
        "variant": {
            "sku": variant_sku,
            "name": text(variant.get("name")),
            "link": refs.product_link(variant_sku, variant.get("uri")) if variant_sku else None,
            "attributes": [{"name": text(a.get("name")), "value": text(a.get("value"))}
                           for a in as_list(variant.get("variants")) if text(as_dict(a).get("name"))],
        },
        "photos": _uniq(as_dict(p).get("url") for p in as_list(content.get("photos"))),
        "videos": [{"link": v.get("url"), "cover": v.get("previewUrl"), "duration_seconds": _duration(v.get("duration"))}
                   for v in as_list(content.get("videos")) if as_dict(v).get("url")],
        "survey": [{"question": text(q.get("question")), "answer": text(q.get("answer"))}
                   for q in as_list(content.get("contextQuestions")) if text(as_dict(q).get("question"))],
        "helpful_count": to_int(g(r, "usefulness", "useful")),
        "unhelpful_count": to_int(g(r, "usefulness", "unuseful")),
        "is_outdated": text(g(r, "badgeDelivery", "text")) == "Отзыв устарел",
        "replies": replies,
        "language": r.get("Lang") or None,
    }


def _duration(value):
    """'00:14' / '1:02:03' -> seconds."""
    parts = [to_int(p) for p in str(value or "").split(":") if p.strip()]
    if not parts or any(p is None for p in parts):
        return None
    total = 0
    for p in parts:
        total = total * 60 + p
    return total


def parse_reviews(page):
    """A /reviews/ page -> {product, summary, results, page, per_page, total}."""
    state = widget(page, "webListReviews")
    title = widget(page, "reviewsTitle")
    score = widget(page, "webReviewProductScore")
    paging = as_dict(state.get("paging"))
    products = as_dict(state.get("products"))
    sku = to_int(title.get("productId")) or to_int(state.get("itemId")) or to_int(analytics(page).get("sku"))
    distribution = {}
    for row in as_list(score.get("score")):
        match = re.match(r"\s*([1-5])\b", str(as_dict(row).get("title") or ""))   # "5 звёзд"
        if match:
            distribution[match.group(1)] = to_int(row.get("value"))
    total = to_int(paging.get("total"))
    if total is None:
        total = to_int(score.get("reviewsCount")) or to_int(title.get("reviewsTotal"))
    return {
        "product": {"sku": sku, "name": text(title.get("productName")),
                    "link": refs.product_link(sku, title.get("productUrl")) if sku else None},
        "rating": rating_value(score.get("totalScore")) or rating_value(state.get("productScore")),
        "reviews_count": total,
        "rating_distribution": distribution or None,
        "results": [_review(r, products) for r in as_list(state.get("reviews"))],
        "page": to_int(paging.get("page")),
        "per_page": to_int(paging.get("perPage")) or REVIEWS_PER_PAGE,
        "total": total,
    }


def reviews_state(page):
    """'ok' | 'past_end' (a page beyond the last: the product's score
    widgets render, the review list does not) | 'none' (product exists, no
    reviews) | 'not_found' (unknown SKU)."""
    if widgets(page, "webListReviews"):
        return "ok"
    title, subtitle = error_widget(page)
    if title and subtitle and "нет отзывов" in subtitle:
        return "none"
    if title:
        return "not_found"
    if widgets(page, "reviewsTitle") or widgets(page, "webReviewProductScore"):
        return "past_end"
    return "none"


# ---- questions -----------------------------------------------------------------------

def _anchor(value):
    """'<a href="…/question/<uuid>">Text</a>' -> (text, link)."""
    raw = value or ""
    match = re.search(r'href="([^"]+)"', raw)
    return _strip_html(raw), (refs.absolute(match.group(1)) if match else None)


_MASKED_AUTHOR = ("предпочёл скрыть", "предпочел скрыть")


def _qa_author(block):
    name = text(g(block, "author", "name", "text"))
    if name and any(m in name.lower() for m in _MASKED_AUTHOR):
        name = None
    return name


def _reaction_counts(reactions):
    likes = dislikes = None
    for r in as_list(reactions):
        params = as_dict(g(r, "common", "action", "params"))
        if params.get("likesCount") is not None:
            likes = to_int(params.get("likesCount"))
        if params.get("dislikesCount") is not None:
            dislikes = to_int(params.get("dislikesCount"))
    return likes, dislikes


def parse_questions(page):
    """A /questions/ page (or a cursor follow-up) -> {results, next}."""
    state = widget(page, "webPDPListQuestions")
    products = as_dict(state.get("products"))
    results = []
    for q in as_list(state.get("questions")):
        q = as_dict(q)
        body, link = _anchor(g(q, "text", "text"))
        q_likes, _ = _reaction_counts(q.get("reactions"))
        answers = []
        for a in as_list(q.get("answers")):
            a = as_dict(a)
            likes, dislikes = _reaction_counts(a.get("reactions"))
            answers.append({
                "id": a.get("answerUuid"),
                "text": _strip_html(g(a, "text", "text")),
                "published_date": ru_date(g(a, "createdAt", "text")),
                "author": {"name": _qa_author(a), "avatar": g(a, "author", "avatarUrl")},
                "helpful_count": likes,
                "unhelpful_count": dislikes,
            })
        more = count(g(q, "loadMoreAnswers", "title")) or 0
        variant_sku = to_int(q.get("itemId"))
        variant = as_dict(products.get(str(q.get("itemId"))))
        results.append({
            "id": q.get("questionUuid"),
            "text": body,
            "link": link,
            "published_date": ru_date(g(q, "createdAt", "text")),
            "author": {"name": _qa_author(q)},
            "helpful_count": q_likes,
            "variant": {"sku": variant_sku, "name": text(g(variant, "name", "text")),
                        "link": refs.product_link(variant_sku, variant.get("url")) if variant_sku else None},
            "answers_count": len(answers) + more,
            "answers": answers,
        })
    return {"results": results, "next": next_page_link(page) if results else None}


def questions_state(page):
    """'ok' | 'none' (product exists, no questions) | 'not_found'."""
    if widgets(page, "webPDPListQuestions"):
        return "ok"
    title, _ = error_widget(page)
    if title:
        return "not_found"
    return "none"


# ---- seller --------------------------------------------------------------------------

def parse_seller_page(page):
    """The storefront page header (sellerTransparency) -> seller fields."""
    state = widget(page, "sellerTransparency")
    info = analytics(page)
    out = {"id": to_int(info.get("sellerId")), "name": text(g(state, "title", "text")),
           "slug": _seller_slug(page_url(page)), "logo": g(state, "logoImage", "backgroundImage"),
           "rating": None, "reviews_count": None, "orders_count": None, "followers_count": None,
           "is_premium": False, "has_storefront": bool(state)}
    for badge in as_list(state.get("badges")):
        badge = as_dict(badge)
        icon, label = badge.get("leftIcon") or "", text(badge.get("text")) or ""
        if "premium" in icon:
            out["is_premium"] = True
        elif icon == "ic_m_star_filled":
            out["rating"] = rating_value(label)
        elif icon == "ic_m_speech_bubble_filled":
            out["reviews_count"] = count(label)
        elif icon == "ic_m_box_filled":
            out["orders_count"] = count(label)
    for button in as_list(state.get("buttons")):
        fav = as_dict(as_dict(button).get("favoriteButton"))
        if fav:
            out["followers_count"] = count(g(fav, "favoriteButton", "button", "title"))
    if not out["name"]:
        title = _seo_title(page) or ""
        out["name"] = text(re.split(r"\s+[–—-]\s+", title, maxsplit=1)[0]) if title else None
    return out


def seller_not_found(page):
    return not widgets(page, "sellerTransparency") and not _seo_title(page)


def parse_seller_modal(page):
    """/modal/shop-in-shop-info -> legal text + the stats cells + verified brands."""
    out = {"legal_name": None, "legal_address": None, "registration_number": None, "country_code": None,
           "is_honest_sign_registered": False, "working_hours": None, "orders_count": None,
           "with_ozon_since_text": None, "rating": None, "reviews_count": None, "is_premium": False,
           "verified_brands": []}
    for state in widgets(page, "textBlock"):
        for atom in as_list(state.get("body")):
            raw = g(atom, "textAtom", "text") or ""
            if raw.strip() in ("О магазине", "Проверенные бренды магазина"):
                continue
            if raw.lower().startswith("режим работы"):
                out["working_hours"] = re.sub(r"^режим работы\s*[—–-]\s*", "", raw, flags=re.I).strip() or None
                continue
            lines = [text(x) for x in re.split(r"<br\s*/?>", raw) if text(x)]
            legal, _ = _split_legal(lines)
            for key, value in legal.items():
                if value:
                    out[key] = value
    for state in widgets(page, "cellList"):
        for cell in as_list(state.get("cells")):
            body = as_dict(as_dict(cell).get("dsCell"))
            title = text(g(body, "centerBlock", "title", "text")) or ""
            value = text(g(body, "rightBlock", "badge", "text"))
            link = g(body, "common", "action", "link")
            if title == "Premium магазин":
                out["is_premium"] = True
            elif title == "Заказов":
                out["orders_count"] = count(value)
            elif title == "Работает с Ozon":
                out["with_ozon_since_text"] = value
            elif title == "Средняя оценка товаров":
                out["rating"] = rating_value((value or "").split(" ")[0])
            elif title == "Количество отзывов":
                out["reviews_count"] = count(value)
            elif link and "/brand/" in link:
                out["verified_brands"].append({
                    "id": refs.id_from_slug_path(link, "brand"), "name": title or None,
                    "logo": g(body, "leftBlock", "icon", "backgroundImage"),
                    "link": refs.absolute(link)})
    return out


def months_with_ozon(label):
    """'7 месяцев' / '8 лет' / '1 год' -> months (int); junk -> None."""
    label = (label or "").lower()
    number = count(label)
    if number is None:
        return None
    if "год" in label or "лет" in label:
        return number * 12
    if "месяц" in label:
        return number
    return None


# ---- brand ---------------------------------------------------------------------------

def parse_brand_header(page):
    state = widget(page, "sellerTransparency")
    followers = None
    for button in as_list(state.get("buttons")):
        fav = as_dict(as_dict(button).get("favoriteButton"))
        if fav:
            followers = count(g(fav, "favoriteButton", "button", "title"))
    return {"id": to_int(analytics(page).get("brandId")), "name": text(g(state, "title", "text")),
            "logo": g(state, "logoImage", "backgroundImage"), "followers_count": followers}


def brand_not_found(page):
    header = widget(page, "sellerTransparency")
    return not text(g(header, "title", "text")) and not _seo_title(page)


# ---- suggestions ---------------------------------------------------------------------

def parse_suggestions(page):
    out = []
    for state in widgets(page, "webSuggestions"):
        for item in as_list(state.get("items")):
            item = as_dict(item)
            body = as_dict(item.get(item.get("type") or ""))
            link = g(body, "common", "action", "link") or ""
            label = text(g(body, "centerBlock", "title", "text"))
            if not label:
                continue
            if link.startswith("/category/"):
                kind, ident = "category", refs.category_id_from_path(link)
            elif link.startswith("/brand/"):
                kind, ident = "brand", refs.id_from_slug_path(link, "brand")
            elif link.startswith("/product/"):
                match = re.search(r"(\d{3,12})/?(?:\?|$)", link)
                kind, ident = "product", to_int(match.group(1)) if match else None
            else:
                kind, ident = "query", None
            out.append({
                "text": label,
                "type": kind,
                "id": ident,
                "parent": text(g(body, "centerBlock", "subtitle", "text")) if kind == "category" else None,
                "image": g(body, "leftBlock", "image", "image"),
                "link": refs.absolute(link) if link else None,
            })
    return out


# ---- categories ----------------------------------------------------------------------

def parse_root_categories(page):
    """catalogMenu (present on every page) -> the top-level categories."""
    out = []
    for cat in as_list(widget(page, "catalogMenu").get("categories")):
        cat = as_dict(cat)
        url = cat.get("url") or ""
        if not url.startswith("/category/"):
            continue
        out.append({"id": to_int(cat.get("id")) or refs.category_id_from_path(url), "name": text(cat.get("title")),
                    "link": refs.category_link(url), "image": cat.get("image")})
    return out


def parse_category_children(payload):
    """getCatalogFilterValues {categories: [{title, level, isActive, urlValue}]}
    -> (path incl. the current category, children)."""
    path, children = [], []
    for cat in as_list(as_dict(payload).get("categories")):
        cat = as_dict(cat)
        url = (cat.get("urlValue") or "").split("?")[0]
        if not url.startswith("/category/"):
            continue
        row = {"id": refs.category_id_from_path(url), "name": text(cat.get("title")), "link": refs.category_link(url)}
        if cat.get("level") == 0:
            path.append(dict(row, is_current=bool(cat.get("isActive"))))
        else:
            children.append(row)
    return path, children
