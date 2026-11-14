"""Central semantic design tokens for the desktop UI."""

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
    accent: str
    accent_hover: str
    danger: str
    warning: str
    success: str
    input: str
    focus: str = "#8bb6ff"

    @property
    def colors(self) -> dict[str, str]:
        return {
            "window": self.window, "surface": self.surface,
            "surface_2": self.surface_raised, "surface_hover": self.surface_hover,
            "text": self.text, "muted": self.muted, "border": self.border,
            "accent": self.accent, "accent_hover": self.accent_hover,
            "danger": self.danger, "warning": self.warning,
            "success": self.success, "input": self.input, "focus": self.focus,
        }


DARK = DesignTokens(
    window="#101319", surface="#181e27", surface_raised="#202936",
    surface_hover="#273344", text="#edf2f7", muted="#9aa8b8", border="#2b3745",
    accent="#75a7ff", accent_hover="#8bb6ff", danger="#ef6470",
    warning="#e5b45f", success="#4cc69a", input="#141a22",
)
LIGHT = DesignTokens(
    window="#f4f6f9", surface="#ffffff", surface_raised="#edf1f6",
    surface_hover="#e5ebf3", text="#1e2937", muted="#64748b", border="#dbe2eb",
    accent="#326ed5", accent_hover="#245bb7", danger="#d94350",
    warning="#a7680c", success="#17845f", input="#ffffff", focus="#326ed5",
)

TYPOGRAPHY = {"family": "Segoe UI, Noto Sans, sans-serif", "body": 13, "small": 11, "heading": 25, "section": 16}
SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "2xl": 32}
RADII = {"sm": 6, "md": 9, "lg": 12, "xl": 16}
BORDERS = {"thin": 1, "focus": 2}
SHADOWS = {"popup": "0 8px 24px rgba(0, 0, 0, 0.18)"}


def get_tokens(theme: str) -> DesignTokens:
    return LIGHT if str(theme).casefold() == "light" else DARK
