"""
app.py  -  Maharashtra Land Locator (web / deploy build)

Browser-free version for hosting on Streamlit Community Cloud (or similar).
Run locally with:  streamlit run app.py
"""

import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium

from services.bhunaksha_service import get_plot_info
from services.asr_service import get_rr_rate, resolve_district_en
from utils.gis_utils import build_gis_code, get_point_latlon, get_polygons_latlon

st.set_page_config(page_title="Maharashtra Land Locator", layout="wide")
st.title("🏞 Maharashtra Land Locator")


@st.cache_data(show_spinner=False, ttl=86400)
def cached_plot_info(giscode, gut):
    """Cache results for a day so repeat lookups don't re-hit Bhunaksha."""
    return get_plot_info(giscode, gut)


@st.cache_data(show_spinner=False, ttl=86400)
def cached_rr_rate(district_csv, taluka, village, survey_no,
                   village_value=None, taluka_value=None):
    return get_rr_rate(resolve_district_en(district_csv), taluka, village,
                       survey_no=survey_no, village_value=village_value,
                       taluka_value=taluka_value)


if "result" not in st.session_state:
    st.session_state.result = None
if "ctx" not in st.session_state:
    st.session_state.ctx = {}

df = pd.read_csv("data/locations.csv", dtype=str)

district = st.selectbox("District", sorted(df.District.unique()))
dd = df[df.District == district]
taluka = st.selectbox("Taluka", sorted(dd.Taluka.unique()))
td = dd[dd.Taluka == taluka]
village = st.selectbox("Village", sorted(td.Village.unique()))
sel = td[td.Village == village].iloc[0]

giscode = build_gis_code("R", sel["District_Code"], sel["Taluka_Code"], sel["Village_Code"])
st.info(f"Generated GIS Code: {giscode}")

gut = st.text_input("Gut Number")

if st.button("Locate Plot"):
    if not gut.strip():
        st.warning("Enter Gut Number")
        st.stop()
    st.session_state.ctx = {
        "district": district,
        "district_code": sel["District_Code"],
        "taluka": taluka,
        "village": village,
        "gut": gut.strip(),
    }
    with st.spinner("Fetching plot from Bhunaksha…"):
        st.session_state.result = cached_plot_info(giscode, gut.strip())

data = st.session_state.result
ctx = st.session_state.ctx

