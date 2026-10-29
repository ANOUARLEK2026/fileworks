"""fx.py - مكوّنات الواجهة المتحركة والمتدرجة (منقولة من تصميم Workflow وملوّنة من ui/design.py).

All painting is done with QPainter (no extra dependencies) and every colour comes from theme.P,
so the whole UI re-skins instantly when the light / dark theme is switched.
"""
from __future__ import annotations

import math

from PySide6.QtCore import (Qt, QDate, QTime, QRectF, QPointF, QPoint, QSize, QEvent, QObject, QTimer, QEasingCurve, QVariantAnimation,
                            QPropertyAnimation, Signal)
from PySide6.QtGui import (QIcon, QColor, QPainter, QPen, QBrush, QFont, QFontMetrics, QLinearGradient, QRadialGradient,
                           QPainterPath)
from PySide6.QtWidgets import (QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout, QStackedWidget,
                               QGraphicsOpacityEffect, QGraphicsDropShadowEffect, QTableWidget, QStyledItemDelegate,
                               QStyle, QStyleOptionViewItem, QMessageBox, QSlider, QComboBox, QListView, QDialog,
                               QFrame, QSizePolicy, QSpinBox, QLineEdit, QCalendarWidget, QTabWidget)

from . import design as theme
from .design import P, qc, mix, paint_shadow, draw_icon

# item-data roles used by the table delegate (256 == Qt.UserRole)
ROLE_ID = 256
ROLE_STATE = 257      # row state: done / cancel / late / progress / scheduled
ROLE_PRIO = 258       # priority 1..10
ROLE_PILL = 259       # status-pill key for a cell

_OUT_CUBIC = QEasingCurve.Type.OutCubic


def anim(parent, duration=200, curve=_OUT_CUBIC) -> QVariantAnimation:
    a = QVariantAnimation(parent)
    a.setDuration(duration)
    a.setEasingCurve(curve)
    return a


def _retarget(a: QVariantAnimation, current: float, target: float):
    a.stop()
    a.setStartValue(float(current))
    a.setEndValue(float(target))
    a.start()


def _font(base: QFont, px: int, weight=QFont.Weight.Normal) -> QFont:
    f = QFont(base)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


# =========================================================================== surfaces
class Backdrop(QWidget):
    """Window background: soft gradient + three large 'light' glows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        theme.signals.changed.connect(self.update)

    def paintEvent(self, e):
        p = QPainter(self)
        r = self.rect()
        g = QLinearGradient(0, 0, r.width(), r.height())
        g.setColorAt(0, QColor(P['bg0']))
        g.setColorAt(1, QColor(P['bg1']))
        p.fillRect(r, g)
        for fx, fy, rad, col in ((0.12, 0.0, 0.55, P['glow_a']), (0.96, 1.0, 0.60, P['glow_b']), (0.88, 0.08, 0.35, P['cyan'])):
            c = qc(col, P['glow_alpha'])
            rg = QRadialGradient(QPointF(r.width() * fx, r.height() * fy), max(r.width(), r.height()) * rad)
            rg.setColorAt(0, c)
            rg.setColorAt(1, qc(col, 0.0))
            p.fillRect(r, QBrush(rg))


class Card(QWidget):
    """Rounded surface with a soft layered shadow. Put children in `card.body` (a QVBoxLayout)."""
    M = 16

    def __init__(self, parent=None, padding=16):
        super().__init__(parent)
        m = self.M
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(m + padding, m - 6 + padding, m + padding, m + 6 + padding)
        self.body.setSpacing(12)
        theme.signals.changed.connect(self.update)

    def visible_rect(self) -> QRectF:
        m = self.M
        return QRectF(self.rect()).adjusted(m, m - 6, -m, -(m + 6))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.visible_rect()
        paint_shadow(p, r, 20, qc(P['shadow'], P['shadow_alpha']), spread=14, dy=6)
        p.setPen(QPen(QColor(P['border']), 1))
        p.setBrush(QColor(P['surface']))
        p.drawRoundedRect(r, 20, 20)


# =========================================================================== buttons
class Btn(QPushButton):
    """Animated button. variants: primary | success | danger | soft | ghost | glass.
    Hover = colour blend + lift + glow, press = squash, keyboard focus = ring."""
    PAD_X, PAD_TOP, PAD_BOT = 6, 3, 9

    def __init__(self, text='', variant='soft', icon=None, parent=None, compact=False):
        super().__init__(text, parent)
        self.variant = variant
        self.icon_kind = icon
        self.compact = compact           # حشو أفقي أضيق (لصفوف الأزرار الكثيرة)
        self._full_text = text           # النص الكامل حين نحوّل الزر إلى أيقونة فقط
        self.dot = None
        self._h = 0.0
        self._pr = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFont(_font(self.font(), 13, QFont.Weight.DemiBold))
        self._ha = anim(self, 180)
        self._ha.valueChanged.connect(self._set_h)
        self._pa = anim(self, 90, QEasingCurve.Type.OutQuad)
        self._pa.valueChanged.connect(self._set_p)
        theme.signals.changed.connect(self.update)

    def _set_h(self, v): self._h = float(v); self.update()
    def _set_p(self, v): self._pr = float(v); self.update()

    def enterEvent(self, e): _retarget(self._ha, self._h, 1.0); super().enterEvent(e)
    def leaveEvent(self, e): _retarget(self._ha, self._h, 0.0); super().leaveEvent(e)

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        _retarget(self._pa, self._pr, 1.0)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        _retarget(self._pa, self._pr, 0.0)

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        t = self.text()
        w = fm.horizontalAdvance(t)
        if self.icon_kind or self.dot:
            w += 18 + (8 if t else 0)
        w += (22 if self.compact else 36) if t else 22
        return QSize(max(w, 88 if t else 44) + 2 * self.PAD_X, 40 + self.PAD_TOP + self.PAD_BOT)

    def minimumSizeHint(self):
        return self.sizeHint()

    def full_width(self):
        """العرض المطلوب والنص ظاهر (حتى لو كان الزر حاليًا أيقونة فقط)."""
        cur = self.text()
        if cur != self._full_text:
            self.setText(self._full_text); w = self.sizeHint().width(); self.setText(cur)
            return w
        return self.sizeHint().width()

    def set_icon_only(self, on):
        """أيقونة فقط عند ضيق العرض (والنص يبقى في التلميح) كي لا تتداخل الأزرار."""
        if on and self.text():
            self.setToolTip(self._full_text); self.setText('')
        elif not on and not self.text() and self._full_text:
            self.setText(self._full_text); self.setToolTip('')
        self.updateGeometry()

    def _style(self, h):
        """-> (colour1, colour2, foreground, border or None, glow or None)"""
        v = self.variant
        if v in ('primary', 'success', 'danger'):
            pairs = {'primary': (P['primary'], P['accent']), 'success': (P['success'], P['success2']), 'danger': (P['danger'], P['danger2'])}
            a, b = (QColor(x) for x in pairs[v])
            a, b = mix(a, a.lighter(118), h), mix(b, b.lighter(118), h)
            return a, b, QColor('#FFFFFF'), None, a
        if v == 'glass':
            bg = qc('#FFFFFF', 0.16 + 0.14 * h)
            return bg, bg, QColor('#FFFFFF'), qc('#FFFFFF', 0.30 + 0.20 * h), None
        if v == 'ghost':
            bg = mix(qc(P['primary_soft'], 0.0), QColor(P['primary_soft']), h)
            return bg, bg, mix(P['text_muted'], P['primary_dark'], h), None, None
        bg = mix(P['surface'], P['primary_soft'], h)
        return bg, bg, mix(P['text'], P['primary_dark'], h), mix(P['border'], P['primary'], h), None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        h = self._h if enabled else 0.0
        r = QRectF(self.rect()).adjusted(self.PAD_X, self.PAD_TOP, -self.PAD_X, -self.PAD_BOT)
        c1, c2, fg, border, glow = self._style(h)
        if not enabled:
            c1 = c2 = QColor(P['surface_alt'])
            fg = QColor(P['text_faint'])
            border, glow = QColor(P['border']), None
        if glow is not None:
            paint_shadow(p, r, 12, qc(glow, 0.36 + 0.16 * h), spread=8, dy=3 + 2 * h)
        s = 1.0 - 0.035 * self._pr
        c = r.center()
        p.translate(c)
        p.scale(s, s)
        p.translate(-c.x(), -c.y() - 1.5 * h)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        if c1 != c2:
            g = QLinearGradient(r.left(), r.top(), r.right(), r.bottom())
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.fillPath(path, g)
            gloss = QLinearGradient(0, r.top(), 0, r.bottom())
            gloss.setColorAt(0, QColor(255, 255, 255, 46))
            gloss.setColorAt(0.55, QColor(255, 255, 255, 0))
            p.fillPath(path, gloss)
        else:
            p.fillPath(path, c1)
        if border is not None:
            p.setPen(QPen(border, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        # content (icon + text, centred, mirrored in RTL)
        p.setFont(self.font())
        text = self.text()
        tw = QFontMetrics(self.font()).horizontalAdvance(text)
        iw = 18 if (self.icon_kind or self.dot) else 0
        gap = 8 if (iw and text) else 0
        total = iw + gap + tw
        x0 = r.center().x() - total / 2
        rtl = self.isRightToLeft()
        ix = x0 + total - iw if rtl else x0
        tx = x0 if rtl else x0 + iw + gap
        if self.icon_kind:
            draw_icon(p, self.icon_kind, QRectF(ix, r.center().y() - 9, 18, 18), fg, 2.1)
        elif self.dot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.dot)
            p.drawEllipse(QPointF(ix + 9, r.center().y()), 5.5, 5.5)
        if text:
            p.setPen(fg)
            p.drawText(QRectF(tx, r.top(), tw + 4, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        if self.hasFocus() and enabled:
            p.setPen(QPen(qc(P['primary'], 0.7), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 14, 14)


class Combo(QComboBox):
    """QComboBox with a styleable popup list (rounded, transparent frame)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setView(QListView())
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMaxVisibleItems(8)
        try:
            w = self.view().window()
            w.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
            w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        except Exception:
            pass


