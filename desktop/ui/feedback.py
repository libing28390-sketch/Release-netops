from __future__ import annotations

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .tokens import theme_tokens


class FeedbackDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        dark: bool,
        confirm_text: str = "确定",
        cancel_text: str | None = None,
        dangerous: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self.setMaximumWidth(680)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        token = theme_tokens(dark)
        action_color = token["danger"] if dangerous else token["accent"]
        action_text = "#FFFFFF" if dangerous else token["accent_text"]
        action_hover = token["danger_bg"] if dangerous else token["text_secondary"]
        self.setStyleSheet(
            f"""
            QDialog {{
                color: {token['text_primary']};
                background-color: {token['bg_overlay']};
            }}
            QLabel {{
                color: {token['text_primary']};
                background: transparent;
            }}
            QLabel#feedback_title {{
                font-size: 16px;
                font-weight: 600;
            }}
            QLabel#feedback_message {{
                color: {token['text_secondary']};
                font-size: 12px;
            }}
            QPushButton {{
                min-width: 76px;
                min-height: 32px;
                padding: 0 14px;
                border-radius: 8px;
                font-weight: 600;
            }}
            QPushButton#cancel_button {{
                color: {token['text_secondary']};
                background: transparent;
                border: 1px solid {token['border_strong']};
            }}
            QPushButton#cancel_button:hover {{
                color: {token['text_primary']};
                background-color: {token['bg_subtle']};
            }}
            QPushButton#confirm_button {{
                color: {action_text};
                background-color: {action_color};
                border: 1px solid {action_color};
            }}
            QPushButton#confirm_button:hover {{
                color: {action_text if not dangerous else token['danger']};
                background-color: {action_hover};
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        title_label = QLabel(title, self)
        title_label.setObjectName("feedback_title")
        message_label = QLabel(message, self)
        message_label.setObjectName("feedback_message")
        message_label.setWordWrap(True)
        message_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(title_label)
        layout.addWidget(message_label)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        if cancel_text is not None:
            cancel_button = QPushButton(cancel_text, self)
            cancel_button.setObjectName("cancel_button")
            cancel_button.setDefault(True)
            cancel_button.clicked.connect(self.reject)
            button_layout.addWidget(cancel_button)

        confirm_button = QPushButton(confirm_text, self)
        confirm_button.setObjectName("confirm_button")
        confirm_button.setAutoDefault(cancel_text is None)
        confirm_button.setDefault(cancel_text is None)
        confirm_button.clicked.connect(self.accept)
        button_layout.addWidget(confirm_button)
        layout.addLayout(button_layout)


def show_message(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    dark: bool,
    confirm_text: str = "确定",
) -> None:
    FeedbackDialog(
        parent,
        title,
        message,
        dark=dark,
        confirm_text=confirm_text,
    ).exec()


def ask_confirmation(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    dark: bool,
    confirm_text: str = "继续",
    cancel_text: str = "取消",
    dangerous: bool = False,
) -> bool:
    dialog = FeedbackDialog(
        parent,
        title,
        message,
        dark=dark,
        confirm_text=confirm_text,
        cancel_text=cancel_text,
        dangerous=dangerous,
    )
    return dialog.exec() == QDialog.Accepted


class Toast(QLabel):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setAccessibleName("操作反馈")
        self.hide()

    def display(self, message: str, *, dark: bool, level: str, duration: int) -> None:
        token = theme_tokens(dark)
        tone = {
            "success": token["success"],
            "warning": token["warning"],
            "error": token["danger"],
        }.get(level, token["text_secondary"])
        self.setStyleSheet(
            f"""
            QLabel#toast {{
                color: {token['text_primary']};
                background-color: {token['bg_overlay']};
                border: 1px solid {tone};
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 11px;
                font-weight: 500;
            }}
            """
        )
        self.setText(message)
        self.adjustSize()
        self.setMinimumWidth(min(420, max(180, self.sizeHint().width())))
        parent = self.parentWidget()
        if parent is not None:
            self.move(max(12, parent.width() - self.width() - 20), 18)
        self.raise_()
        self.show()
        QTimer.singleShot(duration, self.hide)


def show_toast(
    parent: QWidget,
    message: str,
    *,
    dark: bool,
    level: str = "info",
    duration: int = 2400,
) -> None:
    app = QApplication.instance()
    if app is not None and QThread.currentThread() is not app.thread():
        return
    host = parent.centralWidget() if hasattr(parent, "centralWidget") else parent
    toast = getattr(parent, "_feedback_toast", None)
    if toast is None or toast.parentWidget() is not host:
        toast = Toast(host)
        parent._feedback_toast = toast
    toast.display(message, dark=dark, level=level, duration=duration)
