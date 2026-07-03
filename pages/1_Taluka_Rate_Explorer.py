"""
pages/1_Taluka_Rate_Explorer.py

For a chosen taluka, scrape every village's baseline rates from IGR e-ASR 2.0:
  - Farmland  = जिरायत (उर्वरित) land, ₹/hectare
  - Developed = गावठाण / बिनशेती संभाव्यता, ₹/sq.m
then rank to show the cheapest villages by each basis.

NOTE: this is a batch scrape - a full taluka (200+ villages) takes a few
minutes the first time. Results are kept for the session; use "Rebuild" to refresh.
"""

import io
import pandas as pd
import streamlit as st

from services.asr_service import taluka_rate_table, resolve_district_en

st.set_page_config(page_title="Taluka Rate Explorer", layout="wide")
st.title("📊 Taluka Rate Explorer")
st.caption("Find the villages with the lowest Ready Reckoner (ASR) rates in a taluka.")

df = pd.read_csv("data/locations.csv", dtype=str)

c1, c2, c3 = st.columns([3, 3, 2])
with c1:
    district = st.selectbox("District", sorted(df.District.unique()))
dd = df[df.District == district]
with c2:
    taluka = st.selectbox("Taluka", sorted(dd.Taluka.unique()))
with c3:
    test_n = st.number_input("Test: first N villages (0 = all)",
                             min_value=0, max_value=2000, value=0, step=10,
                             help="Start with e.g. 10 to verify quickly, then run all.")

key = f"trt::{district}::{taluka}::{test_n}"
go = st.button("Build / rebuild rate table", type="primary")

if go:
    bar = st.progress(0.0, text="Starting…")
    status = st.empty()

    def _progress(i, total, name):
        frac = (i / total) if total else 1.0
        bar.progress(min(frac, 1.0), text=f"{i}/{total} villages — {name}")

    with st.spinner("Scraping e-ASR 2.0 (this can take a few minutes)…"):
        res = taluka_rate_table(
            resolve_district_en(district), taluka,
            max_villages=(int(test_n) or None), progress=_progress,
        )
    bar.empty()
    status.empty()
    st.session_state[key] = res

res = st.session_state.get(key)

if not res:
    st.info("Pick a district + taluka and click **Build** to fetch village rates. "
            "Tip: set *Test: first N villages* to 10 for a quick trial run first.")
    st.stop()

if not res.get("ok"):
    st.error(res.get("error", "Could not load."))
    if res.get("taluka_options"):
        st.write("Talukas e-ASR offers for this district:", res["taluka_options"])
    st.stop()

rows = res["rows"]
data = pd.DataFrame(rows)
data["Farmland ₹/ha (जिरायत)"] = pd.to_numeric(data.get("farmland_rate"), errors="coerce")
data["Developed ₹/sq.m (गावठाण/बिनशेती)"] = pd.to_numeric(data.get("developed_rate"), errors="coerce")
view = data.rename(columns={"village": "Village"})[
    ["Village", "Farmland ₹/ha (जिरायत)", "Developed ₹/sq.m (गावठाण/बिनशेती)"]]

got_farm = int(view["Farmland ₹/ha (जिरायत)"].notna().sum())
got_dev = int(view["Developed ₹/sq.m (गावठाण/बिनशेती)"].notna().sum())
st.success(f"{res['taluka']}: {res['count']} villages — "
           f"farmland rate for {got_farm}, developed rate for {got_dev}. "
           f"Source: IGR e-ASR ({res.get('portal','')}).")

low_farm = view.dropna(subset=["Farmland ₹/ha (जिरायत)"]).nsmallest(
    10, "Farmland ₹/ha (जिरायत)").reset_index(drop=True)
low_dev = view.dropna(subset=["Developed ₹/sq.m (गावठाण/बिनशेती)"]).nsmallest(
    10, "Developed ₹/sq.m (गावठाण/बिनशेती)").reset_index(drop=True)

a, b = st.columns(2)
with a:
    st.subheader("🌾 10 lowest — farmland (जिरायत)")
    st.dataframe(low_farm[["Village", "Farmland ₹/ha (जिरायत)"]],
                 hide_index=True, use_container_width=True)
with b:
    st.subheader("🏘 10 lowest — developed (गावठाण/बिनशेती)")
    st.dataframe(low_dev[["Village", "Developed ₹/sq.m (गावठाण/बिनशेती)"]],
                 hide_index=True, use_container_width=True)

st.markdown("---")
st.subheader("All villages (sortable)")
st.caption("Click a column header to sort. Blank = no rate of that type on e-ASR for that village.")
st.dataframe(view.sort_values("Farmland ₹/ha (जिरायत)", na_position="last"),
             hide_index=True, use_container_width=True, height=480)

csv = view.to_csv(index=False).encode("utf-8-sig")
st.download_button("⬇ Download CSV", csv,
                   file_name=f"{district}_{taluka}_asr_rates.csv", mime="text/csv")

st.caption("Indicative ASR (Ready Reckoner) rates from IGR Maharashtra e-ASR. "
           "Farmland = lowest जिरायत ₹/hectare; Developed = lowest गावठाण/बिनशेती ₹/sq.m. "
           "Actual valuation depends on a plot's exact classification and survey number.")
