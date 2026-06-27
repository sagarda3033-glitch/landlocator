# Maharashtra Land Locator (web build)

Find the latitude/longitude and map of a Gut (plot) from
District / Taluka / Village using the Maharashtra Bhunaksha service.

This is the **browser-free** build (uses `requests`, no Playwright/Chromium),
so it runs on free hosts like Streamlit Community Cloud.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Before deploying
Replace `data/locations.csv` with your full list. Columns required:

| District | Taluka | Village | District_Code | Taluka_Code | Village_Code |
|----------|--------|---------|---------------|-------------|--------------|

`Village_Code` must be the FULL long code (e.g. `270800010083670000`),
not a short serial number.

## Deploy free (Streamlit Community Cloud)
1. Push this whole folder to a GitHub repo.
2. Go to https://share.streamlit.io , sign in with GitHub, "Create app".
3. Pick the repo, branch `main`, main file `app.py`, Deploy.
4. You get a URL like https://your-app.streamlit.app

## Show it on 712property.com
In WordPress, add a Page with a Custom HTML block:
```html
<iframe src="https://YOUR-APP.streamlit.app/?embed=true"
        style="width:100%;height:850px;border:none;"></iframe>
```

## Notes
- Map: toggle the layer control (top-right) for satellite imagery.
- UTM zone (43N west / 44N east) is auto-selected per plot.
- If a district is consistently offset vs satellite, set a nudge in
  `utils/gis_utils.py` -> `DISTRICT_OFFSETS`.