class FocusGlow(QObject):
    """Animated primary-colour glow around a line edit while it has focus."""

    def __init__(self, widget):
        super().__init__(widget)
        self.fx = QGraphicsDropShadowEffect(widget)
        self.fx.setOffset(0, 0)
        self.fx.setBlurRadius(0)
        self.fx.setColor(qc(P['primary'], 0.55))
        widget.setGraphicsEffect(self.fx)
        self.a = QPropertyAnimation(self.fx, b'blurRadius', self)
        self.a.setDuration(220)
        widget.installEventFilter(self)

    def eventFilter(self, o, e):
        t = e.type()
        if t == QEvent.Type.FocusIn:
            self.fx.setColor(qc(P['primary'], 0.55))
            self._go(18)
        elif t == QEvent.Type.FocusOut:
            self._go(0)
        return False

    def _go(self, v):
        self.a.stop()
        self.a.setStartValue(self.fx.blurRadius())
        self.a.setEndValue(float(v))
        self.a.start()


class SearchGrow(QObject):
    """Header search box smoothly widens when focused."""

    def __init__(self, edit, narrow=300, wide=440):
        super().__init__(edit)
        self.edit, self.narrow, self.wide = edit, narrow, wide
        self.a = QPropertyAnimation(edit, b'maximumWidth', self)
        self.a.setDuration(260)
        self.a.setEasingCurve(_OUT_CUBIC)
        edit.installEventFilter(self)

    def eventFilter(self, o, e):
        t = e.type()
        if t in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.a.stop()
            self.a.setStartValue(self.edit.maximumWidth())
            self.a.setEndValue(self.wide if t == QEvent.Type.FocusIn else self.narrow)
            self.a.start()
        return False


