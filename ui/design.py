"""design.py - نظام التصميم لبرنامج إدارة وثائق الأشغال (منقول من تصميم Workflow بألوان جديدة: تيل + ذهبي).

Everything visual that is *global* lives here:
  * light / dark palettes (teal family with a warm gold accent) - غيّر LIGHT / DARK أدناه لتبديل ألوان البرنامج كله
  * font loading (drop Cairo / Tajawal .ttf files into ./fonts to use them)
  * vector icon set drawn with QPainter (crisp at any DPI, theme aware)
  * the application stylesheet (QSS) built from the active palette
  * small paint helpers (soft layered shadows, colour mixing)
"""
from __future__ import annotations

import math
import re
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QObject, Signal, QPointF, QRectF
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QPainter, QPen, QBrush, QPixmap,
                           QLinearGradient, QPainterPath, QPolygonF, QIcon)

# --------------------------------------------------------------------------- palettes
LIGHT = dict(
    name='light',
    bg0='#F0F8F6', bg1='#FBF6EA',
    surface='#FFFFFF', surface_alt='#F3FAF8',
    border='#D9EBE7', border_strong='#B7D5CF',
    text='#0F2E2B', text_muted='#58766F', text_faint='#98B2AC',
    primary='#0B7A70', primary_dark='#0F766E', primary_soft='#E0F5F1', primary_soft2='#C4EBE3',
    accent='#0E8A7E', pink='#F59E0B', cyan='#06B6D4',          # 'pink' = اللمسة الذهبية (اسم المفتاح موروث)
    success='#15803D', success2='#4D7C0F', warning='#F59E0B', danger='#E11D48', danger2='#C2410C', info='#0284C7',
    input_bg='#FAFEFD', tooltip_bg='#0F2E2B', tooltip_fg='#FFFFFF', scroll='#B7D5CF',
    shadow='#0F766E', shadow_alpha=0.20,
    glow_a='#0D9488', glow_b='#F59E0B', glow_alpha=0.16,
    hero_a='#0A5550', hero_b='#0B7A70', hero_c='#0E8A7E', hero_shadow='#0F766E',
)
DARK = dict(
    name='dark',
    bg0='#06191A', bg1='#102220',
    surface='#0F2625', surface_alt='#143130',
    border='#21423F', border_strong='#2F5C57',
    text='#E4F6F3', text_muted='#8FB5AF', text_faint='#5E8680',
    primary='#0E8A7E', primary_dark='#99F6E4', primary_soft='#173A38', primary_soft2='#1F4C49',
    accent='#0B7A70', pink='#FBBF24', cyan='#22D3EE',
    success='#15803D', success2='#4D7C0F', warning='#FBBF24', danger='#DC2650', danger2='#C2410C', info='#38BDF8',
    input_bg='#0A1D1C', tooltip_bg='#E4F6F3', tooltip_fg='#0F2E2B', scroll='#2F5C57',
    shadow='#000000', shadow_alpha=0.55,
    glow_a='#14B8A6', glow_b='#F59E0B', glow_alpha=0.20,
    hero_a='#063B3A', hero_b='#0B6B66', hero_c='#0E7C70', hero_shadow='#000000',
)

P: dict = dict(LIGHT)          # live palette - mutated in place, so `from theme import P` stays valid
_ICONS: dict = {}              # paths of generated png icons used by the stylesheet


class _Signals(QObject):
    changed = Signal()         # emitted after the palette / stylesheet changed


signals = _Signals()


def mode() -> str:
    return P['name']


# --------------------------------------------------------------------------- colour helpers
def qc(color, alpha: float | None = None) -> QColor:
    """QColor from anything, with optional alpha in 0..1."""
    c = QColor(color)
    if alpha is not None:
        c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def mix(a, b, t: float) -> QColor:
    """Linear blend of two colours (alpha included)."""
    a, b = QColor(a), QColor(b)
    t = max(0.0, min(1.0, t))
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * t,
                           a.greenF() + (b.greenF() - a.greenF()) * t,
                           a.blueF() + (b.blueF() - a.blueF()) * t,
                           a.alphaF() + (b.alphaF() - a.alphaF()) * t)


