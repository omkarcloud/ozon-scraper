"""The 10 Ozon endpoints. Every path is served with and without the `/ozon`
prefix, so code generated against the hosted API on RapidAPI (paths like
/products/details) runs unchanged against this server.

Each route validates its query with the schema in ozon/schemas.py (the same
schemas the hosted API uses), calls ozon/api.py and, for paged endpoints,
returns the flat pagination block (count / per_page / current_page /
total_pages / next / previous) with links back to this server."""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from ozon import api, schemas
from schema_fields import load_query
from scraper_errors import BadRequest, NotFound


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "носки" would arrive garbled)."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page_link(params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "", False)}
    query["page"] = page
    scheme, host = request.urlparts.scheme, request.urlparts.netloc
    return f"{scheme}://{host}{request.path}?{urlencode(query, doseq=True)}"


def paginate(result, raw_params):
    """Lift the result's `pagination` block into the flat shape. Ozon
    publishes no totals for listings: `has_next` drives the next link and
    total_pages / count stay null."""
    pagination = result.pop("pagination", None) or {}
    page = _as_int(pagination.get("page")) or _as_int(raw_params.get("page")) or 1
    if "has_next" in pagination:
        has_next = bool(pagination["has_next"])
        total_pages = pagination.get("total_pages")
    else:
        total_pages = max(_as_int(pagination.get("total_pages")), 0)
        has_next = page < total_pages
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(raw_params, page + 1 if has_next else None),
        "previous": _page_link(raw_params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def call(label, schema, impl, paginated=False):
    """Validate -> run -> map errors: bad params 400, missing record 404,
    everything else (retries exhausted, Antibot refused) 500."""
    raw = query_dict()
    data, error = load_query(schema, raw)
    if error:
        return json_response(error, 400)
    try:
        result = impl(**data)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"ozon rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:
        return json_response({"error": f"ozon {label} failed: {e}"}, 500)
    if paginated:
        result = paginate(result, raw)
    return json_response(result)


ENDPOINTS = [
    ("/products/details", schemas.ProductSchema, api.products_details, False),
    ("/products/search", schemas.ProductsSearchSchema, api.products_search, True),
    ("/search/suggestions", schemas.SuggestionsSchema, api.search_suggestions, False),
    ("/products/reviews", schemas.ProductReviewsSchema, api.products_reviews, True),
    ("/products/questions", schemas.ProductQuestionsSchema, api.products_questions, True),
    ("/categories/products", schemas.CategoryProductsSchema, api.categories_products, True),
    ("/categories/list", schemas.CategoriesListSchema, api.categories_list, False),
    ("/brands/products", schemas.BrandProductsSchema, api.brands_products, True),
    ("/sellers/details", schemas.SellerSchema, api.sellers_details, False),
    ("/sellers/products", schemas.SellerProductsSchema, api.sellers_products, True),
]


def mount(path, schema, impl, paginated):
    """Serve one endpoint at /path and /ozon/path."""
    def handler():
        return call(path.strip("/"), schema, impl, paginated)
    handler.__name__ = "ozon_" + path.strip("/").replace("/", "_")
    route(path, method="GET")(handler)
    route("/ozon" + path, method="GET")(handler)


for _path, _schema, _impl, _paginated in ENDPOINTS:
    mount(_path, _schema, _impl, _paginated)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, *_ in ENDPOINTS]})
