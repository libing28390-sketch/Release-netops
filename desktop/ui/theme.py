from __future__ import annotations

from .tokens import theme_tokens


def build_codex_stylesheet(dark: bool) -> str:
    token = theme_tokens(dark)
    return f"""
QWidget {{
    font-family: "Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI", sans-serif;
    color: {token['text_primary']};
    font-size: 12px;
}}
QMainWindow {{
    background-color: {token['bg_app']};
}}
QWidget#sidebar_container {{
    background-color: {token['bg_sidebar']};
    border-right: 1px solid {token['border']};
}}
QLabel#lbl_sidebar_title {{
    color: {token['text_primary']};
    font-size: 14px;
    font-weight: 600;
}}
QLabel#lbl_sidebar_ver {{
    color: {token['text_muted']};
    font-size: 10px;
    font-weight: 400;
}}
QLabel[role="nav_text"] {{
    background: transparent;
    border: none;
    font-size: 12px;
    font-weight: 500;
}}
QLabel#sidebar_status {{
    margin: 0 16px;
    color: {token['text_muted']};
    font-size: 10px;
}}
QLabel#sidebar_status[connected="true"] {{
    color: {token['success']};
}}
QLabel#sidebar_build {{
    margin: 0 16px 2px 16px;
    color: {token['text_muted']};
    font-size: 9px;
}}
QPushButton.nav_btn {{
    min-height: 36px;
    max-height: 36px;
    margin: 1px 10px;
    padding: 0px 10px;
    color: {token['text_secondary']};
    background: transparent;
    border: none;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton.nav_btn:hover {{
    color: {token['text_primary']};
    background-color: {token['bg_subtle']};
}}
QPushButton.nav_btn:checked {{
    color: {token['text_primary']};
    background-color: {token['bg_surface']};
}}
QStackedWidget#content_pane {{
    background-color: {token['bg_app']};
}}
QWidget#dashboard_page,
QWidget#service_page,
QWidget#logs_page,
QWidget#about_page {{
    background-color: {token['bg_app']};
}}
QWidget#settings_page {{
    background-color: {token['bg_app']};
}}
QScrollArea#settings_scroll,
QWidget#settings_scroll_viewport,
QWidget#settings_scroll_content {{
    background: transparent;
    border: none;
}}
QLabel#page_title {{
    color: {token['text_primary']};
    font-size: 19px;
    font-weight: 600;
}}
QLabel#page_description {{
    color: {token['text_muted']};
    font-size: 11px;
    font-weight: 400;
}}
QLabel#settings_saved {{
    color: {token['success']};
    background-color: {token['bg_subtle']};
    border: 1px solid {token['border']};
    border-radius: 7px;
    padding: 5px 9px;
    font-size: 10px;
    font-weight: 500;
}}
QFrame#settings_section {{
    background-color: {token['bg_surface']};
    border: 1px solid {token['border']};
    border-radius: 10px;
}}
QFrame[class="card"] {{
    background-color: {token['bg_surface']};
    border: 1px solid {token['border']};
    border-radius: 10px;
}}
QFrame#toolbar_surface {{
    background-color: {token['bg_surface']};
    border: 1px solid {token['border']};
    border-radius: 10px;
}}
QLabel#log_status {{
    color: {token['text_muted']};
    font-size: 10px;
    padding: 1px 2px;
}}
QLabel#recent_events {{
    color: {token['text_secondary']};
    font-size: 10px;
    line-height: 17px;
}}
QLabel#lbl_card_title {{
    color: {token['text_muted']};
    font-size: 10px;
    font-weight: 600;
    padding: 6px 4px 10px 4px;
}}
QLabel#pause_label {{
    color: {token['text_secondary']};
    background: transparent;
    font-weight: 600;
}}
QPushButton#section_toggle {{
    min-height: 36px;
    padding: 0 12px;
    color: {token['text_secondary']};
    background: transparent;
    border: none;
    border-radius: 7px;
    text-align: left;
    font-size: 10px;
    font-weight: 600;
}}
QPushButton#section_toggle:hover {{
    color: {token['text_primary']};
    background-color: {token['bg_subtle']};
}}
QWidget.setting_row_widget {{
    background-color: transparent;
    border: none;
    border-bottom: 1px solid {token['border']};
}}
QWidget.setting_row_widget:hover {{
    background-color: {token['bg_subtle']};
}}
QLabel[role="setting_title"] {{
    color: {token['text_primary']};
    font-size: 12px;
    font-weight: 500;
}}
QLabel[role="setting_description"] {{
    color: {token['text_muted']};
    font-size: 10px;
    font-weight: 400;
}}
QLabel[role="spec_name"] {{
    color: {token['text_secondary']};
    font-size: 11px;
    font-weight: 500;
}}
QLabel#lbl_field_val {{
    color: {token['text_primary']};
    font-weight: 500;
}}
QLabel#lbl_cpu_value {{
    color: {token['text_primary']};
    font-size: 11px;
    font-weight: 500;
}}
QLabel#lbl_status_large {{
    font-size: 18px;
    font-weight: 600;
}}
QLabel[tone="success"] {{ color: {token['success']}; }}
QLabel[tone="warning"] {{ color: {token['warning']}; }}
QLabel[tone="error"] {{ color: {token['danger']}; }}
QLabel#status_dot {{
    background-color: {token['text_muted']};
    border-radius: 5px;
}}
QLabel#status_dot[tone="success"] {{ background-color: {token['success']}; }}
QLabel#status_dot[tone="warning"] {{ background-color: {token['warning']}; }}
QLabel#status_dot[tone="error"] {{ background-color: {token['danger']}; }}
QLabel#about_description {{
    color: {token['text_secondary']};
    font-size: 11px;
}}
QLabel#about_name {{
    color: {token['text_primary']};
    font-size: 17px;
    font-weight: 600;
}}
QLabel#about_logo_fallback {{ font-size: 40px; }}
QLabel#qr_code {{
    padding: 6px;
    background-color: #FFFFFF;
    border: 1px solid {token['border_strong']};
    border-radius: 8px;
}}
QLabel#about_caption {{
    color: {token['text_muted']};
    font-size: 10px;
}}
QFrame#subtle_divider {{
    max-height: 1px;
    background-color: {token['border']};
    border: none;
}}
QPushButton#link_button {{
    min-height: 22px;
    padding: 0;
    color: {token['focus']};
    background: transparent;
    border: none;
    text-align: left;
    font-weight: 500;
}}
QPushButton#link_button:hover {{ text-decoration: underline; }}
QPushButton#btn_primary,
QPushButton#btn_start {{
    min-height: 32px;
    padding: 0px 14px;
    color: {token['accent_text']};
    background-color: {token['accent']};
    border: 1px solid {token['accent']};
    border-radius: 8px;
    font-weight: 600;
}}
QPushButton#btn_primary:hover,
QPushButton#btn_start:hover {{
    background-color: {token['text_secondary']};
    border-color: {token['text_secondary']};
}}
QPushButton#btn_secondary,
QPushButton#btn_restart,
QPushButton#btn_copy {{
    min-height: 30px;
    padding: 0px 12px;
    color: {token['text_secondary']};
    background-color: transparent;
    border: 1px solid {token['border_strong']};
    border-radius: 8px;
    font-weight: 500;
}}
QPushButton#btn_secondary:hover,
QPushButton#btn_restart:hover,
QPushButton#btn_copy:hover {{
    color: {token['text_primary']};
    background-color: {token['bg_subtle']};
    border-color: {token['border_strong']};
}}
QPushButton#btn_danger,
QPushButton#btn_stop {{
    min-height: 30px;
    padding: 0px 12px;
    color: {token['danger']};
    background-color: transparent;
    border: 1px solid {token['border']};
    border-radius: 8px;
    font-weight: 500;
}}
QPushButton#btn_danger:hover,
QPushButton#btn_stop:hover {{
    color: {token['danger']};
    background-color: {token['danger_bg']};
    border-color: {token['danger']};
}}
QPushButton:disabled {{
    color: {token['text_muted']};
    background-color: {token['bg_subtle']};
    border-color: {token['border']};
}}
QComboBox,
QLineEdit {{
    min-height: 32px;
    padding: 0px 10px;
    color: {token['text_primary']};
    background-color: {token['bg_subtle']};
    border: 1px solid {token['border']};
    border-radius: 8px;
    selection-background-color: {token['border_strong']};
}}
QComboBox:hover,
QLineEdit:hover {{
    border-color: {token['border_strong']};
}}
QComboBox[invalid="true"] {{ border-color: {token['danger']}; }}
QLineEdit#metadata_value {{
    min-height: 24px;
    padding: 0;
    background: transparent;
    border: none;
}}
QComboBox:focus,
QLineEdit:focus {{
    border: 1px solid {token['focus']};
}}
QComboBox::drop-down {{
    width: 24px;
    border: none;
}}
QAbstractItemView {{
    color: {token['text_primary']};
    background-color: {token['bg_overlay']};
    border: 1px solid {token['border']};
    border-radius: 8px;
    selection-color: {token['text_primary']};
    selection-background-color: {token['bg_subtle']};
    padding: 4px;
}}
QPlainTextEdit,
QPlainTextEdit#log_viewer {{
    color: #D8D6D0;
    background-color: {token['code_bg']};
    border: 1px solid {token['border']};
    border-radius: 8px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    width: 8px;
    margin: 2px;
    background: transparent;
}}
QScrollBar::handle:vertical {{
    min-height: 32px;
    background-color: {token['border_strong']};
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {token['text_muted']};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    height: 0px;
    background: transparent;
}}
QMenu {{
    color: {token['text_primary']};
    background-color: {token['bg_overlay']};
    border: 1px solid {token['border']};
    border-radius: 8px;
    padding: 5px;
}}
QMenu::item {{
    min-height: 28px;
    padding: 2px 12px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background-color: {token['bg_subtle']};
}}
QToolTip {{
    color: {token['text_primary']};
    background-color: {token['bg_overlay']};
    border: 1px solid {token['border']};
    padding: 5px 7px;
}}
QDialog,
QMessageBox {{
    color: {token['text_primary']};
    background-color: {token['bg_overlay']};
}}
QMessageBox QLabel {{
    color: {token['text_primary']};
    background: transparent;
}}
QMessageBox QPushButton {{
    min-width: 76px;
    min-height: 30px;
    padding: 0px 12px;
    color: {token['text_secondary']};
    background-color: transparent;
    border: 1px solid {token['border_strong']};
    border-radius: 8px;
}}
QMessageBox QPushButton:hover {{
    color: {token['text_primary']};
    background-color: {token['bg_subtle']};
}}
"""
