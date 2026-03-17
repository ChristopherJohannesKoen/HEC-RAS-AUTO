# CFM Dense Sampling Toolkit

Utilities for extracting dense elevation-profile samples from Cape Farm Mapper and turning them into mapped outputs.

## Scripts

- `cfm_dense_sampling/generate_transects.py`
  - Generates parallel transects across a polygon boundary.
- `cfm_dense_sampling/cfm_batch_export.py`
  - Automates Cape Farm Mapper with Playwright and downloads elevation-profile CSVs.
- `cfm_dense_sampling/merge_profile_csvs.py`
  - Merges exported CSV files into one long table.
- `cfm_dense_sampling/build_kmz_corridor_boundary.py`
  - Builds an approximate geographic corridor from the three KMZ anchor points.
- `cfm_dense_sampling/map_cfm_profiles.py`
  - Matches exported CSVs back to transects geometrically and renders a map.

## Dependencies

Required beyond the base repo stack:

```powershell
py -3.11 -m pip install requests playwright contextily
py -3.11 -m playwright install chromium
```

## Workflow

### 1. Build a boundary

Use either:

- a real geographic polygon GeoJSON/Shapefile, or
- the KMZ-based corridor helper

Example:

```powershell
py -3.11 cfm_dense_sampling_toolkit\cfm_dense_sampling\build_kmz_corridor_boundary.py `
  --station-kmz "ref\KMZ files\Station 0 (Chainage 3905m).kmz" `
  --floodplain-kmz "ref\KMZ files\Chainage 0m (Station 3905m) Right Bank Floodplain.kmz" `
  --top-kmz "ref\KMZ files\Chainage 0m (Station 3905m) Right Bank Top.kmz" `
  --buffer-m 250 `
  --output-dir outputs\cfm_dense_sampling
```

### 2. Generate transects

Example:

```powershell
py -3.11 cfm_dense_sampling_toolkit\cfm_dense_sampling\generate_transects.py `
  --boundary-file outputs\cfm_dense_sampling\boundary.geojson `
  --spacing-m 20 `
  --azimuth-deg 41.104895491498496 `
  --output-dir outputs\cfm_dense_sampling
```

Smaller `--spacing-m` means more lines.

### 3. Export profiles from CFM

```powershell
py -3.11 cfm_dense_sampling_toolkit\cfm_dense_sampling\cfm_batch_export.py `
  --transects outputs\cfm_dense_sampling\transects.geojson `
  --downloads outputs\cfm_dense_sampling\profiles_full `
  --headless true `
  --start 0 `
  --limit 179 `
  --slow-mo-ms 0
```

### 4. Merge CSVs

```powershell
py -3.11 cfm_dense_sampling_toolkit\cfm_dense_sampling\merge_profile_csvs.py `
  --profiles-dir outputs\cfm_dense_sampling\profiles_full `
  --output outputs\cfm_dense_sampling\all_profiles.csv
```

### 5. Build the map

```powershell
py -3.11 cfm_dense_sampling_toolkit\cfm_dense_sampling\map_cfm_profiles.py `
  --boundary outputs\cfm_dense_sampling\boundary.geojson `
  --transects outputs\cfm_dense_sampling\transects.geojson `
  --profiles-dir outputs\cfm_dense_sampling\profiles_full `
  --output-dir outputs\cfm_dense_sampling\map
```

## Important Behavior

- Cape Farm Mapper may reorder imported lines in its graphics table.
- `map_cfm_profiles.py` does not trust the raw CSV filenames alone.
- It matches each exported CSV back to the correct original transect geometrically.

This is recorded in:

- `map/cfm_profile_match_manifest.csv`

## Main Outputs

- `boundary.geojson`
- `transects.geojson`
- `profiles_full/*.csv`
- `all_profiles.csv`
- `map/cfm_profile_points.geojson`
- `map/cfm_profiled_transects.geojson`
- `map/cfm_profile_map.png`
- `map/cfm_profile_match_manifest.csv`

## Current Example

The full 20 m run built from the supplied four boundary coordinates is under:

- `outputs/cfm_dense_sampling_bounds20/`

Key artifacts:

- `outputs/cfm_dense_sampling_bounds20/all_profiles.csv`
- `outputs/cfm_dense_sampling_bounds20/map/cfm_profile_map.png`
- `outputs/cfm_dense_sampling_bounds20/map/cfm_profile_match_manifest.csv`
