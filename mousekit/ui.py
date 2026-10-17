"""Mousekit settings app, laid out after OpenLogi.

A mouse illustration with callout cards for each button; clicking a card
opens that button's editor (click, four swipe directions, wheel while held).
Pointer and device settings live on their own tabs. Follows the system's
light or dark scheme (MOUSEKIT_THEME=light|dark forces one).
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from PyQt6.QtCore import (
    QObject, QPoint, QPointF, QProcess, QRectF, QSize, QSocketNotifier, Qt, QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QConicalGradient, QDesktopServices, QFont, QFontDatabase, QFontMetrics, QGuiApplication, QIcon,
    QKeySequence, QPainter, QPalette, QPen, QPixmap, QRadialGradient,
)
from PyQt6.QtNetwork import QLocalSocket, QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import (
    QAbstractButton, QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QKeySequenceEdit, QLabel, QLineEdit, QMainWindow,
    QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSlider, QStackedWidget, QTextBrowser, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import __author__, __version__, backups, config, devices, dump, effects, models, updates, vendor
from .drawing import LED_MODES, SINGLE_COLOUR_MODES, Lighting, art_for
from .config import DEFAULT_ACTION, LOCKED_BUTTONS, SWIPE_DIRECTIONS, WHEEL_DIRECTIONS
from .keys import parse_combo
from .presets import (
    BUTTON_LABELS, PRESET_GROUPS, SWIPE_LABELS, SWIPE_NAMES, WHEEL_NAMES, action_icon, action_label,
)

APP_NAME = "Mousekit for GamePro"
SERVICE = "mousekit.service"
UDEV_HINT = ("echo 'SUBSYSTEM==\"input\", KERNEL==\"event*\", ENV{ID_INPUT_MOUSE}==\"1\", "
             "ENV{ID_INPUT_TOUCHPAD}!=\"1\", ENV{ID_INPUT_KEYBOARD}!=\"1\", TAG+=\"uaccess\"' "
             "| sudo tee /etc/udev/rules.d/70-mousekit.rules && sudo udevadm control --reload && "
             "sudo udevadm trigger --subsystem-match=input")


def load_kde_catalog():
    """[(component, friendly component name, [(shortcut, friendly name)])], or [] without D-Bus."""
    try:
        import dbus

        from .actions import COMPONENT_IFACE, KGLOBALACCEL, component_paths

        bus = dbus.SessionBus()
        catalog = []
        for unique, path in component_paths(bus).items():
            obj = bus.get_object(KGLOBALACCEL, path)
            props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
            friendly = str(props.Get(COMPONENT_IFACE, "friendlyName")) or unique
            infos = obj.allShortcutInfos(dbus_interface=COMPONENT_IFACE)
            items = sorted(((str(i[0]), str(i[1]) or str(i[0])) for i in infos), key=lambda x: x[1].lower())
            catalog.append((unique, friendly, items))
        return sorted(catalog, key=lambda c: c[1].lower())
    except Exception:  # noqa: BLE001 - the app still works with presets only
        return []


def systemctl(*args):
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


# Theme


class Theme:
    def __init__(self):
        forced = os.environ.get("MOUSEKIT_THEME")
        window = QApplication.palette().color(QPalette.ColorRole.Window)
        self.dark = forced == "dark" or (forced != "light" and window.lightness() < 128)
        if self.dark:
            self.bg, self.surface, self.hover, self.raised = "#1c1c1e", "#2a2a2d", "#333337", "#3a3a3e"
            self.border, self.text, self.dim, self.line = "#3a3a3d", "#f2f2f7", "#98989d", "#5a5a60"
        else:
            self.bg, self.surface, self.hover, self.raised = "#f5f5f7", "#ebebef", "#e2e2e8", "#ffffff"
            self.border, self.text, self.dim, self.line = "#d6d6dc", "#1d1d1f", "#6e6e73", "#c2c2c8"
        self.accent = QApplication.palette().color(QPalette.ColorRole.Highlight).name()
        self.green, self.orange = "#34c759", "#ff9f0a"

    def stylesheet(self):
        return f"""
        QWidget#root, QWidget#page, QScrollArea#page > QWidget > QWidget {{ background: {self.bg}; }}
        QLabel {{ color: {self.text}; background: transparent; }}
        QLabel[dim="true"] {{ color: {self.dim}; }}
        QFrame#card {{ background: {self.surface}; border: 1px solid {self.border}; border-radius: 10px; }}
        QFrame#card:hover {{ background: {self.hover}; }}
        QFrame#card[active="true"] {{ border: 1px solid {self.accent}; }}
        QFrame#card[empty="true"] QLabel#value {{ color: {self.dim}; }}
        QFrame#panel {{ background: {self.surface}; border: 1px solid {self.border}; border-radius: 12px; }}
        QFrame#segment {{ background: {self.surface}; border-radius: 9px; }}
        QPushButton#seg {{ border: none; border-radius: 7px; padding: 6px 18px; color: {self.text};
                           background: transparent; }}
        QPushButton#seg:checked {{ background: {self.raised}; }}
        QPushButton#seg:hover:!checked {{ color: {self.text}; background: {self.hover}; }}
        QPushButton#seg:disabled {{ color: {self.dim}; }}
        QPushButton#flat {{ border: none; border-radius: 6px; padding: 5px 9px; color: {self.text};
                            background: transparent; }}
        QPushButton#flat:hover {{ background: {self.hover}; }}
        QPushButton#outline {{ border: 1px solid {self.border}; border-radius: 8px; padding: 6px 14px;
                               color: {self.text}; background: {self.raised}; }}
        QPushButton#outline:hover {{ background: {self.hover}; }}
        QLabel#pill {{ border: 1px solid {self.border}; border-radius: 10px; padding: 3px 12px;
                       color: {self.dim}; background: {self.bg}; }}
        QFrame#hline {{ background: {self.border}; border: none; }}
        QPushButton#chip {{ border: 1px solid {self.border}; border-radius: 8px; padding: 7px 12px;
                            background: {self.surface}; color: {self.text}; text-align: left; }}
        QPushButton#chip:hover {{ background: {self.hover}; }}
        QPushButton#chip:checked {{ border: 1px solid {self.accent}; background: {self.raised}; }}
        QPushButton#chip:disabled {{ color: {self.dim}; background: transparent; }}
        """


def font(scale=1.0, weight=None):
    f = QFont(QApplication.font())
    f.setPointSizeF(f.pointSizeF() * scale)
    if weight is not None:
        f.setWeight(weight)
    return f


def repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    for child in widget.findChildren(QWidget):
        child.style().unpolish(child)
        child.style().polish(child)


def dim_label(text="", scale=0.92):
    label = QLabel(text)
    label.setProperty("dim", True)
    label.setFont(font(scale))
    return label


def hline():
    line = QFrame()
    line.setObjectName("hline")
    line.setFixedHeight(1)
    return line


# Small widgets


class Switch(QAbstractButton):
    def __init__(self, theme):
        super().__init__()
        self.theme = theme
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 26)

    def sizeHint(self):
        return QSize(44, 26)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        track = QColor(self.theme.accent if on else self.theme.border)
        if not self.isEnabled():
            track.setAlpha(110)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 44, 26), 13, 13)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(31 if on else 13, 13), 10, 10)


class Pill(QLabel):
    def __init__(self):
        super().__init__()
        self.setObjectName("pill")

    def set_state(self, text, color):
        self.setText(f'<span style="color:{color}">●</span>&nbsp;{text}')


class Segmented(QFrame):
    changed = pyqtSignal(int)

    def __init__(self, labels):
        super().__init__()
        self.setObjectName("segment")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.group = QButtonGroup(self)
        for index, label in enumerate(labels):
            button = QPushButton(label)
            button.setObjectName("seg")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFont(font(1.05))
            self.group.addButton(button, index)
            layout.addWidget(button)
        self.group.button(0).setChecked(True)
        self.group.idClicked.connect(self.changed.emit)


class ChoiceGrid(QWidget):
    """Exclusive chips in a grid; same interface as Segmented (.group, .changed)."""

    changed = pyqtSignal(int)

    def __init__(self, labels, columns=2):
        super().__init__()
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.group = QButtonGroup(self)
        for index, label in enumerate(labels):
            chip = QPushButton(label)
            chip.setObjectName("chip")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            self.group.addButton(chip, index)
            layout.addWidget(chip, index // columns, index % columns)
        self.group.button(0).setChecked(True)
        self.group.idClicked.connect(self.changed.emit)


class Card(QFrame):
    """OpenLogi-style callout: a dim caption over an icon, a value and a chevron."""

    clicked = pyqtSignal()

    def __init__(self, caption, width=270, value_scale=1.15, clickable=True):
        super().__init__()
        self.setObjectName("card")
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(width)
        self.caption = dim_label(caption)
        self.icon = QLabel()
        self.icon.setFixedSize(20, 20)
        self.value = QLabel()
        self.value.setObjectName("value")
        self.value.setFont(font(value_scale))
        chevron = dim_label("›", 1.4)
        chevron.setVisible(clickable)
        row = QHBoxLayout()
        row.setSpacing(9)
        row.addWidget(self.icon)
        row.addWidget(self.value, 1)
        row.addWidget(chevron)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 9, 12, 10)
        layout.setSpacing(3)
        layout.addWidget(self.caption)
        layout.addLayout(row)

    def set_value(self, icon, text, empty=False):
        self.icon.setPixmap(QIcon.fromTheme(icon).pixmap(20, 20))
        room = self.width() - 14 - 12 - 20 - 9 - 9 - 14
        self.value.setText(QFontMetrics(self.value.font()).elidedText(text, Qt.TextElideMode.ElideRight, room))
        self.setToolTip(text if self.value.text() != text else "")
        self.setProperty("empty", empty)
        repolish(self)

    def set_swatch(self, colour, lit, text):
        """Like set_value, with a colour dot instead of an icon: one colour, a rainbow, or an empty ring."""
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(int(20 * ratio), int(20 * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if colour is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(colour)
        elif lit:
            rainbow = QConicalGradient(QPointF(10, 10), 90)
            for i, c in enumerate(("#ff3b30", "#ffcc00", "#34c759", "#00c7ff", "#5856d6", "#ff2d92", "#ff3b30")):
                rainbow.setColorAt(i / 6, QColor(c))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(rainbow)
        else:
            p.setPen(QPen(QColor("#8e8e93"), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(3, 3, 14, 14))
        p.end()
        self.set_value("", text)
        self.icon.setPixmap(pixmap)

    def set_active(self, active):
        if self.property("active") != active:
            self.setProperty("active", active)
            repolish(self)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()


# Action picking


class KeyComboDialog(QDialog):
    def __init__(self, parent, current=""):
        super().__init__(parent)
        self.setWindowTitle("Key combination")
        self.edit = QKeySequenceEdit(QKeySequence(current))
        self.edit.setMaximumSequenceLength(1)
        self.error = QLabel()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Press the key combination the mouse should send:"))
        layout.addWidget(self.edit)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        self.combo = ""

    def _accept(self):
        combo = self.edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        try:
            parse_combo(combo)
        except ValueError:
            self.error.setText("The mouse can't send this combination; pick another one.")
            return
        self.combo = combo
        self.accept()


class KdeActionDialog(QDialog):
    def __init__(self, parent, catalog):
        super().__init__(parent)
        self.setWindowTitle("KDE action")
        self.resize(560, 520)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Search…")
        self.filter.textChanged.connect(self._filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        for unique, friendly, items in catalog:
            parent_item = QTreeWidgetItem([friendly])
            for name, label in items:
                child = QTreeWidgetItem([label])
                child.setData(0, Qt.ItemDataRole.UserRole, (unique, name))
                parent_item.addChild(child)
            self.tree.addTopLevelItem(parent_item)
        self.tree.itemDoubleClicked.connect(lambda *_: self._accept())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.filter)
        layout.addWidget(self.tree)
        layout.addWidget(buttons)
        self.action = None

    def _filter(self, text):
        text = text.lower()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            visible = 0
            for j in range(top.childCount()):
                child = top.child(j)
                hide = bool(text) and text not in child.text(0).lower() and text not in top.text(0).lower()
                child.setHidden(hide)
                visible += not hide
            top.setHidden(visible == 0)
            top.setExpanded(bool(text) and visible > 0)

    def _accept(self):
        item = self.tree.currentItem()
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not data:
            return
        self.action = {"type": "shortcut", "component": data[0], "name": data[1]}
        self.accept()


class ActionTile(Card):
    """A card holding one action; clicking it opens the action menu."""

    changed = pyqtSignal()

    def __init__(self, caption, role, app, button_name, width, value_scale=1.15):
        super().__init__(caption, width, value_scale)
        self.role = role            # "click", "swipe" or "wheel"
        self.app = app
        self.button_name = button_name
        self.allow_precision = True
        self.action = None
        self.clicked.connect(self._menu)

    default_label = None  # shown instead of "Default" (e.g. what the mouse itself does)

    def set_action(self, action):
        self.action = action
        label = action_label(action, self.app.catalog_names)
        if action and action["type"] == "default" and self.default_label:
            label = self.default_label
        self.set_value(action_icon(action), label, empty=not action)

    def _set(self, action):
        self.set_action(action)
        self.changed.emit()

    def _menu(self):
        window = self.window()  # parent menus/dialogs outside the styled tree
        menu = QMenu(window)
        if self.role == "click":
            menu.addAction(QIcon.fromTheme("input-mouse"), "Default", lambda: self._set(dict(DEFAULT_ACTION)))
            menu.addAction(QIcon.fromTheme("dialog-cancel"), "Nothing", lambda: self._set({"type": "disabled"}))
        else:
            menu.addAction(QIcon.fromTheme("edit-clear"), "Not set", lambda: self._set(None))
        menu.addSeparator()
        for group, icon, presets in PRESET_GROUPS:
            sub = menu.addMenu(QIcon.fromTheme(icon), group)
            for label, preset, item_icon in presets:
                sub.addAction(QIcon.fromTheme(item_icon), label, lambda p=preset: self._set(dict(p)))
        sub = menu.addMenu(QIcon.fromTheme("input-mouse"), "Mouse button")
        for name, label in BUTTON_LABELS.items():
            if name != self.button_name:
                sub.addAction(label, lambda n=name: self._set({"type": "button", "button": n}))
        if self.role == "click":
            precision = menu.addAction(QIcon.fromTheme("crosshairs"), "Precision mode (while held)",
                                       lambda: self._set({"type": "precision"}))
            precision.setEnabled(self.allow_precision)
        menu.addSeparator()
        menu.addAction(QIcon.fromTheme("input-keyboard"), "Key combination…", self._pick_keys)
        menu.addAction(QIcon.fromTheme("kde"), "Any KDE action…", self._pick_kde)
        menu.addAction(QIcon.fromTheme("utilities-terminal"), "Command…", self._pick_command)
        menu.exec(self.mapToGlobal(QPoint(0, self.height() + 2)))

    def _pick_keys(self):
        current = self.action.get("combo", "") if self.action and self.action["type"] == "keys" else ""
        dialog = KeyComboDialog(self.window(), current)
        if dialog.exec():
            self._set({"type": "keys", "combo": dialog.combo})

    def _pick_kde(self):
        dialog = KdeActionDialog(self.window(), self.app.catalog)
        if dialog.exec() and dialog.action:
            self._set(dialog.action)

    def _pick_command(self):
        current = self.action.get("command", "") if self.action and self.action["type"] == "command" else ""
        text, ok = QInputDialog.getText(self.window(), "Command", "Command to run:", text=current)
        if ok and text.strip():
            self._set({"type": "command", "command": text.strip()})


# The mouse illustration


class MouseCanvas(QWidget):
    """Paints the mouse, callout lines and dots; the left column is laid over it."""

    def __init__(self, theme, column, buttons, art, lighting=None):
        super().__init__()
        self.theme = theme
        self.column = column
        self.art = art
        self.lighting = lighting
        self.buttons = [b for b in buttons if b in art.dots]
        self.anchors = {}       # button -> widget whose right edge the callout starts from
        self.pressed = set()
        self.selected = None
        # Repaint ~30 times a second while an animated lighting effect is shown.
        self.animation = QTimer(self, interval=33, timeout=self.update)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(column)
        layout.addStretch(1)

    @staticmethod
    def now():
        return time.monotonic()

    def lighting_changed(self):
        animate = self.lighting is not None and self.lighting.animated() and self.isVisible()
        if animate and not self.animation.isActive():
            self.animation.start()
        elif not animate:
            self.animation.stop()
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.lighting_changed()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.animation.stop()

    def _transform(self):
        width, height = self.art.size
        left = self.column.geometry().right() + 70
        avail = QRectF(left, 36, max(1, self.width() - left - 60), max(1, self.height() - 72))
        scale = min(avail.width() / width, avail.height() / height, 1.35)
        return avail.center().x() - width * scale / 2, avail.center().y() - height * scale / 2, scale

    def dot(self, button):
        x, y, s = self._transform()
        dx, dy = self.art.dots[button]
        return QPointF(x + dx * s, y + dy * s)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x, y, s = self._transform()
        p.save()
        p.translate(x, y)
        p.scale(s, s)
        self.art.paint(p, self.theme, self.buttons, self.lighting, self.now())
        p.restore()

        for button, anchor in self.anchors.items():
            if button not in self.art.dots or not anchor.isVisible():
                continue
            a = anchor.mapTo(self, QPoint(anchor.width(), anchor.height() // 2))
            start = QPointF(a.x() + 1, a.y())
            end = self.dot(button)
            lit = button in self.pressed or button == self.selected
            p.setPen(QPen(QColor(self.theme.accent if lit else self.theme.line), 1.6 if lit else 1.1))
            p.drawPolyline([start, QPointF(start.x() + 46, end.y()), end])

        for button in self.buttons:
            lit = button in self.pressed or button == self.selected
            center = self.dot(button)
            if lit:
                halo = QColor(self.theme.accent)
                halo.setAlpha(70)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(halo)
                p.drawEllipse(center, 13, 13)
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.setBrush(QColor(self.theme.accent if lit else "#2c2e33"))
            p.drawEllipse(center, 6.5, 6.5)


class VendorChannel(QObject):
    """The mouse's vendor HID channel: live DPI stage and lighting, lighting writes.

    Survives replugs: when the mouse goes away the channel closes, and the
    poll timer reopens it as soon as the mouse is back.
    """

    stage_changed = pyqtSignal(int)
    pressed = pyqtSignal(bool)
    key_pressed = pyqtSignal()  # a button programmed in the mouse as a media key
    lighting_changed = pyqtSignal(int, int)
    reconnected = pyqtSignal()  # the mouse came back after being unplugged

    def __init__(self, key, node, parent):
        super().__init__(parent)
        self.key = key
        self.fd = None
        self.notifier = None
        self.stage = None
        self.stages = vendor.DPI_STAGES.get(key)
        model = models.identify(key)
        self.verified = bool(model and model.get("verified"))  # memory layout checked: may save to the mouse
        self.led = None
        self._open(node)
        # Also catches the mouse's own lighting button, which changes the mode without telling us.
        self.poll = QTimer(self, interval=1500, timeout=self._poll)
        self.poll.start()

    @classmethod
    def open(cls, key, parent):
        node = vendor.find_hidraw(key)
        if not node:
            return None
        try:
            return cls(key, node, parent)
        except OSError:
            return None

    def _open(self, node):
        fd = os.open(node, os.O_RDWR | os.O_NONBLOCK)
        try:
            stage, stages = vendor.read_dpi(fd)
            led = vendor.lighting(vendor.read_status(fd))
        except OSError:
            os.close(fd)
            raise
        self.fd = fd
        self.stage, self.stages = stage, stages or self.stages
        self.led = led
        self.notifier = QSocketNotifier(fd, QSocketNotifier.Type.Read, self)
        self.notifier.activated.connect(self._readable)

    def _close(self):
        if self.notifier is not None:
            self.notifier.setEnabled(False)
            self.notifier.deleteLater()
            self.notifier = None
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None

    def _reopen(self):
        node = vendor.find_hidraw(self.key)
        if not node:
            return False
        try:
            self._open(node)
        except OSError:
            return False
        if self.stage is not None:
            self.stage_changed.emit(self.stage)
        if self.led:
            self.lighting_changed.emit(*self.led)
        self.reconnected.emit()
        return True

    def _call(self, func, *args):
        """func(fd, *args), reopening once if the mouse was replugged since."""
        if func in vendor.SAVES:
            self._backup_first()
        for _ in range(2):
            if self.fd is None and not self._reopen():
                raise OSError("the mouse is not connected")
            try:
                return func(self.fd, *args)
            except OSError:
                self._close()
        raise OSError("the mouse is not responding")

    def _backup_first(self):
        """Keep the mouse's settings from before Mousekit's first change to it."""
        path = backups.first_path(self.key)
        if not path.exists():
            backups.save(path, backups.make(self.key, self._call(vendor.read_settings)))

    def label(self):
        if self.stage is None:
            return "—"
        total = f" of {self.stages}" if self.stages else ""
        return f"Stage {self.stage + 1}{total}"

    def apply_lighting(self, light):
        try:
            self._call(vendor.apply_lighting, light)
            return True
        except OSError:
            return False

    def save_lighting(self, light):
        """Store lighting in the mouse's memory; returns an error message or None."""
        try:
            self._call(vendor.save_lighting, light)
            return None
        except (OSError, ValueError) as err:
            return str(err)

    def _poll(self):
        if self.fd is None:
            self._reopen()
            return
        try:
            led = vendor.lighting(vendor.read_status(self.fd))
        except OSError:  # unplugged; the next poll reopens
            self._close()
            return
        if led and led != self.led:
            self.led = led
            self.lighting_changed.emit(*led)

    def _readable(self):
        while self.fd is not None:
            try:
                report = os.read(self.fd, 64)
            except BlockingIOError:
                return
            except OSError:
                self._close()
                return
            if vendor.is_key_press(report):
                self.key_pressed.emit()
                continue
            event = vendor.parse_input(report)
            if not event:
                continue
            kind, _, stage = event
            if kind == "dpi-press":
                self.pressed.emit(True)
            else:
                self.pressed.emit(False)
                self.stage = stage
                self.stage_changed.emit(stage)


