from __future__ import annotations

from .tokens import theme_tokens


def build_launcher_stylesheet(dark: bool = True) -> str:
    token = theme_tokens(dark)
    return f"""
    QWidget {{
        font-family: "Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI", sans-serif;
        color: {token['text_primary']};
        font-size: 12px;
    }}
    QMainWindow {{ background-color: {token['bg_app']}; }}
    QLabel#lbl_title {{
        color: {token['text_primary']};
        font-size: 19px;
        font-weight: 600;
    }}
    QLabel#lbl_subtitle,
    QLabel#helper_text,
    QLabel#finish_desc {{
        color: {token['text_muted']};
        font-size: 11px;
    }}
    QLabel#lbl_section {{
        color: {token['text_secondary']};
        font-size: 11px;
        font-weight: 600;
        margin-top: 8px;
    }}
    QFrame#accent_bar {{
        background-color: {token['border_strong']};
        border-radius: 2px;
    }}
    QFrame#card,
    QFrame#db_card {{
        background-color: {token['bg_surface']};
        border: 1px solid {token['border']};
        border-radius: 10px;
    }}
    QFrame#db_card:hover {{
        background-color: {token['bg_subtle']};
        border-color: {token['border_strong']};
    }}
    QRadioButton {{
        color: {token['text_primary']};
        font-size: 12px;
        font-weight: 500;
    }}
    QLineEdit {{
        min-height: 34px;
        padding: 0 10px;
        color: {token['text_primary']};
        background-color: {token['bg_subtle']};
        border: 1px solid {token['border']};
        border-radius: 8px;
        selection-background-color: {token['border_strong']};
    }}
    QLineEdit:hover {{ border-color: {token['border_strong']}; }}
    QLineEdit:focus {{ border-color: {token['focus']}; }}
    QPushButton {{
        min-height: 34px;
        padding: 0 16px;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#btn_primary {{
        color: {token['accent_text']};
        background-color: {token['accent']};
        border: 1px solid {token['accent']};
    }}
    QPushButton#btn_primary:hover {{
        background-color: {token['text_secondary']};
        border-color: {token['text_secondary']};
    }}
    QPushButton#btn_secondary {{
        color: {token['text_secondary']};
        background-color: transparent;
        border: 1px solid {token['border_strong']};
    }}
    QPushButton#btn_secondary:hover {{
        color: {token['text_primary']};
        background-color: {token['bg_subtle']};
    }}
    QPlainTextEdit#console_log {{
        color: #D8D6D0;
        background-color: {token['code_bg']};
        border: 1px solid {token['border']};
        border-radius: 8px;
        padding: 8px;
        font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 10px;
    }}
    QProgressBar {{
        min-height: 10px;
        max-height: 10px;
        color: transparent;
        background-color: {token['bg_subtle']};
        border: none;
        border-radius: 5px;
    }}
    QProgressBar::chunk {{
        background-color: {token['text_secondary']};
        border-radius: 5px;
    }}
    QLabel#status_text {{ color: {token['text_secondary']}; font-weight: 500; }}
    QLabel#success_icon {{ color: {token['success']}; font-size: 48px; font-weight: 600; }}
    QMessageBox {{ color: {token['text_primary']}; background-color: {token['bg_overlay']}; }}
    QMessageBox QLabel {{ color: {token['text_primary']}; background: transparent; }}
    QMessageBox QPushButton {{
        color: {token['text_secondary']};
        background: transparent;
        border: 1px solid {token['border_strong']};
    }}
    QMessageBox QPushButton:hover {{
        color: {token['text_primary']};
        background-color: {token['bg_subtle']};
    }}
    """
