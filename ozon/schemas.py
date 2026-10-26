"""Marshmallow request schemas for every /ozon/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    product    an Ozon SKU (digits) OR any Ozon product link (also its
               /reviews/ or /questions/ pages, ozon.kz / ozon.by / uz.ozon.com)
    category   a category id OR a category link (an id-less SEO collection
               link such as /category/smartfon-apple-iphone18/ works too)
    brand      a brand id OR a /brand/<name>-<id>/ link
    seller     a seller id, the storefront name (mirnyy-atom) OR a seller link
"""
from marshmallow import ValidationError, validate, validates_schema

from ozon import refs
from schema_fields import BaseSchema, ChoiceField, PageField, Price, QueryField, RefField


def _max_length(n):
    """Length(max=n) that tolerates the None an optional StrippedString
    yields for an empty value (QueryField's own Length(min=1) would raise
    TypeError on `?query=`, escaping load_query as a bottle 500)."""
    return lambda value: value is None or bool(validate.Length(max=n)(value))


MAX_LISTING_PAGE = 1000         # past Ozon's real end a listing page is empty (page 5000 of smartphones, 2026-10-24)
MAX_REVIEWS_PAGE = 2000         # 30 per page
MAX_QUESTIONS_PAGE = 50         # 10 per page; deep pages walk Ozon's cursor chain


class ProductRefField(RefField):
    resolver = staticmethod(refs.resolve_product)


class CategoryRefField(RefField):
    resolver = staticmethod(refs.resolve_category)


class BrandRefField(RefField):
    resolver = staticmethod(refs.resolve_brand)


class SellerRefField(RefField):
    resolver = staticmethod(refs.resolve_seller)


def _sort_field():
    return ChoiceField(list(refs.SORTS), load_default=refs.DEFAULT_SORT, metadata={
        "description": "order: popular (default), newest, price_asc, price_desc, rating, discount. Ozon serves "
                       "8 products per page for popular / newest / rating and 36 for the price and discount orders"})


def _page_field():
    return PageField(max_page=MAX_LISTING_PAGE, metadata={"description": "result page (1-1000); past the end is empty"})


def _product_field():
    return ProductRefField(metadata={
        "description": "Ozon SKU (the product's 'Артикул', digits) or a product link "
                       "(https://www.ozon.ru/product/<name>-<sku>/)"})


class _PriceRange(BaseSchema):
    min_price = Price(metadata={"description": "lowest price to include, in RUB (Ozon filters on the Ozon-card price)"})
    max_price = Price(metadata={"description": "highest price to include, in RUB (Ozon filters on the Ozon-card price)"})

    @validates_schema
    def _price_range(self, data, **kwargs):
        lo, hi = data.get("min_price"), data.get("max_price")
        if lo is not None and hi is not None and lo > hi:
            raise ValidationError("min_price must not exceed max_price.", "max_price")


class ProductsSearchSchema(_PriceRange):
    query = QueryField(metadata={"description": "search phrase, Russian or English (iphone 17, носки мужские)"})
    page = _page_field()
    sort = _sort_field()
    category = CategoryRefField(required=False, load_default=None, metadata={
        "description": "category id or category link to search within"})


class ProductSchema(BaseSchema):
    product = _product_field()


class ProductReviewsSchema(BaseSchema):
    product = _product_field()
    page = PageField(max_page=MAX_REVIEWS_PAGE, metadata={"description": "review page (30 reviews per page)"})
    sort = ChoiceField(list(refs.REVIEW_SORTS), load_default=refs.DEFAULT_REVIEW_SORT, metadata={
        "description": "order: most_helpful (default; Ozon's 'new and helpful'), highest_rating, lowest_rating"})


class ProductQuestionsSchema(BaseSchema):
    product = _product_field()
    page = PageField(max_page=MAX_QUESTIONS_PAGE, metadata={"description": "questions page (10 per page, 1-50)"})
    sort = ChoiceField(list(refs.QUESTION_SORTS), load_default=refs.DEFAULT_QUESTION_SORT, metadata={
        "description": "order: most_helpful (default), newest, answered_first, unanswered_first"})


class CategoryProductsSchema(_PriceRange):
    category = CategoryRefField(metadata={
        "description": "category id (15502) or category link (https://www.ozon.ru/category/smartfony-15502/)"})
    page = _page_field()
    sort = _sort_field()


class CategoriesListSchema(BaseSchema):
    category = CategoryRefField(required=False, load_default=None, metadata={
        "description": "category id or link whose subcategories to list; empty = Ozon's top-level categories"})


class BrandProductsSchema(BaseSchema):
    brand = BrandRefField(metadata={
        "description": "brand id (26303000) or brand link (https://www.ozon.ru/brand/apple-26303000/)"})
    page = _page_field()
    sort = _sort_field()


class SellerSchema(BaseSchema):
    seller = SellerRefField(metadata={
        "description": "seller id (4289687), storefront name (mirnyy-atom) or seller link "
                       "(https://www.ozon.ru/seller/mirnyy-atom/)"})


class SellerProductsSchema(BaseSchema):
    seller = SellerRefField(metadata={
        "description": "seller id (4289687), storefront name (mirnyy-atom) or seller link "
                       "(https://www.ozon.ru/seller/mirnyy-atom/)"})
    page = _page_field()
    sort = _sort_field()
    query = QueryField(required=False, load_default=None, validate=_max_length(200), metadata={
        "description": "search phrase within the seller's products"})


class SuggestionsSchema(BaseSchema):
    query = QueryField(max_length=100, metadata={"description": "partial search phrase to complete"})