class MiniMouse(QWidget):
    def __init__(self, theme, buttons, art, height=150):
        super().__init__()
        self.theme = theme
        self.buttons = buttons
        self.art = art
        self.setFixedHeight(height)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.art.size
        s = (self.height() - 12) / height
        p.translate(self.width() / 2 - width * s / 2, 4)
        p.scale(s, s)
        self.art.paint(p, self.theme, self.buttons)


# Device tabs


def button_summary(cfg, catalog):
    """Icon and text a button's callout card shows."""
    swipes = len(cfg.get("swipe", {}))
    wheel = len(cfg.get("wheel", {}))
    if swipes or wheel:
        parts = []
        if swipes:
            parts.append(f"{swipes} gesture{'s' if swipes != 1 else ''}")
        if wheel:
            parts.append("wheel")
        return "transform-move", " + ".join(parts)
    click = cfg.get("click") or DEFAULT_ACTION
    return action_icon(click), action_label(click, catalog)


class ButtonEditor(QWidget):
    back = pyqtSignal()
    changed = pyqtSignal(str, dict)

    TILE = 186

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.name = None
        self.back_button = QPushButton("‹  All buttons")
        self.back_button.setObjectName("flat")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self.back.emit)
        self.title = QLabel()
        self.title.setFont(font(1.6, QFont.Weight.DemiBold))
        self.title_row = QWidget()  # the callout line starts at its right edge
        title_layout = QHBoxLayout(self.title_row)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.addWidget(self.title)
        title_layout.addStretch()

        tile, gap, hub = self.TILE, 8, 56
        full = tile * 2 + hub + gap * 2
        self.click = ActionTile("Click", "click", app, None, full)
        self.swipe = {d: ActionTile(f"{SWIPE_LABELS[d]}  {SWIPE_NAMES[d]}", "swipe", app, None, tile, 1.05)
                      for d in SWIPE_DIRECTIONS}
        self.wheel = {d: ActionTile(WHEEL_NAMES[d], "wheel", app, None, (full - gap) // 2, 1.05)
                      for d in WHEEL_DIRECTIONS}

        # A plus-shaped pad: up and down centred over a small hub between left and right.
        pad = QVBoxLayout()
        pad.setSpacing(gap)
        middle = QHBoxLayout()
        middle.setSpacing(gap)
        hub_icon = QLabel()
        hub_icon.setPixmap(QIcon.fromTheme("transform-move").pixmap(28, 28))
        hub_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hub_icon.setFixedWidth(hub)
        middle.addWidget(self.swipe["left"])
        middle.addWidget(hub_icon)
        middle.addWidget(self.swipe["right"])
        middle.addStretch()
        for row in (self.swipe["up"], None, self.swipe["down"]):
            if row is None:
                pad.addLayout(middle)
                continue
            line = QHBoxLayout()
            line.addSpacing((full - tile) // 2)
            line.addWidget(row)
            line.addStretch()
            pad.addLayout(line)

        wheels = QHBoxLayout()
        wheels.setSpacing(gap)
        for tile_widget in self.wheel.values():
            wheels.addWidget(tile_widget)
        wheels.addStretch()

        self.note = dim_label("", 0.9)
        self.note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 18, 0, 18)
        layout.setSpacing(6)
        layout.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.title_row)
        layout.addSpacing(10)
        layout.addWidget(self.click)
        layout.addSpacing(14)
        layout.addWidget(dim_label("Hold and move the mouse"))
        layout.addLayout(pad)
        layout.addSpacing(14)
        layout.addWidget(dim_label("Hold and turn the wheel"))
        layout.addLayout(wheels)
        layout.addSpacing(10)
        layout.addWidget(self.note)
        layout.addStretch()

        for t in [self.click, *self.swipe.values(), *self.wheel.values()]:
            t.changed.connect(self._emit)

    def load(self, name, cfg):
        self.name = name
        self.title.setText(BUTTON_LABELS.get(name, name))
        for t in [self.click, *self.swipe.values(), *self.wheel.values()]:
            t.button_name = name
        self.click.set_action(cfg.get("click") or dict(DEFAULT_ACTION))
        for d, t in self.swipe.items():
            t.set_action(cfg.get("swipe", {}).get(d))
        for d, t in self.wheel.items():
            t.set_action(cfg.get("wheel", {}).get(d))
        self._update_note()

    def config(self):
        cfg = {}
        if self.click.action and self.click.action["type"] != "default":
            cfg["click"] = self.click.action
        swipe = {d: t.action for d, t in self.swipe.items() if t.action}
        wheel = {d: t.action for d, t in self.wheel.items() if t.action}
        if swipe:
            cfg["swipe"] = swipe
        if wheel:
            cfg["wheel"] = wheel
        return cfg

    def _update_note(self):
        cfg = self.config()
        held = bool(cfg.get("swipe") or cfg.get("wheel"))
        self.click.allow_precision = not held
        if held and self.click.action.get("type") == "precision":
            self.note.setText("Precision mode doesn't work while the button has gestures or wheel actions.")
        elif held:
            self.note.setText("A short press runs the Click action. A gesture fires when you hold the button "
                              "and move the mouse; a wheel action when you turn the wheel while holding it.")
        else:
            self.note.setText("Assign a gesture or a wheel action to make this a gesture button, "
                              "like Logitech's Gesture Button.")

    def _emit(self):
        self._update_note()
        self.changed.emit(self.name, self.config())


