from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QMessageBox
from app.database import db


class BaseDataPage(QWidget):
    def __init__(self, title, table, columns, back_callback, order_by="id DESC", where=""):
        super().__init__()
        self.title = title
        self.table_name = table
        self.columns = columns
        self.order_by = order_by
        self.where = where
        self.back_callback = back_callback
        self.build_ui()
        self.refresh()

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 28)
        header = QHBoxLayout()
        back = QPushButton("← Volver a Opciones")
        back.setStyleSheet("background:#eee5ea;color:#4a3740;")
        back.clicked.connect(self.back_callback)
        title = QLabel(self.title)
        title.setStyleSheet("font-size:28px;font-weight:800;")
        refresh = QPushButton("Actualizar")
        refresh.setStyleSheet("background:#e55b88;color:white;")
        refresh.clicked.connect(self.refresh)
        header.addWidget(back)
        header.addSpacing(18)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(refresh)
        root.addLayout(header)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels([label for _, label in self.columns])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table)

    def refresh(self):
        fields = ",".join([field for field, _ in self.columns])
        sql = f"SELECT {fields} FROM {self.table_name}"
        if self.where:
            sql += f" WHERE {self.where}"
        sql += f" ORDER BY {self.order_by}"
        with db() as conn:
            rows = conn.execute(sql).fetchall()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, (field, _) in enumerate(self.columns):
                value = row[field]
                if value is None:
                    value = ""
                self.table.setItem(r, c, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()

    def not_ready(self, text="Esta función queda preparada para la siguiente etapa."):
        QMessageBox.information(self, self.title, text)