# =========================================================================== header
class HeaderBanner(QWidget):
    """Floating gradient hero banner with slowly drifting light blobs. Populate `self.lay`."""
    M = 16

    def __init__(self, parent=None, height=112):
        super().__init__(parent)
        self.setFixedHeight(height)
        self._phase = 0.0
        m = self.M
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(m + 24, m - 6 + 4, m + 22, m + 6 + 4)
        self.lay.setSpacing(12)
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)

    def showEvent(self, e): self._timer.start(); super().showEvent(e)
    def hideEvent(self, e): self._timer.stop(); super().hideEvent(e)

    def _tick(self):
        self._phase = (self._phase + 0.004) % 1.0
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self.M
        vr = QRectF(self.rect()).adjusted(m, m - 6, -m, -(m + 6))
        paint_shadow(p, vr, 26, qc(P['hero_shadow'], 0.42), spread=14, dy=8)
        path = QPainterPath()
        path.addRoundedRect(vr, 26, 26)
        p.setClipPath(path)
        g = QLinearGradient(vr.left(), vr.top(), vr.right(), vr.bottom())
        g.setColorAt(0.0, QColor(P['hero_a']))
        g.setColorAt(0.55, QColor(P['hero_b']))
        g.setColorAt(1.0, QColor(P['hero_c']))
        p.fillPath(path, g)
        ph = self._phase * 2 * math.pi
        for fx, fy, rad, off, a in ((0.15, 0.2, 260, 0.0, 70), (0.55, 0.9, 300, 2.1, 48), (0.92, 0.15, 220, 4.2, 60)):
            cx = vr.left() + vr.width() * (fx + 0.05 * math.cos(ph + off))
            cy = vr.top() + vr.height() * (fy + 0.22 * math.sin(ph * 1.3 + off))
            rg = QRadialGradient(QPointF(cx, cy), rad)
            rg.setColorAt(0, QColor(255, 255, 255, a))
            rg.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillRect(vr, QBrush(rg))
        p.setPen(QPen(QColor(255, 255, 255, 30), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for k, rad in enumerate((70, 110, 150)):
            p.drawEllipse(QPointF(vr.left() + 40, vr.bottom() + 20), rad, rad)
        gl = QLinearGradient(0, vr.top(), 0, vr.bottom())
        gl.setColorAt(0, QColor(255, 255, 255, 44))
        gl.setColorAt(0.55, QColor(255, 255, 255, 0))
        p.fillPath(path, gl)


class LogoBadge(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 60)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(2, 2, 56, 56)
        p.setPen(QPen(QColor(255, 255, 255, 120), 1.5))
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor(255, 255, 255, 80))
        g.setColorAt(1, QColor(255, 255, 255, 28))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(r, 18, 18)
        draw_icon(p, 'doc', QRectF(15, 15, 30, 30), '#FFFFFF', 2.0)


# =========================================================================== navigation
class PillNav(QWidget):
    """Segmented navigation with a gradient indicator that glides between tabs."""
    currentChanged = Signal(int)
    M = 14

    def __init__(self, labels, icons=None, parent=None):
        super().__init__(parent)
        self.labels = list(labels)
        self.icons = list(icons) if icons else [None] * len(self.labels)
        self._idx = 0
        self._hover = -1
        self._t = 1.0
        self._from = None
        self._ia = anim(self, 340, QEasingCurve.Type.OutBack)
        self._ia.setStartValue(0.0)
        self._ia.setEndValue(1.0)
        self._ia.valueChanged.connect(self._on_t)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(_font(self.font(), 14, QFont.Weight.DemiBold))
        theme.signals.changed.connect(self.update)

    def _on_t(self, v): self._t = float(v); self.update()

    def _item_widths(self):
        fm = QFontMetrics(self.font())
        return [fm.horizontalAdvance(t) + (26 if ic else 0) + 40 for t, ic in zip(self.labels, self.icons)]

    def sizeHint(self):
        return QSize(int(sum(self._item_widths()) + 2 * self.M + 12), 62)

    def minimumSizeHint(self):
        return self.sizeHint()

    def _rects(self):
        ws = self._item_widths()
        box = self._box()
        x = box.right() - 5 if self.isRightToLeft() else box.left() + 5
        out = []
        for w in ws:
            if self.isRightToLeft():
                out.append(QRectF(x - w, box.top() + 5, w, box.height() - 10))
                x -= w
            else:
                out.append(QRectF(x, box.top() + 5, w, box.height() - 10))
                x += w
        return out

    def _box(self):
        return QRectF(self.M, 4, sum(self._item_widths()) + 10, 50)

    def _ind_rect(self):
        target = self._rects()[self._idx]
        if self._from is None or self._t >= 1.0:
            return target
        f, t = self._from, target
        k = self._t
        return QRectF(f.x() + (t.x() - f.x()) * k, f.y(), f.width() + (t.width() - f.width()) * k, f.height())

    def currentIndex(self): return self._idx

    def setCurrentIndex(self, i, animate=True):
        if i == self._idx or not (0 <= i < len(self.labels)):
            return
        self._from = self._ind_rect()
        self._idx = i
        if animate:
            self._t = 0.0
            self._ia.stop()
            self._ia.start()
        else:
            self._t = 1.0
        self.currentChanged.emit(i)
        self.update()

    def _index_at(self, pos):
        for i, r in enumerate(self._rects()):
            if r.contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, e):
        i = self._index_at(e.position())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, e): self._hover = -1; self.update(); super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        i = self._index_at(e.position())
        if i >= 0:
            self.setCurrentIndex(i)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = self._box()
        paint_shadow(p, box, 25, qc(P['shadow'], P['shadow_alpha'] * 0.8), spread=10, dy=4)
        p.setPen(QPen(QColor(P['border']), 1))
        p.setBrush(QColor(P['surface']))
        p.drawRoundedRect(box, 25, 25)
        ind = self._ind_rect()
        gpath = QPainterPath()
        gpath.addRoundedRect(ind, 20, 20)
        paint_shadow(p, ind, 20, qc(P['primary'], 0.42), spread=7, dy=3)
        g = QLinearGradient(ind.left(), ind.top(), ind.right(), ind.bottom())
        g.setColorAt(0, QColor(P['primary']))
        g.setColorAt(1, QColor(P['accent']))
        p.fillPath(gpath, g)
        gloss = QLinearGradient(0, ind.top(), 0, ind.bottom())
        gloss.setColorAt(0, QColor(255, 255, 255, 50))
        gloss.setColorAt(0.6, QColor(255, 255, 255, 0))
        p.fillPath(gpath, gloss)
        p.setFont(self.font())
        fm = QFontMetrics(self.font())
        for i, r in enumerate(self._rects()):
            overlap = max(0.0, min(r.right(), ind.right()) - max(r.left(), ind.left())) / r.width()
            k = max(0.0, min(1.0, (overlap - 0.35) / 0.3))
            base = mix(P['text_muted'], P['primary_dark'], 1.0 if i == self._hover else 0.0)
            col = mix(base, '#FFFFFF', k)
            ic = self.icons[i]
            tw = fm.horizontalAdvance(self.labels[i])
            iw = 18 if ic else 0
            gap = 8 if ic else 0
            total = iw + gap + tw
            x0 = r.center().x() - total / 2
            rtl = self.isRightToLeft()
            ix = x0 + total - iw if rtl else x0
            tx = x0 if rtl else x0 + iw + gap
            if ic:
                draw_icon(p, ic, QRectF(ix, r.center().y() - 9, 18, 18), col, 2.1)
            p.setPen(col)
            p.drawText(QRectF(tx, r.top(), tw + 4, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.labels[i])


def fade_in(widget, ms=240):
    """يُظهر الودجت بتلاشٍ من الشفافية؛ يُزال التأثير بعد الانتهاء لأن QGraphicsEffect يُبطئ الرسم ويشوّش النص الصغير."""
    fx = QGraphicsOpacityEffect(widget)
    fx.setOpacity(0.0)
    widget.setGraphicsEffect(fx)
    a = QPropertyAnimation(fx, b'opacity', widget)
    a.setDuration(ms)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setEasingCurve(_OUT_CUBIC)
    a.finished.connect(lambda w=widget: QTimer.singleShot(0, lambda: w.setGraphicsEffect(None)))
    a.start()
    return a


class FadeStack(QStackedWidget):
    """QStackedWidget that cross-fades to the incoming page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anim = None

    def set_index_animated(self, i):
        if i == self.currentIndex():
            return
        self.setCurrentIndex(i)
        new = self.currentWidget()
        if new is not None:
            self._anim = fade_in(new, 260)


class FadeTabs(QTabWidget):
    """QTabWidget يظهر محتوى التبويب الجديد بتلاشٍ قصير بدل القفز المفاجئ."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fade = None
        self.currentChanged.connect(self._on_changed)

    def _on_changed(self, i):
        w = self.widget(i)
        if w is not None and self.isVisible():
            self._fade = fade_in(w, 220)


class HoverCard(Card):
    """بطاقة بتأثير تمرير: ظل أعمق، إطار بلون الهوية، وشريط علوي متدرج يتسع، مع أيقونة دائرية متدرجة.
    (لا تتحرك محتوياتها، فلا يختل ترتيب العناصر داخلها.)"""

    def __init__(self, icon, c1, c2, parent=None, padding=10):
        super().__init__(parent, padding=padding)
        self.icon, self.c1, self.c2 = icon, QColor(c1), QColor(c2)
        self._h = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._ha = anim(self, 220)
        self._ha.valueChanged.connect(self._set_h)
        m = self.M
        self.body.setContentsMargins(m + 18, m - 6 + padding + 8, m + 18, m + 6 + padding)

    def _set_h(self, v):
        self._h = float(v)
        self.update()

    def _sync(self):
        """التمرير فوق عنصر ابن (زر) يُرسل Leave للأب؛ نحسم الحالة بموضع المؤشر الفعلي."""
        from PySide6.QtGui import QCursor
        inside = self.isVisible() and self.rect().contains(self.mapFromGlobal(QCursor.pos()))
        _retarget(self._ha, self._h, 1.0 if inside else 0.0)

    def enterEvent(self, e):
        _retarget(self._ha, self._h, 1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        QTimer.singleShot(0, self._sync)
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self._h
        r = self.visible_rect()
        paint_shadow(p, r, 20, qc(P['shadow'], P['shadow_alpha'] * (1.0 + 0.9 * h)), spread=int(14 + 6 * h), dy=6 + 4 * h)
        p.setPen(QPen(mix(P['border'], self.c1, 0.65 * h), 1 + 0.6 * h))
        p.setBrush(QColor(P['surface']))
        p.drawRoundedRect(r, 20, 20)
        clip = QPainterPath()
        clip.addRoundedRect(r, 20, 20)
        p.save()
        p.setClipPath(clip)
        g = QLinearGradient(r.left(), 0, r.right(), 0)
        g.setColorAt(0, self.c1)
        g.setColorAt(1, self.c2)
        p.fillRect(QRectF(r.left(), r.top(), r.width(), 4 + 3 * h), QBrush(g))
        p.restore()
        d = 36 + 3 * h                                          # الأيقونة الدائرية عند الطرف المقابل للعنوان (يسار البطاقة)
        ic = QRectF(r.left() + 16, r.top() + 16, d, d)
        gi = QLinearGradient(ic.topLeft(), ic.bottomRight())
        gi.setColorAt(0, self.c1)
        gi.setColorAt(1, self.c2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(gi))
        p.drawEllipse(ic)
        draw_icon(p, self.icon, ic.adjusted(d * 0.27, d * 0.27, -d * 0.27, -d * 0.27), '#FFFFFF', 2.0)


# =========================================================================== gradient cards
class GradCard(QWidget):
    """Gradient tile. numeric=True -> KPI with count-up number; numeric=False -> big clickable action tile."""
    clicked = Signal()
    M = 14

    def __init__(self, title, icon, c1, c2, numeric=True, subtitle='', clickable=False, parent=None):
        super().__init__(parent)
        self.title, self.icon, self.subtitle = title, icon, subtitle
        self.c1, self.c2 = QColor(c1), QColor(c2)
        self.numeric, self.clickable = numeric, clickable
        self._value = 0
        self._text = None          # عند ضبطه يُعرض بدل العدّاد (للمبالغ)
        self._shown = 0.0
        self._h = 0.0
        self.setFixedHeight(122 if numeric else 112)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._va = anim(self, 800)
        self._va.valueChanged.connect(self._on_shown)
        self._ha = anim(self, 200)
        self._ha.valueChanged.connect(self._on_h)

    def _on_shown(self, v): self._shown = float(v); self.update()
    def _on_h(self, v): self._h = float(v); self.update()

    def set_text(self, text):
        self._text = str(text)
        self.update()

    def set_value(self, v):
        v = int(v)
        if v == self._value and int(round(self._shown)) == v:
            return
        self._value = v
        _retarget(self._va, self._shown, v)

    def replay(self):
        self._shown = 0.0
        _retarget(self._va, 0.0, self._value)

    def enterEvent(self, e): _retarget(self._ha, self._h, 1.0); super().enterEvent(e)
    def leaveEvent(self, e): _retarget(self._ha, self._h, 0.0); super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.clickable and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m, h = self.M, self._h
        vr = QRectF(self.rect()).adjusted(m, m - 4, -m, -(m + 4)).adjusted(-3 * h, -3 * h, 3 * h, 3 * h)
        paint_shadow(p, vr, 22, qc(self.c2, 0.42 + 0.16 * h), spread=12, dy=7 + 3 * h)
        path = QPainterPath()
        path.addRoundedRect(vr, 22, 22)
        p.setClipPath(path)
        g = QLinearGradient(vr.left(), vr.top(), vr.right(), vr.bottom())
        g.setColorAt(0, self.c1)
        g.setColorAt(1, self.c2)
        p.fillPath(path, g)
        rtl = self.isRightToLeft()
        # decorative circles on the trailing side
        cx = vr.left() + 30 if rtl else vr.right() - 30
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawEllipse(QPointF(cx, vr.top() + 6 - 8 * h), 78, 78)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawEllipse(QPointF(cx + (-46 if rtl else 46), vr.bottom() + 18), 62, 62)
        gloss = QLinearGradient(0, vr.top(), 0, vr.bottom())
        gloss.setColorAt(0, QColor(255, 255, 255, 52))
        gloss.setColorAt(0.5, QColor(255, 255, 255, 0))
        p.fillPath(path, gloss)
        # icon badge (trailing)
        bs = 46 if self.numeric else 52
        bx = vr.left() + 18 if rtl else vr.right() - 18 - bs
        badge = QRectF(bx, vr.top() + 16, bs, bs)
        p.setPen(QPen(QColor(255, 255, 255, 70), 1))
        p.setBrush(QColor(255, 255, 255, 52))
        p.drawRoundedRect(badge, 15, 15)
        draw_icon(p, self.icon, badge.adjusted(11, 11, -11, -11), '#FFFFFF', 2.0)
        # text (leading)
        align = Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
        tx = QRectF(vr.left() + 20, 0, vr.width() - 40 - bs - 10, 0)
        if rtl:
            tx.setLeft(vr.left() + 18 + bs + 10)
            tx.setRight(vr.right() - 20)
        else:
            tx.setLeft(vr.left() + 20)
            tx.setRight(vr.right() - 18 - bs - 10)
        if self.numeric:
            p.setPen(QColor(255, 255, 255, 225))
            p.setFont(_font(self.font(), 13, QFont.Weight.DemiBold))
            p.drawText(QRectF(tx.left(), vr.top() + 16, tx.width(), 22), align | Qt.AlignmentFlag.AlignVCenter, self.title)
            p.setPen(QColor('#FFFFFF'))
            shown = self._text if self._text is not None else str(int(round(self._shown)))
            fpx = 38 if self._text is None else (26 if len(shown) <= 12 else 20)
            p.setFont(_font(self.font(), fpx, QFont.Weight.ExtraBold))
            p.drawText(QRectF(tx.left(), vr.top() + 40, tx.width(), 52), align | Qt.AlignmentFlag.AlignVCenter, shown)
        else:
            p.setPen(QColor('#FFFFFF'))
            p.setFont(_font(self.font(), 18, QFont.Weight.Bold))
            p.drawText(QRectF(tx.left(), vr.top() + 18, tx.width(), 30), align | Qt.AlignmentFlag.AlignVCenter, self.title)
            p.setPen(QColor(255, 255, 255, 215))
            p.setFont(_font(self.font(), 12))
            p.drawText(QRectF(tx.left(), vr.top() + 50, tx.width(), 20), align | Qt.AlignmentFlag.AlignVCenter, self.subtitle)
            ax = vr.left() + 18 if rtl else vr.right() - 18 - 30
            arect = QRectF(ax, vr.bottom() - 18 - 30 + 3 * (1 - h), 30, 30)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, int(46 + 50 * h)))
            p.drawEllipse(arect)
            draw_icon(p, 'download', arect.adjusted(7, 7, -7, -7), '#FFFFFF', 2.2)