# Buttons whose presses arrive as keys from the mouse's keyboard interface (see daemon.KEY_BUTTONS).
KEY_BUTTONS = {
    "FORWARD_KEY": ("Forward", "Mouse default: next track"),
    "FIRE": ("Fire", "Mouse default: play / pause"),
    "DPI_UP": ("DPI+", "Fast forward (does nothing)"),
    "DPI_DOWN": ("DPI−", "Rewind (does nothing)"),
}


class ButtonsTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, info, profile, app, dpi=None, art=None, lighting=None, hw=None):
        super().__init__()
        hw = hw or {}
        self.app = app
        self.profile = profile
        self.dpi = dpi
        self.lighting = lighting
        self.cards = {}
        art = art or art_for(info.key)
        self.column = QStackedWidget()
        self.column.setFixedWidth(500)

        cards_page = QWidget()
        cards_layout = QVBoxLayout(cards_page)
        cards_layout.setContentsMargins(36, 0, 0, 0)
        cards_layout.setSpacing(12)
        cards_layout.addStretch()
        editable = [b for b in info.buttons if b not in LOCKED_BUTTONS]
        if hw.get("forward_key"):  # Forward is programmed in the mouse as a key, not BTN_EXTRA
            editable = [b for b in editable if b != "BTN_EXTRA"] + ["FORWARD_KEY"]
        if hw.get("fire_key"):
            editable.append("FIRE")
        if hw.get("dpi_keys"):
            editable += ["DPI_UP", "DPI_DOWN"]
        shown = editable + (["DPI"] if dpi and not hw.get("dpi_keys") else []) \
            + (["LIGHT"] if lighting and lighting.known() else [])
        for name in sorted(shown, key=lambda b: art.dots.get(b, (0, 999))[1]):
            if name in KEY_BUTTONS:
                caption, default_label = KEY_BUTTONS[name]
                card = ActionTile(caption, "click", app, name, 270)
                card.default_label = default_label
                card.changed.connect(lambda n=name, c=card: self._key_changed(n, c.action))
            elif name == "LIGHT":
                card = Card("Lighting", clickable=False)
                card.setToolTip("The current lighting mode, read from the mouse.")
            elif name == "DPI":
                # Read-only: the firmware switches DPI itself; we only see the stage.
                card = Card("DPI", clickable=False)
                card.setToolTip("The DPI buttons work in the mouse itself. This shows the current stage.")
                dpi.stage_changed.connect(lambda _: self._show_dpi())
                dpi.pressed.connect(lambda down: self.set_pressed("DPI", down))
            else:
                card = Card(BUTTON_LABELS.get(name, name))
                card.clicked.connect(lambda n=name: self.open_editor(n))
            self.cards[name] = card
            cards_layout.addWidget(card)
        if not editable:
            cards_layout.addWidget(dim_label("This mouse only has left and right buttons."))
        locked = dim_label("Left and right buttons always work as usual.", 0.88)
        cards_layout.addSpacing(6)
        cards_layout.addWidget(locked)
        cards_layout.addStretch()
        self.column.addWidget(cards_page)

        self.editor = ButtonEditor(app)
        self.editor.back.connect(self.close_editor)
        self.editor.changed.connect(self._button_changed)
        self.column.addWidget(self.editor)

        self.canvas = MouseCanvas(app.theme, self.column, shown, art, lighting)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.refresh_cards()
        self.close_editor()

    def refresh_cards(self):
        for name, card in self.cards.items():
            if name in KEY_BUTTONS:
                card.set_action(self.profile["buttons"].get(name, {}).get("click") or dict(DEFAULT_ACTION))
            elif name == "DPI":
                self._show_dpi()
            elif name == "LIGHT":
                self.show_lighting()
            else:
                card.set_value(*button_summary(self.profile["buttons"].get(name, {}), self.app.catalog_names))

    def _show_dpi(self):
        self.cards["DPI"].set_value("speedometer", self.dpi.label())

    def show_lighting(self):
        light = self.lighting
        card = self.cards.get("LIGHT")
        if card is None:
            return
        if light.effect_light:
            effect = light.effect_light.get("effect")
            colour = QColor(*light.effect_light["color"]) if effect in effects.NEEDS_COLOUR else None
            card.set_swatch(colour, True, light.label())
        else:
            colour = QColor(*light.colour) if light.mode in SINGLE_COLOUR_MODES and light.colour else None
            card.set_swatch(colour, light.mode not in (None, 13), light.label())
        self.canvas.lighting_changed()

    def open_editor(self, name):
        self.editor.load(name, self.profile["buttons"].get(name, {}))
        self.column.setCurrentWidget(self.editor)
        self.canvas.selected = name
        self.canvas.anchors = {name: self.editor.title_row}
        self.canvas.update()

    def close_editor(self):
        self.column.setCurrentIndex(0)
        self.canvas.selected = None
        self.canvas.anchors = dict(self.cards)
        self.canvas.update()

    def _key_changed(self, name, action):
        if action and action["type"] != "default":
            self.profile["buttons"][name] = {"click": action}
        else:
            self.profile["buttons"].pop(name, None)
        self.refresh_cards()
        self.changed.emit()

    def _button_changed(self, name, cfg):
        if cfg:
            self.profile["buttons"][name] = cfg
        else:
            self.profile["buttons"].pop(name, None)
        self.refresh_cards()
        self.changed.emit()

    def set_pressed(self, button, pressed):
        (self.canvas.pressed.add if pressed else self.canvas.pressed.discard)(button)
        if button in self.cards:
            self.cards[button].set_active(pressed)
        self.canvas.update()


