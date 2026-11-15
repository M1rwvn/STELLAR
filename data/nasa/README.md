# NASA data used by STELLAR

Real NASA space-weather data for 2024-08-25 .. 2024-10-23 (60 days, solar maximum), replayed as mission days 1-60.
Made by `scripts/fetch_nasa_space_weather.py` (re-run it to download again from NASA).

| File | Source | Content |
|---|---|---|
| `omni_kp_dst_hourly.csv` | NASA Goddard Space Flight Center, Space Physics Data Facility - OMNIWeb, OMNI2 hourly data (`omni2_2024.dat`), https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/ | hourly Kp (planetary geomagnetic index) and Dst (nT) |
| `donki_sep.json` | NASA Space Weather Database Of Notifications, Knowledge, Information (DONKI), Community Coordinated Modeling Center (CCMC), NASA GSFC, via https://api.nasa.gov (`/DONKI/SEP`) | solar energetic particle events (instrument, time, link) |
| `donki_gst.json` | NASA DONKI (CCMC), via https://api.nasa.gov (`/DONKI/GST`) | geomagnetic storms (start, Kp maximum, link) |

Each event keeps its DONKI link (https://ccmc.gsfc.nasa.gov/DONKI/view/...).
Note: the OMNI2 proton-flux columns are empty for 2024, so radiation storms come from DONKI SEP events
measured by GOES at Earth orbit.
