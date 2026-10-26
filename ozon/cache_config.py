"""Cache TTL per /ozon/* endpoint (cache.py, keyed on the validated params)."""
from datetime import timedelta

# Search / category / brand / seller listings: prices, stock counters and
# delivery dates move through the day; a listing is a snapshot anyway.
LISTING_CACHE = timedelta(minutes=30)
# One product (page + its second layout page): price and stock are the point.
PRODUCT_CACHE = timedelta(minutes=20)
# Reviews: a few new ones a day even on best sellers; the order is stable.
REVIEWS_CACHE = timedelta(hours=6)
# Questions pages (and the page_key cursor each one carries for the next).
QUESTIONS_CACHE = timedelta(hours=6)
# Seller record (storefront header + info modal): ratings / order counters move daily.
SELLER_CACHE = timedelta(hours=12)
# Search suggestions: a popularity model Ozon refreshes slowly.
SUGGESTIONS_CACHE = timedelta(hours=24)
# Category tree: changes a few times a year.
CATEGORIES_CACHE = timedelta(hours=24)
