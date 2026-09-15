from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QListWidget, QListWidgetItem, QDialog, QScrollArea, QMessageBox, QComboBox,
    QLineEdit, QFormLayout, QTabWidget, QSizePolicy, QInputDialog
)
from app.database import db
from app.services.offer_service import price_with_offer, apply_cart_offers, display_offer_for_product
from app.services.sale_service import save_sale
from app.services.ticket_service import print_sale_ticket, print_loyalty_ticket
from app.services.loyalty_service import create_or_update_customer, eligible_rewards, reward_discount, get_customer_by_dni
from app.settings_service import get_setting


CATEGORY_STYLE = {
    'HELADOS POR PESO': ('#e94f86', '#fff0f5', '🍨'),
    'CUCURUCHOS': ('#f28b32', '#fff1e4', '🍦'),
    'VASITOS': ('#11a99a', '#e7fbf7', '🥣'),
    'BEBIDAS': ('#348de0', '#eaf4ff', '🥤'),
    'POSTRES': ('#8059c8', '#f1ecff', '🍰'),
    'OTROS': ('#68717d', '#f1f3f5', '🛍️'),
}
FLAVOR_STYLE = {
    'CREMAS': ('#e1a900', '#fff7d5', '🍮'),
    'FRUTALES': ('#28a75f', '#e8f8ed', '🍓'),
    'PREMIUM': ('#8059c8', '#f1ecff', '⭐'),
    'OTROS': ('#348de0', '#eaf4ff', '🍨'),
}


def money(value):
    return f"$ {float(value):,.0f}".replace(',', '.')


