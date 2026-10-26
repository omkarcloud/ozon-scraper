"""Offline tests for the Ozon parsers, reference resolvers and value helpers.

    python -m pytest ozon/test_parsers.py -q

Fixtures (ozon/fixtures/, gzipped when large) are real www.ozon.ru page JSON
captured 2026-10-24 from the GKE pod through a box-minted identity: product
pages (in stock with two variant axes, an age-gated product with a video and
an HTML description, out of stock via oos_search=false, a product without
reviews, an unknown SKU, the age gate and the out-of-stock search redirect),
both layout pages, reviews / questions pages (populated, empty, unknown, past the end, a
cursor follow-up), search (redirected into a category, price-sorted page 2,
a plain search, gibberish), category pages (page 1, price-sorted page 2,
past the end, unknown id, a search scoped to an unknown category), the
catalog page, the category-children action
(branch, leaf, unknown), brand pages (Apple, unknown), seller pages (live,
closed storefront, unknown) and info modals, suggestions, and Ozon's
antibot bodies (challenge / captcha / block, HTML and JSON). No network.
"""
import gzip
import json
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ozon import parsers as P, refs  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def raw(name):
    path = os.path.join(FX, name)
    if name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return f.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def page(name):
    return P.load_page(raw(name))


@pytest.fixture(scope="module")
def iphone():
    return P.parse_product(page("product_5792593898.json.gz"), page("product_5792593898_page2.json.gz"))


@pytest.fixture(scope="module")
def socks():
    return P.parse_product(page("product_1574782712.json.gz"), page("product_1574782712_page2.json.gz"))


# ---- refs ------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("5792593898", 5792593898),
    ("https://www.ozon.ru/product/apple-smartfon-iphone-18-pro-5792593898/", 5792593898),
    ("https://www.ozon.ru/product/5792593898/?at=xyz&sh=abc", 5792593898),
    ("www.ozon.ru/product/noski-1574782712/reviews/", 1574782712),
    ("https://ozon.kz/product/apple-5792593898/", 5792593898),
    ("https://uz.ozon.com/product/x-5792593898/questions/", 5792593898),
    ("https://www.ozon.ru/context/detail/id/148314327/", 148314327),
    ("1", 1),                     # well-formed; Ozon answers its not-found page -> 404
])
def test_resolve_product(value, expected):
    assert refs.resolve_product(value) == expected


@pytest.mark.parametrize("value,message", [
    ("iphone", "SKU"),
    ("https://www.wildberries.ru/catalog/123/detail.aspx", "ozon.ru link"),
    ("https://ozon.ru/t/AbCdE", "Short ozon.ru/t/ links"),
    ("https://www.ozon.ru/category/smartfony-15502/", "product link"),
])
def test_resolve_product_rejects(value, message):
    with pytest.raises(ValueError) as e:
        refs.resolve_product(value)
    assert message in str(e.value)


@pytest.mark.parametrize("value,expected", [
    ("15502", "/category/15502/"),
    ("https://www.ozon.ru/category/smartfony-15502/", "/category/smartfony-15502/"),
    ("https://www.ozon.ru/category/smartfony-15502/apple-26303000/?text=x", "/category/smartfony-15502/"),
    ("https://www.ozon.ru/category/smartfon-apple-iphone18/", "/category/smartfon-apple-iphone18/"),
])
def test_resolve_category(value, expected):
    assert refs.resolve_category(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("26303000", 26303000),
    ("https://www.ozon.ru/brand/apple-26303000/", 26303000),
    ("https://www.ozon.ru/brand/26303000/?page=2", 26303000),
])
def test_resolve_brand(value, expected):
    assert refs.resolve_brand(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("4289687", "4289687"),
    ("mirnyy-atom", "mirnyy-atom"),
    ("https://www.ozon.ru/seller/mirnyy-atom/?miniapp=seller_4289687", "mirnyy-atom"),
    ("https://www.ozon.ru/seller/proffi/brand/proffi-home-136166665/", "proffi"),
    ("https://www.ozon.ru/seller/4289687/products/", "4289687"),
])
def test_resolve_seller(value, expected):
    assert refs.resolve_seller(value) == expected


