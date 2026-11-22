"""Semantic design tokens for Transcriber's bright, friendly desktop workspace.

The default Studio Light palette uses a soft neutral canvas, a gently tinted
navigation surface and a confident periwinkle accent. Color stays purposeful:
it guides navigation and actions without turning every panel into a card.
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
    accent_soft: str
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
            "accent_soft": self.accent_soft,
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
    window="#202432",
    surface="#272D3B",
    surface_raised="#303849",
    surface_hover="#3A455A",
    text="#F0F3FB",
    muted="#B1BBD0",
    border="#3D475C",
    border_hover="#596783",
    accent="#A1B0FF",
    accent_soft="#374365",
    accent_hover="#C0C9FF",
    danger="#FF8393",
    warning="#F3BD75",
    success="#73D2B2",
    input="#252C3A",
    focus="#A1B0FF",
    primary="#879AFF",
    primary_hover="#9EADFF",
    on_primary="#202432",
)

LIGHT = DesignTokens(
    window="#F6F7FC",
    surface="#FFFFFF",
    surface_raised="#EFF2FA",
    surface_hover="#E7ECF8",
    text="#242A3A",
    muted="#68738A",
    border="#E0E5F0",
    border_hover="#C9D3E7",
    accent="#526DE5",
    accent_soft="#E8ECFF",
    accent_hover="#405ACD",
    danger="#B83F56",
    warning="#94601E",
    success="#177A5D",
    input="#FFFFFF",
    focus="#7189F0",
    primary="#526DE5",
    primary_hover="#405ACD",
    on_primary="#FFFFFF",
)

# Typography follows the host OS and avoids ornamental display faces.
TYPOGRAPHY = {
    "family": "'Segoe UI Variable', 'Segoe UI', 'Inter', 'Noto Sans', sans-serif",
    "mono": "'Cascadia Code', 'Consolas', monospace",
    "body": 14,
    "small": 12,
    "heading": 26,
    "section": 17,
    "code": 13,
}

# All spacing values sit on a four-pixel grid.
SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "2xl": 32}

# Softer, contemporary radii; large rounding is reserved for grouped surfaces.
RADII = {"xs": 4, "sm": 7, "md": 9, "lg": 11, "xl": 14, "2xl": 18}
BORDERS = {"hairline": 1, "thin": 1, "focus": 2}
SHADOWS = {
    "popup": "0 8px 18px rgba(35, 46, 78, 0.10)",
    "dialog": "0 16px 34px rgba(35, 46, 78, 0.14)",
}


def get_tokens(theme: str) -> DesignTokens:
    """Return the requested palette; light is the safe and friendly fallback."""
    return DARK if str(theme).strip().casefold() == "dark" else LIGHT
