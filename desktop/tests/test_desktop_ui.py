from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtCore import QRect, Qt

from desktop import desktop_tray
from desktop import launcher
from desktop.desktop_tray import DatabaseResetConfirmDialog
from desktop.release_notes import CLIENT_VERSION, build_release_notes
from desktop.ui.feedback import FeedbackDialog
from desktop.ui.launcher_theme import build_launcher_stylesheet
from desktop.ui.theme import build_codex_stylesheet
from desktop.ui.tokens import theme_tokens


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


@pytest.fixture
def window(tmp_path, monkeypatch, app):
    monkeypatch.setattr(desktop_tray, "DESKTOP_DIR", str(tmp_path / "desktop"))
    monkeypatch.setattr(desktop_tray, "PROJECT_ROOT", str(tmp_path))
    Path(desktop_tray.DESKTOP_DIR).mkdir(parents=True)
    current = desktop_tray.backend_process
    desktop_tray.backend_process = None
    ui = desktop_tray.NetOpsAgentUI()
    ui.poller_running = False
    ui.log_timer.stop()
    ui.poll_timer.stop()
    yield ui
    ui.hide()
    ui.deleteLater()
    app.processEvents()
    desktop_tray.backend_process = current


def test_theme_builders_cover_dark_and_light():
    required = {"bg_app", "bg_surface", "text_primary", "border", "danger"}
    assert required <= theme_tokens(True).keys()
    assert required <= theme_tokens(False).keys()
    assert "QPushButton#btn_primary" in build_codex_stylesheet(True)
    assert "QPlainTextEdit#console_log" in build_launcher_stylesheet(True)


def test_feedback_dialog_defaults_to_cancel(app):
    dialog = FeedbackDialog(
        None,
        "危险操作",
        "确认继续？",
        dark=True,
        confirm_text="继续",
        cancel_text="取消",
        dangerous=True,
    )
    cancel = dialog.findChild(QPushButton, "cancel_button")
    confirm = dialog.findChild(QPushButton, "confirm_button")
    assert dialog.isModal()
    assert dialog.minimumWidth() >= 440
    assert cancel is not None and cancel.isDefault()
    assert confirm is not None and not confirm.isDefault()
    dialog.close()


def test_sidebar_collapses_and_system_info_expands(window, app):
    window.show()
    window.resize(920, 640)
    app.processEvents()
    assert window.sidebar.width() == 64
    assert not window.lbl_sidebar_title.isVisible()

    window.resize(1180, 760)
    app.processEvents()
    assert window.sidebar.width() == 188
    assert window.lbl_sidebar_title.isVisible()

    window.content_pane.setCurrentIndex(3)
    app.processEvents()
    assert not window.sys_content.isVisible()
    window.lbl_sys_card_title.click()
    app.processEvents()
    assert window.sys_content.isVisible()


def test_processor_text_is_not_clipped(window, app):
    window.lbl_cpu_value.setText(
        "Intel64 Family 6 Model 142 Stepping 10, GenuineIntel Processor With Long Description"
    )
    window.resize(1032, 700)
    window.content_pane.setCurrentIndex(3)
    window.lbl_sys_card_title.setChecked(True)
    window._toggle_system_info(True)
    window.show()
    app.processEvents()

    content_width = window.lbl_cpu_value.contentsRect().width()
    required_height = window.lbl_cpu_value.fontMetrics().boundingRect(
        QRect(0, 0, content_width, 1000),
        Qt.TextWordWrap,
        window.lbl_cpu_value.text(),
    ).height()

    assert content_width >= 300
    assert window.lbl_cpu_value.contentsRect().height() >= required_height


def test_settings_persist(window):
    window.chk_auto_start.setChecked(True)
    window.chk_minimize_close.setChecked(False)
    window.combo_controller_ip.setCurrentText("192.0.2.10")
    window.save_settings()

    assert window.settings.value("auto_start_service", type=bool) is True
    assert window.settings.value("minimize_to_tray", type=bool) is False
    assert window.settings.value("controller_ip", type=str) == "192.0.2.10"


def test_release_notes_are_shown_once_per_version(window, monkeypatch):
    messages = []
    monkeypatch.setattr(
        desktop_tray,
        "show_message",
        lambda parent, title, message, **kwargs: messages.append((title, message, kwargs)),
    )

    assert window.show_release_notes_if_needed() is True
    assert len(messages) == 1
    assert CLIENT_VERSION in messages[0][0]
    assert "华为/H3C" in messages[0][1]
    assert window.settings.value("last_seen_release_notes_version", type=str) == CLIENT_VERSION

    assert window.show_release_notes_if_needed() is False
    assert len(messages) == 1