def paint_shadow(p: QPainter, rect: QRectF, radius: float, color, spread: int = 14, dy: float = 6.0):
    """Soft layered drop shadow painted *around* `rect` (no QGraphicsEffect needed, so it is cheap
    and safe to use on cards that contain tables). `color.alphaF()` is the strength at the edge."""
    color = QColor(color)
    total = color.alphaF()
    if total <= 0:
        return
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(spread, 0, -1):
        fall = (1.0 - (i - 1) / spread) ** 2
        c = QColor(color)
        c.setAlphaF(min(1.0, total * 3.0 / spread * fall))
        p.setBrush(c)
        p.drawRoundedRect(rect.translated(0, dy).adjusted(-i, -i, i, i), radius + i, radius + i)
    p.restore()


# --------------------------------------------------------------------------- semantic colours
# حالات العرض للوثائق (مفاتيح services.DISPLAY_STATUSES) + ألوان دلالية عامة
STATUS_KEYS = {'draft': 'draft', 'draft_correction': 'draftfix', 'issued': 'issued', 'issued_correction': 'issuedfix', 'archived': 'archived'}
_STATUS_BASE = {
    'draft': '#F59E0B',        # كهرماني: مسودة
    'draftfix': '#F97316',     # برتقالي: مسودة تصحيحية
    'issued': '#15803D',       # أخضر: صادرة
    'issuedfix': '#0284C7',    # أزرق: تصحيحية صادرة
    'archived': '#94A3B8',     # رمادي: مؤرشفة
    'scheduled': '#0D9488', 'progress': '#F59E0B', 'done': '#16A34A', 'cancel': '#94A3B8', 'late': '#E11D48', 'ontime': '#0284C7',
}


def status_colors(key: str):
    """(foreground, soft background, dot) for a status key."""
    base = QColor(_STATUS_BASE.get(key, '#0D9488'))
    dark = P['name'] == 'dark'
    fg = base.lighter(125) if dark else base.darker(135)
    bg = QColor(base)
    bg.setAlphaF(0.22 if dark else 0.13)
    return fg, bg, base


def priority_colors(v: int):
    v = int(v)
    if v <= 3:
        return QColor('#34D399'), QColor('#10B981')
    if v <= 6:
        return QColor('#FBBF24'), QColor('#F59E0B')
    if v <= 8:
        return QColor('#FB923C'), QColor('#F97316')
    return QColor('#FB7185'), QColor('#F43F5E')


_AVATARS = [('#0D9488', '#14B8A6'), ('#0284C7', '#06B6D4'), ('#16A34A', '#65A30D'), ('#F59E0B', '#F97316'),
            ('#0F766E', '#10B981'), ('#B45309', '#F59E0B'), ('#0891B2', '#0D9488'), ('#E11D48', '#FB923C')]


def avatar_gradient(name: str):
    i = sum(ord(ch) for ch in (name or '?')) % len(_AVATARS)
    return QColor(_AVATARS[i][0]), QColor(_AVATARS[i][1])


# --------------------------------------------------------------------------- fonts
PREFERRED_FONTS = ['Cairo', 'Tajawal', 'IBM Plex Sans Arabic', 'Noto Sans Arabic',
                   'Segoe UI Variable Text', 'Segoe UI', 'Tahoma', 'Arial']


def setup_fonts(app, base_dir) -> str:
    """Load optional fonts from ./fonts and set the application font (first available wins)."""
    fdir = Path(base_dir) / 'fonts'
    if fdir.is_dir():
        for f in sorted(list(fdir.glob('*.ttf')) + list(fdir.glob('*.otf'))):
            QFontDatabase.addApplicationFont(str(f))
    available = set(QFontDatabase.families())
    chosen = [f for f in PREFERRED_FONTS if f in available] or [app.font().family()]
    font = QFont(chosen[0])
    try:
        font.setFamilies(chosen)
    except Exception:
        pass
    font.setPointSizeF(10.0)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)
    return chosen[0]


# --------------------------------------------------------------------------- vector icons (24x24 grid)
def _poly(p, pts):
    p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in pts]))


def _line(p, x1, y1, x2, y2):
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _rrect(p, x, y, w, h, r):
    p.drawRoundedRect(QRectF(x, y, w, h), r, r)


def _circ(p, cx, cy, r):
    p.drawEllipse(QPointF(cx, cy), r, r)


