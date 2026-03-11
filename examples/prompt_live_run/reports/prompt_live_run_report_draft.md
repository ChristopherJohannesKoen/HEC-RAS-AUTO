# PROMPT_LIVE_RUN Report Draft

## Summary
Run `prompt_live_run` was processed in unattended autopilot mode with COM-driven HEC-RAS compute. Outputs were auto-generated for QA, metrics, plots, CAD export, and reporting.

## Inputs
| run_id          | scenario_id   |   upstream_flow_cms |   tributary_flow_cms |   tributary_chainage_m |   upstream_station_hint |   tributary_station_hint |   downstream_station_hint |   upstream_normal_depth_slope |   downstream_normal_depth_slope |
|:----------------|:--------------|--------------------:|---------------------:|-----------------------:|------------------------:|-------------------------:|--------------------------:|------------------------------:|--------------------------------:|
| prompt_live_run | baseline      |                 375 |                  550 |                   1500 |                    3905 |                     2405 |                         0 |                        0.0215 |                         0.00725 |

## QA Status
# Hydraulic QA

- [INFO] `HYD_QA_DONE`: Hydraulic QA executed.


## Key Metrics
| run_id          |   max_wse_m |   max_wse_chainage_m |   max_energy_level_m |   max_energy_chainage_m |   max_velocity_mps |   max_velocity_chainage_m |   flood_extent_area_m2 |   flood_extent_area_ha |   confluence_chainage_m | confluence_note                                                                    | flood_extent_note                                        |
|:----------------|------------:|---------------------:|---------------------:|------------------------:|-------------------:|--------------------------:|-----------------------:|-----------------------:|------------------------:|:-----------------------------------------------------------------------------------|:---------------------------------------------------------|
| prompt_live_run |      290.29 |                    0 |              290.901 |                       0 |            6.01957 |                      1500 |                 784728 |                78.4728 |                    1500 | [VERIFY] Interpret local hydraulic effect using HEC-RAS profile and velocity maps. | Flood extent derived from energy_flood_envelope polygon. |

## Figures
- outputs/prompt_live_run/comparison/scenario2_tier_overlay_profile.png
- outputs/prompt_live_run/plots/longitudinal_profile.png
- outputs/prompt_live_run/plots/xs_chainage_0_completed.png
- outputs/prompt_live_run/sections/section_chainage_0.png
- outputs/prompt_live_run/sections/section_chainage_1500.png
- outputs/prompt_live_run/sections/section_chainage_3905.png

## Scenario Notes
Baseline case. No scenario flow multipliers applied.

## AI Advisory
AI triage unavailable: Error code: 400 - {'error': {'message': "Unsupported parameter: 'temperature' is not supported with this model.", 'type': 'invalid_request_error', 'param': 'temperature', 'code': None}}

## Citations
_No validated external citations were attached._

## Assumptions and Verification Markers

- [VERIFY] Confirm bank station placements in HEC-RAS geometry editor.

- [VERIFY] Confirm selected flow regime (subcritical/supercritical/mixed).

- [VERIFY] Confirm energy-line-based floodline interpretation for final CAD deliverable.