def test_resolve_rejects_other_kinds():
    with pytest.raises(ValueError):
        refs.resolve_brand("https://www.ozon.ru/seller/mirnyy-atom/")
    with pytest.raises(ValueError):
        refs.resolve_category("smartfony")
    with pytest.raises(ValueError):
        refs.resolve_seller("not a seller!")


def test_links_drop_tracking_params():
    assert refs.absolute("/product/x-1/?at=abc&sh=def&from_sku=2") == "https://www.ozon.ru/product/x-1/"
    assert refs.absolute("/search/?text=iphone&from_global=true") == "https://www.ozon.ru/search/?text=iphone"
    assert refs.product_link(5, "/product/foo-5/?at=x") == "https://www.ozon.ru/product/foo-5/"
    assert refs.product_link(5, "/product/other-6/") == "https://www.ozon.ru/product/5/"
    assert refs.category_id_from_path("/category/smartfony-15502/apple-26303000/") == 15502
    assert refs.category_id_from_path("/category/smartfon-apple-iphone18/") is None


# ---- values ----------------------------------------------------------------------------

def test_value_helpers():
    assert P.money("165 079 ₽") == 165079
    assert P.money("193 ₽") == 193
    assert P.money("1 234,50 ₽") == 1234.5
    assert P.money(None) is None and P.money("нет") is None
    assert P.count("41 786\xa0отзывов") == 41786
    assert P.count("440 K") == 440000 and P.count("1,3 M") == 1300000 and P.count("77,3 K") == 77300
    assert P.count("2 077 заказов") == 2077 and P.count("Задать вопрос") is None
    assert P.percent("−49%") == 49
    assert P.rating_value("4,9") == 4.9 and P.rating_value("0") is None
    assert P.ru_date("3 декабря 2025") == "2025-12-03" and P.ru_date("вчера") is None
    assert P.epoch_iso(1788842612) == "2026-09-08T04:43:32Z" and P.epoch_iso(None) is None
    assert P.months_with_ozon("7 месяцев") == 7 and P.months_with_ozon("8 лет") == 96
    assert P.full_image("https://ir.ozone.ru/s3/multimedia-1-h/wc140/15028580609.jpg") == \
        "https://ir.ozone.ru/s3/multimedia-1-h/15028580609.jpg"


def test_delivery_date():
    today = date(2026, 10, 24)
    assert P.delivery_date("27 октября", today) == "2026-10-27"
    assert P.delivery_date("3 января", today) == "2027-01-03"
    assert P.delivery_date("завтра", today) == "2026-10-25"
    assert P.delivery_date("послезавтра", today) == "2026-10-26"
    assert P.delivery_date("В корзину", today) is None


# ---- antibot -----------------------------------------------------------------------------

@pytest.mark.parametrize("name,kind", [
    ("antibot_challenge.html", "challenge"),
    ("antibot_captcha.html", "captcha"),
    ("antibot_block.html", "block"),
    ("antibot_challenge.json", "challenge"),
    ("antibot_captcha.json", "captcha"),
    ("antibot_block.json", "block"),
])
def test_antibot_bodies(name, kind):
    assert P.antibot_kind(403, raw(name)) == kind


def test_real_pages_are_not_antibot():
    assert P.antibot_kind(200, raw("product_5792593898.json.gz")) is None
    assert P.antibot_kind(200, raw("category_children_15501.json")) is None


def test_load_page_tolerates_junk():
    assert P.load_page("") is None and P.load_page("<html>") is None and P.load_page("[1]") is None
    assert P.widgets(None, "webPrice") == [] and P.widget({}, "webPrice") == {}


# ---- product -----------------------------------------------------------------------------

def test_product_identity_and_price(iphone):
    assert iphone["sku"] == 5792593898
    assert iphone["name"].startswith("Apple Смартфон iPhone 18 Pro")
    assert iphone["link"] == ("https://www.ozon.ru/product/apple-smartfon-iphone-18-pro-dual-esim-global-12-1-tb-"
                              "esim-chernyy-prozrachnyy-5792593898/")
    assert iphone["price"] == {"amount": 176438, "card_amount": 165079, "original_amount": 329429,
                               "discount_percent": 49, "currency": "RUB"}
    assert iphone["is_available"] is True
    assert iphone["rating"] == 5.0 and iphone["reviews_count"] == 103 and iphone["questions_count"] == 31


