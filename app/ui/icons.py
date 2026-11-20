"""Vector icons drawn in one style so the window does not depend on a theme icon set."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _pixmap(size: int, paint) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint(painter, size)
    painter.end()
    return pixmap


def _stroke(painter: QPainter, color: str, side: int) -> None:
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.35, side / 11))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _icon(size: int, color: str, paint, disabled: str = "#8d8d8d") -> QIcon:
    icon = QIcon()
    icon.addPixmap(_pixmap(size, lambda painter, side: paint(painter, side, color)), QIcon.Mode.Normal)
    icon.addPixmap(_pixmap(size, lambda painter, side: paint(painter, side, disabled)), QIcon.Mode.Disabled)
    return icon


def app_mark(size: int = 64) -> QPixmap:
    """Stable application mark. It does not change with the day."""

    def paint(painter: QPainter, side: int) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#000000"))
        painter.drawRoundedRect(QRectF(0, 0, side, side), side * 0.22, side * 0.22)
        left = side * 0.22
        top = side * 0.24
        width = side * 0.56
        height = side * 0.56
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(QRectF(left, top, width, height), side * 0.08, side * 0.08)
        painter.setBrush(QColor("#FFCB05"))
        painter.drawRoundedRect(QRectF(left, top, width, height * 0.30), side * 0.08, side * 0.08)
        painter.drawRect(QRectF(left, top + height * 0.16, width, height * 0.16))
        painter.setBrush(QColor("#000000"))
        ring_w = max(1.0, side * 0.055)
        ring_h = side * 0.16
        painter.drawRoundedRect(QRectF(left + width * 0.24, top - ring_h * 0.42, ring_w, ring_h), 1, 1)
        painter.drawRoundedRect(QRectF(left + width * 0.64, top - ring_h * 0.42, ring_w, ring_h), 1, 1)
        painter.setBrush(QColor("#374151"))
        line_h = max(1.0, side * 0.04)
        painter.drawRoundedRect(QRectF(left + width * 0.16, top + height * 0.48, width * 0.40, line_h), 1, 1)
        painter.drawRoundedRect(QRectF(left + width * 0.16, top + height * 0.68, width * 0.58, line_h), 1, 1)

    return _pixmap(size, paint)


def calendar_icon(size: int = 64) -> QIcon:
    return QIcon(app_mark(size))


def messages_icon(size: int = 16, color: str = "#1F4E79") -> QIcon:
    def paint(painter: QPainter, side: int, tint: str) -> None:
        _stroke(painter, tint, side)
        rect = QRectF(side * 0.12, side * 0.20, side * 0.76, side * 0.56)
        painter.drawRoundedRect(rect, 2, 2)
        painter.drawLine(QPointF(rect.left() + 1, rect.top() + 1), QPointF(side * 0.50, side * 0.52))
        painter.drawLine(QPointF(rect.right() - 1, rect.top() + 1), QPointF(side * 0.50, side * 0.52))

    return _icon(size, color, paint)


def gear_icon(size: int = 16, color: str = "#1F4E79") -> QIcon:
    def paint(painter: QPainter, side: int, tint: str) -> None:
        _stroke(painter, tint, side)
        center = side / 2
        painter.drawEllipse(QRectF(center - side * 0.16, center - side * 0.16, side * 0.32, side * 0.32))
        for step in range(8):
            angle = step * math.pi / 4
            painter.drawLine(
                QPointF(center + math.cos(angle) * side * 0.24, center + math.sin(angle) * side * 0.24),
                QPointF(center + math.cos(angle) * side * 0.42, center + math.sin(angle) * side * 0.42),
            )

    return _icon(size, color, paint)


def refresh_icon(size: int = 16, color: str = "#1F4E79") -> QIcon:
    def paint(painter: QPainter, side: int, tint: str) -> None:
        _stroke(painter, tint, side)
        margin = side * 0.22
        rect = QRectF(margin, margin, side - margin * 2, side - margin * 2)
        painter.drawArc(rect, 40 * 16, 280 * 16)
        angle = math.radians(40)
        tip = QPointF(side / 2 + math.cos(angle) * rect.width() / 2, side / 2 - math.sin(angle) * rect.height() / 2)
        painter.drawLine(tip, QPointF(tip.x() - side * 0.16, tip.y() - side * 0.02))
        painter.drawLine(tip, QPointF(tip.x() + side * 0.02, tip.y() + side * 0.16))

    return _icon(size, color, paint)


def chevron_icon(direction: str, size: int = 14, color: str = "#1F4E79") -> QIcon:
    def paint(painter: QPainter, side: int, tint: str) -> None:
        _stroke(painter, tint, side)
        if direction == "left":
            points = (QPointF(side * 0.62, side * 0.22), QPointF(side * 0.34, side * 0.50), QPointF(side * 0.62, side * 0.78))
        else:
            points = (QPointF(side * 0.38, side * 0.22), QPointF(side * 0.66, side * 0.50), QPointF(side * 0.38, side * 0.78))
        painter.drawPolyline(points)

    return _icon(size, color, paint)


def pin_pixmap(size: int = 16, color: str = "#5C6B7A") -> QPixmap:
    def paint(painter: QPainter, side: int) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        path = QPainterPath()
        path.addEllipse(QRectF(side * 0.22, side * 0.06, side * 0.56, side * 0.56))
        path.moveTo(side * 0.30, side * 0.42)
        path.lineTo(side * 0.50, side * 0.94)
        path.lineTo(side * 0.70, side * 0.42)
        path.closeSubpath()
        painter.drawPath(path)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(side * 0.40, side * 0.24, side * 0.20, side * 0.20))

    return _pixmap(size, paint)


def repeat_pixmap(size: int = 16, color: str = "#5C6B7A") -> QPixmap:
    def paint(painter: QPainter, side: int) -> None:
        _stroke(painter, color, side)
        painter.drawArc(QRectF(side * 0.18, side * 0.18, side * 0.64, side * 0.64), 35 * 16, 250 * 16)
        tip = QPointF(side * 0.72, side * 0.30)
        painter.setBrush(QColor(color))
        head = QPainterPath()
        head.moveTo(tip)
        head.lineTo(side * 0.58, side * 0.18)
        head.lineTo(side * 0.86, side * 0.16)
        head.closeSubpath()
        painter.drawPath(head)

    return _pixmap(size, paint)


def warning_pixmap(size: int = 16, color: str = "#9B1C1C") -> QPixmap:
    def paint(painter: QPainter, side: int) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        path = QPainterPath()
        path.moveTo(side * 0.50, side * 0.08)
        path.lineTo(side * 0.92, side * 0.88)
        path.lineTo(side * 0.08, side * 0.88)
        path.closeSubpath()
        painter.drawPath(path)
        painter.setPen(QPen(QColor("#FFFFFF"), max(1.2, side / 10), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(side * 0.50, side * 0.36), QPointF(side * 0.50, side * 0.62))
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(side * 0.44, side * 0.68, side * 0.12, side * 0.12))

    return _pixmap(size, paint)


def sun_icon(size: int = 16, color: str = "#1F4E79") -> QIcon:
    def paint(painter: QPainter, side: int, tint: str) -> None:
        _stroke(painter, tint, side)
        center = side / 2
        painter.drawEllipse(QRectF(center - side * 0.16, center - side * 0.16, side * 0.32, side * 0.32))
        for step in range(8):
            angle = step * math.pi / 4
            painter.drawLine(
                QPointF(center + math.cos(angle) * side * 0.26, center + math.sin(angle) * side * 0.26),
                QPointF(center + math.cos(angle) * side * 0.42, center + math.sin(angle) * side * 0.42),
            )

    return _icon(size, color, paint)


def moon_icon(size: int = 16, color: str = "#1F4E79") -> QIcon:
    def paint(painter: QPainter, side: int, tint: str) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tint))
        painter.drawEllipse(QRectF(side * 0.18, side * 0.12, side * 0.62, side * 0.62))
        painter.setBrush(QColor("#000000"))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.drawEllipse(QRectF(side * 0.36, side * 0.08, side * 0.58, side * 0.58))

    return _icon(size, color, paint)


def tasks_icon(size: int = 16, color: str = "#111111") -> QIcon:
    def paint(painter: QPainter, side: int, tint: str) -> None:
        _stroke(painter, tint, side)
        for index, y in enumerate((0.22, 0.50, 0.78)):
            painter.drawRect(QRectF(side * 0.16, side * y - side * 0.08, side * 0.16, side * 0.16))
            painter.drawLine(
                QPointF(side * 0.42, side * y),
                QPointF(side * 0.84, side * y),
            )

    return _icon(size, color, paint)


def bell_icon(size: int = 16, color: str = "#111111") -> QIcon:
    def paint(painter: QPainter, side: int, tint: str) -> None:
        _stroke(painter, tint, side)
        path = QPainterPath()
        path.moveTo(side * 0.50, side * 0.12)
        path.cubicTo(side * 0.28, side * 0.12, side * 0.22, side * 0.38, side * 0.22, side * 0.52)
        path.lineTo(side * 0.16, side * 0.70)
        path.lineTo(side * 0.84, side * 0.70)
        path.lineTo(side * 0.78, side * 0.52)
        path.cubicTo(side * 0.78, side * 0.38, side * 0.72, side * 0.12, side * 0.50, side * 0.12)
        painter.drawPath(path)
        painter.drawLine(QPointF(side * 0.18, side * 0.70), QPointF(side * 0.82, side * 0.70))
        painter.drawArc(QRectF(side * 0.40, side * 0.72, side * 0.20, side * 0.16), 0, -180 * 16)

    return _icon(size, color, paint)


def dot_pixmap(size: int = 10, color: str = "#111111") -> QPixmap:
    def paint(painter: QPainter, side: int) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        margin = side * 0.12
        painter.drawEllipse(QRectF(margin, margin, side - margin * 2, side - margin * 2))

    return _pixmap(size, paint)
