#!/usr/bin/env python3
"""
Batch-export Cape Farm Mapper elevation-profile CSV files for many imported transect lines.

This script automates the public CFM UI with Playwright. It is intentionally conservative:
- it imports a GeoJSON/KML/KMZ/Shapefile of transect lines,
- opens the graphics attribute table,
- selects each line,
- runs Elevation Profile,
- saves the exported CSV.

Because CFM is a public web app and its UI can change, you may need to tweak one or two selectors.
The generation/import/export flow itself is based on the current CFM 3 UI labels and manual.

Examples
--------
python cfm_batch_export.py \
  --transects out/transects.geojson \
  --downloads out/profiles \
  --start 0 --limit 200

python cfm_batch_export.py \
  --transects out/transects.geojson \
  --downloads out/profiles \
  --headless false
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Iterable, List, Optional

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import Locator, Page, sync_playwright

CFM_URL = "https://gis.elsenburg.com/apps/cfm/"


def parse_bool(s: str) -> bool:
    return str(s).strip().lower() in {"1", "true", "yes", "y", "on"}


def load_line_ids(transects_path: Path) -> List[str]:
    with transects_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    feats = data.get("features", [])
    ids = []
    for i, feat in enumerate(feats, start=1):
        props = feat.get("properties", {}) or {}
        ids.append(str(props.get("line_id") or props.get("name") or f"TX_{i:04d}"))
    if not ids:
        raise SystemExit("No features found in transects file.")
    return ids


def click_if_visible(page: Page, texts: Iterable[str], timeout_ms: int = 2000) -> bool:
    for txt in texts:
        locator = page.get_by_text(txt, exact=True)
        try:
            locator.first.wait_for(timeout=timeout_ms)
            locator.first.click()
            return True
        except Exception:
            pass
    return False


def maybe_dismiss_startup_modals(page: Page) -> None:
    # Previous session prompt.
    click_if_visible(page, ["Cancel", "Accept & Close", "Maybe later"], timeout_ms=1500)
    time.sleep(0.5)
    # Cookies/survey/updates.
    for _ in range(3):
        click_if_visible(page, ["Accept & Close", "Maybe later", "Close"], timeout_ms=1200)
        time.sleep(0.3)


def open_user_data_import(page: Page) -> None:
    page.get_by_text("User Data", exact=True).click(timeout=15000)
    # The file input is usually already visible once User Data is open.
    page.wait_for_timeout(1000)


def import_transects(page: Page, transects_path: Path) -> None:
    open_user_data_import(page)
    file_input = page.locator('input[type="file"]').first
    file_input.set_input_files(str(transects_path))
    page.wait_for_timeout(3000)
    # If the optional label dialog appears, dismiss it so import completes.
    click_if_visible(page, ["Cancel", "Label Graphics"], timeout_ms=1500)
    page.wait_for_timeout(1500)


def open_graphics_table(page: Page) -> None:
    page.get_by_text("Graphics", exact=True).click(timeout=10000)
    page.get_by_text("Attribute Table", exact=True).click(timeout=10000)
    page.wait_for_timeout(1500)


def attribute_rows(page: Page) -> Locator:
    # Try semantic rows first, then HTML table rows.
    rows = page.locator('[role="row"]')
    try:
        if rows.count() >= 2:
            return rows
    except Exception:
        pass
    return page.locator("tr")


def select_row_by_text(page: Page, line_id: str) -> bool:
    # Try row text search.
    for selector in [
        'tr',
        '[role="row"]',
        '[role="gridcell"]',
        'div',
    ]:
        loc = page.locator(selector, has_text=line_id)
        try:
            if loc.count() > 0:
                loc.first.click(timeout=3000)
                page.wait_for_timeout(500)
                return True
        except Exception:
            pass
    return False


def select_row_by_index(page: Page, row_index: int) -> bool:
    rows = attribute_rows(page)
    try:
        count = rows.count()
    except Exception:
        count = 0
    if count == 0:
        return False
    # Skip the first row if it looks like a header.
    idx = min(row_index + 1, count - 1)
    try:
        rows.nth(idx).click(timeout=3000)
        page.wait_for_timeout(500)
        return True
    except Exception:
        return False


def open_feature_actions_if_needed(page: Page) -> None:
    # In current CFM builds, the line actions are often directly visible.
    # If not, try the action section/tab.
    if page.get_by_text("Elevation Profile", exact=True).count() > 0:
        return
    click_if_visible(page, ["Action 1", "Feature Actions"], timeout_ms=1000)
    page.wait_for_timeout(300)


def run_elevation_profile(page: Page) -> None:
    open_feature_actions_if_needed(page)
    page.get_by_text("Elevation Profile", exact=True).first.click(timeout=8000)
    page.get_by_text("Profile Statistics", exact=True).first.wait_for(timeout=30000)
    page.wait_for_timeout(1000)


def visible_export_buttons(page: Page) -> List[Locator]:
    buttons = page.get_by_text("Export to CSV", exact=True)
    out = []
    try:
        count = buttons.count()
    except Exception:
        count = 0
    for i in range(count):
        loc = buttons.nth(i)
        try:
            if loc.is_visible():
                out.append(loc)
        except Exception:
            pass
    return out


def export_current_profile_csv(page: Page, save_path: Path) -> None:
    buttons = visible_export_buttons(page)
    if not buttons:
        raise RuntimeError("Could not find a visible 'Export to CSV' button.")
    # The profile panel export is typically the last visible CSV export button.
    export_button = buttons[-1]
    with page.expect_download(timeout=30000) as dl:
        export_button.click()
    download = dl.value
    save_path.parent.mkdir(parents=True, exist_ok=True)
    download.save_as(str(save_path))
    page.wait_for_timeout(500)


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch-export CFM elevation profiles for many transects.")
    parser.add_argument("--transects", type=Path, required=True, help="Transects GeoJSON file created by generate_transects.py")
    parser.add_argument("--downloads", type=Path, required=True, help="Directory where CSV files will be saved")
    parser.add_argument("--headless", type=parse_bool, default=False, help="Run browser headless (default: false)")
    parser.add_argument("--start", type=int, default=0, help="0-based start index in the transects file")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of transects to export")
    parser.add_argument("--slow-mo-ms", type=int, default=150, help="Playwright slow motion delay in ms")
    args = parser.parse_args()

    line_ids = load_line_ids(args.transects)
    start = max(args.start, 0)
    end = len(line_ids) if args.limit is None else min(len(line_ids), start + args.limit)
    subset = line_ids[start:end]
    if not subset:
        raise SystemExit("No transects selected for export.")

    args.downloads.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, slow_mo=args.slow_mo_ms)
        ctx = browser.new_context(accept_downloads=True, viewport={"width": 1600, "height": 1000})
        page = ctx.new_page()
        page.goto(CFM_URL, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(6000)
        maybe_dismiss_startup_modals(page)

        import_transects(page, args.transects)
        open_graphics_table(page)

        failures = []
        for offset, line_id in enumerate(subset):
            absolute_idx = start + offset
            csv_path = args.downloads / f"{line_id}.csv"
            try:
                ok = select_row_by_text(page, line_id)
                if not ok:
                    ok = select_row_by_index(page, absolute_idx)
                if not ok:
                    raise RuntimeError(f"Could not select row for {line_id}")
                run_elevation_profile(page)
                export_current_profile_csv(page, csv_path)
                print(f"OK {line_id} -> {csv_path}")
            except Exception as exc:
                failures.append({"line_id": line_id, "error": str(exc)})
                print(f"FAIL {line_id}: {exc}")
                page.screenshot(path=str(args.downloads / f"ERROR_{line_id}.png"), full_page=True)
                # Keep going.
                continue

        manifest = {
            "requested": len(subset),
            "start": start,
            "end": end,
            "downloads_dir": str(args.downloads),
            "failures": failures,
        }
        with (args.downloads / "run_manifest.json").open("w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        browser.close()


if __name__ == "__main__":
    main()
