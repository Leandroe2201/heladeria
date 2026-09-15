from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QInputDialog,
    QSplitter, QScrollArea
)

from app.database import db


GREEN = '#16a34a'
BLUE = '#2563eb'
PURPLE = '#7c3aed'
ORANGE = '#ea580c'
RED = '#dc2626'


class ProductosPage(QWidget):
    """V24 · Catálogo de escritorio rediseñado con editor integrado."""

    def __init__(self, back_callback):
        super().__init__()
        self.back_callback = back_callback
        self.current_id = None
        self._loading = False
        self.browse_mode = False
        self.build_ui()
        self.refresh_categories()
        self.refresh()

    def _section(self, title, subtitle=''):
        box = QFrame()
        box.setObjectName('productSection')
        box.setStyleSheet('QFrame#productSection{background:white;border:1px solid #e5e7eb;border-radius:16px;}')
        layout = QVBoxLayout(box)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        lbl = QLabel(title); lbl.setStyleSheet('font-size:18px;font-weight:900;color:#1f2937;')
        layout.addWidget(lbl)
        if subtitle:
            sub = QLabel(subtitle); sub.setWordWrap(True); sub.setStyleSheet('color:#6b7280;font-size:12px;')
            layout.addWidget(sub)
        return box, layout

    def _field_label(self, text):
        lbl = QLabel(text); lbl.setStyleSheet('font-weight:800;color:#374151;font-size:12px;')
        return lbl

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(14)

        header = QHBoxLayout()
        back = QPushButton('← VOLVER')
        back.setMinimumHeight(44)
        back.setStyleSheet('background:#f3f4f6;color:#374151;padding:10px 18px;')
        back.clicked.connect(self.back_callback)
        title_wrap = QVBoxLayout()
        title = QLabel('📦 Productos')
        title.setStyleSheet('font-size:30px;font-weight:950;color:#111827;')
        subtitle = QLabel('Administrá el catálogo desde una sola pantalla. Seleccioná a la izquierda y editá a la derecha.')
        subtitle.setStyleSheet('color:#6b7280;font-size:13px;')
        title_wrap.addWidget(title); title_wrap.addWidget(subtitle)
        new_btn = QPushButton('＋ NUEVO PRODUCTO')
        new_btn.setMinimumHeight(48)
        new_btn.setStyleSheet(f'background:{GREEN};color:white;padding:12px 22px;')
        new_btn.clicked.connect(self.new_product)
        header.addWidget(back); header.addSpacing(14); header.addLayout(title_wrap); header.addStretch(); header.addWidget(new_btn)
        root.addLayout(header)

        toolbar = QFrame(); toolbar.setStyleSheet('background:white;border:1px solid #e5e7eb;border-radius:14px;')
        tl = QHBoxLayout(toolbar); tl.setContentsMargins(14,10,14,10); tl.setSpacing(10)
        self.search = QLineEdit(); self.search.setPlaceholderText('🔎 Buscar producto o código...'); self.search.setClearButtonEnabled(True); self.search.setMinimumHeight(42); self.search.textChanged.connect(self.refresh)
        self.category_filter = QComboBox(); self.category_filter.setMinimumWidth(180); self.category_filter.currentIndexChanged.connect(self.refresh)
        self.active_filter = QComboBox(); self.active_filter.addItems(['TODOS', 'ACTIVOS', 'INACTIVOS']); self.active_filter.currentIndexChanged.connect(self.refresh)
        self.browse_btn = QPushButton('👁 VER ACTIVOS'); self.browse_btn.setStyleSheet('background:#eff6ff;color:#1d4ed8;'); self.browse_btn.clicked.connect(self.toggle_browse)
        refresh_btn = QPushButton('⟳ ACTUALIZAR'); refresh_btn.setStyleSheet('background:#eef2ff;color:#3730a3;'); refresh_btn.clicked.connect(self.refresh)
        tl.addWidget(self.search, 1); tl.addWidget(self.category_filter); tl.addWidget(self.active_filter); tl.addWidget(self.browse_btn); tl.addWidget(refresh_btn)
        root.addWidget(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal); splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        left = QFrame(); left.setStyleSheet('background:white;border:1px solid #e5e7eb;border-radius:16px;')
        ll = QVBoxLayout(left); ll.setContentsMargins(14,14,14,14); ll.setSpacing(10)
        lh = QHBoxLayout(); lt = QLabel('CATÁLOGO'); lt.setStyleSheet('font-size:13px;font-weight:900;color:#6b7280;letter-spacing:1px;'); self.counter = QLabel('0 productos'); self.counter.setStyleSheet('color:#6b7280;')
        lh.addWidget(lt); lh.addStretch(); lh.addWidget(self.counter); ll.addLayout(lh)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Producto', 'Categoría', 'Precio', 'Estado'])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(52)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.doubleClicked.connect(lambda *_: self.name.setFocus())
        ll.addWidget(self.table, 1)
        splitter.addWidget(left)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        editor = QWidget(); editor.setStyleSheet('background:#f8fafc;')
        el = QVBoxLayout(editor); el.setContentsMargins(2,0,2,8); el.setSpacing(12)

        top, top_l = self._section('Ficha del producto')
        tr = QHBoxLayout(); ident = QVBoxLayout()
        self.editor_title = QLabel('Seleccioná un producto'); self.editor_title.setStyleSheet('font-size:24px;font-weight:950;color:#111827;')
        self.editor_hint = QLabel('O creá uno nuevo para agregarlo al catálogo.'); self.editor_hint.setStyleSheet('color:#6b7280;')
        ident.addWidget(self.editor_title); ident.addWidget(self.editor_hint)
        self.status_badge = QLabel('SIN SELECCIÓN'); self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter); self.status_badge.setMinimumWidth(110)
        self.status_badge.setStyleSheet('background:#e5e7eb;color:#374151;border-radius:12px;padding:8px 12px;font-weight:900;')
        tr.addLayout(ident,1); tr.addWidget(self.status_badge); top_l.addLayout(tr); el.addWidget(top)

        main, ml = self._section('Datos principales')
        mg = QGridLayout(); mg.setHorizontalSpacing(14); mg.setVerticalSpacing(8)
        self.code = QLineEdit(); self.code.setPlaceholderText('Código interno / opcional')
        self.name = QLineEdit(); self.name.setPlaceholderText('Ej. 1/2 KG')
        self.price = QDoubleSpinBox(); self.price.setRange(0,999999999); self.price.setPrefix('$ '); self.price.setDecimals(2)
        self.cost = QDoubleSpinBox(); self.cost.setRange(0,999999999); self.cost.setPrefix('$ '); self.cost.setDecimals(2)
        mg.addWidget(self._field_label('Código'),0,0); mg.addWidget(self._field_label('Nombre *'),0,1)
        mg.addWidget(self.code,1,0); mg.addWidget(self.name,1,1)
        mg.addWidget(self._field_label('Precio de venta *'),2,0); mg.addWidget(self._field_label('Costo'),2,1)
        mg.addWidget(self.price,3,0); mg.addWidget(self.cost,3,1)
        ml.addLayout(mg); el.addWidget(main)

        cat, cl = self._section('Categoría')
        cr = QHBoxLayout()
        self.category = QComboBox(); self.category.setMinimumHeight(42)
        add_cat = QPushButton('＋ NUEVA CATEGORÍA'); add_cat.setStyleSheet(f'background:{PURPLE};color:white;'); add_cat.clicked.connect(self.add_category)
        cr.addWidget(self.category,1); cr.addWidget(add_cat); cl.addLayout(cr); el.addWidget(cat)

        sale, sal = self._section('Venta y preparación', 'Definí cómo aparece y se comporta el producto en la pantalla de Ventas.')
        sg = QGridLayout(); sg.setHorizontalSpacing(14); sg.setVerticalSpacing(8)
        self.max_flavors = QSpinBox(); self.max_flavors.setRange(0,12); self.max_flavors.setSuffix(' sabores')
        self.sort_order = QSpinBox(); self.sort_order.setRange(0,9999)
        self.stock_control = QCheckBox('Controlar stock propio del producto')
        self.show = QCheckBox('Mostrar como botón en Ventas'); self.show.setChecked(True)
        self.active = QCheckBox('Producto activo'); self.active.setChecked(True)
        sg.addWidget(self._field_label('Cantidad máxima de sabores'),0,0); sg.addWidget(self._field_label('Orden en pantalla'),0,1)
        sg.addWidget(self.max_flavors,1,0); sg.addWidget(self.sort_order,1,1)
        sg.addWidget(self.stock_control,2,0,1,2); sg.addWidget(self.show,3,0,1,2); sg.addWidget(self.active,4,0,1,2)
        hint = QLabel('Ejemplo: 1/4 KG puede tener 2 sabores. Una bebida puede tener 0.')
        hint.setWordWrap(True); hint.setStyleSheet('background:#eff6ff;color:#1d4ed8;padding:10px;border-radius:10px;')
        sg.addWidget(hint,5,0,1,2); sal.addLayout(sg); el.addWidget(sale)

        action = QFrame(); action.setStyleSheet('background:white;border:1px solid #e5e7eb;border-radius:16px;')
        al = QHBoxLayout(action); al.setContentsMargins(14,12,14,12); al.setSpacing(10)
        self.delete_toggle_btn = QPushButton('⏸ ACTIVAR / DESACTIVAR'); self.delete_toggle_btn.setStyleSheet('background:#fef3c7;color:#92400e;'); self.delete_toggle_btn.clicked.connect(self.toggle_active)
        self.cancel_btn = QPushButton('LIMPIAR / CANCELAR'); self.cancel_btn.setStyleSheet('background:#f3f4f6;color:#374151;'); self.cancel_btn.clicked.connect(self.cancel_edit)
        self.save_btn = QPushButton('💾 GUARDAR PRODUCTO'); self.save_btn.setMinimumHeight(48); self.save_btn.setStyleSheet(f'background:{GREEN};color:white;padding:12px 22px;'); self.save_btn.clicked.connect(self.save_product)
        al.addWidget(self.delete_toggle_btn); al.addWidget(self.cancel_btn); al.addStretch(); al.addWidget(self.save_btn)
        el.addWidget(action); el.addStretch()

        scroll.setWidget(editor); splitter.addWidget(scroll); splitter.setSizes([560,720])
        self._set_editor_enabled(False)

    def _set_editor_enabled(self, enabled):
        for w in (self.code, self.name, self.price, self.cost, self.category, self.max_flavors,
                  self.sort_order, self.stock_control, self.show, self.active, self.save_btn, self.cancel_btn):
            w.setEnabled(enabled)
        self.delete_toggle_btn.setEnabled(bool(enabled and self.current_id))

    def _set_badge(self, active):
        if active is None:
            self.status_badge.setText('SIN SELECCIÓN')
            self.status_badge.setStyleSheet('background:#e5e7eb;color:#374151;border-radius:12px;padding:8px 12px;font-weight:900;')
        elif active:
            self.status_badge.setText('ACTIVO')
            self.status_badge.setStyleSheet('background:#dcfce7;color:#166534;border-radius:12px;padding:8px 12px;font-weight:900;')
        else:
            self.status_badge.setText('INACTIVO')
            self.status_badge.setStyleSheet('background:#fee2e2;color:#991b1b;border-radius:12px;padding:8px 12px;font-weight:900;')

    # ---------- Categorías ----------
    def refresh_categories(self, selected=None):
        current = self.category.currentData() if hasattr(self, 'category') else selected
        with db() as conn:
            rows = conn.execute('SELECT id,name FROM categories WHERE active=1 ORDER BY name COLLATE NOCASE').fetchall()
        self.category.clear(); self.category.addItem('Sin categoría', None)
        for r in rows:
            self.category.addItem(r['name'], r['id'])
        target = selected if selected is not None else current
        if target is not None:
            idx = self.category.findData(target)
            if idx >= 0: self.category.setCurrentIndex(idx)
        if hasattr(self, 'category_filter'):
            prev = self.category_filter.currentData()
            self.category_filter.blockSignals(True)
            self.category_filter.clear(); self.category_filter.addItem('TODAS LAS CATEGORÍAS', None)
            for r in rows: self.category_filter.addItem(r['name'], r['id'])
            idx = self.category_filter.findData(prev)
            if idx >= 0: self.category_filter.setCurrentIndex(idx)
            self.category_filter.blockSignals(False)

    def add_category(self):
        name, ok = QInputDialog.getText(self, 'Nueva categoría', 'Nombre de la categoría:')
        if not ok or not name.strip():
            return
        try:
            with db() as conn:
                cur = conn.execute('INSERT INTO categories(name) VALUES (?)', (name.strip().upper(),))
                cid = cur.lastrowid
            self.refresh_categories(cid)
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, 'Categoría', f'No se pudo crear.\n{exc}')

    # ---------- Listado ----------
    def toggle_browse(self):
        self.browse_mode = not self.browse_mode
        self.browse_btn.setText('✕ OCULTAR LISTA' if self.browse_mode else '👁 VER ACTIVOS')
        if self.browse_mode and not self.search.text().strip():
            self.active_filter.setCurrentText('ACTIVOS')
        self.refresh()

    def refresh(self, *_):
        text = self.search.text().strip().lower() if hasattr(self, 'search') else ''
        if not text and not self.browse_mode:
            self._loading = True
            self.table.setRowCount(0)
            self.table.clearSelection()
            self._loading = False
            self.counter.setText('Buscá por nombre/código o tocá VER ACTIVOS')
            if self.current_id is None:
                self.clear_editor(False)
            return
        category_id = self.category_filter.currentData() if hasattr(self, 'category_filter') else None
        active_filter = self.active_filter.currentText() if hasattr(self, 'active_filter') else 'TODOS'
        with db() as conn:
            rows = conn.execute('''SELECT p.*, COALESCE(c.name,'Sin categoría') category_name
                                   FROM products p LEFT JOIN categories c ON c.id=p.category_id
                                   ORDER BY p.sort_order,p.name COLLATE NOCASE''').fetchall()
        filtered = []
        for r in rows:
            if text and text not in f"{r['name']} {r['code'] or ''}".lower():
                continue
            if category_id is not None and r['category_id'] != category_id:
                continue
            if active_filter == 'ACTIVOS' and not bool(r['active']):
                continue
            if active_filter == 'INACTIVOS' and bool(r['active']):
                continue
            filtered.append(r)

        selected = self.current_id
        self._loading = True
        self.table.setRowCount(len(filtered))
        select_row = -1
        for i, r in enumerate(filtered):
            name = QTableWidgetItem(str(r['name']))
            name.setData(Qt.ItemDataRole.UserRole, int(r['id']))
            price = f"$ {float(r['price'] or 0):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
            items = [name, QTableWidgetItem(str(r['category_name'])), QTableWidgetItem(price), QTableWidgetItem('ACTIVO' if r['active'] else 'INACTIVO')]
            for c, item in enumerate(items):
                self.table.setItem(i,c,item)
                if c in (2,3): item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if int(r['id']) == selected:
                select_row = i
        self.counter.setText(f'{len(filtered)} producto' + ('' if len(filtered)==1 else 's'))
        self._loading = False
        if select_row >= 0:
            self.table.selectRow(select_row)
        elif len(filtered) == 1 and self.current_id is None:
            self.table.selectRow(0)
        elif not filtered:
            self.current_id = None; self.clear_editor()

    def _selection_changed(self):
        if self._loading:
            return
        row = self.table.currentRow()
        if row < 0: return
        item = self.table.item(row,0)
        if not item: return
        pid = item.data(Qt.ItemDataRole.UserRole)
        if pid: self.load_product(int(pid))

    # ---------- Editor ----------
    def new_product(self):
        self.table.clearSelection(); self.current_id = None; self.clear_editor(new_mode=True); self.name.setFocus()

    def clear_editor(self, new_mode=False):
        self._loading = True
        self.code.clear(); self.name.clear(); self.price.setValue(0); self.cost.setValue(0); self.max_flavors.setValue(0); self.sort_order.setValue(0)
        self.stock_control.setChecked(False); self.show.setChecked(True); self.active.setChecked(True)
        if self.category.count(): self.category.setCurrentIndex(0)
        self.editor_title.setText('Nuevo producto' if new_mode else 'Seleccioná un producto')
        self.editor_hint.setText('Completá los datos y guardá.' if new_mode else 'Elegí un producto del catálogo para editarlo.')
        self._set_badge(True if new_mode else None); self._set_editor_enabled(new_mode)
        self._loading = False

    def cancel_edit(self):
        if self.current_id: self.load_product(self.current_id)
        else: self.clear_editor(False)

    def load_product(self, pid):
        with db() as conn:
            r = conn.execute('''SELECT p.*, COALESCE(c.name,'Sin categoría') category_name
                                FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE p.id=?''', (pid,)).fetchone()
        if not r: return
        self.current_id = pid; self._loading = True
        self.code.setText(str(r['code'] or '')); self.name.setText(str(r['name'] or '')); self.refresh_categories(r['category_id'])
        self.price.setValue(float(r['price'] or 0)); self.cost.setValue(float(r['cost'] or 0)); self.max_flavors.setValue(int(r['max_flavors'] or 0)); self.sort_order.setValue(int(r['sort_order'] or 0))
        self.stock_control.setChecked(bool(r['stock_control'])); self.show.setChecked(bool(r['show_in_sales'])); self.active.setChecked(bool(r['active']))
        self.editor_title.setText(str(r['name'])); self.editor_hint.setText(f"{r['category_name']} · Código {r['code'] or 'sin código'}")
        self._set_badge(bool(r['active'])); self._set_editor_enabled(True); self._loading = False

    def save_product(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, 'Producto', 'Ingresá el nombre del producto.'); self.name.setFocus(); return
        data = (
            self.code.text().strip() or None, self.name.text().strip(), self.category.currentData(),
            self.price.value(), self.cost.value(), self.max_flavors.value(), int(self.stock_control.isChecked()),
            int(self.active.isChecked()), int(self.show.isChecked()), self.sort_order.value()
        )
        try:
            with db() as conn:
                if self.current_id:
                    conn.execute('''UPDATE products SET code=?,name=?,category_id=?,price=?,cost=?,max_flavors=?,stock_control=?,active=?,show_in_sales=?,sort_order=? WHERE id=?''', data + (self.current_id,))
                    pid = self.current_id
                else:
                    cur = conn.execute('''INSERT INTO products(code,name,category_id,price,cost,max_flavors,stock_control,active,show_in_sales,sort_order)
                                          VALUES (?,?,?,?,?,?,?,?,?,?)''', data)
                    pid = int(cur.lastrowid)
            self.current_id = pid; self.refresh_categories(self.category.currentData()); self.refresh(); self.load_product(pid)
            QMessageBox.information(self, 'Producto', 'Producto guardado correctamente.')
        except Exception as exc:
            QMessageBox.critical(self, 'Producto', f'No se pudo guardar.\n\n{exc}')

    def toggle_active(self):
        if not self.current_id:
            return
        with db() as conn:
            row = conn.execute('SELECT active,name FROM products WHERE id=?', (self.current_id,)).fetchone()
            if not row: return
            new_value = 0 if row['active'] else 1
            conn.execute('UPDATE products SET active=? WHERE id=?', (new_value, self.current_id))
        self.refresh(); self.load_product(self.current_id)
        QMessageBox.information(self, 'Productos', 'Producto activado.' if new_value else 'Producto desactivado.')
