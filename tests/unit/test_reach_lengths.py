from src.models.geometry import CrossSection, SectionPoint
from src.xs.reach_lengths import assign_reach_lengths


def _make_section(chainage: float, station: float) -> CrossSection:
    return CrossSection(
        chainage_m=chainage,
        river_station=station,
        river_name="R",
        reach_name="Main",
        cutline=[(0.0, 0.0), (1.0, 0.0)],
        points=[
            SectionPoint(station=0.0, elevation=10.0, source="excel"),
            SectionPoint(station=1.0, elevation=11.0, source="excel"),
        ],
        left_bank_station=0.2,
        right_bank_station=0.8,
        mannings_left=0.06,
        mannings_channel=0.04,
        mannings_right=0.06,
    )


def test_assign_reach_lengths() -> None:
    sections = [_make_section(0.0, 3905.0), _make_section(500.0, 3405.0), _make_section(1000.0, 2905.0)]
    out = assign_reach_lengths(sections)
    assert out[0].reach_length_channel == 500.0
    assert out[1].reach_length_left == 500.0
    assert out[2].reach_length_right == 0.0
