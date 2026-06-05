from PyQt6.QtWidgets import QAbstractItemView, QTableView

from pmgen.ui.widgets import configure_table_view


def test_configure_table_view_compact(qtbot):
    view = QTableView()
    qtbot.addWidget(view)

    configure_table_view(view, compact=True)

    assert not view.verticalHeader().isVisible()
    assert view.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert not view.showGrid()
    assert view.alternatingRowColors()
    assert view.verticalHeader().defaultSectionSize() == 32
