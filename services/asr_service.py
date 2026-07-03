"""
services/asr_service.py

Ready Reckoner / ASR from IGR Maharashtra e-ASR 2.0 (ASP.NET WebForms).
Flow: district (URL) -> Marathi -> taluka -> village -> Search By Survey No
-> enter gut number -> Search -> read the rate grid for that gut.

    get_rr_rate(district_en, taluka_mr, village_mr, survey_no, year=None, debug=False)
"""

import re
import requests
import unicodedata
from bs4 import BeautifulSoup

PORTALS = [
    "https://igreval.maharashtra.gov.in/eASR2.0/eASRCommon.aspx",   # ASR 2.0 (preferred)
    "https://easr.igrmaharashtra.gov.in/eASRCommon.aspx",           # fallback
]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
           "Accept": "text/html,application/xhtml+xml"}
_RATE = re.compile(r"^\d[\d,]{2,}$")
_CODE = re.compile(r"^\d+/\d")
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def _norm(text):
    if text is None:
        return ""
    t = unicodedata.normalize("NFC", str(text)).strip()
    parts = t.split(None, 1)
    if len(parts) == 2 and parts[0].isdigit():
        t = parts[1]
    return t.strip()


_STRIP = dict.fromkeys(map(ord, "ंँ़ािीुूृेैोौ्\u200c\u200d \t.:-/"), None)


def _loose(text):
    return _norm(text).translate(_STRIP)


class _ASR:
    def __init__(self, portal, district_en):
        self.portal = portal
        self.district = district_en
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.soup = None
        self.form = {}

    def _refresh_form(self):
        self.form = {}
        for inp in self.soup.select("input[type=hidden]"):
            if inp.get("name"):
                self.form[inp["name"]] = inp.get("value", "")
        for sel in self.soup.find_all("select"):
            name = sel.get("name")
            if not name:
                continue
            chosen = ""
            opts = sel.find_all("option")
            for o in opts:
                if o.has_attr("selected"):
                    chosen = o.get("value", "")
            if not chosen and opts:
                chosen = opts[0].get("value", "")
            self.form[name] = chosen
        # carry currently-checked radios
        for r in self.soup.find_all("input", {"type": "radio"}):
            if r.has_attr("checked") and r.get("name"):
                self.form[r["name"]] = r.get("value", "")

    def get(self):
        r = self.s.get(self.portal, params={"hDistName": self.district}, timeout=30)
        self.soup = BeautifulSoup(r.text, "lxml")
        self._refresh_form()
        return r.status_code, len(r.text)

    def submit(self, extra=None, event_target=""):
        data = dict(self.form)
        if extra:
            data.update(extra)
        data["__EVENTTARGET"] = event_target
        data["__EVENTARGUMENT"] = ""
        r = self.s.post(self.portal, params={"hDistName": self.district},
                        data=data, timeout=30)
        body = r.text
        if body[:1].isdigit() and "|" in body[:200] and "<" in body:
            body = body[body.find("<"):]
        self.soup = BeautifulSoup(body, "lxml")
        self._refresh_form()
        return r.status_code

    def postback(self, name, value):
        return self.submit(extra={name: value}, event_target=name)

    def selects(self):
        out = []
        for sel in self.soup.find_all("select"):
            out.append({"name": sel.get("name") or sel.get("id") or "",
                        "options": [(o.get("value", ""), o.get_text(strip=True))
                                    for o in sel.find_all("option")]})
        return out

    def find_select_by_name(self, *kw):
        for s in self.selects():
            if any(k in s["name"].lower() for k in kw):
                return s
        return None


def _match_option(select, wanted):
    w, wl = _norm(wanted), _loose(wanted)
    for val, txt in select["options"]:
        if _norm(txt) == w:
            return val, txt
    for val, txt in select["options"]:
        if wl and _loose(txt) == wl:
            return val, txt
    for val, txt in select["options"]:
        nt = _norm(txt)
        if w and (w in nt or nt in w):
            return val, txt
    return None, None


