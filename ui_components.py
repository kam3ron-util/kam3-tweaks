"""Small, code-native UI primitives; no system settings or persistence."""
from PySide6.QtCore import QSize, QEvent, QTimer, Signal
from PySide6.QtWidgets import QWidget, QGridLayout, QSizePolicy, QLabel


class ResponsiveGrid(QWidget):
    """Reflow cards using available space and the user's font size."""
    def __init__(self, minimum_card_width=310, maximum_columns=2, parent=None):
        super().__init__(parent)
        self.minimum_card_width = minimum_card_width
        self.maximum_columns = maximum_columns
        self.columns = 0
        self.cards = []
        self._reflow_pending = False
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def add_card(self, card):
        card.setMinimumWidth(0)
        policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(bool(card.layout() and card.layout().hasHeightForWidth()))
        card.setSizePolicy(policy)
        self.cards.append(card)
        self.reflow(force=True)

    def minimumSizeHint(self):
        return QSize(0, self.grid.minimumSize().height())

    def reflow(self, force=False):
        # Font scaling must be allowed to reduce column count, not truncate text.
        minimum = max(self.minimum_card_width, self.fontMetrics().horizontalAdvance('M') * 27)
        columns = max(1, min(self.maximum_columns, (self.width() + 12) // (minimum + 12)))
        changed = columns != self.columns or force
        if changed:
            while self.grid.count():
                self.grid.takeAt(0)
            for column in range(self.maximum_columns):
                self.grid.setColumnStretch(column, 1 if column < columns else 0)
            for index, card in enumerate(self.cards):
                self.grid.addWidget(card, index // columns, index % columns)
            self.columns = columns
        card_width = max(1, (self.width() - 12 * (columns - 1)) // columns)
        for card in self.cards:
            # Ignoring horizontal minimum hints allows long labels to wrap. Qt's
            # grid can then under-allocate vertical space; retain the wrapped height.
            required = card.heightForWidth(card_width)
            if required >= 0 and card.minimumHeight() != required:
                card.setMinimumHeight(required)
                changed = True
        if changed:
            self.updateGeometry()

    def _deferred_reflow(self):
        self._reflow_pending = False
        self.reflow()

    def event(self, event):
        if (event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.Show)
                and hasattr(self, '_reflow_pending') and not self._reflow_pending):
            # Hidden stacked pages receive their final font/width hints on show.
            self._reflow_pending = True
            QTimer.singleShot(0, self._deferred_reflow)
        return super().event(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, 'cards'):
            self.reflow(force=True)


class StatusLabel(QLabel):
    text_changed = Signal(str)

    def setText(self, text):
        super().setText(text)
        self.setAccessibleDescription(text)
        self.text_changed.emit(text)
