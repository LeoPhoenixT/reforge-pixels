"""Resolution calculation rules shared by the GUI and processing pipeline."""

from __future__ import annotations

from dataclasses import dataclass


VALID_SCALES = (1, 2, 3, 4)


@dataclass(frozen=True, slots=True)
class Resolution:
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Resolution dimensions must be positive")

    def scaled(self, scale: int) -> "Resolution":
        if scale not in VALID_SCALES:
            raise ValueError(f"Scale must be one of {VALID_SCALES}")
        return Resolution(self.width * scale, self.height * scale)

    def display(self) -> str:
        return f"{self.width:,} × {self.height:,}"


def oriented_resolution(width: int, height: int, rotation: int = 0) -> Resolution:
    """Return display dimensions after normalizing container rotation metadata."""
    normalized = rotation % 360
    if normalized not in (0, 90, 180, 270):
        raise ValueError("Rotation must be a multiple of 90 degrees")
    if normalized in (90, 270):
        return Resolution(height, width)
    return Resolution(width, height)


def resolution_summary(source: Resolution, scale: int) -> str:
    output = source.scaled(scale)
    return f"Input: {source.display()}  →  Output at {scale}x: {output.display()}"