class DonutChart(QWidget):
    """Animated donut with hover pop-out, centre read-out and legend."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(240)
        self.setMouseTracking(True)
        self.items = []
        self.center_label, self.empty_label = 'الإجمالي', 'لا بيانات'
        self._hover = -1
        self._t = 1.0
        self._ta = anim(self, 1000)
        self._ta.setStartValue(0.0)
        self._ta.setEndValue(1.0)
        self._ta.valueChanged.connect(self._on_t)
        theme.signals.changed.connect(self.update)

    def _on_t(self, v): self._t = float(v); self.update()

    def replay(self):
        self._ta.stop()
        self._t = 0.0
        self._ta.start()

    def set_data(self, items):
        items = [(str(l), int(v), str(c)) for l, v, c in items]
        if items == self.items:
            return
        self.items = items
        self._hover = -1
        self.replay()

    def _geom(self):
        legend_h = 52
        d = max(60.0, min(self.width() - 60.0, self.height() - legend_h - 30.0))
        cx, cy = self.width() / 2, 14 + d / 2 + 8
        return QPointF(cx, cy), d, max(14.0, d * 0.16), legend_h

    def mouseMoveEvent(self, e):
        total = sum(v for _, v, _ in self.items)
        if not total:
            return
        c, d, thick, _ = self._geom()
        dx, dy = e.position().x() - c.x(), e.position().y() - c.y()
        dist = math.hypot(dx, dy)
        idx = -1
        if d / 2 - thick - 6 <= dist <= d / 2 + 10:
            ang = math.degrees(math.atan2(dx, -dy)) % 360
            acc = 0.0
            for i, (_, v, _c) in enumerate(self.items):
                acc += v / total * 360
                if ang <= acc:
                    idx = i if v else -1
                    break
        if idx != self._hover:
            self._hover = idx
            self.update()

    def leaveEvent(self, e): self._hover = -1; self.update(); super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c, d, thick, legend_h = self._geom()
        total = sum(v for _, v, _ in self.items)
        rect = QRectF(c.x() - d / 2, c.y() - d / 2, d, d).adjusted(thick / 2 + 6, thick / 2 + 6, -thick / 2 - 6, -thick / 2 - 6)
        track = QPen(qc(P['border'], 0.9), thick)
        track.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(track)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)
        nonzero = sum(1 for _, v, _c in self.items if v)
        gap = 3.0 if nonzero > 1 else 0.0
        if total:
            visible = self._t * 360.0
            acc = 0.0
            for i, (label, v, color) in enumerate(self.items):
                if not v:
                    continue
                sweep = v / total * 360.0
                draw = max(0.0, min(sweep, visible - acc))
                if draw > 0:
                    pen = QPen(QColor(color), thick + (7 if i == self._hover else 0))
                    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                    p.setPen(pen)
                    p.drawArc(rect, int((90 - acc - gap / 2) * 16), int(-max(0.5, draw - gap) * 16))
                acc += sweep
        # centre read-out
        p.setPen(QColor(P['text']))
        if self._hover >= 0 and total:
            label, v, color = self.items[self._hover]
            p.setPen(QColor(color))
            p.setFont(_font(self.font(), 30, QFont.Weight.ExtraBold))
            p.drawText(QRectF(c.x() - 60, c.y() - 28, 120, 40), Qt.AlignmentFlag.AlignCenter, str(v))
            p.setPen(QColor(P['text_muted']))
            p.setFont(_font(self.font(), 12, QFont.Weight.DemiBold))
            p.drawText(QRectF(c.x() - 60, c.y() + 10, 120, 20), Qt.AlignmentFlag.AlignCenter, label)
        else:
            p.setFont(_font(self.font(), 32, QFont.Weight.ExtraBold))
            p.drawText(QRectF(c.x() - 60, c.y() - 28, 120, 40), Qt.AlignmentFlag.AlignCenter, str(int(round(total * min(1.0, self._t * 1.2)))))
            p.setPen(QColor(P['text_muted']))
            p.setFont(_font(self.font(), 12, QFont.Weight.DemiBold))
            p.drawText(QRectF(c.x() - 60, c.y() + 10, 120, 20), Qt.AlignmentFlag.AlignCenter, self.center_label if total else self.empty_label)
        # legend (2 columns)
        p.setFont(_font(self.font(), 12))
        colw = (self.width() - 24) / 2
        for i, (label, v, color) in enumerate(self.items):
            col, row = i % 2, i // 2
            if self.isRightToLeft():
                x = self.width() - 12 - (col + 1) * colw
            else:
                x = 12 + col * colw
            y = self.height() - legend_h + 4 + row * 24
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            dot_x = x + colw - 14 if self.isRightToLeft() else x + 8
            p.drawEllipse(QPointF(dot_x, y + 10), 5, 5)
            p.setPen(QColor(P['text']) if i != self._hover else QColor(color))
            p.drawText(QRectF(x + (8 if self.isRightToLeft() else 20), y, colw - 30, 20),
                       (Qt.AlignmentFlag.AlignRight if self.isRightToLeft() else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter,
                       f'{label}  {v}')


# =========================================================================== table
class HoverTable(QTableWidget):
    """Borderless table with animated row hover and an empty-state message."""

    def __init__(self, rows=0, cols=0, parent=None):
        super().__init__(rows, cols, parent)
        self.setObjectName('hoverTable')
        self.hover_row, self.hover_t = -1, 0.0
        self._ha = anim(self, 150)
        self._ha.setStartValue(0.0)
        self._ha.setEndValue(1.0)
        self._ha.valueChanged.connect(self._tick)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.viewport().installEventFilter(self)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(50)
        hh = self.horizontalHeader()
        hh.setStretchLastSection(True)
        hh.setHighlightSections(False)
        hh.setMinimumSectionSize(70)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignVCenter)
        self._empty = QLabel('', self.viewport())
        self._empty.setObjectName('empty')
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._empty.hide()

    def set_empty_text(self, text):
        self._empty.setText(text)
        self.refresh_empty()

    def refresh_empty(self):
        self._empty.setGeometry(self.viewport().rect())
        self._empty.setVisible(self.rowCount() == 0 and bool(self._empty.text()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._empty.setGeometry(self.viewport().rect())

    def fit_columns(self, mins=None):
        self.resizeColumnsToContents()
        for c, w in (mins or {}).items():
            if self.columnWidth(c) < w:
                self.setColumnWidth(c, w)
        self.refresh_empty()

    def eventFilter(self, obj, ev):
        if obj is self.viewport():
            t = ev.type()
            if t == QEvent.Type.MouseMove:
                self._set_hover(self.rowAt(int(ev.position().y())))
            elif t == QEvent.Type.Leave:
                self._set_hover(-1)
        return super().eventFilter(obj, ev)

    def _set_hover(self, r):
        if r == self.hover_row:
            return
        old, self.hover_row = self.hover_row, r
        self._ha.stop()
        self.hover_t = 0.0
        self._repaint_row(old)
        if r >= 0:
            self._ha.start()
        self._repaint_row(r)

    def _tick(self, v):
        self.hover_t = float(v)
        self._repaint_row(self.hover_row)

    def _repaint_row(self, r):
        if 0 <= r < self.rowCount():
            self.viewport().update(0, self.rowViewportPosition(r), self.viewport().width(), self.rowHeight(r))


class DocDelegate(QStyledItemDelegate):
    """يرسم صفوف الوثائق: خلفيات خفيفة، صور رمزية للمشاريع، شارات حالة. (مأخوذ من TaskDelegate في Workflow)
    `kinds` maps column -> 'text' | 'title' | 'muted' | 'person' | 'pill' | 'priority'."""

    def __init__(self, table, kinds):
        super().__init__(table)
        self.table, self.kinds = table, kinds

    def sizeHint(self, option, index):
        kind = self.kinds.get(index.column(), 'text')
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or '')
        f = QFont(option.font)
        if kind == 'title':
            f.setWeight(QFont.Weight.DemiBold)
        w = QFontMetrics(f).horizontalAdvance(text)
        extra = {'text': 30, 'muted': 30, 'title': 34, 'person': 30 + 38, 'pill': 28 + 26}.get(kind, 30)
        if kind == 'priority':
            return QSize(124, 50)
        return QSize(w + extra, 50)

    def paint(self, p, option, index):
        kind = self.kinds.get(index.column(), 'text')
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        rect = QRectF(opt.rect)
        row, col = index.row(), index.column()
        state = index.data(ROLE_STATE) or 'scheduled'
        rtl = opt.direction == Qt.LayoutDirection.RightToLeft
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # ---- row background
        if row % 2:
            p.fillRect(rect, qc(P['surface_alt'], 0.55))
        if state == 'late':
            p.fillRect(rect, qc(P['danger'], 0.10))
        elif state == 'done':
            p.fillRect(rect, qc(P['success'], 0.08))
        if row == self.table.hover_row and not selected:
            p.fillRect(rect, qc(P['primary'], 0.10 * max(0.25, self.table.hover_t)))
        if selected:
            p.fillRect(rect, qc(P['primary'], 0.17))
            if col == 0:
                bar = QRectF(rect.right() - 4 if rtl else rect.left(), rect.top() + 7, 4, rect.height() - 14)
                g = QLinearGradient(bar.topLeft(), bar.bottomLeft())
                g.setColorAt(0, QColor(P['primary']))
                g.setColorAt(1, QColor(P['accent']))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(g))
                p.drawRoundedRect(bar, 2, 2)
        else:
            p.setPen(QPen(qc(P['border'], 0.7), 1))
            p.drawLine(QPointF(rect.left(), rect.bottom() - 0.5), QPointF(rect.right(), rect.bottom() - 0.5))
        inner = rect.adjusted(14, 0, -14, 0)
        dim = state in ('done', 'cancel', 'archived')
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or '')
        align = opt.displayAlignment | Qt.AlignmentFlag.AlignVCenter

        def lead(offset, width):
            return inner.right() - offset - width if rtl else inner.left() + offset

        if kind == 'pill':
            fg, bg, dot = theme.status_colors(index.data(ROLE_PILL) or 'scheduled')
            f = _font(opt.font, 12, QFont.Weight.DemiBold)
            p.setFont(f)
            tw = QFontMetrics(f).horizontalAdvance(text)
            pw = tw + 36
            pr = QRectF(lead(0, pw), rect.center().y() - 13, pw, 26)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(pr, 13, 13)
            p.setBrush(dot)
            dx = pr.right() - 13 if rtl else pr.left() + 13
            p.drawEllipse(QPointF(dx, pr.center().y()), 3.5, 3.5)
            p.setPen(fg)
            tr = QRectF(pr.left() + (10 if rtl else 22), pr.top(), pr.width() - 32, pr.height())
            p.drawText(tr, Qt.AlignmentFlag.AlignCenter, text)
        elif kind == 'priority':
            v = int(index.data(ROLE_PRIO) or 1)
            c1, c2 = theme.priority_colors(v)
            bw = 62.0
            bx = lead(0, bw)
            track = QRectF(bx, rect.center().y() - 4, bw, 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qc(P['border_strong'], 0.55))
            p.drawRoundedRect(track, 4, 4)
            fill = QRectF(track)
            fill.setWidth(bw * v / 10)
            if rtl:
                fill.moveRight(track.right())
            g = QLinearGradient(fill.left(), 0, fill.right(), 0)
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.setBrush(QBrush(g))
            p.drawRoundedRect(fill, 4, 4)
            p.setPen(c2)
            p.setFont(_font(opt.font, 13, QFont.Weight.Bold))
            p.drawText(QRectF(lead(bw + 8, 26), rect.top(), 26, rect.height()), Qt.AlignmentFlag.AlignCenter, str(v))
        elif kind == 'person':
            c1, c2 = theme.avatar_gradient(text)
            d = 30.0
            ar = QRectF(lead(0, d), rect.center().y() - d / 2, d, d)
            g = QLinearGradient(ar.topLeft(), ar.bottomRight())
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(ar)
            p.setPen(QColor('#FFFFFF'))
            p.setFont(_font(opt.font, 14, QFont.Weight.Bold))
            p.drawText(ar, Qt.AlignmentFlag.AlignCenter, (text.strip()[:1] or '?').upper())
            f = _font(opt.font, 13, QFont.Weight.Medium)
            p.setFont(f)
            p.setPen(QColor(P['text_muted'] if dim else P['text']))
            tr = QRectF(inner.left() + (0 if rtl else d + 10), rect.top(), inner.width() - d - 10, rect.height())
            if rtl:
                tr.setRight(inner.right() - d - 10)
            p.drawText(tr, align, QFontMetrics(f).elidedText(text, Qt.TextElideMode.ElideRight, int(tr.width())))
        else:
            f = QFont(opt.font)
            f.setPixelSize(13)
            if kind == 'title':
                f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            color = P['text_muted'] if (dim or kind == 'muted') else P['text']
            p.setPen(QColor(color))
            p.drawText(inner, align, QFontMetrics(f).elidedText(text, Qt.TextElideMode.ElideRight, int(inner.width())))
        p.restore()


# =========================================================================== toast
class Toast(QWidget):
    """Slide-up notification pill, drawn manually (gradient + shadow)."""
    M = 18
    KINDS = {'success': ('#16A34A', '#2DB87A', 'check_circle'), 'info': ('#0D9488', '#14B8A6', 'check_circle'),
             'warn': ('#F59E0B', '#F97316', 'alert'), 'error': ('#E11D48', '#FB7185', 'alert')}

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._text, self._kind = '', 'success'
        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)
        self._oa = QPropertyAnimation(self._fx, b'opacity', self)
        self._pa = QPropertyAnimation(self, b'pos', self)
        self._oa.finished.connect(self._after)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._out)
        self.hide()

    def show_message(self, text, kind='success'):
        self._text, self._kind = text, kind if kind in self.KINDS else 'info'
        f = _font(self.font(), 14, QFont.Weight.DemiBold)
        w = QFontMetrics(f).horizontalAdvance(text) + 96 + 2 * self.M
        h = 56 + 2 * self.M
        self.resize(w, h)
        pw, ph = self.parentWidget().width(), self.parentWidget().height()
        x, y = (pw - w) // 2, ph - h - 22
        self._timer.stop()
        self._oa.stop()
        self._pa.stop()
        self.move(x, y + 20)
        self.show()
        self.raise_()
        self.update()
        self._oa.setDuration(220)
        self._oa.setStartValue(self._fx.opacity())
        self._oa.setEndValue(1.0)
        self._pa.setDuration(320)
        self._pa.setEasingCurve(QEasingCurve.Type.OutBack)
        self._pa.setStartValue(self.pos())
        self._pa.setEndValue(QPoint(x, y))
        self._oa.start()
        self._pa.start()
        self._timer.start(2800)

    def _out(self):
        self._oa.stop()
        self._oa.setDuration(320)
        self._oa.setStartValue(self._fx.opacity())
        self._oa.setEndValue(0.0)
        self._oa.start()

    def _after(self):
        if self._fx.opacity() < 0.01:
            self.hide()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c1, c2, icon = self.KINDS[self._kind]
        vr = QRectF(self.rect()).adjusted(self.M, self.M, -self.M, -self.M)
        paint_shadow(p, vr, vr.height() / 2, qc(c2, 0.45), spread=14, dy=6)
        path = QPainterPath()
        path.addRoundedRect(vr, vr.height() / 2, vr.height() / 2)
        g = QLinearGradient(vr.left(), 0, vr.right(), 0)
        g.setColorAt(0, QColor(c1))
        g.setColorAt(1, QColor(c2))
        p.fillPath(path, g)
        rtl = self.isRightToLeft()
        ic = QRectF((vr.right() - 14 - 30) if rtl else (vr.left() + 14), vr.center().y() - 15, 30, 30)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawEllipse(ic)
        draw_icon(p, icon, ic.adjusted(6, 6, -6, -6), '#FFFFFF', 2.2)
        tr = QRectF(vr.left() + (22 if rtl else 56), vr.top(), vr.width() - 78, vr.height())
        p.setPen(QColor('#FFFFFF'))
        p.setFont(_font(self.font(), 14, QFont.Weight.DemiBold))
        p.drawText(tr, Qt.AlignmentFlag.AlignCenter, self._text)


# =========================================================================== dialogs
class DialogHeader(QWidget):
    def __init__(self, title, subtitle='', icon='doc', parent=None):
        super().__init__(parent)
        self.title, self.subtitle, self.icon = title, subtitle, icon
        self.setFixedHeight(92)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor(P['hero_a']))
        g.setColorAt(0.6, QColor(P['hero_b']))
        g.setColorAt(1, QColor(P['hero_c']))
        p.fillRect(r, g)
        p.setPen(QPen(QColor(255, 255, 255, 34), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        rtl = self.isRightToLeft()
        ex = r.left() + 30 if rtl else r.right() - 30
        for rad in (60, 100, 140):
            p.drawEllipse(QPointF(ex, r.bottom() + 10), rad, rad)
        gl = QLinearGradient(0, 0, 0, r.height())
        gl.setColorAt(0, QColor(255, 255, 255, 40))
        gl.setColorAt(0.6, QColor(255, 255, 255, 0))
        p.fillRect(r, gl)
        bx = r.right() - 24 - 52 if rtl else r.left() + 24
        badge = QRectF(bx, r.center().y() - 26, 52, 52)
        p.setPen(QPen(QColor(255, 255, 255, 110), 1.2))
        p.setBrush(QColor(255, 255, 255, 52))
        p.drawRoundedRect(badge, 17, 17)
        draw_icon(p, self.icon, badge.adjusted(13, 13, -13, -13), '#FFFFFF', 2.0)
        align = Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
        tx = QRectF(r.left() + 24, 0, r.width() - 48 - 52 - 14, 0)
        if rtl:
            tx.moveLeft(r.left() + 24)
        else:
            tx.moveLeft(r.left() + 24 + 52 + 14)
        p.setPen(QColor('#FFFFFF'))
        p.setFont(_font(self.font(), 20, QFont.Weight.ExtraBold))
        p.drawText(QRectF(tx.left(), r.center().y() - 28, tx.width(), 32), align | Qt.AlignmentFlag.AlignVCenter, self.title)
        if self.subtitle:
            p.setPen(QColor(255, 255, 255, 215))
            p.setFont(_font(self.font(), 12))
            p.drawText(QRectF(tx.left(), r.center().y() + 4, tx.width(), 22), align | Qt.AlignmentFlag.AlignVCenter, self.subtitle)


class FancyDialog(QDialog):
    """Dialog shell: gradient title strip, content area (`self.cl`), fade-in on first show."""

    def __init__(self, title, subtitle='', icon='doc', parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(DialogHeader(title, subtitle, icon))
        self.content = QWidget()
        self.cl = QVBoxLayout(self.content)
        self.cl.setContentsMargins(26, 22, 26, 22)
        self.cl.setSpacing(14)
        root.addWidget(self.content)
        self._faded = False
        self._fade = None

    def showEvent(self, e):
        super().showEvent(e)
        if not self._faded:
            self._faded = True
            self.setWindowOpacity(0.0)
            a = QPropertyAnimation(self, b'windowOpacity', self)
            a.setDuration(220)
            a.setStartValue(0.0)
            a.setEndValue(1.0)
            a.setEasingCurve(_OUT_CUBIC)
            self._fade = a
            a.start()


# =========================================================================== message helpers
def _box(parent, icon, title, text, buttons):
    box = QMessageBox(icon, title, text, QMessageBox.StandardButton.NoButton, parent)
    roles = {'accept': QMessageBox.ButtonRole.AcceptRole, 'reject': QMessageBox.ButtonRole.RejectRole,
             'destructive': QMessageBox.ButtonRole.DestructiveRole}
    made = []
    for label, role in buttons:
        b = box.addButton(label, roles[role])
        if role == 'reject':
            b.setProperty('secondary', True)
        elif role == 'destructive':
            b.setProperty('danger', True)
        made.append(b)
    for b, (_, role) in zip(made, buttons):
        if role == 'reject':
            box.setDefaultButton(b)          # Enter لا يؤكد عملية خطرة: الافتراضي هو «إلغاء»
            break
    box.exec()
    clicked = box.clickedButton()
    return made.index(clicked) if clicked in made else -1


def info(parent, title, text):
    _box(parent, QMessageBox.Icon.Information, title, text, [('حسنًا', 'accept')])


def warn(parent, title, text):
    _box(parent, QMessageBox.Icon.Warning, title, text, [('حسنًا', 'accept')])


def error(parent, title, text):
    _box(parent, QMessageBox.Icon.Critical, title, text, [('إغلاق', 'accept')])


def ask(parent, title, text, yes='نعم', no='إلغاء', danger=False) -> bool:
    return _box(parent, QMessageBox.Icon.Question, title, text,
                [(yes, 'destructive' if danger else 'accept'), (no, 'reject')]) == 0


def ask_choice(parent, title, text, buttons) -> int:
    """buttons: [(label, 'accept'|'destructive'|'reject'), ...] -> index of clicked button or -1."""
    return _box(parent, QMessageBox.Icon.Question, title, text, buttons)
