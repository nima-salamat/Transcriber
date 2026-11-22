"""Semantic design tokens for the Transcriber desktop experience.

The palette is intentionally neutral and content-first. Accent colors are reserved
for focus, links, active controls and status; primary actions use high-contrast
monochrome fills in both themes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DesignTokens:
    window: str
    surface: str
    surface_raised: str
    surface_hover: str
    text: str
    muted: str
    border: str
    border_hover: str
    accent: str
    accent_hover: str
    danger: str
    warning: str
    success: str
    input: str
    focus: str
    primary: str
    primary_hover: str
    on_primary: str

    @property
    def colors(self) -> dict[str, str]:
        """Expose stable semantic names to QSS and page-specific components."""
        return {
            "window": self.window,
            "surface": self.surface,
            "surface_2": self.surface_raised,
            "surface_hover": self.surface_hover,
            "text": self.text,
            "muted": self.muted,
            "border": self.border,
            "border_hover": self.border_hover,
            "accent": self.accent,
            "accent_hover": self.accent_hover,
            "danger": self.danger,
            "warning": self.warning,
            "success": self.success,
            "input": self.input,
            "focus": self.focus,
            "primary": self.primary,
            "primary_hover": self.primary_hover,
            "on_primary": self.on_primary,
        }


DARK = DesignTokens(
    window="#181818",
    surface="#212121",
    surface_raised="#282828",
    surface_hover="#303030",
    text="#f3f3f3",
    muted="#afafaf",
    border="#393939",
    border_hover="#4f4f4f",
    accent="#339cff",
    accent_hover="#66b5ff",
    danger="#ff6764",
    warning="#ff8549",
    success="#40c977",
    input="#222222",
    focus="#339cff",
    primary="#ffffff",
    primary_hover="#dfdfdf",
    on_primary="#181818",
)

LIGHT = DesignTokens(
    window="#ffffff",
    surface="#f9f9f9",
    surface_raised="#f3f3f3",
    surface_hover="#ededed",
    text="#1a1c1f",
    muted="#5d5d5d",
    border="#dfdfdf",
    border_hover="#cdcdcd",
    accent="#339cff",
    accent_hover="#0285ff",
    danger="#ba2623",
    warning="#e25507",
    success="#008635",
    input="#ffffff",
    focus="#0169cc",
    primary="#1a1c1f",
    primary_hover="#303030",
    on_primary="#ffffff",
)

# Typography follows the host operating system rather than introducing a display face.
TYPOGRAPHY = {
    "family": "'Segoe UI', 'Noto Sans', sans-serif",
    "mono": "'Cascadia Code', 'Consolas', monospace",
    "body": 14,
    "small": 12,
    "heading": 28,
    "section": 18,
    "code": 13,
}

# All spacing values sit on a four-pixel grid.
SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "2xl": 32}

# Rounded corners are restrained; larger radii are reserved for grouped surfaces.
RADII = {"xs": 4, "sm": 6, "md": 8, "lg": 10, "xl": 12, "2xl": 16}
BORDERS = {"hairline": 1, "thin": 1, "focus": 2}
SHADOWS = {
    "popup": "0 8px 16px rgba(0, 0, 0, 0.18)",
    "dialog": "0 16px 32px rgba(0, 0, 0, 0.24)",
}


def get_tokens(theme: str) -> DesignTokens:
    """Return the palette for a named theme; unknown values fall back to dark."""
    return LIGHT if str(theme).strip().casefold() == "light" else DARK
