"""Reference resolvers, sort tables and link builders for /ozon/*.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair): each resolver takes a bare id OR any Ozon link for the
same record and returns what fetch.py needs; it raises ValueError with a
user-facing message (schema_fields.RefField turns that into a 400).

Identifier shapes (captured 2026-10-24):
  * product   the SKU ("Артикул"), 3-12 digits. Links: /product/<slug>-<sku>/,
              /product/<sku>/, any /reviews/ or /questions/ sub-page, the old
              /context/detail/id/<sku>/ form. Every Ozon storefront host
              (ozon.ru, ozon.kz, ozon.by, uz.ozon.com, am.ozon.com) shares
              the SKU space (seo hreflang alternates), so their links are
              accepted and fetched from www.ozon.ru.
  * category  digits. Links /category/<slug>-<id>/[<brand>-<brand id>/].
              SEO collections (/category/smartfon-apple-iphone18/) carry no
              id: the path itself is kept and fetched as is.
  * brand     digits. Links /brand/<slug>-<id>/ (a bare /brand/<id>/ serves
              the same page).
  * seller    a numeric seller id OR the storefront slug ("mirnyy-atom").
              Links /seller/<slug or id>/[...]. /seller/<id>/ resolves to the
              slug page; the numeric id the info modal needs comes from the
              page itself (pageInfo.analyticsInfo.sellerId).

Short links (ozon.ru/t/<code>) are redirects that need a network round trip
and are rejected with a message asking for the full link.
"""
import re
from urllib.parse import urlparse

SITE = "https://www.ozon.ru"
CURRENCY = "RUB"

_HOSTS = ("ozon.ru", "ozon.kz", "ozon.by", "ozon.com", "ozon.uz")

SKU_RE = re.compile(r"^\d{1,12}$")
ID_RE = re.compile(r"^\d{1,12}$")
SELLER_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-_.]{0,80}$", re.I)

_PRODUCT_LINK_RE = re.compile(r"/product/(?:[^/?#]*-)?(\d{3,12})(?:[/?#]|$)")
_OLD_PRODUCT_LINK_RE = re.compile(r"/context/detail/id/(\d{3,12})(?:[/?#]|$)")
_CATEGORY_LINK_RE = re.compile(r"/category/([^/?#]+)")
_BRAND_LINK_RE = re.compile(r"/brand/(?:[^/?#]*-)?(\d{1,12})(?:[/?#]|$)")
_SELLER_LINK_RE = re.compile(r"/seller/([^/?#]+)")
_TRAILING_ID_RE = re.compile(r"(?:^|-)(\d{1,12})$")

# Public sort value -> Ozon's `sorting` token (the searchResultsSort widget's
# option links, 2026-10-24). popular/newest/rating pages hold 8 products,
# price/discount pages 36 (Ozon's own page sizes; one page = one call).
SORTS = {
    "popular": "score",
    "newest": "new",
    "price_asc": "price",
    "price_desc": "price_desc",
    "rating": "rating",
    "discount": "discount",
}
DEFAULT_SORT = "popular"

# /reviews/?sort= (webListReviews.sortings)
REVIEW_SORTS = {
    "most_helpful": "usefulness_desc",
    "highest_rating": "score_desc",
    "lowest_rating": "score_asc",
}
DEFAULT_REVIEW_SORT = "most_helpful"

# /questions/?qsort= (webPDPListQuestions.sorting.options)
QUESTION_SORTS = {
    "most_helpful": "usefulness_desc",
    "newest": "created_at_desc",
    "answered_first": "has_answers_desc",
    "unanswered_first": "has_answers_asc",
}
DEFAULT_QUESTION_SORT = "most_helpful"


# ---- link parsing ------------------------------------------------------------------

def _is_link(value):
    return value.startswith(("http://", "https://", "//")) or value.startswith(("ozon.", "www.ozon."))


def _parse_link(value):
    url = value
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith(("http://", "https://")):
        url = "https://" + url
    host = (urlparse(url).hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in _HOSTS):
        raise ValueError("Must be an ozon.ru link (or another Ozon storefront: ozon.kz, ozon.by, uz.ozon.com).")
    if re.match(r"^/t/[^/]+/?$", urlparse(url).path or ""):
        raise ValueError("Short ozon.ru/t/ links are not supported; open it and pass the full product link.")
    return url


def resolve_product(value):
    """SKU or product link -> the SKU as an int."""
    value = (value or "").strip()
    if SKU_RE.match(value):
        return int(value)
    if _is_link(value):
        url = _parse_link(value)
        match = _PRODUCT_LINK_RE.search(url) or _OLD_PRODUCT_LINK_RE.search(url)
        if match:
            return int(match.group(1))
        raise ValueError("Must be an Ozon product link (https://www.ozon.ru/product/<name>-<sku>/).")
    raise ValueError("Must be an Ozon product SKU (digits) or a product link.")


