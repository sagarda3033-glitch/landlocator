"""
pages/9_Connectivity_Test.py  —  TEMPORARY diagnostic.
Checks whether the government portals respond from wherever this app runs.
Run it on the DEPLOYED app (Streamlit Cloud) — that's the real test of the
"no VPS" plan. Delete this file once we've read the results.
"""
import time
import requests
import streamlit as st

st.set_page_config(page_title="Connectivity Test", layout="centered")
st.title("🔌 Portal Connectivity Test")
st.caption("Tests if each portal responds from THIS server. Run on the deployed "
           "app (not just locally) — local always works because it's an India IP.")

TARGETS = {
    "Bhunaksha (control — should WORK)":
        "https://mahabhunakasha.mahabhumi.gov.in/27/index.html",
    "e-Mojni 2 (mahabhumi)":
        "https://emojni2.mahabhumi.gov.in/",
    "Aapli Chawadi (mahabhumi)":
        "https://echawadicitizen.mahabhumi.gov.in/",
    "e-ASR (control — known BLOCKED on Streamlit Cloud)":
        "https://easr.igrmaharashtra.gov.in/eASRCommon.aspx",
}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

if st.button("Run connectivity test", type="primary"):
    for name, url in TARGETS.items():
        t0 = time.time()
        try:
            r = requests.get(url, headers=UA, timeout=25, allow_redirects=True)
            dt = time.time() - t0
            ok = r.status_code == 200 and len(r.text) > 300
            (st.success if ok else st.warning)(
                f"**{name}**\n\n`{url}`\n\n"
                f"status **{r.status_code}**, {len(r.text):,} bytes, {dt:.1f}s")
        except requests.exceptions.RequestException as e:
            dt = time.time() - t0
            st.error(f"**{name}**\n\n`{url}`\n\n"
                     f"FAILED after {dt:.1f}s — {type(e).__name__}: {str(e)[:200]}")
    st.info("Reading: if e-Mojni and Aapli Chawadi show green (200) like Bhunaksha, "
            "the no-VPS plan is viable. If they FAIL like e-ASR, they're IP-blocked "
            "and would need an India server.")
else:
    st.write("Click the button above to test all four portals from this server.")