if data is not None:
    if isinstance(data, dict) and data.get("error"):
        st.error(data["error"])
        st.code(data.get("body", ""))

    elif not isinstance(data, dict) or not data.get("the_geom"):
        st.error("No geometry in the response — see raw output below.")
        st.json(data)

    else:
        dh = ctx.get("district")
        dc = ctx.get("district_code")
        rings = get_polygons_latlon(data["the_geom"], district=dh, district_code=dc)
        lat, lon = get_point_latlon(data["the_geom"], district=dh, district_code=dc)

        map_col, info_col = st.columns([2, 1])

        with info_col:
            st.success(f"Latitude:  {lat:.6f}")
            st.success(f"Longitude: {lon:.6f}")
            st.markdown(f"[📍 Open in Google Maps](https://www.google.com/maps?q={lat},{lon})")
            if data.get("formatedArea"):
                st.metric("Area (sq. m)", data["formatedArea"])
            if data.get("info"):
                with st.expander("👤 Owner / survey details", expanded=False):
                    st.text(data["info"])
            with st.expander("Raw response"):
                st.json(data)

            st.markdown("---")
            st.subheader("💰 Ready Reckoner Rate (ASR)")
            with st.spinner("Fetching rate from IGR e-ASR…"):
                asr = cached_rr_rate(ctx.get("district"), ctx.get("taluka"),
                                     ctx.get("village"), ctx.get("gut"))

            chosen_tv = None
            # taluka name differs on e-ASR (e.g. renamed) -> let the user pick it
            if asr.get("need_taluka"):
                opts = asr["taluka_options"]
                labels = [t for _, t in opts]
                st.caption(f"Couldn't auto-match taluka '{ctx.get('taluka')}' on e-ASR — "
                           "pick it:")
                pick = st.selectbox("e-ASR taluka", labels, key="asr_tal")
                chosen_tv = next(v for v, t in opts if t == pick)
                with st.spinner("Fetching rate…"):
                    asr = cached_rr_rate(ctx.get("district"), ctx.get("taluka"),
                                         ctx.get("village"), ctx.get("gut"),
                                         taluka_value=chosen_tv)

            # village name differs on e-ASR -> let the user pick it
            if asr.get("need_village"):
                opts = asr["village_options"]
                labels = [t for _, t in opts]
                st.caption(f"Couldn't auto-match '{ctx.get('village')}' on e-ASR — "
                           "pick the matching village:")
                pick = st.selectbox("e-ASR village", labels, key="asr_vill")
                chosen_val = next(v for v, t in opts if t == pick)
                with st.spinner("Fetching rate…"):
                    asr = cached_rr_rate(ctx.get("district"), ctx.get("taluka"),
                                         ctx.get("village"), ctx.get("gut"),
                                         village_value=chosen_val, taluka_value=chosen_tv)

            if asr.get("ok") and asr.get("rates"):
                try:
                    area_sqm = float(str(data.get("formatedArea", "")).replace(",", ""))
                except ValueError:
                    area_sqm = None

                def row_value(r):
                    if not area_sqm:
                        return None
                    if "हेक्टर" in r["unit"]:
                        return area_sqm / 10000.0 * r["rate"]
                    if "मीटर" in r["unit"]:
                        return area_sqm * r["rate"]
                    return None

                rows = []
                for r in asr["rates"]:
                    v = row_value(r)
                    rows.append({"विभाग": r["code"], "वर्णन": r["desc"],
                                 "दर (₹)": f"{r['rate']:,}", "एकक": r["unit"],
                                 "मूल्य (₹)": f"{v:,.0f}" if v else "—"})
                st.dataframe(pd.DataFrame(rows), hide_index=True,
                             use_container_width=True)

                # headline: the gut's applicable rate (first row that yields a value)
                prim = next((r for r in asr["rates"] if row_value(r) is not None), None)
                if prim and area_sqm:
                    v = row_value(prim)
                    per = (f"{prim['rate']:,}/sq.m × {area_sqm:,.0f} sq.m"
                           if "मीटर" in prim["unit"]
                           else f"{prim['rate']:,}/hectare × {area_sqm/10000:.4f} ha")
                    st.metric("Indicative land value", f"₹ {v:,.0f}",
                              help=f"विभाग {prim['code']} — {per}")
                st.caption(
                    ("Gut-specific rate" if asr.get("mode") == "survey"
                     else "Village/zone rate (no gut-specific entry)")
                    + " — Source: IGR Maharashtra e-ASR. Indicative estimate (rate × area).")
            else:
                st.info(f"ASR rate not found for gut {ctx.get('gut')}.")
                with st.expander("ASR debug"):
                    st.write({
                        "sent_district_en": resolve_district_en(ctx.get("district")),
                        "sent_taluka": ctx.get("taluka"),
                        "sent_village": ctx.get("village"),
                        "sent_gut": ctx.get("gut"),
                    })
                    st.json(asr.get("diagnostics", {}))

        with map_col:
            m = folium.Map(location=[lat, lon], zoom_start=18, tiles=None)
            folium.TileLayer("OpenStreetMap", name="Street").add_to(m)
            folium.TileLayer(
                tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                attr="Esri World Imagery",
                name="Satellite",
            ).add_to(m)
            for ring in rings:
                folium.Polygon(ring, color="red", weight=2, fill=True, fill_opacity=0.15).add_to(m)
            folium.Marker([lat, lon], popup=f"Gut {ctx.get('gut', '')}").add_to(m)
            folium.LayerControl().add_to(m)
            st_folium(m, width=900, height=600)