class FlavorDialog(QDialog):
    """Selector táctil/visual de gustos. Mantiene orden de selección y máximo visible."""
    def __init__(self, product_name, max_flavors, parent=None):
        super().__init__(parent)
        self.max_flavors = max(1, int(max_flavors))
        self.selected = []
        self.buttons = {}
        self.labels = {}
        self.setWindowTitle(f'Gustos · {product_name}')
        self.resize(940, 680)
        self.setMinimumSize(760, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(11)

        top = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel(f'🍨 {product_name}')
        title.setStyleSheet('font-size:29px;font-weight:950;color:#4d2034;')
        subtitle = QLabel('Tocá los gustos en el orden que los querés cargar.')
        subtitle.setStyleSheet('font-size:14px;color:#725e68;')
        titles.addWidget(title)
        titles.addWidget(subtitle)
        top.addLayout(titles)
        top.addStretch()
        self.counter = QLabel()
        self.counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.counter.setMinimumWidth(190)
        self.counter.setStyleSheet('background:#e94f86;color:white;padding:12px 16px;border-radius:14px;font-size:18px;font-weight:950;')
        top.addWidget(self.counter)
        root.addLayout(top)

        self.selected_label = QLabel()
        self.selected_label.setWordWrap(True)
        self.selected_label.setMinimumHeight(58)
        self.selected_label.setStyleSheet('background:#fff0f5;border:2px solid #f6c8d9;border-radius:14px;padding:12px;font-size:16px;font-weight:800;color:#5c3244;')
        root.addWidget(self.selected_label)

        with db() as conn:
            flavors = conn.execute('''SELECT * FROM flavors
                                      WHERE active=1 AND available=1 AND stock_kg>0
                                      ORDER BY CASE WHEN premium=1 THEN 1 ELSE 0 END, category, name''').fetchall()

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        categories = []
        for row in flavors:
            cat = ('PREMIUM' if row['premium'] else (row['category'] or 'OTROS')).upper()
            if cat not in categories:
                categories.append(cat)

        if not categories:
            empty = QLabel('No hay gustos disponibles.\nRevisá Stock / Sabores desde Administración.')
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet('font-size:19px;color:#8b6677;padding:40px;')
            root.addWidget(empty, 1)
        else:
            for cat in categories:
                accent, soft, icon = FLAVOR_STYLE.get(cat, FLAVOR_STYLE['OTROS'])
                page = QWidget()
                lay = QVBoxLayout(page)
                lay.setContentsMargins(8, 10, 8, 8)
                hint = QLabel(f'{icon} {cat.title()}')
                hint.setStyleSheet(f'font-size:17px;font-weight:900;color:{accent};padding:2px 4px;')
                lay.addWidget(hint)
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QFrame.Shape.NoFrame)
                body = QWidget()
                grid = QGridLayout(body)
                grid.setSpacing(12)
                group = [r for r in flavors if ('PREMIUM' if r['premium'] else (r['category'] or 'OTROS')).upper() == cat]
                for idx, fl in enumerate(group):
                    extra = f"\n+ {money(fl['premium_extra'])}" if fl['premium'] and float(fl['premium_extra'] or 0) else ''
                    base_label = f"{fl['name']}{extra}"
                    btn = QPushButton(base_label)
                    btn.setCheckable(True)
                    btn.setMinimumHeight(94)
                    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                    btn.setStyleSheet(f'''
                        QPushButton{{background:{soft};color:#392d32;border:2px solid {accent};border-radius:15px;
                                    font-size:16px;font-weight:850;text-align:left;padding:12px 14px;}}
                        QPushButton:hover{{background:white;border:3px solid {accent};}}
                        QPushButton:checked{{background:{accent};color:white;border:3px solid #4d2034;}}
                    ''')
                    btn.clicked.connect(lambda checked, name=fl['name'], b=btn: self.toggle(name, b, checked))
                    grid.addWidget(btn, idx // 4, idx % 4)
                    self.buttons[fl['name']] = btn
                    self.labels[fl['name']] = base_label
                grid.setRowStretch((len(group) + 3) // 4, 1)
                scroll.setWidget(body)
                lay.addWidget(scroll, 1)
                tabs.addTab(page, f'{icon} {cat.title()}')
            root.addWidget(tabs, 1)

        bottom = QHBoxLayout()
        clear = QPushButton('↺ BORRAR SELECCIÓN')
        clear.setMinimumHeight(50)
        clear.setStyleSheet('background:#f5e8ed;color:#8f3c5d;')
        clear.clicked.connect(self.clear_selection)
        cancel = QPushButton('Cancelar')
        cancel.setMinimumHeight(50)
        cancel.setStyleSheet('background:#eee5ea;color:#4a3740;')
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton('✓ CONFIRMAR GUSTOS')
        self.ok.setMinimumHeight(54)
        self.ok.setStyleSheet('QPushButton{background:#25b86b;color:white;font-size:17px;} QPushButton:disabled{background:#cfd8d3;color:#758078;}')
        self.ok.clicked.connect(self.accept_valid)
        bottom.addWidget(clear)
        bottom.addStretch()
        bottom.addWidget(cancel)
        bottom.addWidget(self.ok)
        root.addLayout(bottom)
        self.update_selection_ui()

    def toggle(self, name, button, checked):
        if checked:
            if len(self.selected) >= self.max_flavors:
                button.setChecked(False)
                QMessageBox.information(self, 'Gustos', f'Este producto admite hasta {self.max_flavors} gustos.')
                return
            if name not in self.selected:
                self.selected.append(name)
        elif name in self.selected:
            self.selected.remove(name)
        self.update_selection_ui()

    def clear_selection(self):
        self.selected.clear()
        for button in self.buttons.values():
            button.setChecked(False)
        self.update_selection_ui()

    def update_selection_ui(self):
        self.counter.setText(f'{len(self.selected)} / {self.max_flavors} GUSTOS')
        if self.selected:
            pieces = [f'{i + 1}. {name}' for i, name in enumerate(self.selected)]
            self.selected_label.setText('SELECCIONADOS  •  ' + '   |   '.join(pieces))
        else:
            self.selected_label.setText(f'SELECCIONÁ HASTA {self.max_flavors} GUSTOS')
        for name, button in self.buttons.items():
            base = self.labels[name]
            if name in self.selected:
                number = self.selected.index(name) + 1
                button.setText(f'✓ {number}  {base}')
                button.setChecked(True)
            else:
                button.setText(base)
                button.setChecked(False)
        self.ok.setEnabled(bool(self.selected))

    def accept_valid(self):
        if not self.selected:
            QMessageBox.information(self, 'Gustos', 'Seleccioná al menos un gusto.')
            return
        self.accept()


class PaymentDialog(QDialog):
    """Cobro táctil: F12 abre este diálogo y un botón elige el medio de pago."""
    METHODS = [
        ('EFECTIVO', '💵', '#22b866', '1'),
        ('DÉBITO', '💳', '#358ee3', '2'),
        ('CRÉDITO', '💳', '#8059c8', '3'),
        ('QR / TRANSFERENCIA', '📱', '#f28b32', '4'),
    ]

    def __init__(self, total, parent=None):
        super().__init__(parent)
        self.payment_method = None
        self.setWindowTitle('F12 · Cobrar venta')
        self.resize(720, 500)
        self.setMinimumSize(640, 440)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(15)

        title = QLabel('¿CÓMO ABONA?')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet('font-size:28px;font-weight:950;color:#4d2034;')
        root.addWidget(title)
        total_label = QLabel(f'TOTAL  {money(total)}')
        total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        total_label.setStyleSheet('background:#fff0f5;color:#4d2034;border:2px solid #f0bfd2;border-radius:16px;padding:15px;font-size:35px;font-weight:950;')
        root.addWidget(total_label)
        instruction = QLabel('Tocá una forma de pago · Teclas 1 a 4')
        instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instruction.setStyleSheet('font-size:14px;color:#78646d;')
        root.addWidget(instruction)

        grid = QGridLayout()
        grid.setSpacing(14)
        for idx, (method, icon, color, key) in enumerate(self.METHODS):
            label = 'QR / TRANSFERENCIA' if method == 'QR / TRANSFERENCIA' else method
            btn = QPushButton(f'{icon}\n{label}\n{key}')
            btn.setMinimumHeight(122)
            btn.setStyleSheet(f'''QPushButton{{background:{color};color:white;border:3px solid rgba(255,255,255,.8);border-radius:18px;
                                  font-size:20px;font-weight:950;}} QPushButton:hover{{border:4px solid #33232b;}}''')
            btn.clicked.connect(lambda _, m=method: self.choose(m))
            grid.addWidget(btn, idx // 2, idx % 2)
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(lambda m=method: self.choose(m))
        root.addLayout(grid, 1)

        cancel = QPushButton('ESC · VOLVER SIN COBRAR')
        cancel.setMinimumHeight(48)
        cancel.setStyleSheet('background:#eee5ea;color:#594650;')
        cancel.clicked.connect(self.reject)
        root.addWidget(cancel)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self.reject)

    def choose(self, method):
        self.payment_method = method
        self.accept()


class LoyaltyCheckoutDialog(QDialog):
    def __init__(self, items, current_total, parent=None):
        super().__init__(parent)
        self.items = items
        self.current_total = current_total
        self.customer = None
        self.result_data = None
        self.setWindowTitle('Cliente / Puntos')
        self.resize(620, 500)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)
        title = QLabel('⭐ CLIENTE / PUNTOS')
        title.setStyleSheet('font-size:25px;font-weight:950;color:#4d2034;')
        root.addWidget(title)
        text = QLabel('Ingresá el DNI para sumar puntos, consultar la tarjeta o canjear un beneficio.')
        text.setWordWrap(True)
        text.setStyleSheet('font-size:15px;color:#6e5964;')
        root.addWidget(text)
        row = QHBoxLayout()
        self.dni = QLineEdit()
        self.dni.setPlaceholderText('DNI del cliente')
        self.dni.setMinimumHeight(50)
        find = QPushButton('🔎 BUSCAR / CREAR')
        find.setMinimumHeight(50)
        find.setStyleSheet('background:#3a8ee6;color:white;')
        find.clicked.connect(self.lookup)
        row.addWidget(self.dni, 1)
        row.addWidget(find)
        root.addLayout(row)
        self.card = QLabel('')
        self.card.setStyleSheet('background:#f7edf2;padding:13px;border-radius:11px;font-size:16px;font-weight:800;')
        self.card.hide()
        root.addWidget(self.card)
        form = QFormLayout()
        self.name = QLineEdit()
        self.phone = QLineEdit()
        self.name.setPlaceholderText('Nombre si es cliente nuevo')
        self.phone.setPlaceholderText('Teléfono opcional')
        form.addRow('Nombre', self.name)
        form.addRow('Teléfono', self.phone)
        root.addLayout(form)
        self.reward = QComboBox()
        self.reward.setMinimumHeight(44)
        self.reward.addItem('Sin canje de puntos', None)
        self.reward.currentIndexChanged.connect(self.update_reward_info)
        root.addWidget(QLabel('Canje disponible'))
        root.addWidget(self.reward)
        self.reward_info = QLabel('')
        self.reward_info.setWordWrap(True)
        self.reward_info.setStyleSheet('color:#80506a;font-weight:700;')
        root.addWidget(self.reward_info)
        root.addStretch()
        buttons = QHBoxLayout()
        skip = QPushButton('SEGUIR SIN DNI')
        skip.setMinimumHeight(52)
        skip.setStyleSheet('background:#eee5ea;color:#4a3740;')
        skip.clicked.connect(self.skip_customer)
        ok = QPushButton('✓ CONTINUAR')
        ok.setMinimumHeight(52)
        ok.setStyleSheet('background:#26b86a;color:white;font-size:17px;')
        ok.clicked.connect(self.confirm)
        buttons.addWidget(skip)
        buttons.addStretch()
        buttons.addWidget(ok)
        root.addLayout(buttons)

    def lookup(self):
        try:
            self.customer = create_or_update_customer(self.dni.text(), self.name.text().strip(), self.phone.text().strip())
        except Exception as e:
            QMessageBox.warning(self, 'Cliente', str(e))
            return
        self.name.setText(self.customer['name'] or '')
        self.phone.setText(self.customer['phone'] or '')
        self.card.setText(f"Tarjeta: {self.customer['loyalty_card_number']}     ⭐ {int(self.customer['points'] or 0)} puntos")
        self.card.show()
        self.reward.clear()
        self.reward.addItem('Sin canje de puntos', None)
        for r in eligible_rewards(int(self.customer['points'] or 0)):
            self.reward.addItem(f"{r['name']} · {r['points_cost']} puntos", dict(r))

    def update_reward_info(self):
        reward = self.reward.currentData()
        if not reward:
            self.reward_info.setText('')
            return
        disc, desc = reward_discount(reward, self.items, self.current_total)
        if reward['reward_type'] == 'PRODUCTO_GRATIS' and disc <= 0:
            self.reward_info.setText(f"⚠ Para usar '{desc}' el producto correspondiente debe estar en la venta.")
        else:
            self.reward_info.setText(f"Beneficio aplicado: {desc} · ahorro aproximado {money(disc)}")

    def skip_customer(self):
        self.result_data = {'customer_id': None, 'reward_id': None, 'points_redeemed': 0, 'discount': 0.0, 'description': ''}
        self.accept()

    def confirm(self):
        if not self.dni.text().strip():
            QMessageBox.information(self, 'Cliente', 'Ingresá un DNI o elegí “Seguir sin DNI”.')
            return
        if self.customer is None:
            self.lookup()
        if self.customer is None:
            return
        reward = self.reward.currentData()
        discount = 0.0
        desc = ''
        points = 0
        reward_id = None
        if reward:
            discount, desc = reward_discount(reward, self.items, self.current_total)
            if reward['reward_type'] == 'PRODUCTO_GRATIS' and discount <= 0:
                QMessageBox.warning(self, 'Canje', 'Ese beneficio requiere que el producto correspondiente esté cargado en la venta.')
                return
            points = int(reward['points_cost'])
            reward_id = int(reward['id'])
        self.result_data = {
            'customer_id': int(self.customer['id']), 'reward_id': reward_id,
            'points_redeemed': points, 'discount': discount, 'description': desc
        }
        self.accept()


class PointsRedemptionDialog(QDialog):
    """Canje directo por DNI. Los beneficios de producto generan una venta final de $0."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.customer = None
        self.selected_reward = None
        self.selected_product = None
        self.reward_buttons = []
        self.result_data = None
        self.setWindowTitle('Canje de puntos')
        self.resize(760, 660)
        self.setMinimumSize(680, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel('⭐ CANJE DE PUNTOS')
        title.setStyleSheet('font-size:28px;font-weight:950;color:#4d2034;')
        root.addWidget(title)
        info = QLabel('Buscá al cliente por DNI. El sistema muestra su tarjeta, puntos y beneficios disponibles para canje.')
        info.setWordWrap(True)
        info.setStyleSheet('font-size:15px;color:#6e5964;')
        root.addWidget(info)

        row = QHBoxLayout()
        self.dni = QLineEdit()
        self.dni.setPlaceholderText('DNI del cliente')
        self.dni.setMinimumHeight(52)
        self.dni.returnPressed.connect(self.lookup)
        search = QPushButton('🔎 BUSCAR')
        search.setMinimumHeight(52)
        search.setStyleSheet('background:#358ee3;color:white;font-size:16px;font-weight:900;')
        search.clicked.connect(self.lookup)
        row.addWidget(self.dni, 1)
        row.addWidget(search)
        root.addLayout(row)

        self.customer_card = QLabel('Ingresá un DNI para consultar la tarjeta.')
        self.customer_card.setWordWrap(True)
        self.customer_card.setStyleSheet('background:#f7edf2;border:1px solid #ead5df;border-radius:13px;padding:14px;font-size:16px;font-weight:800;color:#5d3949;')
        root.addWidget(self.customer_card)

        lbl = QLabel('BENEFICIOS DISPONIBLES')
        lbl.setStyleSheet('font-size:16px;font-weight:950;color:#4d2034;margin-top:4px;')
        root.addWidget(lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.reward_body = QWidget()
        self.reward_layout = QVBoxLayout(self.reward_body)
        self.reward_layout.setContentsMargins(0, 0, 0, 0)
        self.reward_layout.setSpacing(9)
        self.reward_layout.addStretch()
        scroll.setWidget(self.reward_body)
        root.addWidget(scroll, 1)

        self.selection = QLabel('Todavía no seleccionaste un beneficio.')
        self.selection.setWordWrap(True)
        self.selection.setStyleSheet('background:#fff7df;border:2px solid #efcf72;border-radius:12px;padding:12px;color:#654d13;font-weight:800;')
        root.addWidget(self.selection)

        buttons = QHBoxLayout()
        cancel = QPushButton('ESC · CANCELAR')
        cancel.setMinimumHeight(50)
        cancel.setStyleSheet('background:#eee5ea;color:#594650;')
        cancel.clicked.connect(self.reject)
        self.confirm_button = QPushButton('✓ CONFIRMAR CANJE')
        self.confirm_button.setMinimumHeight(56)
        self.confirm_button.setEnabled(False)
        self.confirm_button.setStyleSheet('QPushButton{background:#8059c8;color:white;font-size:17px;font-weight:950;} QPushButton:disabled{background:#cfc7d9;color:#80778a;}')
        self.confirm_button.clicked.connect(self.confirm)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(self.confirm_button)
        root.addLayout(buttons)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self.reject)
        self.dni.setFocus()

    def _clear_rewards(self):
        while self.reward_layout.count():
            item = self.reward_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.reward_buttons = []
        self.selected_reward = None
        self.selected_product = None
        self.confirm_button.setEnabled(False)
        self.selection.setText('Todavía no seleccionaste un beneficio.')

    def lookup(self):
        self._clear_rewards()
        row = get_customer_by_dni(self.dni.text())
        if not row:
            self.customer = None
            self.customer_card.setText('⚠ No se encontró un cliente con ese DNI. El canje requiere una tarjeta de fidelidad existente.')
            self.reward_layout.addStretch()
            return
        self.customer = dict(row)
        points = int(self.customer.get('points') or 0)
        self.customer_card.setText(
            f"👤 {self.customer.get('name') or 'Cliente'}\n"
            f"DNI: {self.customer.get('dni') or '-'}     Tarjeta: {self.customer.get('loyalty_card_number') or '-'}\n"
            f"⭐ SALDO ACTUAL: {points} PUNTOS"
        )
        rewards = eligible_rewards(points)
        if not rewards:
            empty = QLabel('No tiene beneficios disponibles con el saldo actual.')
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet('padding:28px;color:#8b6677;font-size:16px;')
            self.reward_layout.addWidget(empty)
            self.reward_layout.addStretch()
            return

        direct_count = 0
        for rr in rewards:
            r = dict(rr)
            direct = str(r.get('reward_type') or '').upper() == 'PRODUCTO_GRATIS' and bool(r.get('product_id'))
            if direct:
                direct_count += 1
            product_name = r.get('product_name') or ''
            suffix = f"\n🎁 {product_name}" if product_name else ''
            if not direct:
                suffix += '\nℹ Este beneficio se aplica dentro de una compra con F12.'
            btn = QPushButton(f"{r['name']}\n⭐ {int(r['points_cost'])} puntos{suffix}")
            btn.setCheckable(direct)
            btn.setEnabled(direct)
            btn.setMinimumHeight(82)
            if direct:
                btn.setStyleSheet('QPushButton{background:#f4efff;color:#4d365d;border:2px solid #8059c8;border-radius:14px;text-align:left;padding:10px 14px;font-size:15px;font-weight:850;} QPushButton:hover{background:#fff;border:3px solid #8059c8;} QPushButton:checked{background:#8059c8;color:white;border:3px solid #4d2034;}')
                btn.clicked.connect(lambda checked, reward=r, b=btn: self.choose_reward(reward, b, checked))
            else:
                btn.setStyleSheet('background:#f1eef0;color:#968991;border:1px solid #d9d0d5;border-radius:14px;text-align:left;padding:10px 14px;')
            self.reward_layout.addWidget(btn)
            self.reward_buttons.append(btn)
        if direct_count == 0:
            note = QLabel('No hay canjes directos configurados. En Administración → Fidelidad creá un beneficio de tipo PRODUCTO_GRATIS y asignale un producto.')
            note.setWordWrap(True)
            note.setStyleSheet('background:#fff3cd;color:#735b12;padding:12px;border-radius:10px;font-weight:700;')
            self.reward_layout.addWidget(note)
        self.reward_layout.addStretch()

    def choose_reward(self, reward, button, checked):
        if not checked:
            if self.selected_reward and int(self.selected_reward['id']) == int(reward['id']):
                self.selected_reward = None
                self.selected_product = None
                self.confirm_button.setEnabled(False)
                self.selection.setText('Todavía no seleccionaste un beneficio.')
            return
        for other in self.reward_buttons:
            if other is not button and other.isCheckable():
                other.setChecked(False)
        with db() as conn:
            p = conn.execute("""SELECT p.*,COALESCE(c.name,'OTROS') category_name
                                FROM products p LEFT JOIN categories c ON c.id=p.category_id
                                WHERE p.id=? AND p.active=1 LIMIT 1""", (reward.get('product_id'),)).fetchone()
        if not p:
            button.setChecked(False)
            QMessageBox.warning(self, 'Canje', 'El producto configurado para este beneficio ya no está activo.')
            return
        self.selected_reward = reward
        self.selected_product = dict(p)
        self.selection.setText(
            f"✓ BENEFICIO SELECCIONADO\n{reward['name']}\n"
            f"Producto: {p['name']}   ·   Se descontarán {int(reward['points_cost'])} puntos\n"
            f"La venta se registrará con TOTAL $ 0."
        )
        self.confirm_button.setEnabled(True)

    def confirm(self):
        if not self.customer or not self.selected_reward or not self.selected_product:
            return
        fresh = get_customer_by_dni(self.customer.get('dni'))
        if not fresh:
            QMessageBox.warning(self, 'Canje', 'El cliente ya no está disponible.')
            return
        cost = int(self.selected_reward['points_cost'])
        if int(fresh['points'] or 0) < cost:
            QMessageBox.warning(self, 'Canje', 'El saldo cambió y ya no alcanza para este beneficio. Volvé a buscar el DNI.')
            self.lookup()
            return
        flavors = []
        max_flavors = int(self.selected_product.get('max_flavors') or 0)
        if max_flavors > 0:
            dlg = FlavorDialog(self.selected_product['name'], max_flavors, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            flavors = dlg.selected
        if QMessageBox.question(
            self, 'Confirmar canje',
            f"¿Confirmar el canje de '{self.selected_reward['name']}'?\n\n"
            f"Cliente: {fresh['name']}\nDNI: {fresh['dni']}\n"
            f"Puntos a descontar: {cost}\nTotal de la venta: $ 0",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        product = self.selected_product
        self.result_data = {
            'customer_id': int(fresh['id']),
            'dni': fresh['dni'],
            'customer_name': fresh['name'],
            'card': fresh['loyalty_card_number'],
            'points_before': int(fresh['points'] or 0),
            'reward_id': int(self.selected_reward['id']),
            'reward_name': self.selected_reward['name'],
            'points_redeemed': cost,
            'item': {
                'product_id': int(product['id']), 'name': product['name'],
                'base_price': float(product['price'] or 0), 'final_price': float(product['price'] or 0),
                'offer_id': None, 'offer_name': None, 'flavors': flavors, 'quantity': 1
            }
        }
        self.accept()


class SalesPage(QWidget):
    def __init__(self, options_callback, orders_callback=None, cash_callback=None, chat_callback=None, current_user=None):
        super().__init__()
        self.options_callback = options_callback
        self.orders_callback = orders_callback
        self.cash_callback = cash_callback
        self.chat_callback = chat_callback
        self.current_user = current_user or {'id':1,'name':'Administrador','role':'ADMIN'}
        self.cart = []
        self.manual_discount_percent = 0.0
        self.current_category = 'TODOS'
        self.build_ui()
        self.load_categories()
        self.load_products()
        self.refresh_cart()
        self.f12 = QShortcut(QKeySequence(Qt.Key.Key_F12), self)
        self.f12.activated.connect(self.checkout)
        self.f9 = QShortcut(QKeySequence(Qt.Key.Key_F9), self)
        self.f9.activated.connect(self.redeem_points)
        self.delete_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self)
        self.delete_shortcut.activated.connect(self.remove_selected)

    def show_web_order_notification(self, order):
        try:
            oid = int(order.get('id'))
            customer = str(order.get('customer_name') or 'Cliente')
            total = money(order.get('total') or 0)
            kind = str(order.get('order_type') or 'DELIVERY').replace('_',' ')
            self.web_order_banner_label.setText(f'🔔 NUEVO PEDIDO WEB #{oid} · {customer} · {kind} · {total}')
            self.web_order_banner.show()
        except Exception:
            pass

    def refresh_business_name(self):
        if hasattr(self, 'title_label'):
            self.title_label.setText('🍦 ' + get_setting('store_name', 'Dulces Momentos'))

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(12)

        self.web_order_banner = QFrame()
        self.web_order_banner.setStyleSheet('background:#fff0d9;border:2px solid #f28b32;border-radius:14px;')
        bl = QHBoxLayout(self.web_order_banner); bl.setContentsMargins(14,10,14,10)
        self.web_order_banner_label = QLabel('🔔 NUEVO PEDIDO WEB')
        self.web_order_banner_label.setStyleSheet('font-size:17px;font-weight:950;color:#7b4308;')
        self.web_order_banner_label.setWordWrap(True)
        see_order = QPushButton('VER PEDIDO →')
        see_order.setMinimumHeight(42)
        see_order.setStyleSheet('background:#f28b32;color:white;font-weight:950;')
        see_order.clicked.connect(lambda: self.orders_callback() if self.orders_callback else None)
        close_banner = QPushButton('✕')
        close_banner.setFixedSize(42,42)
        close_banner.setStyleSheet('background:#f7d9bc;color:#78410c;font-weight:950;')
        close_banner.clicked.connect(self.web_order_banner.hide)
        bl.addWidget(self.web_order_banner_label,1); bl.addWidget(see_order); bl.addWidget(close_banner)
        self.web_order_banner.hide()
        root.addWidget(self.web_order_banner)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        self.title_label = QLabel('🍦 ' + get_setting('store_name', 'Dulces Momentos'))
        self.title_label.setStyleSheet('font-size:29px;font-weight:950;color:#4d2034;')
        sub = QLabel(f"Operador: {self.current_user.get('name','')} · Mouse: seleccionar · F12: cobrar · F9: canje · Esc: volver")
        sub.setStyleSheet('font-size:14px;color:#765f6a;')
        titles.addWidget(self.title_label)
        titles.addWidget(sub)
        header.addLayout(titles)
        header.addStretch()

        redeem = QPushButton('⭐ F9 · CANJEAR\nPuntos')
        redeem.setMinimumSize(145, 62)
        redeem.setStyleSheet('background:#8059c8;color:white;font-size:14px;font-weight:900;')
        redeem.clicked.connect(self.redeem_points)
        header.addWidget(redeem)

        cash = QPushButton('💰 CAJA\nAbrir / Cerrar')
        cash.setMinimumSize(145, 62)
        cash.setStyleSheet('background:#20a86b;color:white;font-size:14px;font-weight:900;')
        cash.clicked.connect(lambda: self.cash_callback() if self.cash_callback else None)
        header.addWidget(cash)

        chat = QPushButton('💬 CHAT\nInterno')
        chat.setMinimumSize(125, 62)
        chat.setStyleSheet('background:#3b91e8;color:white;font-size:14px;font-weight:900;')
        chat.clicked.connect(lambda: self.chat_callback() if self.chat_callback else None)
        header.addWidget(chat)

        if str(self.current_user.get('role','')).upper() == 'ADMIN':
            orders = QPushButton('📋 PEDIDOS\nDelivery / Retira')
            orders.setMinimumSize(155, 62)
            orders.setStyleSheet('background:#f28b32;color:white;font-size:14px;font-weight:900;')
            orders.clicked.connect(lambda: self.orders_callback() if self.orders_callback else None)
            header.addWidget(orders)
            opt = QPushButton('⚙ ADMINISTRACIÓN\nOpciones')
            opt.setMinimumSize(165, 62)
            opt.setStyleSheet('background:#594650;color:white;font-size:14px;font-weight:900;')
            opt.clicked.connect(self.options_callback)
            header.addWidget(opt)
        root.addLayout(header)

        self.category_bar = QHBoxLayout()
        self.category_bar.setSpacing(8)
        root.addLayout(self.category_bar)

        body = QHBoxLayout()
        body.setSpacing(16)
        left = QFrame()
        left.setStyleSheet('background:white;border:1px solid #eadfe4;border-radius:18px;')
        lv = QVBoxLayout(left)
        lv.setContentsMargins(12, 12, 12, 12)
        ph = QLabel('TOCÁ UN PRODUCTO PARA AGREGARLO')
        ph.setStyleSheet('font-size:16px;font-weight:900;color:#5b4350;padding:2px 4px;')
        lv.addWidget(ph)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        gridw = QWidget()
        self.product_grid = QGridLayout(gridw)
        self.product_grid.setSpacing(12)
        scroll.setWidget(gridw)
        lv.addWidget(scroll, 1)
        body.addWidget(left, 3)

        right = QFrame()
        right.setMinimumWidth(390)
        right.setStyleSheet('background:#fff;border:1px solid #eadfe4;border-radius:18px;')
        rv = QVBoxLayout(right)
        rv.setContentsMargins(16, 16, 16, 16)
        rt = QLabel('🧾 VENTA ACTUAL')
        rt.setStyleSheet('font-size:22px;font-weight:950;color:#4d2034;')
        rv.addWidget(rt)
        self.cart_list = QListWidget()
        self.cart_list.setStyleSheet('border:none;background:#fff;font-size:15px;')
        rv.addWidget(self.cart_list, 1)
        rm = QPushButton('⌫ QUITAR SELECCIONADO · Supr')
        rm.setMinimumHeight(42)
        rm.setStyleSheet('background:#f6d6e0;color:#993d60;')
        rm.clicked.connect(self.remove_selected)
        rv.addWidget(rm)
        discount_row = QHBoxLayout()
        self.discount_button = QPushButton('🏷️ DESCUENTO %')
        self.discount_button.setMinimumHeight(44)
        self.discount_button.setStyleSheet('background:#f1b83b;color:#4f3b08;font-weight:950;')
        self.discount_button.clicked.connect(self.set_manual_discount)
        self.discount_label = QLabel('Sin descuento manual')
        self.discount_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.discount_label.setStyleSheet('color:#806820;font-weight:850;')
        discount_row.addWidget(self.discount_button); discount_row.addWidget(self.discount_label, 1)
        rv.addLayout(discount_row)
        self.total_label = QLabel('TOTAL   $ 0')
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.total_label.setStyleSheet('font-size:33px;font-weight:950;color:#3d2932;padding:8px 0;')
        rv.addWidget(self.total_label)
        hint = QLabel('Mouse para productos · F12 cobrar · Esc volver')
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet('font-size:14px;color:#7a6670;font-weight:700;')
        rv.addWidget(hint)
        self.pay_button = QPushButton('💳  F12 · COBRAR')
        self.pay_button.setMinimumHeight(76)
        self.pay_button.setStyleSheet('background:#22b866;color:white;font-size:23px;font-weight:950;')
        self.pay_button.clicked.connect(self.checkout)
        rv.addWidget(self.pay_button)
        clear = QPushButton('Cancelar venta')
        clear.setMinimumHeight(44)
        clear.setStyleSheet('background:#f7d7e1;color:#a23f62;')
        clear.clicked.connect(self.clear_cart)
        rv.addWidget(clear)
        body.addWidget(right, 2)
        root.addLayout(body, 1)

    def load_categories(self):
        while self.category_bar.count():
            item = self.category_bar.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        cats = ['TODOS']
        with db() as conn:
            cats += [r['name'] for r in conn.execute('SELECT name FROM categories WHERE active=1 ORDER BY name')]
        for cat in cats:
            if cat == 'TODOS':
                accent, soft, icon = '#4d2034', '#f4edf1', '▦'
            else:
                accent, soft, icon = CATEGORY_STYLE.get(cat, ('#68717d', '#f1f3f5', '•'))
            b = QPushButton(f'{icon}  ' + ('Todos' if cat == 'TODOS' else cat.title()))
            b.setCheckable(True)
            b.setChecked(cat == self.current_category)
            b.setMinimumHeight(44)
            b.setStyleSheet(f'''QPushButton{{background:{soft};color:#4d3741;border:2px solid {accent};padding:8px 13px;font-weight:850;}}
                                QPushButton:checked{{background:{accent};color:white;}}''')
            b.clicked.connect(lambda _, c=cat: self.set_category(c))
            self.category_bar.addWidget(b)
        self.category_bar.addStretch()

    def set_category(self, cat):
        self.current_category = cat
        self.load_categories()
        self.load_products()

    def load_products(self):
        while self.product_grid.count():
            item = self.product_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        query = '''SELECT p.*,COALESCE(c.name,'OTROS') category_name
                   FROM products p LEFT JOIN categories c ON c.id=p.category_id
                   WHERE p.active=1 AND p.show_in_sales=1'''
        params = []
        if self.current_category != 'TODOS':
            query += ' AND c.name=?'
            params.append(self.current_category)
        query += ' ORDER BY p.sort_order,p.name'
        with db() as conn:
            rows = conn.execute(query, params).fetchall()
        for i, product in enumerate(rows):
            final, _ = price_with_offer(product)
            badge = display_offer_for_product(product['id'])
            cat = product['category_name']
            accent, soft, icon = CATEGORY_STYLE.get(cat, ('#68717d', '#f1f3f5', '🛍️'))
            price_text = money(final)
            text = f'{icon}\n{product["name"]}\n{price_text}'
            if badge:
                typ = badge['offer_type']
                if typ == '2X1':
                    offer_txt = f"{badge['trigger_qty']}x{badge['pay_qty']}"
                elif typ == 'CANTIDAD_PRECIO':
                    offer_txt = f"{badge['bundle_qty']} por {money(badge['value'])}"
                else:
                    offer_txt = 'OFERTA'
                text += f'\n🔥 {offer_txt}'
            btn = QPushButton(text)
            btn.setMinimumSize(180, 142)
            btn.setStyleSheet(f'''QPushButton{{background:{accent};color:white;font-size:18px;font-weight:950;border:3px solid rgba(255,255,255,.85);
                                      border-radius:18px;text-align:center;padding:10px;}}
                                    QPushButton:hover{{border:4px solid #33232b;}}
                                    QPushButton:pressed{{border:5px solid #33232b;}}''')
            btn.clicked.connect(lambda _, p=dict(product): self.add_product(p))
            self.product_grid.addWidget(btn, i // 3, i % 3)
        self.product_grid.setRowStretch((len(rows) + 2) // 3, 1)

    def add_product(self, product):
        flavors = []
        if int(product.get('max_flavors', 0)) > 0:
            dlg = FlavorDialog(product['name'], int(product['max_flavors']), self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            flavors = dlg.selected
        final, offer = price_with_offer(product)
        self.cart.append({
            'product_id': product['id'], 'name': product['name'], 'base_price': float(product['price']),
            'final_price': float(final), 'offer_id': offer['id'] if offer else None,
            'offer_name': offer['name'] if offer else None, 'flavors': flavors, 'quantity': 1
        })
        apply_cart_offers(self.cart)
        self.refresh_cart()

    def refresh_cart(self):
        apply_cart_offers(self.cart)
        self.cart_list.clear()
        total = 0
        for item in self.cart:
            flavors = f"\n   🍨 {', '.join(item['flavors'])}" if item['flavors'] else ''
            offer = f"\n   🔥 {item['offer_name']}" if item.get('offer_name') else ''
            price = 'GRATIS' if item['final_price'] == 0 else money(item['final_price'])
            self.cart_list.addItem(QListWidgetItem(f"{item['name']}   ·   {price}{offer}{flavors}"))
            total += item['final_price']
        manual_amount = total * max(0.0, min(float(self.manual_discount_percent or 0), 100.0)) / 100.0
        payable = max(total - manual_amount, 0.0)
        if self.manual_discount_percent:
            self.discount_label.setText(f'-{self.manual_discount_percent:g}%  ({money(manual_amount)})')
        else:
            self.discount_label.setText('Sin descuento manual')
        self.total_label.setText(f'TOTAL   {money(payable)}')
        self.pay_button.setEnabled(bool(self.cart))

    def remove_selected(self):
        row = self.cart_list.currentRow()
        if 0 <= row < len(self.cart):
            self.cart.pop(row)
            self.refresh_cart()

    def clear_cart(self):
        if self.cart and QMessageBox.question(self, 'Cancelar venta', '¿Vaciar toda la venta actual?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.cart.clear()
        self.manual_discount_percent = 0.0
        self.refresh_cart()

    def set_manual_discount(self):
        if not self.cart:
            QMessageBox.information(self, 'Descuento de venta', 'Primero cargá al menos un producto.')
            return

        apply_cart_offers(self.cart)
        subtotal = sum(float(item.get('final_price') or 0) for item in self.cart)
        value, ok = QInputDialog.getDouble(
            self,
            'Descuento de venta',
            'Porcentaje de descuento (%):',
            float(self.manual_discount_percent or 0),
            0.0, 100.0, 2
        )
        if not ok:
            return

        value = max(0.0, min(float(value), 100.0))
        if value == 0:
            self.manual_discount_percent = 0.0
            self.refresh_cart()
            QMessageBox.information(self, 'Descuento de venta', 'Se quitó el descuento manual de la venta.')
            return

        discount_amount = subtotal * value / 100.0
        final_total = max(subtotal - discount_amount, 0.0)
        operator_name = self.current_user.get('name', 'Operador')
        detail = (
            f'Operador: {operator_name}\n\n'
            f'Subtotal: {money(subtotal)}\n'
            f'Descuento: {value:g}%  (-{money(discount_amount)})\n'
            f'TOTAL CON DESCUENTO: {money(final_total)}\n\n'
            '¿Aplicar este descuento a la venta?'
        )
        answer = QMessageBox.question(
            self, 'Confirmar descuento', detail,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.manual_discount_percent = value
        self.refresh_cart()


    def redeem_points(self):
        if get_setting('loyalty_enabled', '1') != '1':
            QMessageBox.information(self, 'Puntos', 'El sistema de fidelidad está desactivado desde Administración → Fidelidad / Puntos.')
            return
        dlg = PointsRedemptionDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result_data:
            return
        data = dlg.result_data
        item = data['item']
        try:
            sale_id, total, earned = save_sale(
                [item], 'CANJE DE PUNTOS', user_id=int(self.current_user.get('id') or 1),
                customer_id=data['customer_id'],
                loyalty_reward_id=data['reward_id'],
                loyalty_points_redeemed=data['points_redeemed'],
                loyalty_discount=float(item['final_price'] or 0),
                loyalty_description='Canje directo: ' + data['reward_name']
            )
        except Exception as e:
            QMessageBox.critical(self, 'Canje de puntos', f'No se pudo registrar el canje.\n\n{e}')
            return

        with db() as conn:
            fresh = conn.execute('SELECT points FROM customers WHERE id=?', (data['customer_id'],)).fetchone()
            points_after = int(fresh['points'] or 0) if fresh else max(0, data['points_before'] - data['points_redeemed'])

        print_errors = []
        try:
            print_sale_ticket(sale_id, parent=self)
        except Exception as e:
            print_errors.append('Ticket de venta: ' + str(e))
        try:
            print_loyalty_ticket(sale_id, parent=self)
        except Exception as e:
            print_errors.append('Comprobante de puntos: ' + str(e))

        msg = (
            f"CANJE CONFIRMADO\n\nVenta #{sale_id} · TOTAL {money(total)}\n"
            f"Cliente: {data['customer_name']}\nTarjeta: {data['card']}\n"
            f"Beneficio: {data['reward_name']}\n"
            f"Puntos descontados: -{data['points_redeemed']}\nSaldo actual: {points_after} puntos"
        )
        if print_errors:
            msg += '\n\nEl canje quedó guardado, pero hubo un problema de impresión:\n• ' + '\n• '.join(print_errors)
            QMessageBox.warning(self, 'Canje confirmado', msg)
        else:
            msg += '\n\nSe enviaron a imprimir el ticket de venta por $0 y el comprobante de canje.'
            QMessageBox.information(self, 'Canje confirmado', msg)
        self.load_products()

    def checkout(self):
        if not self.cart:
            QMessageBox.information(self, 'Venta', 'Primero cargá al menos un producto.')
            return
        apply_cart_offers(self.cart)
        cart_total = sum(float(x['final_price']) for x in self.cart)
        manual_discount_amount = cart_total * max(0.0, min(float(self.manual_discount_percent or 0), 100.0)) / 100.0
        payable_before_loyalty = max(cart_total - manual_discount_amount, 0.0)

        pay = PaymentDialog(payable_before_loyalty, self)
        if pay.exec() != QDialog.DialogCode.Accepted or not pay.payment_method:
            return
        payment_method = pay.payment_method

        loyalty = {'customer_id': None, 'reward_id': None, 'points_redeemed': 0, 'discount': 0.0, 'description': ''}
        if get_setting('loyalty_enabled', '1') == '1':
            dlg = LoyaltyCheckoutDialog(self.cart, payable_before_loyalty, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            loyalty = dlg.result_data or loyalty

        try:
            sale_id, total, earned = save_sale(
                self.cart, payment_method, user_id=int(self.current_user.get('id') or 1),
                manual_discount_percent=self.manual_discount_percent,
                customer_id=loyalty['customer_id'], loyalty_reward_id=loyalty['reward_id'],
                loyalty_points_redeemed=loyalty['points_redeemed'], loyalty_discount=loyalty['discount'],
                loyalty_description=loyalty['description']
            )
        except Exception as e:
            QMessageBox.critical(self, 'Venta', f'No se pudo guardar la venta.\n\n{e}')
            return

        msg = f'Venta #{sale_id}\nTotal: {money(total)}\nPago: {payment_method}'
        if earned:
            msg += f'\nPuntos sumados: +{earned}'
        should_print = get_setting('auto_print_sale', '0') == '1'
        if not should_print:
            should_print = QMessageBox.question(
                self, 'Venta confirmada', msg + '\n\n¿Imprimir ticket?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes
        if should_print:
            main_printed = False
            loyalty_printed = False
            loyalty_error = None
            try:
                print_sale_ticket(sale_id, parent=self)
                main_printed = True
            except Exception as e:
                QMessageBox.warning(self, 'Ticket', f'La venta se guardó, pero no se pudo imprimir el ticket de venta.\n\n{e}')

            if main_printed and loyalty['customer_id'] and (earned or loyalty['points_redeemed']):
                if get_setting('auto_print_loyalty_receipt', '1') == '1':
                    try:
                        print_loyalty_ticket(sale_id, parent=self)
                        loyalty_printed = True
                    except Exception as e:
                        loyalty_error = str(e)

            if main_printed:
                extra = '\n\nTicket de venta enviado a la impresora.'
                if loyalty_printed:
                    extra += '\nComprobante de puntos enviado por separado.'
                elif loyalty_error:
                    extra += f'\n\nEl ticket de venta salió, pero el comprobante de puntos no pudo imprimirse:\n{loyalty_error}'
                QMessageBox.information(self, 'Venta confirmada', msg + extra)
        else:
            QMessageBox.information(self, 'Venta confirmada', msg)
        self.cart.clear()
        self.manual_discount_percent = 0.0
        self.refresh_cart()
        self.load_products()
