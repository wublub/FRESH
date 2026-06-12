"""生成 app.ico —— 与 main.py 的 _make_app_icon 同款（绿底圆角 + 白色 F）。

打包前运行一次即可：python gen_icon.py
需要 PySide6（项目已依赖）。无显示环境下用 offscreen 平台插件渲染。
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap, QPainter, QColor, QFont


def render_icon(size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(QColor('#34C759'))
    painter.setPen(Qt.NoPen)
    margin = max(1, round(size * 8 / 256))
    radius = max(2, round(size * 48 / 256))
    painter.drawRoundedRect(margin, margin, size - 2 * margin, size - 2 * margin, radius, radius)
    painter.setPen(QColor('#FFFFFF'))
    font = QFont(painter.font())
    font.setPixelSize(int(size * 0.56))
    font.setWeight(QFont.Bold)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignCenter, 'F')
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
