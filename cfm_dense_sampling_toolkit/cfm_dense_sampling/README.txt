CFM dense sampling toolkit
==========================

Files
-----
1) generate_transects.py
   Generates a dense set of parallel transect lines across a farm/area polygon and writes them to GeoJSON.

2) cfm_batch_export.py
   Uses Playwright to automate Cape Farm Mapper, import the transects GeoJSON, run Elevation Profile for each line,
   and save each profile as a CSV file.

3) merge_profile_csvs.py
   Merges all downloaded profile CSV files into one master CSV.

4) build_kmz_corridor_boundary.py
   Builds an approximate corridor polygon from KMZ anchor points so the toolkit can run from end-point markers.

5) map_cfm_profiles.py
   Converts exported CFM profile CSV files into spatial points along the transects and renders a map PNG.

Recommended workflow
--------------------
A. Build a corridor boundary from KMZ anchors
   python build_kmz_corridor_boundary.py --station-kmz "Station 0 (Chainage 3905m).kmz" ^
     --floodplain-kmz "Chainage 0m (Station 3905m) Right Bank Floodplain.kmz" ^
     --top-kmz "Chainage 0m (Station 3905m) Right Bank Top.kmz" ^
     --buffer-m 250 --output-dir out

B. Generate transects
   python generate_transects.py --boundary-file out/boundary.geojson --spacing-m 20 ^
     --azimuth-deg 0 --output-dir out

   Or use an SG code directly:
   python generate_transects.py --sg-code C01300000000005900000 --spacing-m 10 --output-dir out

   For even denser sampling:
   python generate_transects.py --sg-code C01300000000005900000 --spacing-m 5 --output-dir out_5m

C. Batch export profiles from CFM
   python cfm_batch_export.py --transects out/transects.geojson --downloads out/profiles --headless false

   If the app struggles with too many lines at once, do it in chunks:
   python cfm_batch_export.py --transects out/transects.geojson --downloads out/profiles_a --start 0 --limit 200
   python cfm_batch_export.py --transects out/transects.geojson --downloads out/profiles_b --start 200 --limit 200

D. Merge all CSVs
   python merge_profile_csvs.py --profiles-dir out/profiles --output out/all_profiles.csv

E. Build a map from the exported CFM CSV files
   python map_cfm_profiles.py --boundary out/boundary.geojson --transects out/transects.geojson ^
     --profiles-dir out/profiles --output-dir out/map

Notes
-----
- GeoJSON is used because Cape Farm Mapper imports GeoJSON directly.
- Keep spacing realistic. Very small spacing (e.g. 1-2 m) on a large farm can create thousands of transects and make CFM slow.
- For flood analysis, 5-10 m spacing is a practical starting point for screening. Engineering-grade flood levels still need a better DEM or survey.
- If the CFM UI changes, cfm_batch_export.py may need small selector edits.