class SettingsPanel(QFrame):
    """A rounded panel of rows: title + description on the left, a control on the right."""

    def __init__(self):
        super().__init__()
        self.setObjectName("panel")
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(20, 6, 20, 6)
        self.layout_.setSpacing(0)
        self.rows = 0

    def add_row(self, title, description, control=None, below=None):
        if self.rows:
            self.layout_.addWidget(hline())
        self.rows += 1
        row = QHBoxLayout()
        row.setContentsMargins(0, 12, 0, 12)
        text = QVBoxLayout()
        text.setSpacing(2)
        heading = QLabel(title)
        heading.setFont(font(1.05, QFont.Weight.DemiBold))
        text.addWidget(heading)
        if description:
            desc = dim_label(description, 0.9)
            desc.setWordWrap(True)
            text.addWidget(desc)
        row.addLayout(text, 1)
        if control is not None:
            row.addSpacing(16)
            row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self.layout_.addLayout(row)
        if below is not None:
            self.layout_.addWidget(below)
            self.layout_.addSpacing(12)
        return heading


def centered_scroll(*widgets):
    area = QScrollArea()
    area.setObjectName("page")
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    body = QWidget()
    outer = QHBoxLayout(body)
    column = QVBoxLayout()
    column.setSpacing(18)
    column.setContentsMargins(0, 28, 0, 28)
    for widget in widgets:
        column.addWidget(widget)
    column.addStretch()
    holder = QWidget()
    holder.setLayout(column)
    holder.setMaximumWidth(680)
    outer.addStretch()
    outer.addWidget(holder, 1)
    outer.addStretch()
    area.setWidget(body)
    return area


def slider_control(low, high, value, fmt, callback, width=280):
    widget = QWidget()
    widget.setFixedWidth(width)
    row = QHBoxLayout(widget)
    row.setContentsMargins(0, 0, 0, 0)
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(low, high)
    slider.setValue(int(value))
    label = dim_label(fmt.format(int(value)), 0.95)
    label.setFixedWidth(64)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    slider.valueChanged.connect(lambda v: (label.setText(fmt.format(v)), callback(v)))
    row.addWidget(slider, 1)
    row.addWidget(label)
    return widget


class DpiPanel(SettingsPanel):
    """The mouse's six DPI stages: value and on/off, saved into the mouse's memory."""

    def __init__(self, app, channel):
        super().__init__()
        self.app = app
        self.channel = channel
        self.stage_rows = []
        try:
            stages, current = channel._call(vendor.read_dpi_config)
        except OSError:
            stages, current = [(None, False)] * 6, None
        for stage, (dpi, on) in enumerate(stages):
            combo = QComboBox()
            for value in vendor.DPI_STEPS:
                combo.addItem(f"{value} DPI", value)
            if dpi in vendor.DPI_STEPS:
                combo.setCurrentIndex(vendor.DPI_STEPS.index(dpi))
            switch = Switch(app.theme)
            switch.setChecked(on)
            controls = QWidget()
            row = QHBoxLayout(controls)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(14)
            row.addWidget(combo)
            row.addWidget(switch)
            heading = self.add_row(f"Stage {stage + 1}", "", controls)
            self.stage_rows.append((heading, combo, switch))
        self.current = QComboBox()
        for stage in range(len(stages)):
            self.current.addItem(f"Stage {stage + 1}", stage)
        self.current.activated.connect(self._set_current)
        self.add_row("Current stage", "The stage the mouse uses now and after power-up.", self.current)
        save = QPushButton("Save")
        save.setObjectName("outline")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.clicked.connect(self._save)
        self.add_row("Save to mouse", "Values and enabled stages. The mouse skips disabled stages "
                     "when its own DPI buttons switch stages.", save)
        if not channel.verified:
            for _, combo, switch in self.stage_rows:
                combo.setEnabled(False)
                switch.setEnabled(False)
            self.current.setEnabled(False)
            save.setEnabled(False)
            self.add_row("Read only", "Saving to this mouse model isn't verified yet. "
                         "Request support on the Device tab.", None)
        self.show_current(current)
        channel.stage_changed.connect(self.show_current)

    def show_current(self, current):
        for stage, (heading, _, _) in enumerate(self.stage_rows):
            heading.setText(f"Stage {stage + 1}" + ("  ·  current" if stage == current else ""))
        if current is not None:
            self.current.setCurrentIndex(current)

    def _set_current(self, index):
        stage = self.current.itemData(index)
        try:
            self.channel._call(vendor.set_dpi_stage, stage)
        except (OSError, ValueError) as err:
            self.app.footer.show_event(f"Couldn't change the stage: {err}")
            self.show_current(self.channel.stage)
            return
        self.channel.stage = stage
        self.channel.stage_changed.emit(stage)
        self.app.footer.show_event(f"Current DPI stage: {stage + 1}")

    def _save(self):
        stages = [(combo.currentData(), switch.isChecked()) for _, combo, switch in self.stage_rows]
        try:
            self.channel._call(vendor.save_dpi, stages)
            current, total = self.channel._call(vendor.read_dpi)
        except (OSError, ValueError) as err:
            self.app.footer.show_event(f"Couldn't save DPI: {err}")
            return
        self.channel.stage, self.channel.stages = current, total or self.channel.stages
        self.channel.stage_changed.emit(current)
        self.app.footer.show_event("DPI stages saved to the mouse")


class PointerTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, profile, app=None, channel=None):
        super().__init__()
        self.profile = profile
        gestures = SettingsPanel()
        gestures.add_row("Gesture distance", "How far to move the mouse for a gesture to fire. Shorter is more responsive.",
                         slider_control(20, 400, profile["gesture"]["threshold"], "{}",
                                        lambda v: self._set_gesture("threshold", v)))
        gestures.add_row("Gesture delay", "A press shorter than this is always a normal click, even if the mouse moved.",
                         slider_control(60, 400, profile["gesture"]["hold_ms"], "{} ms",
                                        lambda v: self._set_gesture("hold_ms", v)))
        precision = SettingsPanel()
        precision.add_row("Precision mode", "Pointer speed while a button with the Precision mode action is held.",
                          slider_control(10, 90, round(profile["precision"] * 100), "{} %", self._set_precision))
        kde = QPushButton("Open…")
        kde.setObjectName("outline")
        kde.setCursor(Qt.CursorShape.PointingHandCursor)
        kde.clicked.connect(lambda: subprocess.Popen(["systemsettings", "kcm_mouse"]))
        system = SettingsPanel()
        system.add_row("Speed, acceleration and scrolling",
                       "Set per mouse in KDE System Settings; Mousekit doesn't change them.", kde)
        panels = [gestures, precision, system]
        if channel is not None:
            panels.insert(0, DpiPanel(app, channel))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(centered_scroll(*panels))

    def _set_gesture(self, key, value):
        self.profile["gesture"][key] = value
        self.changed.emit()

    def _set_precision(self, value):
        self.profile["precision"] = round(value / 100, 2)
        self.changed.emit()


