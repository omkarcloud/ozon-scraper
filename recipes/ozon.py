"""Ozon (www.ozon.ru): Ozon's own "Antibot" sits in front of every path,
the /api/ JSON gateway included, and serves one of three bodies per exit IP
(reputation, not the client):

  * "Antibot Challenge Page" (incident fab_chlg_*): a JavaScript proof of
    work (st.ozone.ru/s3/abt-challenge/script_v*.js, SHA1, POST /abt/result)
    that a real Chrome clears in ~5 s with no interaction, then reloads the
    page with ?__rr=1&abt_att=1. This is the only variant worth a browser.
  * "Antibot Captcha" (fab_cp_*): a slider puzzle with decoy holes whose
    fingerprint is computed by a bytecode VM. Not solved here: the exit is
    refused at once and GKE mints on another one.
  * "Похоже, нет соединения" (fab_* / fab_nmk_*): a hard block (datacenter
    ranges, flagged IPs).

The seed is a tiny JSON call (composer-api.bx/_action/summaryV2): the
challenge page is served on it like on any page, and once the proof of work
passes the reload answers `{}` — no storefront, no images, ~200 bytes after
the challenge script (Mac mechanics 2026-10-24: passed in 5–7 s). The
identity is the cookie jar + UA; `abt_data` is the pass token (alone it
makes curl pass every entrypoint-api call). ozon/fetch.py replays it with
curl_cffi on the SAME sticky exit and only sends an exit here after its own
curl pre-screen saw the challenge variant on it.

Images, fonts, media and stylesheets are blocked (the challenge needs none
of them; proxy traffic must not grow with this site)."""
from browser_worker.types import CookieMint, RecipeError

SEED = "https://www.ozon.ru/api/composer-api.bx/_action/summaryV2"
COOKIE = "abt_data"
# Body tells (recipe and ozon/parsers.py antibot_kind agree on these).
CHALLENGE_MARKERS = ("abt-challenge/script_", "Antibot Challenge Page")
CAPTCHA_MARKERS = ("abt-challenge/captcha_", "Antibot Captcha")
BLOCK_MARKERS = ("abt-challenge/incidents/images/warn", "нет соединения")


class Ozon(CookieMint):
    name = "ozon"
    headless = False
    variants = {"": SEED}
    wait_for_cookie = COOKIE
    challenge_markers = CHALLENGE_MARKERS
    block_resources = ("image", "font", "media", "stylesheet")
    geoip_timezone = True
    require_challenge = False     # a clean exit answers the JSON at once; that cookie is good too
    nav_settle = False            # poll from domcontentloaded: the proof of work starts on load
    timeout = 40
    poll = 1.0
    referer = "https://www.ozon.ru/"
    ttl_seconds = 12 * 3600       # GKE drops the identity on the first antibot body anyway

    def passed(self, cookies, driver):
        """True once the seed answered its JSON (the challenge reloaded into
        it); RecipeError at once on the captcha or the hard block, so GKE
        moves to another exit instead of waiting out the timeout."""
        try:
            html = (driver.call(lambda page: page.content()) or "")[:8000]
        except Exception:
            return False          # mid-reload after the proof of work
        if any(m in html for m in CAPTCHA_MARKERS):
            raise RecipeError("ozon: slider captcha on this exit (refused, not solvable here)")
        if any(m in html for m in BLOCK_MARKERS):
            raise RecipeError("ozon: hard block on this exit")
        if any(m in html for m in CHALLENGE_MARKERS):
            return False
        return COOKIE in cookies and "<pre" in html.lower()

    def tokens(self, cookies, driver):
        return {COOKIE: cookies[COOKIE]}


RECIPE = Ozon
