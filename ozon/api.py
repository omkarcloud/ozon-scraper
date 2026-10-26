"""The /ozon/* endpoint functions (route_glue's route_table calls them with
the schema's loaded kwargs). Caching happens here (cache.cached_call keyed
on the validated params), tofler/allegro-style:

  * one upstream page = one cache row; a product whose second layout page
    failed is served but not cached (DontCache), so the next call retries it
  * questions walk Ozon's page_key cursor: every cached questions page keeps
    the cursor to the next one, so page N costs one fetch when page N-1 was
    asked for recently, and N fetches cold (capped by the schema)
  * paged endpoints return a `pagination` block for route_glue.paginate;
    listings publish no total, so they set has_next and leave the totals null
"""
import math

from cache import DontCache, cached_call
from ozon import cache_config as ttl
from ozon import fetch, parsers
from ozon.fetch import OzonNotFound
from ozon.refs import (DEFAULT_QUESTION_SORT, DEFAULT_REVIEW_SORT, DEFAULT_SORT, QUESTION_SORTS, REVIEW_SORTS,
                       SORTS, brand_link, category_link, product_link, seller_link)


def _listing_pagination(page, results, has_next):
    return {"page": page, "items_per_page": len(results) or None, "total_pages": None, "total_count": None,
            "has_next": bool(has_next)}


def _listing_body(parsed, page, sort):
    return {
        "sort": sort,
        "results": parsed["results"],
        "facets": parsed["facets"],
        "pagination": _listing_pagination(page, parsed["results"], parsed["has_next"]),
    }


# ---- products/search -----------------------------------------------------------------

def _products_search(query, page, sort, min_price, max_price, category):
    raw = fetch.fetch_search(query, page=page, sort=SORTS[sort], min_price=min_price, max_price=max_price,
                             category=category)
    if category and parsers.listing_not_found(raw):
        raise OzonNotFound(f"category {category} not found")
    parsed = parsers.parse_listing(raw)
    return {
        "query": query,
        # Ozon resolves most queries into a category (and often a brand) and
        # lists that; null when the results stayed a plain search
        "category": parsed["category"],
        "category_path": parsed["category_path"],
        "brand_id": parsed["brand_id"],
        **_listing_body(parsed, page, sort),
    }


def products_search(**data):
    return cached_call("ozon.search", data, _products_search, ttl.LISTING_CACHE)


# ---- products/details ----------------------------------------------------------------

def _product_details(product):
    page1, page2 = fetch.fetch_product(product)
    record = parsers.parse_product(page1, page2)
    return DontCache(record) if page2 is None else record


def products_details(**data):
    return cached_call("ozon.product", data, _product_details, ttl.PRODUCT_CACHE)


# ---- products/reviews ----------------------------------------------------------------

def _product_reviews(product, page, sort):
    raw = fetch.fetch_reviews(product, page=page, sort=REVIEW_SORTS[sort])
    state = parsers.reviews_state(raw)
    if state == "not_found":
        raise OzonNotFound(f"product {product} not found")
    if state == "none":
        return {
            "product": {"sku": product, "name": None, "link": product_link(product)},
            "rating": None, "reviews_count": 0, "rating_distribution": None, "sort": sort, "results": [],
            "pagination": {"page": page, "items_per_page": None, "total_pages": 0, "total_count": 0},
        }
    parsed = parsers.parse_reviews(raw)             # 'ok', or 'past_end' (score widgets, no list)
    per_page = parsed["per_page"]
    total = parsed["total"]
    total_pages = math.ceil(total / per_page) if (total is not None and per_page) else None
    results = parsed["results"]
    if total_pages is not None and page > total_pages:
        results = []              # past the end Ozon repeats its last page, or drops the list
    return {
        "product": parsed["product"],
        "rating": parsed["rating"],
        "reviews_count": total,
        "rating_distribution": parsed["rating_distribution"],
        "sort": sort,
        "results": results,
        "pagination": {"page": page, "items_per_page": per_page, "total_pages": total_pages, "total_count": total},
    }


def products_reviews(**data):
    return cached_call("ozon.reviews", data, _product_reviews, ttl.REVIEWS_CACHE)


# ---- products/questions --------------------------------------------------------------

def _questions_page(product, sort, page):
    """One cached questions page {results, next, state}; page N>1 follows the
    cursor of (cached) page N-1."""
    if page == 1:
        raw = fetch.fetch_questions(product, sort=QUESTION_SORTS[sort])
        state = parsers.questions_state(raw)
        if state == "not_found":
            raise OzonNotFound(f"product {product} not found")
        if state == "none":
            return {"results": [], "next": None}
        return parsers.parse_questions(raw)
    previous = _questions_record(product, sort, page - 1)
    if not previous.get("next"):
        return {"results": [], "next": None}            # past the end: an empty page
    return parsers.parse_questions(fetch.fetch_questions(product, cursor=previous["next"]))


def _questions_record(product, sort, page):
    return cached_call("ozon.questions_page", {"product": product, "sort": sort, "page": page},
                       _questions_page, ttl.QUESTIONS_CACHE)


def products_questions(product, page, sort):
    record = _questions_record(product, sort, page)
    return {
        "product": {"sku": product, "link": product_link(product)},
        "sort": sort,
        "results": record["results"],
        "pagination": {"page": page, "items_per_page": len(record["results"]) or None,
                       "total_pages": None, "total_count": None, "has_next": bool(record.get("next"))},
    }