class DeviceTab(QWidget):
    changed = pyqtSignal()
    renamed = pyqtSignal()
    dpi_buttons = pyqtSignal(bool)  # the page writes it to the mouse

    def __init__(self, info, profile, app, dpi=None, hw=None):
        super().__init__()
        self.profile = profile
        self.info = info
        self.app = app
        self.dpi = dpi
        main = SettingsPanel()
        self.name_edit = QLineEdit(profile.get("label", ""))
        self.name_edit.setPlaceholderText(models.display_name(info.key, info.name))
        self.name_edit.setFixedWidth(260)
        self.name_edit.editingFinished.connect(self._renamed)
        main.add_row("Name", "What Mousekit calls this mouse.", self.name_edit)
        self.switch = Switch(app.theme)
        self.switch.setChecked(bool(profile.get("enabled")))
        self.switch.setEnabled(info.accessible)
        self.switch.toggled.connect(self._toggled)
        main.add_row("Manage this mouse",
                     "Mousekit takes over the mouse and applies these settings. Turn it off and the mouse works as it is.",
                     self.switch)
        panels = [main]
        if dpi is not None and dpi.verified and hw:
            buttons = SettingsPanel()
            self.dpi_switch = Switch(app.theme)
            self.dpi_switch.setChecked(bool(hw.get("dpi_keys")))
            self.dpi_switch.toggled.connect(self.dpi_buttons.emit)
            self.replug_note = QLabel(f'<span style="color:{app.theme.orange}">●</span>&nbsp;'
                                      "Replug the mouse: the new button settings take effect after that.")
            self.replug_note.setWordWrap(True)
            self.replug_note.hide()
            buttons.add_row("DPI buttons are set in Mousekit",
                            "Saved to the mouse: the DPI buttons stop changing DPI and can be given any action "
                            "on the Buttons tab (desktop left and right by default). DPI is then picked "
                            "on the Pointer tab. The mouse applies this after a replug. "
                            "Turn it off to go back.",
                            self.dpi_switch, below=self.replug_note)
            panels.append(buttons)
        if dpi is not None and dpi.verified:
            backup = SettingsPanel()
            save = QPushButton("Back up…")
            restore = QPushButton("Restore…")
            for button, slot in ((save, self._backup), (restore, self._restore)):
                button.setObjectName("outline")
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.clicked.connect(slot)
            backup.add_row("Back up the mouse",
                           "Saves the settings stored in the mouse (lighting, DPI, buttons) to a file. "
                           "Back up, then experiment.", save)
            backup.add_row("Restore from a backup",
                           "Puts the mouse back as it was in a backup. Mousekit also keeps one from before "
                           f"its first change to this mouse, in {str(backups.BACKUP_DIR).replace(str(Path.home()), '~', 1)}.", restore)
            panels.append(backup)
        if not info.accessible:
            access = SettingsPanel()
            cmd = QLineEdit(UDEV_HINT)
            cmd.setReadOnly(True)
            cmd.setCursorPosition(0)
            access.add_row("No access to the mouse",
                           "To let Mousekit manage any mouse, run this once in a terminal:", below=cmd)
            panels.append(access)
        about = SettingsPanel()
        for title, value in (("System name", info.name), ("USB ID", info.key), ("Device", info.node)):
            label = dim_label(value, 0.95)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            about.add_row(title, "", label)
        if dpi:
            stage = dim_label(dpi.label(), 0.95)
            dpi.stage_changed.connect(lambda _: stage.setText(dpi.label()))
            about.add_row("Current DPI stage", "Read from the mouse. Picked on the Pointer tab.", stage)
        panels.append(about)
        model = models.identify(info.key)
        if not (model and model.get("verified")):
            support = SettingsPanel()
            request = QPushButton("Request support…")
            request.setObjectName("outline")
            request.setCursor(Qt.CursorShape.PointingHandCursor)
            request.clicked.connect(lambda: SupportDialog(app, info).exec())
            support.add_row("Lighting, DPI and buttons stored in the mouse",
                            "Not supported for this mouse yet. Mousekit can learn it: collect the details "
                            "(nothing is sent to the mouse) and file a request on GitHub.", request)
            panels.append(support)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(centered_scroll(*panels))

    def _backup(self):
        default = str(Path.home() / backups.default_name(self.info.key))
        path, _ = QFileDialog.getSaveFileName(self, "Back up the mouse", default, "Mousekit backups (*.json)")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            backups.save(path, backups.make(self.info.key, self.dpi._call(vendor.read_settings)))
        except OSError as err:
            self.app.footer.show_event(f"Couldn't back up the mouse: {err}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.app.footer.show_event(f"Backed up to {path}")

    def _restore(self):
        start = backups.BACKUP_DIR if backups.BACKUP_DIR.exists() else Path.home()
        path, _ = QFileDialog.getOpenFileName(self, "Restore the mouse", str(start), "Mousekit backups (*.json)")
        if not path:
            return
        try:
            backup = backups.load(path, self.info.key, vendor.SETTINGS_SIZE)
        except ValueError as err:
            QMessageBox.warning(self, "Restore the mouse", f"Can't restore it: {err}.")
            return
        when = backup.get("created", "").replace("T", " ")[:16]
        answer = QMessageBox.question(
            self, "Restore the mouse", f"Put the mouse back as it was on {when}?\n\n"
            "The lighting, DPI and buttons stored in the mouse are replaced with the backup's.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            changed = self.dpi._call(vendor.restore_settings, backup["data"])
        except (OSError, ValueError) as err:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Restore the mouse", f"Couldn't restore it: {err}.")
            return
        QApplication.restoreOverrideCursor()
        if not changed:
            self.app.footer.show_event("The mouse already matches this backup")
            return
        app = self.app
        page = app.reload_device(self.info.key, show_device_tab=True)  # this tab is replaced
        note = getattr(page.device_tab, "replug_note", None) if page else None
        if note is not None:
            note.show()
        app.footer.show_event("Restored. Replug the mouse for the button settings to take effect")

    def _renamed(self):
        self.profile["label"] = self.name_edit.text().strip()
        self.renamed.emit()
        self.changed.emit()

    def _toggled(self, on):
        self.profile["enabled"] = on
        self.changed.emit()


class LightingTab(QWidget):
    """Lighting: Mousekit's smooth streamed effects, or the mouse's own modes sent live."""

    changed = pyqtSignal()

    COLOURS = [(255, 0, 0), (255, 136, 0), (255, 255, 0), (0, 255, 0), (0, 255, 255),
               (0, 0, 255), (136, 0, 255), (255, 0, 255), (255, 255, 255)]
    # Which controls each mode takes, as the vendor app enables them (skin_color.ini control ids 40-50).
    DIRECTIONS = ["Clockwise", "Counter-clockwise", "Both ways", "Overlap"]
    DIRECTION_MODES = [{3, 4, 5, 7, 10}, {3, 4, 5, 7, 10}, {3, 4, 5}, {3}]
    SYMMETRY_MODES = {3, 4, 5, 7}
    BRIGHTNESS_MODES = {2, 3, 4, 5}
    NO_SPEED_MODES = {2, 9, 12, 13}

    def __init__(self, profile, app, channel, lighting, art):
        super().__init__()
        self.app = app
        self.profile = profile
        self.channel = channel
        self.lighting = lighting
        stored = profile.get("lighting") or {}
        mode = stored.get("mode", lighting.mode if lighting.mode is not None else 2)
        self.light = {
            "mode": mode if mode < len(LED_MODES) else 2,
            "speed": min(5, stored.get("speed", lighting.speed if lighting.speed is not None else 3)),
            "bright": stored.get("bright", 7),
            "direction": stored.get("direction", 0),
            "symmetric": stored.get("symmetric", False),
            "color": list(stored.get("color") or (255, 255, 255)),
            "restore": stored.get("restore", True),
            "engine": stored.get("engine", "firmware"),   # "mousekit": streamed by the daemon
            "effect": stored.get("effect", "breathe"),
            "glow": stored.get("glow", 3),                # click flash: background level 0-6
            "on_scroll": stored.get("on_scroll", True),   # click flash: also on wheel turns
        }
        if self.light["mode"] not in self.DIRECTION_MODES[self.light["direction"] & 3]:
            self.light["direction"] = 0
        if self.light["effect"] not in effects.EFFECTS:
            self.light["effect"] = "breathe"
        self.apply_timer = QTimer(self, singleShot=True, interval=120, timeout=self._apply)

        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(36, 18, 12, 18)
        column.setSpacing(8)

        def chips(names, group):
            grid = QGridLayout()
            grid.setSpacing(6)
            for position, (index, name) in enumerate(names):
                chip = QPushButton(name)
                chip.setObjectName("chip")
                chip.setCheckable(True)
                chip.setCursor(Qt.CursorShape.PointingHandCursor)
                group.addButton(chip, index)
                grid.addWidget(chip, position // 2, position % 2)
            return grid

        column.addWidget(dim_label("Smooth Mousekit effects"))
        self.effect_ids = list(effects.EFFECTS)
        self.effect_group = QButtonGroup(self)
        column.addLayout(chips(enumerate(effects.EFFECTS.values()), self.effect_group))
        self.effect_group.idClicked.connect(lambda index: self._choose("mousekit", "effect", self.effect_ids[index]))
        column.addSpacing(10)
        column.addWidget(dim_label("The mouse's own effects"))
        self.mode_group = QButtonGroup(self)
        # 12 (button response) needs per-button settings we haven't decoded; "Click flash" replaces it.
        column.addLayout(chips(((i, n) for i, n in enumerate(LED_MODES) if i != 12), self.mode_group))
        self.mode_group.idClicked.connect(lambda index: self._choose("firmware", "mode", index))

        self.colour_box = QWidget()
        colour_layout = QVBoxLayout(self.colour_box)
        colour_layout.setContentsMargins(0, 10, 0, 0)
        colour_layout.addWidget(dim_label("Colour"))
        swatches = QHBoxLayout()
        swatches.setSpacing(8)
        self.swatch_group = QButtonGroup(self)
        self.swatches = {}
        for rgb in self.COLOURS:
            swatch = QPushButton()
            swatch.setCheckable(True)
            swatch.setFixedSize(30, 30)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.setStyleSheet(
                f"QPushButton {{ background: rgb{rgb}; border: 2px solid {app.theme.border}; border-radius: 15px; }}"
                f"QPushButton:checked {{ border: 3px solid {app.theme.text}; }}")
            swatch.clicked.connect(lambda _, c=rgb: self._set("color", list(c)))
            self.swatch_group.addButton(swatch)
            self.swatches[rgb] = swatch
            swatches.addWidget(swatch)
        more = QPushButton("Other…")
        more.setObjectName("outline")
        more.setCursor(Qt.CursorShape.PointingHandCursor)
        more.clicked.connect(self._pick_colour)
        swatches.addWidget(more)
        swatches.addStretch()
        colour_layout.addLayout(swatches)
        column.addWidget(self.colour_box)

        panel = SettingsPanel()
        self.brightness = slider_control(1, 7, self.light["bright"], "{} / 7",
                                         lambda v: self._set("bright", v), 210)
        panel.add_row("Brightness", "Not every mode has it.", self.brightness)
        self.speed = slider_control(1, 6, self.light["speed"] + 1, "{} / 6",
                                    lambda v: self._set("speed", v - 1), 210)
        panel.add_row("Speed", "For animated modes.", self.speed)
        self.glow = slider_control(0, 6, self.light["glow"], "{}0 %", lambda v: self._set("glow", v), 210)
        panel.add_row("Background glow", "For Click flash: the same colour between clicks.", self.glow)
        self.on_scroll = Switch(app.theme)
        self.on_scroll.toggled.connect(lambda on: self._set("on_scroll", on))
        panel.add_row("Flash on scroll", "For Click flash: every notch of the wheel.", self.on_scroll)
        self.direction = ChoiceGrid(self.DIRECTIONS)
        self.direction.changed.connect(lambda index: self._set("direction", index))
        panel.add_row("Direction", "For moving effects.", None, below=self.direction)
        self.symmetric = Switch(app.theme)
        self.symmetric.toggled.connect(lambda on: self._set("symmetric", on))
        panel.add_row("Symmetric", "", self.symmetric)
        self.restore = Switch(app.theme)
        self.restore.toggled.connect(self._set_restore)
        panel.add_row("Apply on connect",
                      "The Mousekit service puts this lighting back when the mouse connects.", self.restore)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("outline")
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.clicked.connect(self._save_to_mouse)
        panel.add_row("Save to mouse",
                      "Keeps the lighting without Mousekit, e.g. in Windows. For the mouse's own "
                      "modes except Twinkle, Star trail, Ripple and Colour dance.",
                      self.save_button)
        column.addSpacing(10)
        column.addWidget(panel)
        note = dim_label("Mousekit effects are smooth and change the whole mouse at once, but only run while "
                         "the Mousekit service does (while you're logged in). The mouse's own effects always "
                         "work, though in steps. Static colour and Mousekit effects use the DPI stage colours, "
                         "so the mouse flashes that colour when the DPI stage changes. To keep lighting without "
                         "Mousekit, save one of the mouse's own modes to the mouse.", 0.88)
        note.setWordWrap(True)
        column.addWidget(note)
        column.addStretch()

        scroll = QScrollArea()
        scroll.setObjectName("page")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedWidth(500)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        self.canvas = MouseCanvas(app.theme, scroll, [], art, lighting)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self._sync()

    def _sync(self):
        """Show self.light in the controls without sending anything."""
        light = self.light
        mode = light["mode"]
        streamed = light["engine"] == "mousekit"
        for group, checked in ((self.mode_group, None if streamed else self.mode_group.button(mode)),
                               (self.effect_group, self.effect_group.button(self.effect_ids.index(light["effect"]))
                                if streamed else None)):
            group.setExclusive(False)
            for button in group.buttons():
                button.setChecked(button is checked)
            group.setExclusive(True)
        for widget in (self.mode_group, self.swatch_group):
            widget.blockSignals(True)
        swatch = self.swatches.get(tuple(light["color"]))
        self.swatch_group.setExclusive(False)
        for button in self.swatches.values():
            button.setChecked(button is swatch)
        self.swatch_group.setExclusive(True)
        for widget in (self.mode_group, self.swatch_group):
            widget.blockSignals(False)
        for control, value in ((self.brightness, light["bright"]), (self.speed, light["speed"] + 1),
                               (self.glow, light["glow"])):
            slider = control.findChild(QSlider)
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
            control.findChild(QLabel).setText(f"{value}0 %" if control is self.glow else f"{value} / {slider.maximum()}")
        self.direction.group.button(light["direction"]).setChecked(True)
        for switch, on in ((self.symmetric, light["symmetric"]), (self.restore, light["restore"]),
                           (self.on_scroll, light["on_scroll"])):
            switch.blockSignals(True)
            switch.setChecked(on)
            switch.blockSignals(False)
            switch.update()
        self.save_button.setEnabled(not streamed and mode in vendor.SAVABLE_MODES
                                    and self.channel is not None and self.channel.verified)
        if streamed:
            self.colour_box.setVisible(light["effect"] in effects.NEEDS_COLOUR)
            self.brightness.setEnabled(True)
            self.speed.setEnabled(light["effect"] != "click")
            self.glow.setEnabled(light["effect"] == "click")
            self.on_scroll.setEnabled(light["effect"] == "click")
            for button in self.direction.group.buttons():
                button.setEnabled(False)
            self.symmetric.setEnabled(False)
            return
        self.colour_box.setVisible(mode in SINGLE_COLOUR_MODES)
        self.glow.setEnabled(False)
        self.on_scroll.setEnabled(False)
        self.brightness.setEnabled(mode in self.BRIGHTNESS_MODES)
        self.speed.setEnabled(mode not in self.NO_SPEED_MODES)
        for index, modes in enumerate(self.DIRECTION_MODES):
            self.direction.group.button(index).setEnabled(mode in modes)
        self.symmetric.setEnabled(mode in self.SYMMETRY_MODES)

    def _set(self, key, value):
        self.light[key] = value
        if key == "mode" and value not in self.DIRECTION_MODES[self.light["direction"]]:
            self.light["direction"] = 0
        self._sync()
        self.apply_timer.start()

    def _choose(self, engine, key, value):
        self.light["engine"] = engine
        self._set(key, value)

    def _save_to_mouse(self):
        self.apply_timer.stop()
        self._apply()  # show exactly what gets stored
        error = self.channel.save_lighting(self.light)
        if error:
            self.app.footer.show_event(f"Couldn't save to the mouse: {error}")
        else:
            self.app.footer.show_event(f"Saved to the mouse: {LED_MODES[self.light['mode']]}")

    def _set_restore(self, on):
        self.light["restore"] = on
        self._save()

    def _pick_colour(self):
        colour = QColorDialog.getColor(QColor(*self.light["color"]), self.window(), "Lighting colour")
        if colour.isValid():
            self._set("color", [colour.red(), colour.green(), colour.blue()])

    def _apply(self):
        if self.light["engine"] == "mousekit":
            # The daemon streams it; it picks the change up from the saved config.
            self.lighting.effect_light = dict(self.light)
            self._save()
            if not self.app.service_active:
                self.app.footer.show_event("Mousekit effects need the service: start it at the bottom left")
            return
        self.lighting.effect_light = None
        sent = self.channel.apply_lighting(self.light) if self.channel else False
        self.lighting.mode = self.light["mode"]
        self.lighting.speed = self.light["speed"]
        self.lighting.colour = tuple(self.light["color"])
        self._save()
        if not sent:
            self.app.footer.show_event("Couldn't send the lighting to the mouse")

    def _save(self):
        self.profile["lighting"] = dict(self.light)
        self.changed.emit()

    def external_change(self, mode, speed):
        """The mouse changed its lighting itself (its lighting button)."""
        if mode >= len(LED_MODES) or self.light["engine"] == "mousekit":
            return
        self.light["mode"], self.light["speed"] = mode, min(5, speed)
        self._sync()
        self.canvas.lighting_changed()


class DevicePage(QWidget):
    back = pyqtSignal()
    changed = pyqtSignal()

    def __init__(self, info, profile, app):
        super().__init__()
        self.setObjectName("page")
        self.info = info
        self.profile = profile
        self.app = app

        back = QPushButton("‹  Mice")
        back.setObjectName("flat")
        back.setFont(font(1.1))
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self.back.emit)
        self.title = QLabel()
        self.title.setFont(font(2.0, QFont.Weight.DemiBold))
        self.pill = Pill()

        self.lighting = Lighting()
        self.dpi = VendorChannel.open(info.key, self)
        if self.dpi:
            self.dpi.stage_changed.connect(lambda _: app.footer.show_event(f"DPI: {self.dpi.label().lower()}"))
            self.dpi.stage_changed.connect(self._dpi_stage)
            self.dpi.lighting_changed.connect(self._lighting_changed)
            self.dpi.key_pressed.connect(self.flash)
            self.dpi.pressed.connect(lambda down: down and self.flash())
            if self.dpi.led:
                self.lighting.mode, self.lighting.speed = self.dpi.led
            self.lighting.dpi_stage = self.dpi.stage or 0
            # The mouse can't report colours; use the last one Mousekit set.
            stored = profile.get("lighting") or {}
            colour = stored.get("color")
            self.lighting.colour = tuple(colour) if colour else None
            if stored.get("engine") == "mousekit":
                self.lighting.effect_light = dict(stored)
        self.art = art_for(info.key)
        self.hw = self._read_hw()
        self.buttons_tab = ButtonsTab(info, profile, app, self.dpi, self.art, self.lighting, self.hw)
        self.lighting_tab = LightingTab(profile, app, self.dpi, self.lighting, self.art) if self.dpi else None
        pointer = PointerTab(profile, app, self.dpi)
        device = DeviceTab(info, profile, app, self.dpi, self.hw)
        device.dpi_buttons.connect(self._set_dpi_buttons)
        self.device_tab = device
        if self.dpi:
            self.dpi.reconnected.connect(self._replugged)
        tabs = [("Buttons", self.buttons_tab), ("Lighting", self.lighting_tab),
                ("Pointer", pointer), ("Device", device)]
        tabs = [(label, tab) for label, tab in tabs if tab is not None]
        self.tabs = Segmented([label for label, _ in tabs])

        header = QGridLayout()
        header.setContentsMargins(24, 18, 24, 18)
        left = QHBoxLayout()
        left.setSpacing(18)
        left.addWidget(back)
        left.addWidget(self.title)
        left.addStretch()
        right = QHBoxLayout()
        right.addStretch()
        right.addWidget(self.pill)
        header.addLayout(left, 0, 0)
        header.addWidget(self.tabs, 0, 1, Qt.AlignmentFlag.AlignCenter)
        header.addLayout(right, 0, 2)
        header.setColumnStretch(0, 1)
        header.setColumnStretch(2, 1)

        self.stack = QStackedWidget()
        for _, tab in tabs:
            self.stack.addWidget(tab)
            tab.changed.connect(self.changed.emit)
        if self.lighting_tab:
            self.lighting_tab.changed.connect(self._lighting_set)
        device.renamed.connect(self.update_title)
        self.tabs.changed.connect(self.stack.setCurrentIndex)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(hline())
        layout.addWidget(self.stack, 1)
        self.update_title()

    def update_title(self):
        self.title.setText(self.profile.get("label") or models.display_name(self.info.key, self.info.name))

    def _replugged(self):
        note = getattr(self.device_tab, "replug_note", None)
        if note is not None and note.isVisible():
            note.hide()
            self.app.footer.show_event("Mouse reconnected: the DPI buttons use the new assignment")

    def _read_hw(self):
        """Which buttons the mouse itself sends as keys (from its stored button table)."""
        if not self.dpi or not self.dpi.verified:
            return {}
        try:
            buttons = self.dpi._call(vendor.read_buttons)
        except OSError:
            return {}
        return {"dpi_keys": vendor.dpi_buttons_remapped(buttons),
                "fire_key": buttons["fire"][0] == vendor.MEDIA_CODE,
                "forward_key": buttons["forward"][0] == vendor.MEDIA_CODE}

    def _set_dpi_buttons(self, as_keys):
        try:
            self.dpi._call(vendor.set_dpi_buttons, as_keys)
        except OSError as err:
            self.app.footer.show_event(f"Couldn't change the DPI buttons: {err}")
            switch = self.device_tab.dpi_switch
            switch.blockSignals(True)
            switch.setChecked(not as_keys)
            switch.blockSignals(False)
            return False
        buttons = self.profile["buttons"]
        if as_keys and "DPI_UP" not in buttons and "DPI_DOWN" not in buttons:
            buttons["DPI_UP"] = {"click": {"type": "shortcut", "component": "kwin", "name": "Switch One Desktop to the Right"}}
            buttons["DPI_DOWN"] = {"click": {"type": "shortcut", "component": "kwin", "name": "Switch One Desktop to the Left"}}
        self.hw = self._read_hw()
        index = self.stack.indexOf(self.buttons_tab)
        old = self.buttons_tab
        self.buttons_tab = ButtonsTab(self.info, self.profile, self.app, self.dpi, self.art, self.lighting, self.hw)
        self.buttons_tab.changed.connect(self.changed.emit)
        self.stack.insertWidget(index, self.buttons_tab)
        self.stack.removeWidget(old)
        old.deleteLater()
        self.changed.emit()
        self.app.footer.show_event("Saved to the mouse. Replug it for the new DPI buttons to take effect")
        self.device_tab.replug_note.show()
        return True

    def _dpi_stage(self, stage):
        self.lighting.dpi_stage = stage
        self.buttons_tab.canvas.update()

    def _lighting_changed(self, mode, speed):
        if self.lighting.effect_light or (mode, speed) == (self.lighting.mode, self.lighting.speed):
            return
        self.lighting.mode, self.lighting.speed = mode, speed
        self.buttons_tab.show_lighting()
        if self.lighting_tab:
            self.lighting_tab.external_change(mode, speed)
        self.app.footer.show_event(f"Lighting: {self.lighting.label()}")

    def _lighting_set(self):
        self.buttons_tab.show_lighting()
        self.lighting_tab.canvas.lighting_changed()
        self.app.footer.show_event(f"Lighting: {self.lighting.label()}")

    def flash(self):
        """A click, for the button-response lighting preview."""
        self.lighting.flash_until = MouseCanvas.now() + 0.35
        self.lighting.clicks.append(MouseCanvas.now())
        self.buttons_tab.canvas.update()
        if self.lighting_tab:
            self.lighting_tab.canvas.update()

    def set_state(self, text, color):
        self.pill.set_state(text, color)


class DeviceTile(QFrame):
    clicked = pyqtSignal()

    def __init__(self, info, app):
        super().__init__()
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(250, 270)
        self.info = info
        self.name = QLabel()
        self.name.setFont(font(1.2, QFont.Weight.DemiBold))
        self.name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pill = Pill()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(MiniMouse(app.theme, info.buttons, art_for(info.key)))
        layout.addWidget(self.name)
        key = dim_label(info.key, 0.9)
        key.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(key)
        layout.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignCenter)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class HomePage(QWidget):
    open_device = pyqtSignal(str)

    def __init__(self, app):
        super().__init__()
        self.setObjectName("page")
        self.app = app
        title = QLabel("Mice")
        title.setFont(font(2.0, QFont.Weight.DemiBold))
        header = QHBoxLayout()
        header.setContentsMargins(36, 18, 24, 18)
        header.addWidget(title)
        header.addStretch()
        self.grid = QGridLayout()
        self.grid.setSpacing(18)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.empty = dim_label("No mice found. Connect one and it shows up here.", 1.05)
        body = QVBoxLayout()
        body.setContentsMargins(36, 28, 36, 28)
        body.addLayout(self.grid)
        body.addWidget(self.empty)
        body.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(hline())
        layout.addLayout(body, 1)
        self.tiles = {}

    def set_devices(self, mice):
        while self.grid.count():
            self.grid.takeAt(0).widget().deleteLater()
        self.tiles = {}
        for index, info in enumerate(mice):
            tile = DeviceTile(info, self.app)
            tile.clicked.connect(lambda k=info.key: self.open_device.emit(k))
            self.grid.addWidget(tile, index // 3, index % 3)
            self.tiles[info.key] = tile
        self.empty.setVisible(not mice)


# Main window


class Footer(QWidget):
    def __init__(self, app):
        super().__init__()
        self.status = QLabel()
        self.service_button = QPushButton()
        self.service_button.setObjectName("flat")
        self.service_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.service_button.clicked.connect(app.service_action)
        self.event = dim_label("", 0.95)
        self.event.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version = QPushButton(f"{APP_NAME} {__version__}")
        self.version.setObjectName("flat")
        self.version.setCursor(Qt.CursorShape.PointingHandCursor)
        self.version.setToolTip("About, updates")
        self.version.clicked.connect(app.show_about)
        self.app = app
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 8, 24, 10)
        layout.addWidget(self.status)
        layout.addWidget(self.service_button)
        layout.addWidget(self.event, 1)
        layout.addWidget(self.version)
        self.event_timer = QTimer(self, singleShot=True, interval=4000, timeout=lambda: self.event.setText(""))

    def show_event(self, text):
        self.event.setText(text)
        self.event_timer.start()

    def show_update(self, version):
        if version:
            self.version.setText(f"●  Update {version} available")
            self.version.setStyleSheet(f"color: {self.app.theme.accent}")
        else:
            self.version.setText(f"{APP_NAME} {__version__}")
            self.version.setStyleSheet("")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon.fromTheme("input-mouse"))
        self.resize(1180, 800)
        self.setMinimumSize(1000, 700)
        self.theme = Theme()
        self.config = config.load()
        self.catalog = load_kde_catalog()
        self.catalog_names = {(c, n): label for c, _, items in self.catalog for n, label in items}
        self.mice = []
        self.pages = {}
        self.managed = set()
        self.service_active = False
        self.save_timer = QTimer(self, singleShot=True, interval=300, timeout=self._save)

        root = QWidget()
        root.setObjectName("root")
        root.setStyleSheet(self.theme.stylesheet())
        self.stack = QStackedWidget()
        self.home = HomePage(self)
        self.home.open_device.connect(self.open_device)
        self.stack.addWidget(self.home)
        self.footer = Footer(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.stack, 1)
        layout.addWidget(hline())
        layout.addWidget(self.footer)
        self.setCentralWidget(root)

        self.socket = QLocalSocket(self)
        self.socket.readyRead.connect(self._read_socket)
        self.socket.disconnected.connect(self._socket_lost)
        self.socket.errorOccurred.connect(lambda *_: self._socket_lost())
        self.reconnect_timer = QTimer(self, interval=2000, timeout=self._connect)

        self._refresh_devices()
        self._refresh_service()
        QTimer(self, interval=3000, timeout=self._refresh_devices).start()
        QTimer(self, interval=3000, timeout=self._refresh_service).start()
        self._connect()
        self.about = None
        self.updates = UpdateChecker(self)
        self.updates.done.connect(self._updates_checked)
        QTimer.singleShot(5000, self._auto_check)
        QTimer(self, interval=updates.CHECK_INTERVAL * 1000, timeout=self._auto_check).start()
        # Like OpenLogi: open straight into the mouse when there's just one.
        if len(self.mice) == 1:
            self.open_device(self.mice[0].key)

    # Devices

    def _profile(self, info):
        devices_cfg = self.config["devices"]
        if info.key not in devices_cfg:
            devices_cfg[info.key] = config.new_profile(info.name)
        return devices_cfg[info.key]

    def _refresh_devices(self):
        mice = []
        seen = set()
        for info in devices.scan():
            if info.key not in seen:  # one entry per model, even with several event nodes
                seen.add(info.key)
                mice.append(info)
        if [(m.key, m.node, m.accessible) for m in mice] != [(m.key, m.node, m.accessible) for m in self.mice]:
            self.mice = mice
            self.home.set_devices(mice)
        self._update_states()

    def _state(self, key):
        info = next((m for m in self.mice if m.key == key), None)
        profile = self.config["devices"].get(key, {})
        if info is None:
            return "Disconnected", self.theme.dim
        if not info.accessible:
            return "No access", self.theme.orange
        if key in self.managed:
            return "Managed", self.theme.green
        if profile.get("enabled"):
            return "Waiting for service", self.theme.orange
        return "Not managed", self.theme.dim

    def _update_states(self):
        for key, tile in self.home.tiles.items():
            profile = self.config["devices"].get(key, {})
            tile.name.setText(profile.get("label") or models.display_name(tile.info.key, tile.info.name))
            tile.pill.set_state(*self._state(key))
        for key, page in self.pages.items():
            page.set_state(*self._state(key))

    def show_about(self):
        if self.about is None:
            self.about = AboutDialog(self)
        else:
            self.about._check()
        self.about.show()
        self.about.raise_()
        self.about.activateWindow()

    def _auto_check(self):
        if self.config.get("check_updates", True) and updates.installed_from_package():
            self.updates.check()

    def _updates_checked(self, newer, _recent, error):
        if not error and updates.installed_from_package():
            self.footer.show_update(updates.release_version(newer[0]) if newer else None)

    def schedule_save(self):
        self.save_timer.start()

    def open_device(self, key):
        info = next((m for m in self.mice if m.key == key), None)
        if info is None:
            return
        page = self.pages.get(key)
        if page is None:
            page = DevicePage(info, self._profile(info), self)
            page.back.connect(lambda: self.stack.setCurrentWidget(self.home))
            page.changed.connect(self._changed)
            self.pages[key] = page
            self.stack.addWidget(page)
        page.set_state(*self._state(key))
        self.stack.setCurrentWidget(page)

    def reload_device(self, key, show_device_tab=False):
        """Rebuild a mouse's page from what's in the mouse now."""
        old = self.pages.pop(key, None)
        if old is not None:
            if old.dpi is not None:
                old.dpi._close()
            self.stack.removeWidget(old)
            old.deleteLater()
        self.open_device(key)
        page = self.pages.get(key)
        if page is not None and show_device_tab:
            index = page.stack.indexOf(page.device_tab)
            page.tabs.group.button(index).setChecked(True)
            page.stack.setCurrentIndex(index)
        return page

    def _changed(self):
        self._update_states()
        self.save_timer.start()

    def _save(self):
        # Write only profiles the user actually touched; untouched ones stay
        # in memory because open pages still edit them.
        data = dict(self.config)
        data["devices"] = {
            key: p for key, p in self.config["devices"].items()
            if p.get("enabled") or p.get("buttons") or p.get("label")
            or p.get("gesture") != config.DEFAULT_GESTURE or p.get("precision") != config.DEFAULT_PRECISION
        }
        config.save(data)
        self.footer.show_event("Saved: the mouse already uses the new settings")

    # Service

    def _refresh_service(self):
        self.service_active = systemctl("is-active", SERVICE).stdout.strip() == "active"
        color = self.theme.green if self.service_active else self.theme.orange
        text = "Service running" if self.service_active else "Service stopped"
        self.footer.status.setText(f'<span style="color:{color}">●</span>&nbsp;{text}')
        self.footer.service_button.setText("Restart" if self.service_active else "Start")

    def service_action(self):
        if self.service_active:
            systemctl("restart", SERVICE)
        else:
            systemctl("enable", "--now", SERVICE)
        QTimer.singleShot(800, self._refresh_service)

    # Live events

    def _connect(self):
        if self.socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            self.socket.connectToServer(str(config.SOCKET_PATH))
        if self.socket.waitForConnected(200):
            self.reconnect_timer.stop()
        else:
            self.reconnect_timer.start()

    def _socket_lost(self):
        self.managed = set()
        self._update_states()
        if not self.reconnect_timer.isActive():
            self.reconnect_timer.start()

    def _read_socket(self):
        while self.socket.canReadLine():
            try:
                event = json.loads(bytes(self.socket.readLine()).decode())
            except ValueError:
                continue
            self._event(event)

    def _event(self, event):
        kind = event.get("type")
        if kind == "status":
            self.managed = set(event.get("managed", []))
            self._update_states()
            return
        key = event.get("device")
        page = self.pages.get(key)
        if kind == "button" and page:
            page.buttons_tab.set_pressed(event["button"], event["pressed"])
            if event["pressed"]:
                page.flash()
        if kind == "scroll" and page:
            effect = page.lighting.effect_light or {}
            if effect.get("on_scroll", True):
                page.flash()
            return
        profile = self.config["devices"].get(key, {})
        cfg = profile.get("buttons", {}).get(event.get("button"), {})
        button = BUTTON_LABELS.get(event.get("button"), event.get("button"))
        if kind == "swipe":
            action = cfg.get("swipe", {}).get(event["direction"])
            self.footer.show_event(f"{button}, gesture {SWIPE_LABELS[event['direction']]}:  "
                                   f"{action_label(action, self.catalog_names)}")
        elif kind == "wheel":
            action = cfg.get("wheel", {}).get(event["direction"])
            self.footer.show_event(f"{button} + {WHEEL_NAMES[event['direction']].lower()}:  "
                                   f"{action_label(action, self.catalog_names)}")


