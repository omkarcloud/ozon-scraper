"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. The first call opens Chrome for a few seconds to pass Ozon's
Antibot challenge, then everything runs over plain HTTP.
"""
import json
import os

from ozon.api import products_details, products_reviews, products_search

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a SKU or any ozon.ru product link
    save("product_3215946988.json", products_details(product=3215946988))

    # 8 products per page by popularity, 36 when sorted by price or discount
    save("search_raspberry_pi.json", products_search(query="raspberry pi", page=1, sort="popular",
                                                     min_price=None, max_price=None, category=None))

    # 30 reviews per page with photos, videos and the variant bought
    save("reviews_3215946988.json", products_reviews(product=3215946988, page=1, sort="most_helpful"))
