"""Generic value helpers for the Ozon parsers: safe nested access, numbers,
text and HTML -> text. Pure functions, no network; every helper tolerates
None and junk.

The same-named helpers as seek/shared.py (which mirror indeed's); the ones every
site shares come from scraper_utils and the rest live here, because the ozon
package ships as its own open-source repo, which must not pull in other sites'
modules."""
from html.parser import HTMLParser
from scraper_utils.values import as_dict, as_list, g, num, to_int_round as to_int
from scraper_utils.text import clean as text, html_to_text, multiline


# ---- HTML -> text ------------------------------------------------------------------------------------

_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table",
               "section", "article", "header", "footer", "blockquote", "pre", "hr", "dd", "dt", "dl"}
_SKIP_TAGS = {"script", "style", "noscript", "template", "head"}