def test_product_brand_category_breadcrumbs(iphone):
    assert iphone["brand"] == {"name": "Apple", "id": 26303000, "link": "https://www.ozon.ru/brand/26303000/",
                               "is_verified": True, "is_original": True}
    assert iphone["category"] == {"id": 15502, "name": "Смартфоны",
                                  "link": "https://www.ozon.ru/category/smartfony-15502/"}
    assert [c["id"] for c in iphone["breadcrumbs"]] == [15500, 15501, 15502]


def test_product_media_and_description(iphone, socks):
    assert len(iphone["images"]) == 10 and iphone["image"] == iphone["images"][0]
    assert iphone["description"].startswith("Абсолютно новый")
    assert "https://ir.ozone.ru/s3/multimedia-1-9/15113534553.jpg" in iphone["description_images"]
    assert iphone["description_sections"] == [{"title": "Комплектация", "content": "Смартфон, зарядный кабель USB Type-C"}]
    assert socks["videos"][0]["link"].endswith("asset_2_h264.mp4?type=pdp")
    assert socks["description"].startswith("Рады представить вам носки")
    assert "<br" not in socks["description"]
    assert socks["model_info"].startswith("Модель: рост 170 см")
    assert "#носки_мужские_прикольные" in socks["hashtags"]


def test_product_characteristics_full_list(iphone, socks):
    assert len(iphone["characteristics"]) == 40
    sku_row = iphone["characteristics"][0]
    assert sku_row == {"key": "Sku", "name": "Артикул", "values": ["5792593898"], "group": None}
    material = next(c for c in socks["characteristics"] if c["key"] == "Material")
    assert material["values"] == ["Трикотаж", "Хлопок"]
    assert any(c["key"] == "DocumentQuality" for c in socks["characteristics"])     # the "long" group


def test_product_variants(iphone, socks):
    axes = {v["key"]: v for v in iphone["variants"]}
    assert set(axes) == {"Color", "VolumeMemoryPhone"}
    assert axes["Color"]["options_count"] == 7
    selected = [o for o in axes["VolumeMemoryPhone"]["options"] if o["is_selected"]]
    assert selected[0]["sku"] == 5792593898 and selected[0]["value"] == "1 ТБ"
    sizes = next(v for v in socks["variants"] if v["key"] == "size")
    assert [o["value"] for o in sizes["options"]] == ["36–40 RU / 36-40", "41–45 RU / 41-45"]
    assert all("/wc140/" not in (o["image"] or "") for v in socks["variants"] for o in v["options"])


def test_product_seller(iphone, socks):
    s = iphone["seller"]
    assert s["id"] == 2090753 and s["name"] == "Дубайский Экспресс" and s["slug"] == "dubaidutyfree"
    assert s["is_premium"] is True and s["rating"] == 5.0 and s["orders_count"] == 440000
    assert s["legal_name"] == "WISE BRIDGE BROKER SERVICES - FZCO" and s["country_code"] == "AE"
    assert s["working_hours"] == "согласно режиму работы Ozon"
    t = socks["seller"]
    assert t["registration_number"] == "321508100185676" and t["is_honest_sign_registered"] is True
    assert t["legal_address"] is None


def test_product_extras(iphone):
    assert iphone["other_offers"] == {"count": 24, "lowest_price": 151212}
    assert iphone["customs_duty_estimate"] == 24447
    assert iphone["labels"] == ["Цена что надо"] and iphone["has_price_drop"] is True


def test_product_out_of_stock():
    r = P.parse_product(page("product_out_of_stock_3755501937.json.gz"),
                        page("product_out_of_stock_3755501937_page2.json.gz"))
    assert r["sku"] == 3755501937 and r["is_available"] is False
    assert r["price"]["amount"] == 235701 and r["price"]["card_amount"] is None
    assert r["description"] and r["characteristics"]


