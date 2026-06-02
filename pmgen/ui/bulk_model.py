from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PyQt6.QtGui import QColor, QBrush

class BulkQueueModel(QAbstractTableModel):
    def __init__(self, custom_col_name="", parent=None):
        super().__init__(parent)
        self.has_custom = bool(custom_col_name)
        
        # Build headers dynamically
        self.headers = ["#", "Serial", "Model", "Customer", "Machine State", "Unpack Date"]
        if self.has_custom:
            self.headers.append(custom_col_name)
        self.headers.extend(["Status", "Result"])
        
        # Internal Data Structure is strictly: 
        # [Serial(0), Model(1), Customer(2), MachineState(3), UnpackDate(4), Custom08(5), Status(6), Result(7)]
        self._data = []

        self.visual_to_internal = { 1: 0, 2: 1, 3: 2, 4: 3, 5: 4 }
        
        if self.has_custom:
            self.visual_to_internal.update({ 6: 5, 7: 6, 8: 7 })
            self.status_col = 7
            self.result_col = 8
        else:
            self.visual_to_internal.update({ 6: 6, 7: 7 })
            self.status_col = 6
            self.result_col = 7

    def rowCount(self, parent=None):
        return len(self._data)

    def columnCount(self, parent=None):
        return len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        
        row = index.row()
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return str(row + 1)
            
            if col in self.visual_to_internal:
                return self._data[row][self.visual_to_internal[col]]
        
        if role == Qt.ItemDataRole.ForegroundRole and col == self.status_col:
            status = self._data[row][6]
            if status == "Done": return QBrush(QColor("#40ed68"))       # Green
            if status == "Failed": return QBrush(QColor("#f7768e"))     # Pink/Red
            if status == "Processing": return QBrush(QColor("#7aa2f7")) # Blue
            if status == "Queued": return QBrush(QColor("#bbbbbb"))     # Grey
            if status == "Filtered": return QBrush(QColor("#d83d37"))   # Red/Orange

        return None

    def headerData(self, section, orientation, role):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None

    def sort(self, column, order):
        if column == 0:
            return
        
        internal_idx = self.visual_to_internal.get(column)
        if internal_idx is None:
            return

        self.layoutAboutToBeChanged.emit()
        reverse = (order == Qt.SortOrder.DescendingOrder)

        def status_priority(val):
            if val == "Done": return 0
            if val == "Failed": return 1
            if val == "Filtered": return 2
            if val == "Queued": return 3
            return 4

        def percentage_value(val_str):
            try:
                return float(val_str.replace('%', ''))
            except (ValueError, AttributeError):
                return -1.0

        def sort_key(row_data):
            val = row_data[internal_idx]
            
            if internal_idx == 6: # Status
                return status_priority(val)
            
            if internal_idx == 7: # Result
                s_val = str(val)
                if "%" in s_val:
                    return (0, percentage_value(s_val))
                return (1, s_val.lower())

            return str(val).lower()

        self._data.sort(key=sort_key, reverse=reverse)
        self.layoutChanged.emit()

    def add_item(self, serial, model="Unknown", customer="", machine_status=""):
        self.beginInsertRows(QModelIndex(), len(self._data), len(self._data))
        self._data.append([serial, model, customer, machine_status, "", "", "Queued", ""])
        self.endInsertRows()

    def update_status(self, serial, status, result, model=None, unpack_date=None, customer=None, custom08_val=None, machine_status=None):
        for i, row in enumerate(self._data):
            if row[0] == serial:
                row[6] = status
                row[7] = result
                
                if model and model != "Unknown": row[1] = model
                if customer: row[2] = customer
                if machine_status: row[3] = machine_status
                if unpack_date: row[4] = unpack_date
                if custom08_val is not None: row[5] = custom08_val

                self.dataChanged.emit(self.index(i, 1), self.index(i, self.columnCount() - 1))
                return
    
    def get_serial_at(self, row):
        if 0 <= row < len(self._data):
            return self._data[row][0]
        return None

    def clear(self):
        self.beginResetModel()
        self._data = []
        self.endResetModel()

    def sort_by_status(self):
        self.sort(self.status_col, Qt.SortOrder.AscendingOrder)