"""生成 app.ico —— 与 main.py 的 _make_app_icon 同款（便笺 + 勾）。

打包前运行一次即可：python gen_icon.py
需要 PySide6（项目已依赖）。无显示环境下用 offscreen 平台插件渲染。
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QGuiApplication, QPixmap, QPainter, QColor, QLinearGradient, QPen,
)


def render_icon(size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor('#5AC8FA'))
    gradient.setColorAt(1.0, QColor('#007AFF'))
    painter.setBrush(gradient)
    painter.setPen(Qt.NoPen)
    margin = max(1, round(size * 8 / 256))
    radius = max(2, round(size * 48 / 256))
    painter.drawRoundedRect(margin, margin, size - 2 * margin, size - 2 * margin, radius, radius)
    scale = size / 256.0
    painter.setBrush(QColor('#FFFFFF'))
    painter.drawRoundedRect(QRectF(55 * scale, 42 * scale, 146 * scale, 172 * scale), 24 * scale, 24 * scale)
    ink = QPen(QColor('#007AFF'), max(1.5, 13 * scale))
    ink.setCapStyle(Qt.RoundCap)
    ink.setJoinStyle(Qt.RoundJoin)
    painter.setPen(ink)
    for x1, y1, x2, y2 in (
        (82, 86, 174, 86),
        (82, 119, 151, 119),
        (83, 163, 109, 187),
        (109, 187, 174, 145),
    ):
        painter.drawLine(
            QPointF(x1 * scale, y1 * scale),
            QPointF(x2 * scale, y2 * scale),
        )
    painter.end()
    return pix


def main():
    app = QGuiApplication([])
    # 256 画布渲染后存 ICO；Qt 的 ICO writer 会写入该尺寸，Windows 自行缩放。
    pix = render_icon(256)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.ico')
    ok = pix.save(out, 'ICO')
    print('saved' if ok else 'FAILED', out)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