def test_product_without_reviews_and_page2():
    r = P.parse_product(page("product_no_reviews_5948543555.json.gz"))      # page 2 missing
    assert r["reviews_count"] == 0 and r["rating"] is None and r["questions_count"] == 0
    assert r["description"] is None
    assert r["characteristics"] and r["characteristics"][0]["group"] is None   # short list fallback
    assert r["seller"]["name"] == "Charge"


def test_product_not_found_shapes():
    assert P.product_not_found(page("product_unknown_1.json.gz")) is True
    assert P.product_not_found(page("product_5792593898.json.gz")) is False
    assert P.is_out_of_stock_redirect(page("product_out_of_stock_redirect_3755501937.json.gz")) is True
    assert P.is_adult_gate(page("product_adult_gate_1574782712.json")) is True
    assert P.is_adult_gate(page("product_1574782712.json.gz")) is False


def test_product_parser_survives_empty_pages():
    r = P.parse_product({}, {})
    assert r["sku"] is None and r["images"] == [] and r["variants"] == [] and r["seller"] is None
    assert r["price"]["amount"] is None and r["characteristics"] == []


# ---- listings ------------------------------------------------------------------------------

def test_search_resolved_into_category():
    L = P.parse_listing(page("search_iphone_p1.json.gz"))
    assert L["page_type"] == "category"
    assert L["category"] == {"id": 15502, "name": "Смартфоны", "link": "https://www.ozon.ru/category/smartfony-15502/"}
    assert L["brand_id"] == 26303000
    assert [c["id"] for c in L["category_path"]] == [15500, 15501, 15502]
    assert len(L["results"]) == 8 and L["has_next"] is True
    first = L["results"][0]
    assert first["sku"] == 5792593898 and first["price"]["discount_percent"] == 49
    assert first["delivery_date"] and first["is_premium_seller"] is True
    assert first["rating"] == 5.0 and first["reviews_count"] == 103 and first["stock_left"] == 1
    assert first["link"].endswith("-5792593898/") and "?at=" not in first["link"]


def test_listing_tile_shape():
    L = P.parse_listing(page("category_smartfony_price_p2.json.gz"))
    assert len(L["results"]) == 36
    keys = {"sku", "name", "link", "image", "images", "price", "rating", "reviews_count", "brand", "stock_left",
            "delivery_date", "is_sold_by_ozon", "has_express_delivery", "is_premium_seller", "has_price_drop",
            "is_adult", "labels"}
    assert all(set(r) == keys for r in L["results"])
    assert all(r["price"]["currency"] == "RUB" and r["price"]["amount"] for r in L["results"])
    assert L["facets"]["price_range"]["min"] is not None and L["facets"]["brands"]


def test_plain_search_has_category_facets_not_a_path():
    L = P.parse_listing(page("search_gift_no_category.json.gz"))
    assert L["page_type"] == "search" and L["category"] is None and L["category_path"] == []
    assert len(L["facets"]["categories"]) >= 3


def test_sold_by_ozon_and_express_flags():
    flags = [r for name in ("brand_apple_p1.json.gz", "search_iphone_p1.json.gz", "category_smartfony_p1.json.gz")
             for r in P.parse_listing(page(name))["results"]]
    assert any(r["is_sold_by_ozon"] for r in flags)
    assert any(r["has_express_delivery"] for r in flags)


def test_listing_past_the_end_and_unknown():
    L = P.parse_listing(page("category_smartfony_p5000.json.gz"))
    assert L["results"] == [] and L["has_next"] is False and L["category"]["name"] == "Смартфоны"
    assert P.listing_not_found(page("category_unknown.json.gz")) is True
    # a search scoped to an unknown category keeps a seo title (from the query) but shows sign-error
    assert P.listing_not_found(page("search_in_unknown_category.json.gz")) is True
    assert P.listing_not_found(page("category_smartfony_p1.json.gz")) is False
    assert P.listing_not_found(page("search_gibberish.json.gz")) is False


