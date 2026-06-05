import os
import io
import numpy as np
import pandas as pd
import logging
from pmgen.system.wrappers import safe_slot
from PyQt6.QtCore import Qt, QAbstractTableModel, QStandardPaths, QModelIndex
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QTableView, QFileDialog, QHeaderView, QApplication, QMessageBox
)

from .components import CustomMessageBox
from .icons import set_themed_icon
from .theme import SPACING_MD, SPACING_SM
from .widgets import configure_table_view, make_card


def get_cache_path():
    """Returns the standardized path to the inventory CSV."""
    base_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
    return os.path.join(base_dir, "inventory_cache.csv")

def load_inventory_cache() -> pd.DataFrame:
    """
    Loads the inventory dataframe from disk. 
    Used by both the UI and the Rules Engine.
    """
    path = get_cache_path()
    if not os.path.exists(path):
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(path)
        # Ensure numeric types for calculation
        if "Quantity" in df.columns:
            df["Quantity"] = pd.to_numeric(df["Quantity"], errors='coerce').fillna(0)
        
        # Clean up string columns for matching
        if "Part Number" in df.columns:
            df["Part Number"] = df["Part Number"].astype(str).str.strip().str.upper()
        if "Unit Name" in df.columns:
            df["Unit Name"] = df["Unit Name"].astype(str).str.strip().str.upper()
            
        return df
    except Exception as e:
        print(f"Error loading inventory cache: {e}")
        return pd.DataFrame()

class InventoryModel(QAbstractTableModel):
    """
    A custom model to display the Pandas DataFrame in a QTableView.
    Now supports editing, row deletion, and adding rows.
    """
    def __init__(self, data=None):
        super().__init__()
        self._df = data if data is not None else pd.DataFrame()
        # Define default columns in case the app starts empty
        self.default_columns = ['Part Number', 'Unit Name', 'Quantity', 'Unit Cost', 'Total Cost']

    def rowCount(self, parent=None):
        return self._df.shape[0]

    def columnCount(self, parent=None):
        return self._df.shape[1]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid():
            if role == Qt.ItemDataRole.DisplayRole or role == Qt.ItemDataRole.EditRole:
                # Handle empty dataframe edge case
                if self._df.empty:
                    return None
                
                val = self._df.iloc[index.row(), index.column()]
                
                # If editing, return raw number (no formatting)
                if role == Qt.ItemDataRole.EditRole:
                    return str(val)

                # Format currency columns for display
                col_name = self._df.columns[index.column()]
                if isinstance(val, (float, int)) and ("Cost" in col_name):
                    return f"${val:,.2f}"
                return str(val)
        return None

    def headerData(self, section, orientation, role):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                if self._df.empty and section < len(self.default_columns):
                    return self.default_columns[section]
                return self._df.columns[section]
            if orientation == Qt.Orientation.Vertical:
                return str(section + 1)
        return None

    def flags(self, index):
        """
        Determines if a cell is editable.
        """
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        base_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        
        # Check which column this is
        col_name = self._df.columns[index.column()]

        # Prevent editing of "Total Cost" (Calculated field)
        if col_name not in ["Total Cost"]:
            return base_flags | Qt.ItemFlag.ItemIsEditable

        return base_flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        """
        Saves user input to the DataFrame and recalculates math.
        """
        if index.isValid() and role == Qt.ItemDataRole.EditRole:
            row = index.row()
            col = index.column()
            col_name = self._df.columns[col]

            # 1. Clean the input
            clean_val = value
            if isinstance(value, str):
                clean_val = value.replace('$', '').replace(',', '').strip()

            # 2. Convert data types based on column
            try:
                if col_name in ["Quantity"]:
                    self._df.iloc[row, col] = float(clean_val)
                elif "Cost" in col_name:
                    self._df.iloc[row, col] = float(clean_val)
                else:
                    self._df.iloc[row, col] = str(clean_val)
            except ValueError:
                return False

            # 3. Recalculate Total Cost
            if col_name in ["Quantity", "Unit Cost"]:
                try:
                    qty = float(self._df.iloc[row, self._df.columns.get_loc("Quantity")])
                    cost = float(self._df.iloc[row, self._df.columns.get_loc("Unit Cost")])
                    
                    if "Total Cost" in self._df.columns:
                        ext_idx = self._df.columns.get_loc("Total Cost")
                        new_ext = qty * cost
                        self._df.iloc[row, ext_idx] = new_ext
                        
                        ext_model_idx = self.index(row, ext_idx)
                        self.dataChanged.emit(ext_model_idx, ext_model_idx, [Qt.ItemDataRole.DisplayRole])
                except Exception:
                    pass 

            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])
            return True
            
        return False

    def remove_rows(self, rows_to_delete):
        """
        Removes rows from the dataframe by index list.
        """
        if not rows_to_delete:
            return

        self.beginResetModel()
        # Drop rows by index
        self._df.drop(self._df.index[rows_to_delete], inplace=True)
        # Reset index so 0..N is continuous again
        self._df.reset_index(drop=True, inplace=True)
        self.endResetModel()

    def add_row(self):
        """
        Adds a new blank row to the bottom of the DataFrame.
        """
        # If the dataframe is empty, initialize it with default columns
        if self._df.empty:
            self._df = pd.DataFrame(columns=self.default_columns)
            # Notify view that columns have changed (headers appear)
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self.default_columns)-1)

        # Create a default row dictionary
        new_row_data = {}
        for col in self._df.columns:
            if "Quantity" in col:
                new_row_data[col] = 0.0
            elif "Cost" in col:
                new_row_data[col] = 0.0
            else:
                new_row_data[col] = "New Item" if col == "Part Number" else ""

        # Calculate insertion index
        idx = len(self._df)
        
        # Notify View we are adding 1 row
        self.beginInsertRows(QModelIndex(), idx, idx)
        
        # Create small DF for the new row and append it
        new_row_df = pd.DataFrame([new_row_data])
        
        # Use concat as append is deprecated in newer pandas versions
        self._df = pd.concat([self._df, new_row_df], ignore_index=True)
        
        self.endInsertRows()

    def update_data(self, df):
        self.beginResetModel()
        self._df = df
        self.endResetModel()

    def get_dataframe(self):
        return self._df


