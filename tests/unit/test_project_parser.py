from __future__ import annotations

from pathlib import Path

from src.analyse.project_parser import parse_hecras_project


def test_parse_hecras_project_extracts_sections_and_flow_summary(tmp_path: Path) -> None:
    project = tmp_path / "Example Project"
    project.mkdir(parents=True, exist_ok=True)

    (project / "Meerlustkloof.prj").write_text(
        "\n".join(
            [
                "Proj Title=Example",
                "Current Plan=p01",
                "Geom File=g01",
                "Flow File=f01",
            ]
        )
        + "\n",
        encoding="cp1252",
    )
    (project / "Meerlustkloof.p01").write_text(
        "\n".join(
            [
                "Plan Title=Existing Conditions Run",
                "Short Identifier=Existing",
                "Geom File=g01",
                "Flow File=f01",
                "Mixed Flow",
            ]
        )
        + "\n",
        encoding="cp1252",
    )
    (project / "Meerlustkloof.f01").write_text(
        "\n".join(
            [
                "Flow Title=Auto Generated 100-year Flow",
                "Number of Profiles= 1",
                "Profile Names=Q100",
                "River Rch & RM=Meerlustkloof,Main            ,100.000",
                "     375",
                "River Rch & RM=Meerlustkloof,Main            ,0.000",
                "     550",
                "Boundary for River Rch & Prof#=Meerlustkloof,Main            , 1",
                "Up Type= 3",
                "Up Slope=0.0215",
                "Dn Type= 3",
                "Dn Slope=0.00725",
            ]
        )
        + "\n",
        encoding="cp1252",
    )
    (project / "Meerlustkloof.g01").write_text(
        "\n".join(
            [
                "Geom Title=Example Geometry",
                "River Reach=Meerlustkloof   ,Main",
                "Reach XY= 2",
                "0 0 10 0",
                "Type RM Length L Ch R = 1 ,100.000,10,10,10",
                "BEGIN DESCRIPTION:",
                "Auto-generated cross section at chainage 0.000 m",
                "END DESCRIPTION:",
                "#Sta/Elev= 4",
                "-10 290 -5 289 5 288 10 289",
                "#Mann= 3 ,0,0",
                "-10 .06 0 -5 .04 0 10 .06 0",
                "Bank Sta=-5,5",
                "XS Rating Curve= 0 ,0",
                "Type RM Length L Ch R = 1 ,0.000,0,0,0",
                "BEGIN DESCRIPTION:",
                "Auto-generated cross section at chainage 100.000 m",
                "END DESCRIPTION:",
                "#Sta/Elev= 4",
                "-8 280 -2 279 2 278 8 279",
                "#Mann= 3 ,0,0",
                "-8 .06 0 -2 .04 0 8 .06 0",
                "Bank Sta=-2,2",
                "XS Rating Curve= 0 ,0",
            ]
        )
        + "\n",
        encoding="cp1252",
    )

    meta = parse_hecras_project(project)

    assert meta["project_title"] == "Example"
    assert "steady" in meta["model_types"]
    assert meta["active_plan_summary"]["flow_regime"] == "mixed"
    assert meta["geometry_summary"]["cross_section_count"] == 2
    assert [round(sec.chainage_m, 3) for sec in meta["geometry_summary"]["sections"]] == [0.0, 100.0]
    assert len(meta["flow_summary"]["flow_locations"]) == 2
    assert meta["flow_summary"]["boundary_conditions"]["upstream_slope"] == 0.0215