def test_brand_header_and_unknown_brand():
    assert P.parse_brand_header(page("brand_apple_p1.json.gz")) == {
        "id": 26303000, "name": "Apple",
        "logo": "https://cdn1.ozonusercontent.com/s3/product-service-meta-media/6a3b9a40-2c45-4651-9725-bd1755b6e2fe.jpg",
        "followers_count": 77300}
    brand_rows = P.parse_listing(page("brand_apple_p1.json.gz"))["results"]
    assert len(brand_rows) == 8          # the 30-tile "Возможно, вам понравится" shelf is not the brand's
    assert all("Apple" in (r["name"] or "") or (r["brand"] or {}).get("name") == "Apple" for r in brand_rows[:2])
    assert P.brand_not_found(page("brand_unknown.json.gz")) is True
    assert P.tiles(page("brand_unknown.json.gz")) == []          # only the recommendation shelf there
    assert P.brand_not_found(page("brand_apple_p1.json.gz")) is False


# ---- reviews -------------------------------------------------------------------------------

def test_reviews_page():
    R = P.parse_reviews(page("reviews_1574782712_p1.json.gz"))
    assert R["product"]["sku"] == 1574782712 and R["total"] == 41786 and R["per_page"] == 30
    assert R["rating_distribution"] == {"5": 40184, "4": 1360, "3": 133, "2": 49, "1": 60}
    assert len(R["results"]) == 30
    r = R["results"][0]
    assert r["id"] == "01a07f54-0c43-7490-8c98-f692e2d945e8" and r["rating"] == 5
    assert r["published_at"] == "2026-09-08T04:43:32Z" and r["author"]["name"] == "Александр И."
    assert r["variant"]["sku"] == 1574778549 and r["variant"]["attributes"][0]["name"] == "Цвет товара"
    assert r["pros"] is None and r["cons"] is None and r["replies"] == []


def test_review_media_survey_and_flags():
    results = [r for name in ("reviews_1574782712_p1.json.gz", "reviews_1574782712_p2_score_asc.json.gz",
                              "reviews_5792593898_p1.json.gz")
               for r in P.parse_reviews(page(name))["results"]]
    assert any(r["photos"] for r in results)
    video = next(r for r in results if r["videos"])["videos"][0]
    assert video["link"].startswith("https://") and video["duration_seconds"] == 14
    assert any(r["survey"] for r in results)
    anon = [r for r in results if r["author"]["is_anonymous"]]
    assert anon and all(r["author"]["name"] is None for r in anon)
    assert any(r["is_outdated"] for r in results)
    low = P.parse_reviews(page("reviews_1574782712_p2_score_asc.json.gz"))
    assert low["page"] == 2 and all(r["rating"] <= 2 for r in low["results"])


def test_reviews_states():
    assert P.reviews_state(page("reviews_1574782712_p1.json.gz")) == "ok"
    assert P.reviews_state(page("reviews_none_5948543555.json.gz")) == "none"
    assert P.reviews_state(page("reviews_unknown_1.json.gz")) == "not_found"
    assert P.reviews_state(page("reviews_past_end_5792593898_p50.json.gz")) == "past_end"


def test_reviews_past_end_keeps_the_totals():
    R = P.parse_reviews(page("reviews_past_end_5792593898_p50.json.gz"))
    assert R["results"] == [] and R["product"]["sku"] == 5792593898
    assert R["total"] and R["total"] >= 100 and R["per_page"] == 30


# ---- questions -------------------------------------------------------------------------------

def test_questions_page_and_cursor():
    Q = P.parse_questions(page("questions_1574782712_p1.json.gz"))
    assert len(Q["results"]) == 10
    assert Q["next"].startswith("/product/1574782712/questions/?layout_page_index=2&page_key=")
    q = Q["results"][0]
    assert q["id"] == "019ae3f6-6b70-7648-8600-439d2ddae120" and q["published_date"] == "2025-12-03"
    assert q["text"].startswith("Здравствуйте, а как заказать") and "<a" not in q["text"]
    assert q["link"].endswith("/question/019ae3f6-6b70-7648-8600-439d2ddae120")
    assert q["variant"]["sku"] == 2049311487 and q["helpful_count"] == 3
    a = q["answers"][0]
    assert a["author"]["name"] == "Pinto Socks" and a["helpful_count"] == 1 and a["unhelpful_count"] == 3
    Q2 = P.parse_questions(page("questions_1574782712_p2.json.gz"))
    assert len(Q2["results"]) == 10 and "layout_page_index=3" in Q2["next"]
    assert not {q["id"] for q in Q["results"]} & {q["id"] for q in Q2["results"]}