class InventoryTab(QWidget):
    """
    The widget that lives inside the 'Tools' tab.
    Handles loading, cleaning, displaying, persisting, and deleting inventory items.
    """
    def __init__(self, parent=None, icon_dir=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(SPACING_MD, SPACING_MD, SPACING_MD, SPACING_MD)
        self._layout.setSpacing(SPACING_MD)
        self.icon_dir = icon_dir

        toolbar = make_card(self, "InventoryToolbar")
        top_bar = QHBoxLayout(toolbar)
        top_bar.setContentsMargins(SPACING_MD, SPACING_SM, SPACING_MD, SPACING_SM)
        top_bar.setSpacing(SPACING_SM)
        
        self.btn_load = QPushButton("Import")
        self.btn_load.setProperty("class", "primary")
        self.btn_load.setToolTip("Import Inventory CSV")
        set_themed_icon(self.btn_load, "import", self.icon_dir, role="primary")
        self.btn_load.clicked.connect(self._load_csv)
        self.btn_load.setFixedHeight(32)

        self.btn_add = QPushButton("Add Item")
        self.btn_add.setProperty("class", "secondary")
        self.btn_add.setToolTip("Add a new empty row")
        set_themed_icon(self.btn_add, "add", self.icon_dir)
        self.btn_add.clicked.connect(self._add_new_row)
        self.btn_add.setFixedHeight(32)

        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setProperty("class", "danger")
        self.btn_delete.setToolTip("Delete selected rows")
        set_themed_icon(self.btn_delete, "delete", self.icon_dir, role="danger")
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_delete.setFixedHeight(32)
        
        self.lbl_status = QLabel("No inventory loaded")
        self.lbl_status.setProperty("class", "muted")

        self.lbl_total = QLabel("Total Value: $0.00")
        self.lbl_total.setProperty("class", "success-label")
        
        top_bar.addWidget(self.btn_load)
        top_bar.addWidget(self.btn_add)
        top_bar.addWidget(self.btn_delete)
        top_bar.addWidget(self.lbl_status)
        top_bar.addStretch(1)
        top_bar.addWidget(self.lbl_total)

        self.table_view = QTableView()
        self.model = InventoryModel()
        self.table_view.setModel(self.model)
        
        # Connect data changes (Edit)
        self.model.dataChanged.connect(self._recalculate_total_label)
        self.model.dataChanged.connect(self._auto_save_to_cache)

        # Connect model reset (Load new file, Delete rows, Add rows)
        self.model.modelReset.connect(self._recalculate_total_label)
        self.model.modelReset.connect(self._auto_save_to_cache)
        self.model.rowsInserted.connect(self._auto_save_to_cache)

        configure_table_view(self.table_view, compact=False)
        self.table_view.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        self._layout.addWidget(toolbar)
        self._layout.addWidget(self.table_view)

        self._load_from_cache()

    @safe_slot
    def _add_new_row(self, *args):
        """
        Adds a row to the model and scrolls to it.
        """
        self.model.add_row()
        self.lbl_status.setText("Added new item")
        # Scroll to bottom
        self.table_view.scrollToBottom()

    @safe_slot
    def _delete_selected(self, *args):
        """
        Gets the selected rows from the view and asks the model to remove them.
        """
        selection = self.table_view.selectionModel().selectedRows()
        if not selection:
            CustomMessageBox.info(self, "No Selection", "Please select row(s) to delete.", "")
            return

        # Ask for confirmation
        count = len(selection)
        confirm = CustomMessageBox.confirm(
            self, 
            "Delete Rows", 
            f"Are you sure you want to delete {count} row(s)?",
            self.icon_dir
        )
        
        if confirm == "ok":
            # Get the row indices
            rows_to_delete = [index.row() for index in selection]
            # Remove them (model handles sort/reset)
            self.model.remove_rows(rows_to_delete)
            self.lbl_status.setText(f"Deleted {count} item(s)")

    def _get_cache_path(self):
        base_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
        return os.path.join(base_dir, "inventory_cache.csv")

    def _auto_save_to_cache(self):
        df = self.model.get_dataframe()
        if df is not None:
            try:
                path = self._get_cache_path()
                df.to_csv(path, index=False)
            except Exception as e:
                print(f"Failed to autosave inventory: {e}")

    def _load_from_cache(self):
        path = self._get_cache_path()
        if os.path.exists(path):
            try:
                df = pd.read_csv(path)
                # Ensure numeric types
                if "Quantity" in df.columns:
                    df["Quantity"] = pd.to_numeric(df["Quantity"], errors='coerce').fillna(0)
                if "Unit Cost" in df.columns:
                    df["Unit Cost"] = pd.to_numeric(df["Unit Cost"], errors='coerce').fillna(0.0)
                if "Total Cost" in df.columns:
                    df["Total Cost"] = pd.to_numeric(df["Total Cost"], errors='coerce').fillna(0.0)

                self.model.update_data(df)
                self.lbl_status.setText("Restored previous session")
                self.table_view.resizeColumnsToContents()
            except Exception:
                pass

    def _recalculate_total_label(self):
        df = self.model.get_dataframe()
        if df is not None and not df.empty and "Total Cost" in df.columns:
            total_val = df['Total Cost'].sum()
            self.lbl_total.setText(f"Total Value: ${total_val:,.2f}")
        else:
            self.lbl_total.setText("Total Value: $0.00")

    @safe_slot
    def _load_csv(self, *args):
        path, _ = QFileDialog.getOpenFileName(self, "Open Inventory CSV", "", "CSV Files (*.csv);;All Files (*.*)")
        if not path:
            return

        try:
            self.lbl_status.setText("Processing...")
            QApplication.processEvents()
            clean_df = self._process_messy_csv(path)
            
            if clean_df is not None and not clean_df.empty:
                self.model.update_data(clean_df)
                self.lbl_status.setText(f"Loaded: {os.path.basename(path)}")
                self.table_view.resizeColumnsToContents()
                self.table_view.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
                self.table_view.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            else:
                self.lbl_status.setText("Error: No data found")
                
        except Exception as e:
            CustomMessageBox.warn(self, "Import Failed", f"Could not process file:\n{str(e)}", "")
            self.lbl_status.setText("Import Failed")

    def _process_messy_csv(self, file_path):
        # 1. Read file and filter lines
        valid_lines = []
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.strip().startswith('","'):
                    valid_lines.append(line)

        if not valid_lines:
            raise ValueError("File format not recognized (no valid data rows).")

        clean_csv_string = "\n".join(valid_lines)
        df = pd.read_csv(io.StringIO(clean_csv_string), header=None)
        
        clean_df = pd.DataFrame()
        is_layout_a = df[6].notnull()

        clean_df['Part Number']   = np.where(is_layout_a, df[6], df[11])
        clean_df['Unit Name']   = np.where(is_layout_a, df[7], df[12])
        clean_df['Quantity']      = np.where(is_layout_a, df[8], df[13])
        clean_df['Unit Cost']     = np.where(is_layout_a, df[9], df[14])
        
        def clean_money(val):
            if isinstance(val, str):
                val = val.replace('$', '').replace(',', '')
                try: return float(val)
                except: return 0.0
            return val if isinstance(val, (int, float)) else 0.0

        clean_df['Unit Cost'] = clean_df['Unit Cost'].apply(clean_money)
        clean_df['Quantity'] = pd.to_numeric(clean_df['Quantity'], errors='coerce').fillna(0)
        clean_df['Total Cost'] = clean_df['Quantity'] * clean_df['Unit Cost']

        clean_df = clean_df.dropna(subset=['Part Number'])
        return clean_df