_VILLAGE_FILLERS = {"मौजे", "तरफ", "तर्फ", "ता", "नगर", "पंचायत", "मौजे:"}
_TOK_STRIP = dict.fromkeys(map(ord, "ंँ़ािीुूृेैोौ्\u200c\u200d"), None)


def _tok_norm(t):
    return t.translate(_TOK_STRIP)


def _toks(s):
    s = re.sub(r"[()\/.:,\-]", " ", _norm(s))
    out = set()
    for t in s.split():
        if not t or t in _VILLAGE_FILLERS:
            continue
        tn = _tok_norm(t)
        if tn:
            out.add(tn)
    return out


def _match_village(vsel, wanted):
    """Robust village match avoiding short-name false hits: exact, loose, then tokens."""
    w, wl = _norm(wanted), _loose(wanted)
    for val, txt in vsel["options"]:
        if _norm(txt) == w:
            return val, txt
    for val, txt in vsel["options"]:
        if wl and _loose(txt) == wl:
            return val, txt
    wt = _toks(wanted)
    if not wt:
        return None, None
    for val, txt in vsel["options"]:          # same distinctive token set
        if _toks(txt) == wt:
            return val, txt
    best = None                                # wanted tokens all inside option
    for val, txt in vsel["options"]:
        ot = _toks(txt)
        if ot and wt <= ot:
            score = len(ot ^ wt)
            if best is None or score < best[0]:
                best = (score, val, txt)
    if best:
        return best[1], best[2]
    for val, txt in vsel["options"]:          # option tokens (2+) inside wanted
        ot = _toks(txt)
        if len(ot) >= 2 and ot <= wt:
            score = len(ot ^ wt)
            if best is None or score < best[0]:
                best = (score, val, txt)
    return (best[1], best[2]) if best else (None, None)


# ---------------------------------------------------------------------------
# Cross-script matching: ASR 2.0 lists taluka/village in ENGLISH and won't
# switch to Marathi (the language postback redirects to the portal home).
# So we transliterate the Marathi CSV name to a rough Latin consonant skeleton
# and match it against the English option text (and vice-versa).
# ---------------------------------------------------------------------------
_HAL = "्"
_LABIAL = set("पफबभम")
_VOW = {"अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u", "ऋ": "ru",
        "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e", "ॲ": "a"}
_MAT = {"ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ru", "े": "e",
        "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e", "ः": "h", "़": ""}
_CON = {"क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh",
        "ज": "j", "झ": "jh", "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh",
        "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n", "प": "p",
        "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l",
        "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h", "ळ": "l", "ऱ": "r",
        "ऴ": "l"}


def _translit(s):
    res, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        nxt = s[i + 1] if i + 1 < n else ""
        nn = s[i + 2] if i + 2 < n else ""
        if ch in _CON:
            res.append(_CON[ch])
            if nxt == _HAL:
                i += 2; continue
            if nxt == "ं":
                res.append("m" if nn in _LABIAL else "n"); i += 2; continue
            if nxt in _MAT:
                res.append(_MAT[nxt])
                if nn == "ं":
                    lab = (s[i + 3] if i + 3 < n else "") in _LABIAL
                    res.append("m" if lab else "n"); i += 3; continue
                i += 2; continue
            res.append("a"); i += 1; continue
        if ch in _VOW:
            res.append(_VOW[ch])
            if nxt == "ं":
                res.append("m" if nn in _LABIAL else "n"); i += 2; continue
            i += 1; continue
        if ch == "ं":
            res.append("m" if nxt in _LABIAL else "n"); i += 1; continue
        if ch in _MAT:
            res.append(_MAT[ch]); i += 1; continue
        res.append(" " if ch.isspace() else "")
        i += 1
    return "".join(res)


_ABBR = [(r"\bbk\b", "budruk"), (r"\bbu\b", "budruk"), (r"\bbdr\b", "budruk"),
         (r"\bkh\b", "khurd"), (r"\bkhu\b", "khurd"), (r"\bkhd\b", "khurd")]
_EN_FILL = {"mouje", "mauje", "mouja", "moje", "ta", "tarf", "taraf", "taraf"}


