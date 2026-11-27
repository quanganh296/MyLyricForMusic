try:
    from PyQt6.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QGraphicsDropShadowEffect, QFrame, QDialog, QLineEdit, QListWidget,
        QListWidgetItem, QMessageBox, QComboBox, QSpinBox, QDoubleSpinBox,
        QSlider, QGroupBox, QFormLayout, QSystemTrayIcon, QMenu, QSizeGrip,
        QTabWidget, QTextEdit, QColorDialog, QSizePolicy, QProgressBar
    )
    from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal as Signal, QThread, QObject, QUrl, QRectF, QRect, QSize
    from PyQt6.QtGui import QColor, QFont, QFontMetrics, QCursor, QPixmap, QImage, QPainter, QIcon, QPen, QBrush, QPainterPath
    try:
        from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink
        MULTIMEDIA_AVAILABLE = True
    except ImportError:
        QMediaPlayer = QAudioOutput = QVideoSink = None
        MULTIMEDIA_AVAILABLE = False
    QT_LIB = "PyQt6"
except ImportError:
    from PySide6.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QGraphicsDropShadowEffect, QFrame, QDialog, QLineEdit, QListWidget,
        QListWidgetItem, QMessageBox, QComboBox, QSpinBox, QDoubleSpinBox,
        QSlider, QGroupBox, QFormLayout, QSystemTrayIcon, QMenu, QSizeGrip,
        QTabWidget, QTextEdit, QColorDialog, QSizePolicy, QProgressBar
    )
    from PySide6.QtCore import Qt, QPoint, QTimer, Signal, QThread, QObject, QUrl, QRectF, QRect, QSize
    from PySide6.QtGui import QColor, QFont, QFontMetrics, QCursor, QPixmap, QImage, QPainter, QIcon, QPen, QBrush, QPainterPath
    try:
        from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink
        MULTIMEDIA_AVAILABLE = True
    except ImportError:
        QMediaPlayer = QAudioOutput = QVideoSink = None
        MULTIMEDIA_AVAILABLE = False
    QT_LIB = "PySide6"