# About, updates and support requests


class UpdateChecker(QObject):
    """Fetches the release list from GitHub; `done(newer, recent, error)` with newest releases first."""

    done = pyqtSignal(list, list, str)

    def __init__(self, parent):
        super().__init__(parent)
        self.net = QNetworkAccessManager(self)
        self.reply = None
        self.newer = []

    def check(self):
        if self.reply is not None:
            return
        request = QNetworkRequest(QUrl(updates.RELEASES_API))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", f"mousekit/{__version__}".encode())
        request.setTransferTimeout(20000)
        self.reply = self.net.get(request)
        self.reply.finished.connect(self._finished)

    def _finished(self):
        reply, self.reply = self.reply, None
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            self.done.emit([], [], "no releases are published yet" if status == 404 else reply.errorString())
            return
        try:
            releases = json.loads(bytes(reply.readAll()))
        except ValueError:
            self.done.emit([], [], "GitHub sent something unexpected")
            return
        self.newer = updates.newer_releases(releases)
        self.done.emit(self.newer, updates.recent_releases(releases), "")


class AboutDialog(QDialog):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.newer = []
        self.download = None
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumSize(600, 560)

        icon = QLabel()
        icon.setPixmap(QIcon.fromTheme("input-mouse").pixmap(64, 64))
        title = QLabel(f"<span style='font-size:18pt; font-weight:600'>{APP_NAME}</span><br>Version {__version__}")
        header = QHBoxLayout()
        header.addWidget(icon)
        header.addWidget(title, 1)
        about = QLabel(
            "Mouse settings for KDE Plasma: lighting, DPI and buttons of GamePro mice, "
            "plus gestures and button remapping for any mouse.<br><br>"
            f"Author: <a href='{updates.AUTHOR_URL}'>{__author__}</a>  ·  "
            f"<a href='{updates.HOMEPAGE}'>Source code</a>  ·  MIT license<br>"
            "Not affiliated with GamePro.<br>"
            f"Your mouse isn't supported yet? <a href='{updates.new_mouse_issue()}'>Request support</a> "
            "(the Device tab can fill it in for you).")
        about.setWordWrap(True)
        about.setOpenExternalLinks(True)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.check_button = QPushButton("Check for updates")
        self.check_button.clicked.connect(self._check)
        self.auto = QCheckBox("Check for updates every hour")
        self.auto.setChecked(app.config.get("check_updates", True))
        self.auto.toggled.connect(self._auto_toggled)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.install_button = QPushButton("Install update")
        self.install_button.clicked.connect(self._install)
        self.install_button.hide()
        releases = QPushButton("All releases")
        releases.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"{updates.HOMEPAGE}/releases")))
        buttons = QHBoxLayout()
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.install_button)
        buttons.addStretch(1)
        buttons.addWidget(releases)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(about)
        layout.addSpacing(8)
        layout.addWidget(hline())
        layout.addWidget(self.status)
        layout.addLayout(buttons)
        layout.addWidget(self.auto)
        layout.addWidget(self.notes, 1)
        layout.addWidget(close)
        app.updates.done.connect(self._checked)
        self._check()

    def _auto_toggled(self, on):
        self.app.config["check_updates"] = on
        self.app.schedule_save()

    def _check(self):
        self.status.setText("Checking for updates…")
        self.check_button.setEnabled(False)
        self.app.updates.check()

    def _checked(self, newer, recent, error):
        self.check_button.setEnabled(True)
        self.newer = newer
        self.install_button.hide()
        if error:
            self.status.setText(f"Couldn't check for updates: {error}")
            return
        if not newer:
            self.status.setText("You have the latest version.")
            self.notes.setMarkdown("## Recent changes\n\n" + updates.changelog(recent) if recent else "")
            return
        version = updates.release_version(newer[0])
        if updates.installed_from_package() and updates.deb_asset(newer[0]):
            self.status.setText(f"<b>Version {version} is available.</b>")
            self.install_button.show()
            self.install_button.setEnabled(True)
        else:
            self.status.setText(f"<b>Version {version} is available.</b> This copy runs from source: "
                                "update it with <code>git pull</code>.")
        self.notes.setMarkdown("## What's new\n\n" + updates.changelog(newer))

    def _install(self):
        name, url, digest = updates.deb_asset(self.newer[0])
        self.install_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.status.setText("Downloading…")
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", f"mousekit/{__version__}".encode())
        self.download = self.app.updates.net.get(request)
        self.download.downloadProgress.connect(
            lambda got, total: total > 0 and self.status.setText(f"Downloading… {got * 100 // total}%"))
        self.download.finished.connect(lambda: self._downloaded(name, digest))

    def _failed(self, text):
        self.status.setText(text)
        self.install_button.setEnabled(True)
        self.check_button.setEnabled(True)

    def _downloaded(self, name, digest):
        reply, self.download = self.download, None
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._failed(f"Download failed: {reply.errorString()}")
            return
        updates.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.package = updates.DOWNLOAD_DIR / name
        self.package.write_bytes(bytes(reply.readAll()))
        if digest and updates.sha256(self.package) != digest:
            self.package.unlink()
            self._failed("The download is damaged (its checksum doesn't match). Try again.")
            return
        self.status.setText("Installing… enter your password when asked.")
        self.process = QProcess(self)
        self.process.finished.connect(self._installed)
        self.process.start("pkexec", ["/usr/bin/apt-get", "install", "-y", str(self.package)])

    def _installed(self, code, _status=None):
        if code in (126, 127):
            self._failed("Installation cancelled.")
            return
        if code:
            self._failed(f"Installation failed. Install it from a terminal: sudo apt install {self.package}")
            return
        self.status.setText("Updated. Restarting Mousekit…")
        systemctl("try-restart", SERVICE)
        QProcess.startDetached("/usr/bin/mousekit", ["--about"])
        QTimer.singleShot(300, QApplication.quit)