def _skel(s):
    """Latin consonant-skeleton token set; works for Devanagari or English."""
    s = _translit(s) if _DEVANAGARI.search(s) else s.lower()
    s = s.replace(".", " ")
    s = re.sub(r"[^a-z\s]", " ", s)
    for pat, rep in _ABBR:
        s = re.sub(pat, rep, s)
    toks = set()
    for t in s.split():
        if t in _EN_FILL:
            continue
        t = re.sub(r"[aeiou]", "", t)            # drop vowels
        t = t.replace("v", "").replace("w", "")  # semivowels ~ silent
        t = re.sub(r"(.)\1+", r"\1", t)          # collapse doubles
        if t:
            toks.add(t)
    return toks


def _match_skel(sel, *wanted_names):
    """Match by transliterated skeleton (for English option lists on ASR 2.0)."""
    cands = [w for w in wanted_names if w]
    qsets = [(_skel(w)) for w in cands]
    qsets = [q for q in qsets if q]
    if not qsets:
        return None, None
    opt_sets = [(val, txt, _skel(txt)) for val, txt in sel["options"]
                if val and "select" not in txt.lower() and "निवडा" not in txt]
    for q in qsets:                              # exact skeleton-set equality
        for val, txt, o in opt_sets:
            if o and o == q:
                return val, txt
    best = None                                  # query fully inside an option
    for q in qsets:
        for val, txt, o in opt_sets:
            if o and q <= o:
                score = len(o ^ q)
                if best is None or score < best[0]:
                    best = (score, val, txt)
    if best and best[0] <= 1:                     # accept only if unambiguous/close
        return best[1], best[2]
    return None, None


def _is_english_list(sel):
    return sel and not any(_DEVANAGARI.search(t) for _, t in sel["options"])


def _extract_rates(soup):
    unit_set = ("हेक्टर", "चौ. मीटर", "चौ.मीटर", "चौरस मीटर", "चौ. मी.", "मीटर")
    out, seen = [], set()
    for tr in soup.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if any(len(c) > 500 for c in cells):   # skip merged form/container rows only
            continue
        nums = [c for c in cells if _RATE.match(c)]
        units = [c for c in cells if len(c) <= 14 and any(u in c for u in unit_set)]
        if not (nums and units):
            continue
        code = next((c for c in cells if _CODE.match(c)), "")
        rate = int(nums[-1].replace(",", ""))
        unit = units[-1]
        skip = set(nums) | set(units) | {code, "SurveyNo", "Select", "गट नंबर"}
        # avoid the merged header/summary cell (it repeats the rate + header words)
        def _good(c):
            return (str(rate) not in c and "उपविभाग" not in c
                    and "Attribute" not in c and "एकक" not in c)
        descs = [c for c in cells if c not in skip and _good(c)]
        desc = max(descs, key=len) if descs else ""
        desc = re.sub(r"^\s*\d+(?:\.\d+)?-\s*", "", desc)        # drop "11.5-" prefix
        desc = re.sub(r"\b(सर्वेक्षण\s*नंबर|गट\s*नंबर|SurveyNo)\b", "", desc)
        desc = re.sub(r"\s+", " ", desc).strip(" -")
        key = (code, rate, unit)
        if key in seen:
            continue
        seen.add(key)
        out.append({"code": code, "desc": desc, "rate": rate, "unit": unit})
    return out


def _dump_controls(soup):
    radios = []
    for r in soup.find_all("input", {"type": "radio"}):
        lbl = ""
        if r.get("id"):
            l = soup.find("label", {"for": r.get("id")})
            if l:
                lbl = l.get_text(strip=True)
        radios.append({"name": r.get("name"), "value": r.get("value"),
                       "id": r.get("id"), "label": lbl, "checked": r.has_attr("checked")})
    texts = [{"name": i.get("name"), "id": i.get("id")}
             for i in soup.find_all("input")
             if (i.get("type") or "text") == "text"]
    buttons = [{"name": b.get("name"), "value": b.get("value"), "id": b.get("id"),
                "type": b.get("type")}
               for b in soup.find_all(["input", "button"])
               if b.get("type") in ("submit", "button") or b.name == "button"]
    selects = [{"name": s.get("name"),
                "options": [o.get_text(strip=True) for o in s.find_all("option")][:30]}
               for s in soup.find_all("select")]
    return {"radios": radios, "text_inputs": texts, "buttons": buttons, "selects": selects}