def _i_plus(p): _line(p, 12, 5, 12, 19); _line(p, 5, 12, 19, 12)
def _i_edit(p): _poly(p, [(15.5, 4), (20, 8.5), (8.5, 20), (3.5, 20.5), (4, 15.5), (15.5, 4)]); _line(p, 13, 6.5, 17.5, 11)
def _i_check(p): _poly(p, [(5, 12.5), (10, 17.5), (19, 7)])
def _i_check_circle(p): _circ(p, 12, 12, 9); _poly(p, [(7.8, 12.3), (10.8, 15.3), (16.3, 9.3)])
def _i_clock(p): _circ(p, 12, 12, 9); _poly(p, [(12, 7), (12, 12), (15.5, 14)])
def _i_alert(p): _poly(p, [(12, 3.5), (21.5, 20), (2.5, 20), (12, 3.5)]); _line(p, 12, 9.5, 12, 14); _line(p, 12, 17.2, 12, 17.3)
def _i_tasks(p): _rrect(p, 5, 4.5, 14, 17, 2.5); _rrect(p, 9, 2.5, 6, 4, 1.5); _poly(p, [(8.5, 13.5), (11, 16), (15.5, 10.5)])
def _i_calendar(p): _rrect(p, 3.5, 5, 17, 15.5, 3); _line(p, 3.5, 10, 20.5, 10); _line(p, 8, 3, 8, 7); _line(p, 16, 3, 16, 7)
def _i_archive(p): _rrect(p, 3, 4, 18, 4.5, 1.2); _poly(p, [(5, 8.5), (5, 19.5), (19, 19.5), (19, 8.5)]); _line(p, 10, 12.5, 14, 12.5)
def _i_trash(p): _line(p, 4, 7, 20, 7); _poly(p, [(6, 7), (7, 20), (17, 20), (18, 7)]); _poly(p, [(9, 7), (9, 4), (15, 4), (15, 7)]); _line(p, 10, 11, 10, 16); _line(p, 14, 11, 14, 16)
def _i_copy(p): _rrect(p, 9, 9, 11, 11, 2.2); _poly(p, [(9, 15), (4, 15), (4, 4), (15, 4), (15, 9)])
def _i_download(p): _poly(p, [(7, 10.5), (12, 15.5), (17, 10.5)]); _line(p, 12, 3.5, 12, 15.5); _line(p, 4.5, 20, 19.5, 20)
def _i_chev_l(p): _poly(p, [(15, 5), (8, 12), (15, 19)])
def _i_chev_r(p): _poly(p, [(9, 5), (16, 12), (9, 19)])
def _i_chev_d(p): _poly(p, [(5, 9), (12, 16), (19, 9)])
def _i_chev_u(p): _poly(p, [(5, 15), (12, 8), (19, 15)])
def _i_search(p): _circ(p, 11, 11, 6.5); _line(p, 16, 16, 21, 21)
def _i_chart(p): _line(p, 6, 20, 6, 12); _line(p, 12, 20, 12, 5); _line(p, 18, 20, 18, 9)
def _i_file(p): _poly(p, [(6, 3), (14, 3), (19, 8), (19, 21), (6, 21), (6, 3)]); _poly(p, [(14, 3), (14, 8), (19, 8)])
def _i_doc(p): _i_file(p); _line(p, 9.5, 13, 15.5, 13); _line(p, 9.5, 16.5, 15.5, 16.5)
def _i_sheet(p): _i_file(p); _line(p, 9, 13, 16, 13); _line(p, 9, 17, 16, 17); _line(p, 12.5, 11, 12.5, 19)


def _i_users(p):
    _circ(p, 9, 8, 3.5)
    a = QPainterPath(); a.moveTo(2.5, 20); a.cubicTo(2.5, 13.5, 15.5, 13.5, 15.5, 20); p.drawPath(a)
    _circ(p, 17.5, 9, 2.5)
    b = QPainterPath(); b.moveTo(17.5, 14.2); b.cubicTo(20.5, 14.2, 22, 16, 22, 19); p.drawPath(b)


def _i_restore(p):
    p.drawArc(QRectF(5, 5, 14, 14), 90 * 16, 250 * 16)
    _poly(p, [(14.5, 2.5), (12, 5), (14.5, 7.5)])


