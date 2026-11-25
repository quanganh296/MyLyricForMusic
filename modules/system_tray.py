from modules.qt_compat import (
    QSystemTrayIcon, QMenu, QIcon, QPixmap,
    Signal, QObject
)
from modules.icon_factory import IconFactory

class SystemTrayManager(QObject):
    toggle_overlay_signal = Signal()
    toggle_lock_signal = Signal()
    open_search_signal = Signal()
    open_settings_signal = Signal()
    exit_app_signal = Signal()

    def __init__(self, parent_app, icon_path=None):
        super().__init__()
        self.app = parent_app
        self.tray_icon = QSystemTrayIcon()

        if icon_path and QPixmap(icon_path).isNull() is False:
            icon = QIcon(icon_path)
        else:
            icon = IconFactory.create_icon("music", "#38bdf8", 32)

        self.tray_icon.setIcon(icon)
        self.tray_icon.setToolTip("LyricOverLay - Lời bài hát nổi Windows")

        self.setup_menu()
        self.tray_icon.show()

    def setup_menu(self):
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #18181b;
                color: #e4e4e7;
                border: 1px solid #3f3f46;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
                font-size: 12px;
            }
            QMenu::item:selected {
                background-color: #38bdf8;
                color: #09090b;
                font-weight: bold;
            }
        """)

        act_toggle = menu.addAction(IconFactory.create_icon("eye", "#ffffff"), "Ẩn / Hiện lời bài hát")
        act_toggle.triggered.connect(self.toggle_overlay_signal.emit)

        act_lock = menu.addAction(IconFactory.create_icon("lock", "#ffffff"), "Khóa / Mở khóa vị trí")
        act_lock.triggered.connect(self.toggle_lock_signal.emit)

        menu.addSeparator()

        act_search = menu.addAction(IconFactory.create_icon("search", "#ffffff"), "Tìm lời bài hát thủ công...")
        act_search.triggered.connect(self.open_search_signal.emit)

        act_settings = menu.addAction(IconFactory.create_icon("settings", "#ffffff"), "Cài đặt giao diện...")
        act_settings.triggered.connect(self.open_settings_signal.emit)

        menu.addSeparator()

        act_exit = menu.addAction(IconFactory.create_icon("close", "#f43f5e"), "Thoát LyricOverLay")
        act_exit.triggered.connect(self.exit_app_signal.emit)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self.on_tray_activated)

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_overlay_signal.emit()

    def show_message(self, title: str, message: str):
        if self.tray_icon.isSystemTrayAvailable():
            self.tray_icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 3000)