def _survey_search(a, survey_no):
    """Switch to 'Survey No' mode (own postback), then fill the gut number and Search."""
    soup = a.soup

    # locate the Survey-No radio
    radio_name = radio_val = None
    for r in soup.find_all("input", {"type": "radio"}):
        rid = (r.get("id") or "").lower()
        lbl = ""
        if r.get("id"):
            l = soup.find("label", {"for": r.get("id")})
            if l:
                lbl = l.get_text(strip=True)
        blob = (rid + " " + lbl).lower()
        if "surveyno" in rid or "survey no" in lbl.lower() or "सर्व्हे" in lbl or "गट" in lbl:
            radio_name, radio_val = r.get("name"), r.get("value")
            break

    # step 1: switch the radio to Survey No (AutoPostBack)
    prefix = "ctl00$ContentPlaceHolder5$"
    if radio_name and "$" in radio_name:
        prefix = radio_name.rsplit("$", 1)[0] + "$"
    else:
        for s in a.selects():                       # derive prefix from a known select
            if s.get("name") and "$" in s["name"]:
                prefix = s["name"].rsplit("$", 1)[0] + "$"
                break
        radio_name, radio_val = prefix + "grpSurveyLocation", "rdbSurveyNo"
    if radio_name and radio_val:
        a.postback(radio_name, radio_val)
        soup = a.soup

    # (re)discover field + button on the updated page
    survey_field = None
    for i in soup.find_all("input"):
        if (i.get("type") or "text") != "text":
            continue
        nm = ((i.get("name") or "") + " " + (i.get("id") or "")).lower()
        if any(k in nm for k in ("commonsurvey", "survey", "serveyno", "srno", "srvy", "txtsr")):
            survey_field = i.get("name")
            break

    btn = None
    for b in soup.find_all(["input", "button"]):
        if b.name == "button" or b.get("type") in ("submit", "button"):
            blob = ((b.get("value") or "") + " " + (b.get("name") or "") + " " +
                    (b.get("id") or "")).lower()
            if "searchcommonsr" in blob or "search" in blob or "शोध" in (b.get("value") or ""):
                btn = (b.get("name"), b.get("value", ""))
                break

    # fallback to the known e-ASR control names if the partial page hid them
    if not survey_field:
        survey_field = prefix + "txtCommonSurvey"
    if not btn or not btn[0]:
        btn = (prefix + "btnSearchCommonSr", "Search")

    # step 2: fill survey number + click Search
    extra = {}
    if radio_name and radio_val:
        extra[radio_name] = radio_val
    extra[survey_field] = str(survey_no)
    extra[btn[0]] = btn[1]
    a.submit(extra=extra, event_target="")

    return {"radio": [radio_name, radio_val], "survey_field": survey_field,
            "button": btn, "rates_found": len(_extract_rates(a.soup))}


def _location_search(a, land_type="जिरायत"):
    """Location mode (default): pick a vibhag (land-type) and read the zone rate."""
    zsel = None
    for s in a.selects():
        blob = " ".join(t for _, t in s["options"])
        if any(k in blob for k in ("जिरायत", "बागायत", "बिनशेती", "उर्वरीत", "गायरान")):
            zsel = s
            break
    if not zsel:
        return {"vibhag": None}
    zv, zt = _match_option(zsel, land_type)
    if not zv:  # first real (non-placeholder) option
        for val, txt in zsel["options"]:
            if val and "निवडा" not in txt and txt not in ("NA", "--", ""):
                zv, zt = val, txt
                break
    if zv:
        a.postback(zsel["name"], zv)
    return {"vibhag": zt}


TALUKA_ALIASES = {
    "औरंगाबाद": ["छत्रपती संभाजीनगर", "संभाजीनगर"],
    "छत्रपती संभाजीनगर": ["औरंगाबाद"],
    "उस्मानाबाद": ["धाराशिव"],
    "धाराशिव": ["उस्मानाबाद"],
    "अहमदनगर": ["अहिल्यानगर"],
    "अहिल्यानगर": ["अहमदनगर"],
}