def _i_moon(p):
    a = QPainterPath(); a.addEllipse(QPointF(12, 12), 8.5, 8.5)
    b = QPainterPath(); b.addEllipse(QPointF(16.5, 8), 7, 7)
    p.setBrush(p.pen().color()); p.drawPath(a.subtracted(b)); p.setBrush(Qt.BrushStyle.NoBrush)


def _i_sun(p):
    _circ(p, 12, 12, 4)
    for i in range(8):
        a = i * math.pi / 4
        _line(p, 12 + 7.2 * math.cos(a), 12 + 7.2 * math.sin(a), 12 + 9.8 * math.cos(a), 12 + 9.8 * math.sin(a))


def _i_home(p): _poly(p, [(3, 11), (12, 3.5), (21, 11)]); _poly(p, [(5.5, 9.5), (5.5, 20.5), (18.5, 20.5), (18.5, 9.5)]); _poly(p, [(10, 20.5), (10, 14.5), (14, 14.5), (14, 20.5)])
def _i_folder(p): _poly(p, [(3, 6.5), (3, 19), (21, 19), (21, 8.5), (11, 8.5), (9, 6.5), (3, 6.5)])
def _i_eye(p):
    a = QPainterPath(); a.moveTo(2.5, 12); a.quadTo(12, 3, 21.5, 12); a.quadTo(12, 21, 2.5, 12); p.drawPath(a); _circ(p, 12, 12, 3)
def _i_shield(p):
    a = QPainterPath(); a.moveTo(12, 3); a.lineTo(20, 6); a.lineTo(20, 12); a.cubicTo(20, 16.5, 16.5, 19.5, 12, 21)
    a.cubicTo(7.5, 19.5, 4, 16.5, 4, 12); a.lineTo(4, 6); a.closeSubpath(); p.drawPath(a); _poly(p, [(8.5, 12), (11, 14.5), (15.5, 9.5)])
def _i_database(p):
    p.drawEllipse(QPointF(12, 6), 8, 3); _line(p, 4, 6, 4, 18); _line(p, 20, 6, 20, 18)
    p.drawArc(QRectF(4, 9, 16, 6), 180 * 16, 180 * 16); p.drawArc(QRectF(4, 15, 16, 6), 180 * 16, 180 * 16)


ICONS = {
    'home': _i_home, 'folder': _i_folder, 'eye': _i_eye, 'shield': _i_shield, 'database': _i_database,
    'plus': _i_plus, 'edit': _i_edit, 'check': _i_check, 'check_circle': _i_check_circle, 'clock': _i_clock,
    'alert': _i_alert, 'tasks': _i_tasks, 'calendar': _i_calendar, 'archive': _i_archive, 'trash': _i_trash,
    'copy': _i_copy, 'download': _i_download, 'chevron_left': _i_chev_l, 'chevron_right': _i_chev_r,
    'chev_down': _i_chev_d, 'chev_up': _i_chev_u, 'search': _i_search, 'chart': _i_chart, 'file': _i_file,
    'doc': _i_doc, 'sheet': _i_sheet, 'users': _i_users, 'restore': _i_restore, 'moon': _i_moon, 'sun': _i_sun,
}


def draw_icon(p: QPainter, kind: str, rect, color, width: float = 2.0):
    """Draw icon `kind` inside `rect` using `color` (stroke width is in 24-grid units)."""
    fn = ICONS.get(kind)
    if fn is None:
        return
    rect = QRectF(rect)
    s = min(rect.width(), rect.height()) / 24.0
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(rect.center().x() - 12 * s, rect.center().y() - 12 * s)
    p.scale(s, s)
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    fn(p)
    p.restore()


def icon_pixmap(kind: str, color, size: int = 20) -> QPixmap:
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.GlobalColor.transparent)
    pm.setDevicePixelRatio(scale)
    p = QPainter(pm)
    draw_icon(p, kind, QRectF(0, 0, size, size), color)
    p.end()
    return pm