def test_questions_masked_author_and_states():
    Q = P.parse_questions(page("questions_5792593898_newest.json.gz"))
    assert any(q["author"]["name"] is None for q in Q["results"])     # "Пользователь предпочёл скрыть свои данные"
    assert P.questions_state(page("questions_none_5948543555.json.gz")) == "none"
    assert P.questions_state(page("questions_unknown_1.json.gz")) == "not_found"
    assert P.parse_questions(page("questions_none_5948543555.json.gz")) == {"results": [], "next": None}


# ---- seller --------------------------------------------------------------------------------

def test_seller_page_and_modal():
    s = P.parse_seller_page(page("seller_4289687.json.gz"))
    assert s == {"id": 4289687, "name": "Мирный Атом", "slug": "mirnyy-atom",
                 "logo": "https://cdn1.ozonusercontent.com/s3/marketing-api/5f/t3a/b21628ef-8832-46eb-b629-8ec6a020f7e7.png",
                 "rating": 4.9, "reviews_count": 689, "orders_count": 2077, "followers_count": 308,
                 "is_premium": True, "has_storefront": True}
    m = P.parse_seller_modal(page("seller_modal_4289687.json"))
    assert m["legal_name"] == "ИП Джалыков Владимир Валентинович" and m["registration_number"] == "326080000002966"
    assert m["with_ozon_since_text"] == "7 месяцев" and m["rating"] == 4.9 and m["reviews_count"] == 689


def test_closed_storefront_and_unknown_seller():
    closed = page("seller_closed_storefront_1.json.gz")
    assert P.seller_not_found(closed) is False
    head = P.parse_seller_page(closed)
    assert head["name"] == "Proffi" and head["has_storefront"] is False
    m = P.parse_seller_modal(page("seller_modal_1.json"))
    assert m["legal_name"] == 'ООО "ПАНОРАМА ГРУП"' and m["legal_address"].startswith("123056, Россия")
    assert m["orders_count"] == 1300000 and [b["id"] for b in m["verified_brands"]] == [136166665, 146693659]
    assert P.seller_not_found(page("seller_unknown_999999999.json.gz")) is True
    assert P.parse_seller_modal(page("seller_modal_unknown_999999999.json"))["legal_name"] is None


# ---- suggestions / categories ------------------------------------------------------------------

def test_suggestions():
    S = P.parse_suggestions(page("suggestions_iphone.json"))
    assert [s["type"] for s in S].count("query") == 5
    cat = next(s for s in S if s["type"] == "category")
    assert cat == {"text": "Смартфоны", "type": "category", "id": 15502, "parent": "Электроника",
                   "image": cat["image"], "link": "https://www.ozon.ru/category/smartfony-15502/"}
    brand = next(s for s in S if s["type"] == "brand")
    assert brand["id"] == 26303000 and brand["parent"] is None
    assert P.parse_suggestions(page("suggestions_gibberish.json")) == []


def test_root_categories():
    roots = P.parse_root_categories(page("catalog_root.json.gz"))
    assert len(roots) == 29 and roots[0]["id"] == 15500 and roots[0]["name"] == "Электроника"
    assert all(r["link"].startswith("https://www.ozon.ru/category/") for r in roots)


def test_category_children_action():
    path, children = P.parse_category_children(json.loads(raw("category_children_15501.json")))
    assert [c["id"] for c in path] == [15500, 15501] and path[-1]["is_current"] is True
    assert len(children) == 10 and children[0] == {"id": 15502, "name": "Смартфоны",
                                                   "link": "https://www.ozon.ru/category/smartfony-15502/"}
    leaf_path, leaf_children = P.parse_category_children(json.loads(raw("category_children_15502.json")))
    assert leaf_path[-1]["id"] == 15502 and leaf_children == []
    assert P.parse_category_children(json.loads(raw("category_children_unknown.json"))) == ([], [])
