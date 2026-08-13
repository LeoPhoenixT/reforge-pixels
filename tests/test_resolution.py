import pytest

from reforge_pixels.resolution import Resolution, oriented_resolution, resolution_summary


def test_scale_resolution() -> None:
    assert Resolution(1920, 1080).scaled(4) == Resolution(7680, 4320)


def test_resolution_summary() -> None:
    assert resolution_summary(Resolution(1920, 1080), 2) == (
        "Input: 1,920 × 1,080  →  Output at 2x: 3,840 × 2,160"
    )


@pytest.mark.parametrize("rotation", [90, 270, -90])
def test_oriented_resolution_swaps_quarter_turns(rotation: int) -> None:
    assert oriented_resolution(1920, 1080, rotation) == Resolution(1080, 1920)


def test_rejects_unsupported_scale() -> None:
    with pytest.raises(ValueError):
        Resolution(640, 480).scaled(5)