def app_icon() -> QIcon:
    """Gradient app icon (window + tray)."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, size, size)
        g.setColorAt(0, QColor('#0A5550')); g.setColorAt(0.6, QColor('#14B8A6')); g.setColorAt(1, QColor('#F59E0B'))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.24, size * 0.24)
        draw_icon(p, 'doc', QRectF(size * 0.2, size * 0.2, size * 0.6, size * 0.6), '#FFFFFF', width=2.2)
        p.end()
        icon.addPixmap(pm)
    return icon


def _build_qss_icons():
    """Arrow images referenced by the stylesheet (QSS cannot draw arrows by itself)."""
    d = Path(tempfile.gettempdir()) / 'WorksApp_ui' / P['name']
    d.mkdir(parents=True, exist_ok=True)
    specs = {'down': ('chev_down', P['text_muted']), 'up': ('chev_up', P['text_muted']),
             'check': ('check', '#FFFFFF'), 'cal_prev': ('chevron_right', '#FFFFFF'), 'cal_next': ('chevron_left', '#FFFFFF')}
    _ICONS.clear()
    for key, (kind, color) in specs.items():
        for scale, suffix in ((1, ''), (2, '@2x')):
            size = 14 * scale
            pm = QPixmap(size, size)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            draw_icon(p, kind, QRectF(0, 0, size, size), color, width=2.6)
            p.end()
            pm.save(str(d / f'{key}{suffix}.png'), 'PNG')
        _ICONS['ico_' + key] = (d / f'{key}.png').as_posix()


# --------------------------------------------------------------------------- stylesheet
_QSS = '''
* { outline: none; }
QMainWindow { background: @bg0@; }
QDialog { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 @bg0@, stop:1 @bg1@); }
QWidget { color: @text@; }
QLabel { background: transparent; }
QToolTip { background: @tooltip_bg@; color: @tooltip_fg@; border: 0; border-radius: 8px; padding: 7px 11px; }

QLabel#heroTitle { color: #FFFFFF; font-size: 26px; font-weight: 800; }
QLabel#heroSub { color: rgba(255,255,255,215); font-size: 13px; }
QLabel#cardTitle { font-size: 15px; font-weight: 700; }
QLabel#muted { color: @text_muted@; }
QLabel#fieldLabel { color: @text_muted@; font-weight: 600; font-size: 12px; }
QLabel#chip { background: @primary_soft@; color: @primary_dark@; border-radius: 13px; padding: 5px 14px; font-weight: 700; }
QLabel#empty { color: @text_faint@; font-size: 14px; font-weight: 600; }

QLineEdit#heroSearch { background: rgba(255,255,255,46); border: 1px solid rgba(255,255,255,90); border-radius: 15px;
    color: #FFFFFF; padding: 10px 16px; placeholder-text-color: rgba(255,255,255,175);
    selection-background-color: rgba(255,255,255,100); selection-color: #FFFFFF; }
QLineEdit#heroSearch:hover { background: rgba(255,255,255,62); }
QLineEdit#heroSearch:focus { background: rgba(255,255,255,80); border: 1px solid #FFFFFF; }

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QTimeEdit, QDateEdit, QComboBox {
    background: @input_bg@; border: 1px solid @border@; border-radius: 12px; padding: 6px 12px;
    selection-background-color: @primary@; selection-color: #FFFFFF; }
QTextEdit, QPlainTextEdit { padding: 8px 12px; }
QSpinBox, QTimeEdit, QDateEdit, QComboBox { padding: 8px 30px; min-height: 22px; }
QLineEdit:hover, QTextEdit:hover, QSpinBox:hover, QTimeEdit:hover, QDateEdit:hover, QComboBox:hover { border-color: @border_strong@; }
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QTimeEdit:focus, QDateEdit:focus, QComboBox:focus { border: 1px solid @primary@; background: @surface@; }

QSpinBox#timePart { padding: 8px 4px; min-width: 44px; font-weight: 700; }
QLabel#timeColon { font-weight: 800; color: @text_muted@; }
QComboBox { combobox-popup: 0; }
QComboBox::drop-down, QDateEdit::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 30px; border: 0; background: transparent; }
QComboBox::down-arrow, QDateEdit::down-arrow { image: url(@ico_down@); width: 14px; height: 14px; }
QSpinBox::up-button, QTimeEdit::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 24px; border: 0; background: transparent; margin: 4px 4px 0 4px; }
QSpinBox::down-button, QTimeEdit::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 24px; border: 0; background: transparent; margin: 0 4px 4px 4px; }
QSpinBox::up-arrow, QTimeEdit::up-arrow { image: url(@ico_up@); width: 10px; height: 10px; }
QSpinBox::down-arrow, QTimeEdit::down-arrow { image: url(@ico_down@); width: 10px; height: 10px; }
QComboBox QAbstractItemView { background: @surface@; border: 1px solid @border@; border-radius: 12px; padding: 6px;
    selection-background-color: @primary_soft@; selection-color: @primary_dark@; outline: 0; }
QComboBox QAbstractItemView::item { padding: 8px 12px; border-radius: 8px; min-height: 24px; }
QComboBox QAbstractItemView::item:selected, QComboBox QAbstractItemView::item:hover { background: @primary_soft@; color: @primary_dark@; }


QScrollArea { background: transparent; border: 0; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 4px 2px; }
QScrollBar::handle:vertical { background: @scroll@; border-radius: 4px; min-height: 36px; margin: 0 2px; }
QScrollBar::handle:vertical:hover { background: @primary@; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px 4px; }
QScrollBar::handle:horizontal { background: @scroll@; border-radius: 4px; min-width: 36px; margin: 2px 0; }
QScrollBar::handle:horizontal:hover { background: @primary@; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QTableWidget { background: @surface@; alternate-background-color: @surface_alt@; border: 1px solid @border@; border-radius: 12px;
    gridline-color: @border@; selection-background-color: @primary_soft2@; selection-color: @text@; }
QTableWidget#hoverTable { background: transparent; border: 0; gridline-color: transparent; }
QTableView::item { padding: 3px 6px; }
QHeaderView { background: transparent; border: 0; }
QHeaderView::section { background: @surface_alt@; color: @text_muted@; border: 0; border-bottom: 2px solid @border@; border-left: 1px solid @border@;
    padding: 9px 10px; font-weight: 700; font-size: 12px; }
QTableWidget#hoverTable QHeaderView::section { background: transparent; border-left: 0; }
QTableCornerButton::section { background: transparent; border: 0; }

QSlider::groove:horizontal { height: 8px; border-radius: 4px; background: @border@; }
QSlider::sub-page:horizontal { border-radius: 4px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @info@, stop:1 @accent@); }
QSlider::add-page:horizontal { border-radius: 4px; background: @border@; }
QSlider::handle:horizontal { width: 12px; height: 12px; margin: -5px 0; border-radius: 9px; background: @surface@; border: 3px solid @primary@; }
QSlider::handle:horizontal:hover { border-color: @accent@; }

QProgressBar { background: @border@; border: 0; border-radius: 5px; max-height: 10px; min-height: 10px; }
QProgressBar::chunk { border-radius: 5px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @info@, stop:1 @accent@); }

QStatusBar { background: transparent; color: @text_muted@; }
QStatusBar::item { border: 0; }

QMenu { background: @surface@; border: 1px solid @border@; border-radius: 12px; padding: 6px; }
QMenu::item { padding: 8px 22px; border-radius: 8px; }
QMenu::item:selected { background: @primary_soft@; color: @primary_dark@; }

QMessageBox { background: @surface@; }
QMessageBox QLabel { color: @text@; font-size: 14px; min-width: 280px; }
QMessageBox QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @primary@, stop:1 @accent@); color: #FFFFFF;
    border: 0; border-radius: 11px; padding: 9px 22px; min-width: 88px; font-weight: 700; }
QMessageBox QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @primary_dark@, stop:1 @primary@); }
QMessageBox QPushButton[secondary="true"] { background: @primary_soft@; color: @primary_dark@; }
QMessageBox QPushButton[secondary="true"]:hover { background: @primary_soft2@; }
QMessageBox QPushButton[danger="true"] { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @danger@, stop:1 @danger2@); }
/* ---------- عناصر برنامج الأشغال (أسماء الكائنات الموروثة) ---------- */
QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @primary@, stop:1 @accent@); color: #FFFFFF; border: 0; border-radius: 11px;
    padding: 8px 18px; font-weight: 700; min-height: 20px; }
QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @primary_dark@, stop:1 @primary@); }
QPushButton:disabled { background: @surface_alt@; color: @text_faint@; }
QPushButton#secondary, QPushButton#tool { background: @primary_soft@; color: @primary_dark@; font-weight: 600; }
QPushButton#secondary:hover, QPushButton#tool:hover { background: @primary_soft2@; }
QPushButton#secondary:disabled, QPushButton#tool:disabled { background: @surface_alt@; color: @text_faint@; }
QPushButton#danger { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @danger@, stop:1 @danger2@); }
QPushButton#danger:hover { background: @danger@; }
QPushButton:focus { border: 2px solid @pink@; }

QLabel#title { font-size: 18px; font-weight: 800; }
QLabel#hint { color: @text_muted@; font-size: 12px; }
QLabel#summary { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @surface@, stop:1 @primary_soft@); color: @primary_dark@;
    border: 1px solid @border@; border-right: 4px solid @primary@; border-radius: 12px; padding: 10px 14px; font-weight: 600; }
QLabel#warnBox { background: rgba(245,158,11,40); color: @text@; border: 1px solid rgba(245,158,11,120); border-radius: 12px; padding: 9px 14px; }
QLabel#projectTitle { color: rgba(255,255,255,225); font-size: 14px; font-weight: 600; }
QLabel#statValue { font-size: 24px; font-weight: 800; }
QLabel#companyName { font-size: 17px; font-weight: 800; }
QLabel#companyMeta { color: @text_muted@; }
QLabel#badgeDraft { background: rgba(245,158,11,45); color: #B45309; border-radius: 11px; padding: 3px 12px; font-weight: 700; }
QLabel#badgeIssued { background: rgba(22,163,74,40); color: #15803D; border-radius: 11px; padding: 3px 12px; font-weight: 700; }
QLabel#badgeNone { background: @surface_alt@; color: @text_muted@; border-radius: 11px; padding: 3px 12px; }

QFrame#card, QFrame#sidebar, QFrame#dedCard { background: @surface@; border: 1px solid @border@; border-radius: 18px; }
QFrame#dedCard { border-radius: 14px; }
QFrame#dedCard[disabledCard="true"] { background: @surface_alt@; border: 1px dashed @border_strong@; }
QLabel#cardTitle { font-size: 15px; font-weight: 700; }

QListWidget { background: transparent; border: 0; outline: 0; }
QListWidget::item { padding: 11px 12px; margin: 2px 0; border-radius: 12px; }
QListWidget::item:hover { background: @primary_soft@; }
QListWidget::item:selected { background: @primary_soft2@; color: @primary_dark@; border-right: 4px solid @primary@; }

QGroupBox { background: @surface@; border: 1px solid @border@; border-radius: 16px; margin-top: 18px; padding: 14px 12px 12px 12px; }
QGroupBox::title { subcontrol-origin: margin; right: 16px; padding: 0 8px; color: @primary_dark@; font-weight: 700; }

QTabWidget::pane { border: 1px solid @border@; background: @surface@; border-radius: 16px; top: -1px; }
QTabBar::tab { background: transparent; color: @text_muted@; padding: 9px 20px; margin: 4px 3px 6px 3px; border-radius: 14px; font-weight: 600; }
QTabBar::tab:hover { background: @primary_soft@; color: @primary_dark@; }
QTabBar::tab:selected { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @primary@, stop:1 @accent@); color: #FFFFFF; font-weight: 700; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 6px; border: 1px solid @border_strong@; background: @input_bg@; }
QCheckBox::indicator:hover { border-color: @primary@; }
QCheckBox::indicator:checked { background: @primary@; border: 1px solid @primary_dark@; image: url(@ico_check@); }
QCheckBox::indicator:checked:hover { background: @primary_dark@; }
QSplitter::handle { background: transparent; width: 8px; }
QPlainTextEdit { background: @input_bg@; }
'''


def build_qss() -> str:
    tokens = dict(P)
    tokens.update(_ICONS)
    return re.sub(r'@(\w+)@', lambda m: str(tokens.get(m.group(1), '#FF00FF')), _QSS)


def apply(app, which: str | None = None):
    """Activate a palette ('light' / 'dark'), rebuild icons + stylesheet and notify widgets."""
    src = DARK if which == 'dark' else LIGHT
    P.clear()
    P.update(src)
    _build_qss_icons()
    app.setStyleSheet(build_qss())
    signals.changed.emit()
