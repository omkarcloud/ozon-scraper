# 🛒 Ozon Scraper

Ozon Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Ozon data for free.

## ✨ What Can I Get?

- 🛍️ **Full details on any of Ozon's millions of products** — card & regular prices, stock, every spec, variants, videos & seller
- 🔍 **Search & browse all 29 departments** — sort by price, rating or discount, with price filters, brands & sellers
- ⭐ **Every review & buyer question** — photos, videos, pros & cons, rating breakdown & seller answers
- 🏪 **Full seller & brand profiles** — ratings, orders, followers, legal entity & every storefront product

## 🎥 Example: A Full Ozon Product

```json
{
  "sku": 3215946988,
  "name": "Колье Swarovski MATRIX 5681800",
  "link": "https://www.ozon.ru/product/kole-swarovski-matrix-5681800-3215946988/",
  "brand": { "name": "Swarovski", "id": 17982501, "is_verified": true, "is_original": true },
  "category": { "id": 17027, "name": "Колье, ожерелья и бусы", "link": "https://www.ozon.ru/category/kole-i-ozherelya-bizhuternye-zhenskie-17027/" },
  "price": { "amount": 29044, "card_amount": 26140, "original_amount": 84169, "discount_percent": 68, "currency": "RUB" },
  "is_available": true,
  "rating": 4.9,
  "reviews_count": 30,
  "questions_count": 13,
  "image": "https://ir-20.ozone.ru/s3/multimedia-1-f/8606485527.jpg",
  "videos": [
    { "link": "https://v-1.ozone.ru/vod/video-70/01KD6320PFNS9TM6JE4ZZSKMXZ/asset_1_h264.mp4?type=pdp", "cover": "https://ir-20.ozone.ru/s3/video-70/01KD6320PFNS9TM6JE4ZZSKMXZ/cover/cover.jpg" }
  ],
  "description": "Колье Swarovski Matrix Tennis Necklace (арт. 5681800) из коллекции Matrix Tennis создано, чтобы завораживать и придавать образу сияние...",
  "characteristics": [
    { "key": "Gem", "name": "Вставка", "values": ["Кристаллы swarovski"] },
    { "key": "Country", "name": "Страна-изготовитель", "values": ["Австрия"] }
  ],
  "variants": [
    { "name": "Цвет", "key": "Color", "options_count": 87, "options": [{ "sku": 2324450892, "name": "Колье Swarovski 5487069", "price": 8821, "is_available": true }] }
  ],
  "seller": { "id": 2586238, "name": "CityWatches", "rating": 4.9, "orders_count": 3000, "legal_name": "ИП Хромов Александр Кириллович" },
  "other_offers": { "count": 4, "lowest_price": 9033 },
  "hashtags": ["#колье", "#swarovski"]
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Ozon Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/ozon-scraper
cd ozon-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/products/details?product=3215946988"
```

```json
{
  "sku": 3215946988,
  "name": "Колье Swarovski MATRIX 5681800",
  "link": "https://www.ozon.ru/product/kole-swarovski-matrix-5681800-3215946988/",
  "brand": { "name": "Swarovski", "id": 17982501, "is_verified": true, "is_original": true },
  "category": { "id": 17027, "name": "Колье, ожерелья и бусы" },
  "price": { "amount": 29044, "card_amount": 26140, "original_amount": 84169, "discount_percent": 68, "currency": "RUB" },
  "is_available": true,
  "rating": 4.9,
  "reviews_count": 30,
  "questions_count": 13,
  "characteristics": [
    { "key": "Material", "name": "Материал", "values": ["Металл"] },
    { "key": "CoverAdornment", "name": "Покрытие", "values": ["Родирование"] }
  ],
  "seller": { "id": 2586238, "name": "CityWatches", "rating": 4.9, "orders_count": 3000 }
}
```

All 10 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

10 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Product Details | `/products/details` | Prices, stock, specs, variants, description and seller in one call |
| Search Products | `/products/search` | 8–36 products per page, sortable, with price filters |
| Search Suggestions | `/search/suggestions` | Typeahead phrases plus matching categories and brands |
| Product Reviews | `/products/reviews` | 30 reviews per page with photos, videos, pros and cons |
| Product Questions | `/products/questions` | Buyer questions with their answers, 10 per page |
| Category Products | `/categories/products` | Products from any category, sortable, with price filters |
| Categories | `/categories/list` | Top-level departments, or any category's full subcategory list |
| Brand Products | `/brands/products` | Any brand's products, plus its logo and follower count |
| Seller Details | `/sellers/details` | Rating, reviews, orders, followers, legal entity and verified brands |
| Seller Products | `/sellers/products` | Any seller's storefront products, searchable |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-ozon-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-ozon-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-ozon-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/products/details",
    params={"product": "3215946988"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Ozon Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Ozon%20Scraper%20API.)

[![Ask Us by Email about Ozon Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Ozon%20Scraper%20API&body=I%20need%20help%20using%20the%20Ozon%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/ozon-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/ozon-scraper)