# ---- categories/products ---------------------------------------------------------------

def _category_products(category, page, sort, min_price, max_price):
    raw = fetch.fetch_category(category, page=page, sort=SORTS[sort], min_price=min_price, max_price=max_price)
    if parsers.listing_not_found(raw):
        raise OzonNotFound(f"category {category} not found")
    parsed = parsers.parse_listing(raw)
    return {
        "category": parsed["category"] or {"id": None, "name": parsed["title"], "link": category_link(category)},
        "category_path": parsed["category_path"],
        **_listing_body(parsed, page, sort),
    }


def categories_products(**data):
    return cached_call("ozon.category", data, _category_products, ttl.LISTING_CACHE)


# ---- categories/list -----------------------------------------------------------------

def _categories(category):
    if not category:
        roots = parsers.parse_root_categories(fetch.fetch_catalog())
        return {"category": None, "path": [], "subcategories": roots}
    path, children = parsers.parse_category_children(fetch.fetch_category_children(category))
    current = next((c for c in path if c["is_current"]), None)
    if current is None:
        raise OzonNotFound(f"category {category} not found")
    return {
        "category": {"id": current["id"], "name": current["name"], "link": current["link"]},
        "path": [{k: c[k] for k in ("id", "name", "link")} for c in path if not c["is_current"]],
        "subcategories": [dict(c, image=None) for c in children],
    }


def categories_list(**data):
    return cached_call("ozon.categories", data, _categories, ttl.CATEGORIES_CACHE)


# ---- brands/products -----------------------------------------------------------------

def _brand_products(brand, page, sort):
    raw = fetch.fetch_brand(brand, page=page, sort=SORTS[sort])
    if parsers.brand_not_found(raw):
        raise OzonNotFound(f"brand {brand} not found")
    header = parsers.parse_brand_header(raw)
    parsed = parsers.parse_listing(raw)
    brand_id = header["id"] or brand
    return {
        "brand": {"id": brand_id, "name": header["name"], "link": brand_link(brand_id, parsers.page_url(raw)),
                  "logo": header["logo"], "followers_count": header["followers_count"]},
        **_listing_body(parsed, page, sort),
    }


def brands_products(**data):
    return cached_call("ozon.brand", data, _brand_products, ttl.LISTING_CACHE)


# ---- sellers/details -----------------------------------------------------------------

def _seller_details(seller):
    page = fetch.fetch_seller_page(seller)
    if parsers.seller_not_found(page):
        raise OzonNotFound(f"seller {seller} not found")
    head = parsers.parse_seller_page(page)
    seller_id = head["id"] or (int(seller) if seller.isdigit() else None)
    modal = parsers.parse_seller_modal(fetch.fetch_seller_modal(seller_id)) if seller_id else {}
    slug = head["slug"] or seller
    return {
        "id": seller_id,
        "name": head["name"],
        "slug": slug,
        "link": seller_link(slug),
        "logo": head["logo"],
        "is_premium": bool(head["is_premium"] or modal.get("is_premium")),
        # False when Ozon shows "Магазин не нашёлся" on the storefront of a
        # seller whose legal record still exists (closed / paused storefront)
        "has_storefront": head["has_storefront"],
        "rating": head["rating"] if head["rating"] is not None else modal.get("rating"),
        "reviews_count": head["reviews_count"] if head["reviews_count"] is not None else modal.get("reviews_count"),
        "orders_count": head["orders_count"] if head["orders_count"] is not None else modal.get("orders_count"),
        "followers_count": head["followers_count"],
        "months_on_ozon": parsers.months_with_ozon(modal.get("with_ozon_since_text")),
        "legal": {
            "name": modal.get("legal_name"),
            "address": modal.get("legal_address"),
            "registration_number": modal.get("registration_number"),
            "country_code": modal.get("country_code"),
            "is_honest_sign_registered": modal.get("is_honest_sign_registered"),
        },
        "working_hours": modal.get("working_hours"),
        "verified_brands": modal.get("verified_brands") or [],
    }


def sellers_details(**data):
    return cached_call("ozon.seller", data, _seller_details, ttl.SELLER_CACHE)


# ---- sellers/products ----------------------------------------------------------------

def _seller_products(seller, page, sort, query):
    raw = fetch.fetch_seller_products(seller, page=page, sort=SORTS[sort], query=query)
    if parsers.seller_not_found(raw) or parsers.listing_not_found(raw):
        raise OzonNotFound(f"seller {seller} not found")
    head = parsers.parse_seller_page(raw)
    parsed = parsers.parse_listing(raw)
    slug = head["slug"] or seller
    return {
        "seller": {"id": head["id"], "name": head["name"], "slug": slug, "link": seller_link(slug)},
        "query": query,
        **_listing_body(parsed, page, sort),
    }


def sellers_products(**data):
    return cached_call("ozon.seller_products", data, _seller_products, ttl.LISTING_CACHE)


# ---- search/suggestions --------------------------------------------------------------

def _suggestions(query):
    return {"query": query, "results": parsers.parse_suggestions(fetch.fetch_suggestions(query))}


def search_suggestions(**data):
    return cached_call("ozon.suggestions", data, _suggestions, ttl.SUGGESTIONS_CACHE)