def resolve_category(value):
    """Category id or category link -> the category path fetch.py loads:
    "/category/15502/" for an id, "/category/<first segment>/" for a link
    (a brand sub-segment is dropped; an id-less SEO collection keeps its slug)."""
    value = (value or "").strip()
    if ID_RE.match(value):
        return f"/category/{int(value)}/"
    if _is_link(value):
        url = _parse_link(value)
        match = _CATEGORY_LINK_RE.search(url)
        if match and match.group(1).strip("-"):
            return f"/category/{match.group(1)}/"
        raise ValueError("Must be an Ozon category link (https://www.ozon.ru/category/<name>-<id>/).")
    raise ValueError("Must be an Ozon category id (digits) or a category link.")


def resolve_brand(value):
    """Brand id or brand link -> the brand id as an int."""
    value = (value or "").strip()
    if ID_RE.match(value):
        return int(value)
    if _is_link(value):
        url = _parse_link(value)
        match = _BRAND_LINK_RE.search(url)
        if match:
            return int(match.group(1))
        raise ValueError("Must be an Ozon brand link (https://www.ozon.ru/brand/<name>-<id>/).")
    raise ValueError("Must be an Ozon brand id (digits) or a brand link.")


def resolve_seller(value):
    """Seller id, storefront slug or seller link -> the id or slug string
    (what goes after /seller/)."""
    value = (value or "").strip()
    if ID_RE.match(value):
        return str(int(value))
    if _is_link(value):
        url = _parse_link(value)
        match = _SELLER_LINK_RE.search(url)
        if match and SELLER_SLUG_RE.match(match.group(1)):
            return match.group(1).lower()
        raise ValueError("Must be an Ozon seller link (https://www.ozon.ru/seller/<name>/).")
    if SELLER_SLUG_RE.match(value):
        return value.lower()
    raise ValueError("Must be an Ozon seller id, storefront name (mirnyy-atom) or seller link.")


def category_id_from_path(path):
    """"/category/smartfony-15502/" -> 15502; an SEO slug without id -> None."""
    match = _CATEGORY_LINK_RE.search(path or "")
    if not match:
        return None
    seg = match.group(1)
    trailing = _TRAILING_ID_RE.search(seg)
    return int(trailing.group(1)) if trailing else None


def id_from_slug_path(path, kind):
    """The trailing id of a /<kind>/<slug>-<id>/ path; None when absent."""
    match = re.search(rf"/{kind}/([^/?#]+)", path or "")
    if not match:
        return None
    trailing = _TRAILING_ID_RE.search(match.group(1))
    return int(trailing.group(1)) if trailing else None


# ---- link building -----------------------------------------------------------------

_KEEP_QUERY = {"text", "page", "sorting"}


def absolute(path):
    """A site path or link -> an absolute www.ozon.ru link without Ozon's
    per-response tracking params (at, sh, from_sku, oos_search, miniapp,
    perehod, __rr, abt_att, start_page_id, paginator_token, utm_* ...)."""
    if not path or not isinstance(path, str):
        return None
    if path.startswith("ozon://"):
        return None
    url = path if path.startswith(("http://", "https://")) else SITE + ("" if path.startswith("/") else "/") + path
    parts = urlparse(url)
    query = "&".join(p for p in (parts.query or "").split("&")
                     if p and p.split("=", 1)[0] in _KEEP_QUERY)
    return f"{parts.scheme}://{parts.netloc}{parts.path}" + (f"?{query}" if query else "")


def product_link(sku, slug_path=None):
    """Canonical product link: the slugged path when known, else /product/<sku>/."""
    if slug_path:
        clean = absolute(slug_path)
        if clean and re.search(rf"/product/(?:[^/]*-)?{sku}/?$", urlparse(clean).path):
            return clean.split("?")[0]
    return f"{SITE}/product/{sku}/"


def category_link(path_or_id):
    if isinstance(path_or_id, int) or (isinstance(path_or_id, str) and path_or_id.isdigit()):
        return f"{SITE}/category/{int(path_or_id)}/"
    return absolute(path_or_id)


def brand_link(brand_id, slug_path=None):
    if slug_path:
        clean = absolute(slug_path)
        if clean:
            return clean.split("?")[0]
    return f"{SITE}/brand/{brand_id}/"


def seller_link(slug_or_id):
    return f"{SITE}/seller/{slug_or_id}/" if slug_or_id else None
