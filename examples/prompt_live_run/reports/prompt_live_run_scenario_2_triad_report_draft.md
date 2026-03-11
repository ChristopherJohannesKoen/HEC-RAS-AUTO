# PROMPT_LIVE_RUN Scenario 2 Triad Report Draft

## Scenario Definition
- Primary tier: `average`
- Tier order: `lenient, average, conservative`

## Physical Mechanism
A warmer atmosphere can hold more moisture and increases heavy-rainfall potential; design-event rainfall intensities are therefore treated as non-stationary.

## Tier Flow Inputs
| tier         | run_id                                  |   upstream_flow_cms |   tributary_flow_cms |   upstream_normal_depth_slope |   downstream_normal_depth_slope |
|:-------------|:----------------------------------------|--------------------:|---------------------:|------------------------------:|--------------------------------:|
| lenient      | prompt_live_run_scenario_2_lenient      |              431.25 |                632.5 |                        0.0215 |                         0.00725 |
| average      | prompt_live_run_scenario_2_average      |              487.5  |                715   |                        0.0215 |                         0.00725 |
| conservative | prompt_live_run_scenario_2_conservative |              600    |                880   |                        0.0215 |                         0.00725 |

## Tier Comparison Matrix (Baseline vs Scenario 2 Tiers)
| tier         | run_id                                  |   max_wse_m |   delta_max_wse_m |   max_velocity_mps |   delta_max_velocity_mps |   flood_extent_area_ha |   delta_flood_extent_area_ha |   max_energy_level_m |   delta_max_energy_level_m |
|:-------------|:----------------------------------------|------------:|------------------:|-------------------:|-------------------------:|-----------------------:|-----------------------------:|---------------------:|---------------------------:|
| lenient      | prompt_live_run_scenario_2_lenient      |     290.421 |          0.131165 |            6.11868 |                0.0991063 |                79.8288 |                      1.35594 |              291.074 |                   0.172699 |
| average      | prompt_live_run_scenario_2_average      |     290.562 |          0.272583 |            6.26151 |                0.241939  |                81.5999 |                      3.12702 |              291.233 |                   0.332092 |
| conservative | prompt_live_run_scenario_2_conservative |     290.798 |          0.507751 |            6.39021 |                0.370642  |                83.8336 |                      5.36075 |              291.522 |                   0.620728 |

## Tier Envelope Summary
| metric               |   baseline |   scenario_min |   scenario_max |   delta_min |   delta_max |
|:---------------------|-----------:|---------------:|---------------:|------------:|------------:|
| max_wse_m            |  290.29    |      290.421   |      290.798   |   0.131165  |    0.507751 |
| max_velocity_mps     |    6.01957 |        6.11868 |        6.39021 |   0.0991063 |    0.370642 |
| flood_extent_area_ha |   78.4728  |       79.8288  |       83.8336  |   1.35594   |    5.36075  |
| max_energy_level_m   |  290.901   |      291.074   |      291.522   |   0.172699  |    0.620728 |

## Hydraulic Mechanism Interpretation
Higher design discharges increase stage and energy gradients, but response is non-uniform by section because confinement, floodplain activation, and confluence interactions alter conveyance and losses. Conservative forcing should amplify confluence effects at chainage ~1500 m and expand flood extent most strongly.

## Assumptions
- Steady 1D HEC-RAS scenario; geometry and roughness remain unchanged for Scenario 2.
- Peak-flow climate impact is represented with multiplicative scaling of baseline 1:100 discharges.
- The same climate factor is applied to main stem and tributary inflow for assignment-level consistency.

## Limitations
- No rainfall-runoff nonlinearity is modeled explicitly.
- No unsteady timing/routing effects at the confluence are modeled.
- Catchment-specific differences between tributary and main stem climate response are simplified.

## Key Artifacts
- Triad comparison CSV: `outputs\prompt_live_run\comparison\scenario2_tier_comparison.csv`
- Triad envelope CSV: `outputs\prompt_live_run\comparison\scenario2_tier_envelope.csv`
- Triad overlay profile plot: `outputs\prompt_live_run\comparison\scenario2_tier_overlay_profile.png`

## References
1. [IPCC AR6 WG1 Chapter 8: Water Cycle Changes](https://www.ipcc.ch/report/ar6/wg1/chapter/chapter-8/)
   - Atmospheric moisture-holding capacity scales at approximately 7% per degree C.
2. [IPCC AR6 WG1 Chapter 11: Weather and Climate Extreme Events](https://www.ipcc.ch/report/ar6/wg1/chapter/chapter-11/)
   - Heavy precipitation intensity/frequency has increased in many regions and is projected to continue increasing.
3. [McBride et al. (2022) Changes in extreme daily rainfall characteristics in South Africa](https://repository.up.ac.za/bitstream/handle/2263/88622/McBride_Changes_2022.pdf?sequence=1)
   - Later-period South African rainfall return levels are frequently higher than earlier periods.
4. [WRC TT 921/23 Design Flood Estimation Guideline](https://www.wrc.org.za/wp-content/uploads/mdocs/TT%20921%20final%20web.pdf)
   - Interim climate allowances (including around 15% and wider ranges) are recommended for design practice.
5. [DWS Climate Change Assessment Example](https://www.dws.gov.za/iwrp/uMkhomazi/Documents/Module%201/2/P%20WMA%2011_U10_00_3312_3_1_11%20-%20Climate%20Change_FINAL.pdf)
   - South African planning studies have applied around 30% design flood peak increases in future horizons.