def get_rr_rate(district_en, taluka_mr, village_mr, survey_no=None,
                village_value=None, taluka_value=None, year=None,
                portal=None, debug=False):
    last = {}
    portals = [portal] if portal else PORTALS
    for portal in portals:
        d = {"portal": portal, "steps": []}
        try:
            a = _ASR(portal, district_en)
            st, sz = a.get()
            d["steps"].append(f"GET {st} ({sz}b)")
            if st != 200 or sz < 500:
                last = d
                continue

            is_v2 = "easr2" in portal.lower() or "igreval" in portal.lower()
            # ASR 2.0 only works in English (the Marathi switch redirects to the
            # portal home). 1.x switches to Marathi fine. We match cross-script,
            # so navigating 2.0 in English is OK.
            lang = a.find_select_by_name("language", "lang")
            if lang and not is_v2:
                lv, _ = _match_option(lang, "Marathi")
                if lv:
                    a.postback(lang["name"], lv)
                    if not a.find_select_by_name("taluka", "tehsil", "tahsil"):
                        a.get()      # switch broke scope -> re-GET the district page

            if year:
                ysel = a.find_select_by_name("year", "varsh")
                if ysel:
                    yv, _ = _match_option(ysel, str(year))
                    if yv:
                        a.postback(ysel["name"], yv)

            tsel = a.find_select_by_name("taluka", "tehsil", "tahsil")
            if tsel:
                joined = " ".join(t for _, t in tsel["options"])
                d["taluka_lang"] = "marathi" if _DEVANAGARI.search(joined) else "english"
            if not tsel:
                d["error_at"] = "no taluka dropdown"
                last = d
                continue
            if taluka_value is not None:
                tv, tt = next(((v, t) for v, t in tsel["options"]
                               if v == taluka_value), (None, None))
            elif _is_english_list(tsel):                 # ASR 2.0 (English)
                names = [taluka_mr] + TALUKA_ALIASES.get(_norm(taluka_mr), [])
                tv, tt = _match_skel(tsel, *names)
            else:                                        # 1.x (Marathi)
                tv, tt = _match_option(tsel, taluka_mr)
                if not tv:  # try known renames (Aurangabad->Sambhajinagar, etc.)
                    for alias in TALUKA_ALIASES.get(_norm(taluka_mr), []):
                        tv, tt = _match_option(tsel, alias)
                        if tv:
                            break
            d["steps"].append(f"taluka {taluka_mr!r} -> {tt!r}")
            if not tv:
                opts = [[v, t] for v, t in tsel["options"]
                        if v and "Select" not in t and "निवडा" not in t and v != "0"]
                return {"ok": False, "need_taluka": True, "taluka_options": opts,
                        "diagnostics": d}
            a.postback(tsel["name"], tv)

            vsel = a.find_select_by_name("village", "gaav", "gav")
            if not vsel:
                d["error_at"] = "no village dropdown"
                last = d
                continue
            if village_value is not None:
                vv, vt = next(((val, txt) for val, txt in vsel["options"]
                               if val == village_value), (None, None))
            elif _is_english_list(vsel):                 # ASR 2.0 (English)
                vv, vt = _match_skel(vsel, village_mr)
            else:                                        # 1.x (Marathi)
                vv, vt = _match_village(vsel, village_mr)
            d["steps"].append(f"village {village_mr!r} -> {vt!r}")
            if not vv:
                opts = [[val, txt] for val, txt in vsel["options"]
                        if val and "निवडा" not in txt and "Select" not in txt and val != "0"]
                return {"ok": False, "need_village": True, "village_options": opts,
                        "diagnostics": d}
            a.postback(vsel["name"], vv)

            # snapshot the post-village page so we can try a second strategy
            snap_form = dict(a.form)
            snap_soup = a.soup
            if debug:
                d["controls_after_village"] = _dump_controls(a.soup)

            rates, mode = [], None

            # strategy 1: gut-specific survey-number search
            if survey_no:
                d["search"] = _survey_search(a, survey_no)
                d["steps"].append(f"survey search gut {survey_no}")
                rates = _extract_rates(a.soup)
                if rates:
                    mode = "survey"

            # strategy 2: fall back to Location / vibhag (zone) rate
            if not rates:
                a.form, a.soup = dict(snap_form), snap_soup
                info = _location_search(a)
                d["location"] = info
                d["steps"].append(f"location vibhag -> {info.get('vibhag')!r}")
                rates = _extract_rates(a.soup)
                if rates:
                    mode = "location"

            if not rates:
                d["error_at"] = "no rate rows parsed"
                if "controls_after_village" not in d:
                    d["controls_after_village"] = _dump_controls(a.soup)
                last = d
                continue

            out = {"ok": True, "rates": rates, "mode": mode, "note": portal}
            if debug:
                out["diagnostics"] = d
            return out
        except Exception as e:
            d["exception"] = repr(e)
            last = d
            continue

    return {"ok": False, "error": "Could not retrieve ASR rate.", "diagnostics": last}


