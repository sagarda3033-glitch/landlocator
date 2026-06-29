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
from utils.gis_utils import build_gis_code, get_point_latlon, get_polygons_latlon

st.set_page_config(page_title="Maharashtra Land Locator", layout="wide")
st.title("🏞 Maharashtra Land Locator")


@st.cache_data(show_spinner=False, ttl=86400)
def cached_plot_info(giscode, gut):
    """Cache results for a day so repeat lookups don't re-hit Bhunaksha."""
    return get_plot_info(giscode, gut)


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
                st.text(data["info"])
            with st.expander("Raw response"):
                st.json(data)

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
