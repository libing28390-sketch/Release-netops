from __future__ import annotations


THEMES = {
    "dark": {
        "bg_app": "#111110",
        "bg_sidebar": "#151513",
        "bg_surface": "#1A1A18",
        "bg_subtle": "#20201D",
        "bg_overlay": "#242421",
        "border": "#2B2B28",
        "border_strong": "#3A3935",
        "text_primary": "#F2F1ED",
        "text_secondary": "#B5B3AD",
        "text_muted": "#7F7D77",
        "accent": "#E8E6DF",
        "accent_text": "#1A1A18",
        "focus": "#8AB4F8",
        "success": "#5DBB83",
        "warning": "#D7A84B",
        "danger": "#E06C75",
        "danger_bg": "#2A1B1C",
        "code_bg": "#0E0E0D",
    },
    "light": {
        "bg_app": "#F7F7F5",
        "bg_sidebar": "#F1F1EE",
        "bg_surface": "#FFFFFF",
        "bg_subtle": "#F3F3F0",
        "bg_overlay": "#FFFFFF",
        "border": "#E4E3DE",
        "border_strong": "#D4D2CB",
        "text_primary": "#20201D",
        "text_secondary": "#55534E",
        "text_muted": "#8A8881",
        "accent": "#242421",
        "accent_text": "#FFFFFF",
        "focus": "#356AC3",
        "success": "#2F8F5B",
        "warning": "#A66B12",
        "danger": "#B9474E",
        "danger_bg": "#FBEDEE",
        "code_bg": "#171715",
    },
}


def theme_tokens(dark: bool) -> dict[str, str]:
    return THEMES["dark" if dark else "light"]
