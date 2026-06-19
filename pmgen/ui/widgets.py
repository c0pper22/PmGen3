"""Reusable low-level widgets and view configuration helpers for UI pages."""

from __future__ import annotations

from PyQt6.QtWidgets import QAbstractItemView, QTableView, QWidget


def make_card(parent: QWidget | None = None, object_name: str = "Card") -> QWidget:
    card = QWidget(parent)
    card.setObjectName(object_name)
    card.setProperty("class", "card")
    return card


def configure_table_view(view: QTableView, compact: bool = False) -> None:
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    vh = view.verticalHeader()
    if vh is not None:
        vh.setVisible(False)
        vh.setDefaultSectionSize(32 if compact else 40)
    view.setShowGrid(False)
    view.setSortingEnabled(True)
