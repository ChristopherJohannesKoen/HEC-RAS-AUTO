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

Recommended workflow
--------------------
A. Generate transects
   python generate_transects.py --sg-code C01300000000005900000 --spacing-m 10 --output-dir out

   For even denser sampling:
   python generate_transects.py --sg-code C01300000000005900000 --spacing-m 5 --output-dir out_5m

B. Batch export profiles from CFM
   python cfm_batch_export.py --transects out/transects.geojson --downloads out/profiles --headless false

   If the app struggles with too many lines at once, do it in chunks:
   python cfm_batch_export.py --transects out/transects.geojson --downloads out/profiles_a --start 0 --limit 200
   python cfm_batch_export.py --transects out/transects.geojson --downloads out/profiles_b --start 200 --limit 200

C. Merge all CSVs
   python merge_profile_csvs.py --profiles-dir out/profiles --output out/all_profiles.csv

Notes
-----
- GeoJSON is used because Cape Farm Mapper imports GeoJSON directly.
- Keep spacing realistic. Very small spacing (e.g. 1-2 m) on a large farm can create thousands of transects and make CFM slow.
- For flood analysis, 5-10 m spacing is a practical starting point for screening. Engineering-grade flood levels still need a better DEM or survey.
- If the CFM UI changes, cfm_batch_export.py may need small selector edits.
