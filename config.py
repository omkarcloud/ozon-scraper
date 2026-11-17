"""Configuration for the Ozon Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT              port the API listens on (default 8000)
    OZON_PROXY        proxy URL for every request, e.g. http://user:pass@host:port
                      (default: none — your own IP). Ozon's Antibot decides per
                      IP whether it shows a solvable challenge (most home
                      connections), a slider captcha or a hard block. If you get
                      "captcha" / "block" errors, point this at a STICKY proxy
                      (one IP per URL, never a rotating one): the pass is bound
                      to the IP it was earned on.
    OZON_IDENTITIES   Antibot passes kept at once, each earned in its own
                      Chrome run (default 1)
    OZON_EXIT_SCREEN  connection checks before giving up on a pass (default 3)

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

OZON_PROXY = os.environ.get("OZON_PROXY") or None
OZON_IDENTITIES = int(os.environ.get("OZON_IDENTITIES", "1"))
OZON_EXIT_SCREEN = int(os.environ.get("OZON_EXIT_SCREEN", "3"))


def ozon_proxy():
    """The connection Chrome earns the pass on and every request reuses (None = your own IP)."""
    return os.environ.get("OZON_PROXY") or None


# ---- added by the sync: defaults for a direct run ----
def burst_slots(share):
    return share


def exit_geo(proxy, timeout=12):
    """Geo of a proxy's exit IP, looked up THROUGH the proxy (ip-api.com, free
    tier, keyed per exit IP so the quota is never shared). Returns the dict
    {countryCode, regionName, city, timezone, query} or None on any failure —
    callers keep their configured/system timezone then."""
    try:
        import requests
        r = requests.get(
            "http://ip-api.com/json/?fields=status,countryCode,regionName,city,timezone,query",
            proxies={"http": proxy, "https": proxy}, timeout=timeout)
        d = r.json()
        if d.get("status") == "success" and d.get("timezone"):
            return d
    except Exception:
        pass
    return None