# ---------------------------------------------------------------------------
# Taluka rate explorer: list every village in a taluka with its baseline
# farmland (जिरायत, ₹/hectare) and developed (गावठाण/बिनशेती, ₹/sq.m) rate.
# This is a BATCH scrape (one taluka = a few hundred requests) - cache it.
# ---------------------------------------------------------------------------
def _clean_vname(txt):
    t = re.sub(r"^(मौजे|Mouje|Mauje)\s*:?\s*", "", _norm(txt)).strip()
    return t or _norm(txt)


def _vibhag_rate(a, keywords, prefer_unit=None, prefer_desc=None):
    """Select a vibhag (land-type) by keyword and return (rate, unit, desc)."""
    zsel = None
    for s in a.selects():
        blob = " ".join(t for _, t in s["options"])
        if any(k in blob for k in ("जिरायत", "बागायत", "बिनशेती", "गावठाण",
                                    "गायरान", "उर्वर")):
            zsel = s
            break
    if not zsel:
        return (None, None, None)
    target = None
    for kw in keywords:
        for val, txt in zsel["options"]:
            if val and kw in txt and "निवडा" not in txt:
                target = (val, txt)
                break
        if target:
            break
    if not target:
        return (None, None, None)
    a.postback(zsel["name"], target[0])
    rates = _extract_rates(a.soup)
    if not rates:
        return (None, None, None)
    cands = rates
    if prefer_unit:
        u = [r for r in rates if prefer_unit in r["unit"]]
        if u:
            cands = u
    if prefer_desc:
        p = [r for r in cands if prefer_desc in r["desc"]]
        if p:
            cands = p
    r = min(cands, key=lambda x: x["rate"])          # baseline = lowest in group
    return (r["rate"], r["unit"], r["desc"])