def test_release_notes_support_english():
    title, message, confirm_text = build_release_notes("en")

    assert CLIENT_VERSION in title
    assert "Huawei, H3C, and Cisco" in message
    assert confirm_text == "Got it"


def test_about_page_exposes_update_check(window):
    assert window.btn_check_update.text() == "检查更新"
    window.combo_lang_settings.setCurrentIndex(1)
    assert window.btn_check_update.text() == "Check for Updates"


def test_language_theme_and_navigation(window, app):
    window.combo_lang_settings.setCurrentIndex(1)
    assert window.lang == "en"
    assert window.nav_labels["nav_service"].text() == "Service"

    window.combo_theme.setCurrentIndex(1)
    assert window.dark_mode is False
    assert theme_tokens(False)["bg_app"] in window.styleSheet()

    for index, button in enumerate(window.nav_group):
        button.click()
        app.processEvents()
        assert window.content_pane.currentIndex() == index


def test_log_polling_updates_content_and_status(window, tmp_path):
    log_path = tmp_path / "backend_server.log"
    log_path.write_text("first line\nsecond line\n", encoding="utf-8")
    window.content_pane.setCurrentIndex(2)
    window.poll_logs()

    assert "first line" in window.txt_logs_terminal.toPlainText()
    assert "KB" in window.lbl_log_status.text()


def test_service_lifecycle_uses_managed_process(window, monkeypatch):
    class FakeProcess:
        pid = 4321

        def poll(self):
            return None

    fake_process = FakeProcess()
    commands = []

    monkeypatch.setattr(desktop_tray, "get_pid_occupying_port", lambda _port: None)
    monkeypatch.setattr(desktop_tray, "get_python_executable", lambda: "python.exe")
    monkeypatch.setattr(
        desktop_tray.subprocess,
        "Popen",
        lambda *args, **kwargs: commands.append((args, kwargs)) or fake_process,
    )
    monkeypatch.setattr(desktop_tray.subprocess, "run", lambda *args, **kwargs: None)
    window.auto_open_browser = False

    window.start_backend_server()
    assert desktop_tray.backend_process is fake_process
    assert commands
    assert window.start_time is not None

    window.stop_backend_server()
    assert desktop_tray.backend_process is None
    assert window.start_time is None


def test_close_event_minimizes_to_tray(window, app):
    class FakeEvent:
        ignored = False

        def ignore(self):
            self.ignored = True

    event = FakeEvent()
    window.minimize_to_tray = True
    window.show()
    window.closeEvent(event)
    app.processEvents()
    assert event.ignored is True
    assert not window.isVisible()


def test_database_confirmation_requires_exact_name(app):
    target = {
        "backend": "postgresql",
        "host": "127.0.0.1",
        "port": 5432,
        "database": "netops",
    }
    dialog = DatabaseResetConfirmDialog(
        target,
        r"E:\data\netsops\.env",
        r"E:\data\netsops\data\backups\database-reset",
        dark_mode=True,
        lang="zh",
    )
    assert dialog.cancel_button.isDefault()
    assert not dialog.reset_button.isEnabled()
    dialog.confirmation_input.setText("NETOPS")
    assert not dialog.reset_button.isEnabled()
    dialog.confirmation_input.setText("netops")
    assert dialog.reset_button.isEnabled()
    dialog.close()


def test_launcher_reads_database_url(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "DATABASE_URL=postgresql://netops_user:p%40ss@192.0.2.20:5544/netops_db\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher, "PROJECT_ROOT", str(tmp_path))

    config = launcher.load_database_config_from_env()

    assert config == {
        "host": "192.0.2.20",
        "port": "5544",
        "user": "netops_user",
        "password": "p@ss",
        "db_name": "netops_db",
    }


def test_launcher_writes_encoded_database_url(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "PROJECT_ROOT", str(tmp_path))
    worker = launcher.SetupWorker(
        {
            "host": "192.0.2.30",
            "port": "5432",
            "user": "netops user",
            "password": "p@ss/word",
            "db_name": "netops db",
        }
    )

    worker.configure_env_file()

    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD=p@ss/word" in content
    assert (
        "DATABASE_URL=postgresql://netops%20user:p%40ss%2Fword@192.0.2.30:5432/netops%20db"
        in content
    )


def test_launcher_entry_imports_without_package_context(tmp_path):
    launcher_path = Path(launcher.__file__).resolve()
    command = (
        "import runpy; "
        f"runpy.run_path({str(launcher_path)!r}, run_name='entry_import_check')"
    )

    result = subprocess.run(
        [sys.executable, "-I", "-c", command],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
