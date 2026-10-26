"""Offline tests for the /ozon/* request schemas (and the pure URL builders
in ozon/fetch.py they feed).

    python -m pytest ozon/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ozon import fetch, schemas  # noqa: E402
from schema_fields import load_query  # noqa: E402

PRODUCT_LINK = "https://www.ozon.ru/product/apple-smartfon-iphone-18-pro-5792593898/?at=xyz"


def _error(schema, data):
    with pytest.raises(ValidationError) as e:
        schema().load(data)
    return e.value.messages


# ---- products ----------------------------------------------------------------------------

def test_products_search_defaults():
    assert schemas.ProductsSearchSchema().load({"query": "  iphone  17 "}) == {
        "query": "iphone 17", "page": 1, "sort": "popular", "min_price": None, "max_price": None, "category": None}


def test_products_search_full():
    loaded = schemas.ProductsSearchSchema().load({
        "query": "носки", "page": "3", "sort": "Price_Asc", "min_price": "100", "max_price": "500.5",
        "category": "https://www.ozon.ru/category/noski-muzhskie-36563/"})
    assert loaded == {"query": "носки", "page": 3, "sort": "price_asc", "min_price": 100.0, "max_price": 500.5,
                      "category": "/category/noski-muzhskie-36563/"}


@pytest.mark.parametrize("data,field,fragment", [
    ({}, "query", "Missing data"),
    ({"query": "  "}, "query", "Must not be empty"),
    ({"query": "x", "sort": "cheapest"}, "sort", "Must be one of: popular, newest, price_asc"),
    ({"query": "x", "page": "0"}, "page", "greater than or equal to 1"),
    ({"query": "x", "page": "1001"}, "page", "less than or equal to 1000"),
    ({"query": "x", "min_price": "-5"}, "min_price", "greater than or equal to 0"),
    ({"query": "x", "min_price": "900", "max_price": "100"}, "max_price", "min_price must not exceed max_price"),
    ({"query": "x", "category": "smartfony"}, "category", "Must be an Ozon category id"),
    ({"query": "x", "color": "red"}, "color", "Unknown field"),
])
def test_products_search_rejects(data, field, fragment):
    messages = _error(schemas.ProductsSearchSchema, data)
    assert field in messages and fragment in " ".join(messages[field])


@pytest.mark.parametrize("value", ["5792593898", PRODUCT_LINK, "ozon.ru/product/5792593898/reviews/",
                                   "https://ozon.kz/product/x-5792593898/"])
def test_product_accepts_sku_or_link(value):
    assert schemas.ProductSchema().load({"product": value}) == {"product": 5792593898}


@pytest.mark.parametrize("value,fragment", [
    ("iphone", "Must be an Ozon product SKU"),
    ("https://www.amazon.com/dp/B0C", "Must be an ozon.ru link"),
    ("https://ozon.ru/t/xYz12", "Short ozon.ru/t/ links are not supported"),
])
def test_product_rejects(value, fragment):
    assert fragment in " ".join(_error(schemas.ProductSchema, {"product": value})["product"])


def test_product_requires_one_param_not_url_and_id():
    messages = _error(schemas.ProductSchema, {"url": PRODUCT_LINK})
    assert "product" in messages and "url" in messages


def test_reviews_schema():
    assert schemas.ProductReviewsSchema().load({"product": "1574782712"}) == {
        "product": 1574782712, "page": 1, "sort": "most_helpful"}
    assert schemas.ProductReviewsSchema().load({"product": "1574782712", "sort": "LOWEST_RATING", "page": "2"})[
        "sort"] == "lowest_rating"
    messages = _error(schemas.ProductReviewsSchema, {"product": "1574782712", "sort": "newest"})
    assert "Must be one of: most_helpful, highest_rating, lowest_rating" in " ".join(messages["sort"])
    assert "page" in _error(schemas.ProductReviewsSchema, {"product": "1574782712", "page": "2001"})


def test_questions_schema():
    assert schemas.ProductQuestionsSchema().load({"product": PRODUCT_LINK}) == {
        "product": 5792593898, "page": 1, "sort": "most_helpful"}
    assert schemas.ProductQuestionsSchema().load({"product": "5792593898", "sort": "newest"})["sort"] == "newest"
    assert "page" in _error(schemas.ProductQuestionsSchema, {"product": "5792593898", "page": "51"})
    assert "sort" in _error(schemas.ProductQuestionsSchema, {"product": "5792593898", "sort": "oldest"})


# ---- categories / brands / sellers ------------------------------------------------------------

def test_category_products_schema():
    assert schemas.CategoryProductsSchema().load({"category": "15502"}) == {
        "category": "/category/15502/", "page": 1, "sort": "popular", "min_price": None, "max_price": None}
    loaded = schemas.CategoryProductsSchema().load({
        "category": "https://www.ozon.ru/category/smartfony-15502/apple-26303000/", "sort": "discount"})
    assert loaded["category"] == "/category/smartfony-15502/" and loaded["sort"] == "discount"
    assert "category" in _error(schemas.CategoryProductsSchema, {})


def test_categories_list_schema():
    assert schemas.CategoriesListSchema().load({}) == {"category": None}
    assert schemas.CategoriesListSchema().load({"category": "15501"}) == {"category": "/category/15501/"}
    assert "category" in _error(schemas.CategoriesListSchema, {"category": "https://www.ozon.ru/brand/apple-26303000/"})


def test_brand_products_schema():
    assert schemas.BrandProductsSchema().load({"brand": "https://www.ozon.ru/brand/apple-26303000/"}) == {
        "brand": 26303000, "page": 1, "sort": "popular"}
    assert "Must be an Ozon brand id" in " ".join(_error(schemas.BrandProductsSchema, {"brand": "apple"})["brand"])


def test_seller_schemas():
    for value in ("4289687", "mirnyy-atom", "https://www.ozon.ru/seller/mirnyy-atom/"):
        assert schemas.SellerSchema().load({"seller": value})["seller"] in ("4289687", "mirnyy-atom")
    assert schemas.SellerProductsSchema().load({"seller": "Mirnyy-Atom", "query": "iphone"}) == {
        "seller": "mirnyy-atom", "page": 1, "sort": "popular", "query": "iphone"}
    assert "seller" in _error(schemas.SellerSchema, {"seller": "bad seller!"})


def test_suggestions_schema():
    assert schemas.SuggestionsSchema().load({"query": "iph"}) == {"query": "iph"}
    assert "query" in _error(schemas.SuggestionsSchema, {"query": "x" * 101})


def test_load_query_400_body_names_the_field():
    data, error = load_query(schemas.ProductSchema, {"product": "iphone"})
    assert data is None and error["errors"]["product"] and error["error"].startswith("Invalid parameters: product:")


def test_every_field_has_a_description():
    for name in dir(schemas):
        cls = getattr(schemas, name)
        if isinstance(cls, type) and name.endswith("Schema") and not name.startswith("_"):
            for field_name, field in cls().fields.items():
                assert field.metadata.get("description"), f"{name}.{field_name} has no description"


# ---- URL builders (pure) -----------------------------------------------------------------------

def test_listing_path():
    assert fetch.listing_path("/category/15502/") == "/category/15502/"
    assert fetch.listing_path("/category/15502/", page=2, sort="price", min_price=100, max_price=None) == \
        "/category/15502/?sorting=price&currency_price=100.000;1000000000.000&page=2"
    assert fetch.listing_path("/search/", sort="score", text="носки", extra=[("from_global", "true")]) == \
        "/search/?from_global=true&text=%D0%BD%D0%BE%D1%81%D0%BA%D0%B8"


def test_entrypoint_url_encodes_the_whole_path():
    assert fetch.entrypoint_url("/search/?text=a b&page=2") == (
        "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url=%2Fsearch%2F%3Ftext%3Da%20b%26page%3D2")