def taluka_rate_table(district_en, taluka_mr, year=None, max_villages=None,
                      progress=None, portal=None):
    portals = [portal] if portal else PORTALS
    for portal in portals:
        try:
            a = _ASR(portal, district_en)
            stt, sz = a.get()
            if stt != 200 or sz < 500:
                continue
            is_v2 = "easr2" in portal.lower() or "igreval" in portal.lower()
            lang = a.find_select_by_name("language", "lang")
            if lang and not is_v2:
                lv, _ = _match_option(lang, "Marathi")
                if lv:
                    a.postback(lang["name"], lv)
                    if not a.find_select_by_name("taluka", "tehsil", "tahsil"):
                        a.get()
            if year:
                ysel = a.find_select_by_name("year", "varsh")
                if ysel:
                    yv, _ = _match_option(ysel, str(year))
                    if yv:
                        a.postback(ysel["name"], yv)

            tsel = a.find_select_by_name("taluka", "tehsil", "tahsil")
            if not tsel:
                continue
            if _is_english_list(tsel):
                names = [taluka_mr] + TALUKA_ALIASES.get(_norm(taluka_mr), [])
                tv, tt = _match_skel(tsel, *names)
            else:
                tv, tt = _match_option(tsel, taluka_mr)
                if not tv:
                    for al in TALUKA_ALIASES.get(_norm(taluka_mr), []):
                        tv, tt = _match_option(tsel, al)
                        if tv:
                            break
            if not tv:
                return {"ok": False, "error": "taluka not matched",
                        "taluka_options": [t for _, t in tsel["options"]]}
            a.postback(tsel["name"], tv)

            vsel = a.find_select_by_name("village", "gaav", "gav")
            if not vsel:
                continue
            villages = [(val, txt) for val, txt in vsel["options"]
                        if val and "निवडा" not in txt and "Select" not in txt
                        and val != "0"]
            if max_villages:
                villages = villages[:max_villages]

            base_form, base_soup = dict(a.form), a.soup
            vname = vsel["name"]
            rows, total = [], len(villages)
            for i, (vval, vtxt) in enumerate(villages):
                if progress:
                    progress(i, total, _clean_vname(vtxt))
                try:
                    a.form, a.soup = dict(base_form), base_soup
                    a.postback(vname, vval)
                    vform, vsoup = dict(a.form), a.soup
                    farm = _vibhag_rate(a, ["जिरायत"], prefer_unit="हेक्टर",
                                        prefer_desc="उर्वर")
                    a.form, a.soup = dict(vform), vsoup
                    dev = _vibhag_rate(a, ["गावठाण", "बिनशेती संभाव्यता", "बिनशेती"],
                                       prefer_unit="मीटर")
                    rows.append({"village": _clean_vname(vtxt),
                                 "farmland_rate": farm[0], "farmland_unit": farm[1],
                                 "developed_rate": dev[0], "developed_unit": dev[1]})
                except Exception as e:
                    rows.append({"village": _clean_vname(vtxt),
                                 "farmland_rate": None, "developed_rate": None,
                                 "error": repr(e)})
            if progress:
                progress(total, total, "done")
            return {"ok": True, "portal": portal, "taluka": tt,
                    "count": len(rows), "rows": rows}
        except Exception:
            continue
    return {"ok": False, "error": "Could not load taluka village rates."}


# --- District name resolution: CSV Marathi -> e-ASR English (hDistName) ---
DISTRICT_EN = {
    "अहमदनगर": "Ahmadnagar", "अहिल्यानगर": "Ahmadnagar", "अकोला": "Akola",
    "अमरावती": "Amravati", "औरंगाबाद": "Aurangabad", "छत्रपती संभाजीनगर": "Aurangabad",
    "संभाजीनगर": "Aurangabad", "बीड": "Beed", "भंडारा": "Bhandara",
    "बुलढाणा": "Buldhana", "चंद्रपूर": "Chandrapur", "धुळे": "Dhule",
    "गडचिरोली": "Gadchiroli", "गोंदिया": "Gondia", "हिंगोली": "Hingoli",
    "जळगाव": "Jalgaon", "जालना": "Jalna", "कोल्हापूर": "Kolhapur", "लातूर": "Latur",
    "मुंबई शहर": "Mumbai City", "मुंबई उपनगर": "Mumbai Suburban", "नागपूर": "Nagpur",
    "नांदेड": "Nanded", "नंदुरबार": "Nandurbar", "नाशिक": "Nashik",
    "उस्मानाबाद": "Osmanabad", "धाराशिव": "Osmanabad", "पालघर": "Palghar",
    "परभणी": "Parbhani", "पुणे": "Pune", "रायगड": "Raigad", "रत्नागिरी": "Ratnagiri",
    "सांगली": "Sangli", "सातारा": "Satara", "सिंधुदुर्ग": "Sindhudurg",
    "सोलापूर": "Solapur", "ठाणे": "Thane", "वर्धा": "Wardha", "वाशिम": "Washim",
    "यवतमाळ": "Yavatmal",
}


def resolve_district_en(csv_district):
    n = _norm(csv_district)
    if n in DISTRICT_EN:
        return DISTRICT_EN[n]
    nl = _loose(n)
    for mr, en in DISTRICT_EN.items():
        if _loose(mr) == nl:
            return en
    return n