class SupportDialog(QDialog):
    """Collects what's needed to support a mouse and files it as a GitHub issue."""

    def __init__(self, app, info):
        super().__init__(app)
        self.app = app
        self.info = info
        self.name = models.display_name(info.key, info.name)
        self.setWindowTitle(f"Request support: {self.name}")
        self.setMinimumSize(720, 620)
        intro = QLabel(
            "Mousekit learns a mouse from a description of its USB interfaces and a recording of what its "
            "buttons send. Nothing is sent to the mouse, and nothing leaves this computer until you file "
            "the issue yourself.<br><br>"
            "1. Press <b>Record buttons</b> and press each button while it records.<br>"
            "2. Press <b>Open issue on GitHub</b>: the issue opens filled in, and the text is also copied. "
            "Add a link to the manufacturer's app if there is one.")
        intro.setWordWrap(True)
        try:
            self.base = dump.collect(info.key)
        except LookupError as err:
            self.base = f"Couldn't read the mouse: {err}"
        self.recording = []
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.record_button = QPushButton(f"Record buttons ({dump.RECORD_SECONDS} s)")
        self.record_button.clicked.connect(self._record)
        save = QPushButton("Save to file…")
        save.clicked.connect(self._save)
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda: (QGuiApplication.clipboard().setText(self.text.toPlainText()),
                                      self.hint.setText("Copied.")))
        issue = QPushButton("Open issue on GitHub")
        issue.setDefault(True)
        issue.clicked.connect(self._issue)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.record_button)
        buttons.addStretch(1)
        for button in (save, copy, issue, close):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.hint)
        layout.addLayout(buttons)
        self.countdown = QTimer(self, interval=1000, timeout=self._tick)
        self._show()

    def _show(self):
        text = self.base
        if self.recording:
            text += "\n\nRecording. " + dump.RECORD_HINT + "\n" + "\n".join(self.recording)
        self.text.setPlainText(text)

    def _record(self):
        launcher = Path(__file__).resolve().parent.parent / "bin" / "mousekit"
        args = [str(launcher), "--dump", self.info.key, "--recording-only", "--record", str(dump.RECORD_SECONDS)]
        program = sys.executable
        if not dump.can_record_raw(self.info.key):  # raw reports of an unknown mouse need root
            program, args = "pkexec", [sys.executable, *args]
        self.recording = []
        self.record_button.setEnabled(False)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._output)
        self.process.finished.connect(self._recorded)
        self.process.start(program, args)
        self.left = dump.RECORD_SECONDS
        self.started = False

    def _output(self):
        for line in bytes(self.process.readAllStandardOutput()).decode(errors="replace").splitlines():
            if line.startswith("Recording ") and not self.started:  # the recorder is ready
                self.started = True
                self.countdown.start()
                self._tick(first=True)
            self.recording.append(line)
        self._show()

    def _tick(self, first=False):
        if not first:
            self.left -= 1
        self.hint.setText(f"<b>Recording: {max(0, self.left)} s left.</b> {dump.RECORD_HINT}")

    def _recorded(self, code, _status=None):
        self.countdown.stop()
        self.record_button.setEnabled(True)
        if code in (126, 127) and not self.started:
            self.hint.setText("Recording cancelled.")
            return
        self.hint.setText("Recorded. Check that every button shows up, then open the issue.")
        self._show()

    def _save(self):
        default = str(Path.home() / f"mousekit-dump-{self.info.key.replace(':', '-')}.txt")
        path, _ = QFileDialog.getSaveFileName(self, "Save the dump", default, "Text files (*.txt)")
        if path:
            Path(path).write_text(self.text.toPlainText() + "\n")
            self.hint.setText(f"Saved to {path}.")

    def _issue(self):
        text = self.text.toPlainText()
        QGuiApplication.clipboard().setText(text)
        url = updates.new_mouse_issue(self.name, self.info.key, text)
        if len(url) > 7500:  # too long for a link: GitHub would refuse it
            url = updates.new_mouse_issue(self.name, self.info.key)
            self.hint.setText("The text is too long for the link, so it's only copied: paste it into the "
                              "“Mousekit dump” field.")
        else:
            self.hint.setText("Opened in the browser. The text is also copied.")
        QDesktopServices.openUrl(QUrl.fromEncoded(url.encode()))



def main():
    app = QApplication(sys.argv)
    app.setApplicationName("mousekit")
    app.setDesktopFileName("mousekit")
    window = MainWindow()
    window.show()
    if "--about" in sys.argv[1:]:
        QTimer.singleShot(300, window.show_about)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
