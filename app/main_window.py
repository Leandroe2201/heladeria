from PyQt6.QtWidgets import QMainWindow, QStackedWidget, QWidget, QVBoxLayout, QGridLayout, QPushButton, QLabel, QInputDialog, QMessageBox, QApplication
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QShortcut, QKeySequence

from app.config import APP_NAME, DEFAULT_ADMIN_PIN
from app.styles import APP_STYLE, CARD_COLORS
from app.modules.ventas import SalesPage
from app.modules.productos import ProductosPage
from app.modules.sabores import SaboresPage
from app.modules.stock import StockPage
from app.modules.ofertas import OfertasPage
from app.modules.pedidos import PedidosPage
from app.modules.clientes import ClientesPage
from app.modules.proveedores import ProveedoresPage
from app.modules.compras import ComprasPage
from app.modules.gastos import GastosPage
from app.modules.caja import CajaPage
from app.modules.reportes import ReportesPage
from app.modules.usuarios import UsuariosPage
from app.modules.configuracion import ConfiguracionPage
from app.modules.impresora import ImpresoraPage
from app.modules.web_panel import WebPanelPage
from app.modules.fidelidad import FidelidadPage
from app.modules.chat import ChatPage
from app.web_manager import WebServerManager
from app.settings_service import get_setting
from app.database import db
from app.services.ticket_service import print_order_ticket
from app.services.mercadopago_service import sync_local_order


class OptionsPage(QWidget):
    def __init__(self, open_module, back_to_sales):
        super().__init__()
        root = QVBoxLayout(self); root.setContentsMargins(28,24,28,28); root.setSpacing(18)
        title = QLabel("⚙ Opciones / Administración")
        title.setStyleSheet("font-size:30px;font-weight:900;color:#51283a;")
        sub = QLabel("Todo lo que administra la heladería está acá. La pantalla de venta queda simple para el cajero.")
        sub.setWordWrap(True); sub.setStyleSheet("font-size:15px;color:#7a6670;")
        root.addWidget(title); root.addWidget(sub)

        grid = QGridLayout(); grid.setSpacing(14)
        modules = [
            ("📦 Productos","productos"),("🍨 Sabores / Gustos","sabores"),("📊 Stock","stock"),("🏷️ Ofertas","ofertas"),
            ("📲 Pedidos Web / Delivery","pedidos"),("⭐ Fidelidad / Puntos","fidelidad"),("👥 Clientes","clientes"),("🚚 Proveedores","proveedores"),("🛒 Compras","compras"),
            ("💸 Gastos","gastos"),("💰 Caja","caja"),("📈 Reportes","reportes"),("👤 Usuarios","usuarios"),
            ("🖨 Tickets / Impresora","impresora"),("🌐 Panel Web / Control remoto","web"),("⚙ Configuración","configuracion"),
        ]
        for i,(label,key) in enumerate(modules):
            b=QPushButton(label); b.setMinimumSize(185,90); b.setStyleSheet(f"background:{CARD_COLORS[i % len(CARD_COLORS)]};color:#2f2530;font-size:17px;font-weight:800;")
            b.clicked.connect(lambda _, k=key: open_module(k)); grid.addWidget(b,i//4,i%4)
        root.addLayout(grid)
        root.addStretch()
        back=QPushButton("← Volver a Ventas"); back.setMinimumHeight(54); back.setStyleSheet("background:#e55b88;color:white;font-size:18px;"); back.clicked.connect(back_to_sales); root.addWidget(back)


class MainWindow(QMainWindow):
    def __init__(self, current_user):
        super().__init__()
        self.current_user = current_user or {'id':1,'name':'Administrador','role':'ADMIN'}
        self.setWindowTitle('Heladería · ' + get_setting('store_name', 'Dulces Momentos'))
        self.resize(1280, 820)
        self.setMinimumSize(1050, 700)
        self.setStyleSheet(APP_STYLE)
        self.web_manager = WebServerManager(self)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.sales = SalesPage(self.ask_admin, self.open_orders_from_sales, self.open_cash_from_sales, self.open_chat_from_sales, self.current_user)
        self.options = OptionsPage(self.open_module, self.show_sales)
        self.stack.addWidget(self.sales)
        self.stack.addWidget(self.options)
        self.stack.setCurrentWidget(self.sales)
        if get_setting("web_auto_start","0") == "1":
            QTimer.singleShot(500, self.web_manager.start)

        # V19 · ESC vuelve a Ventas desde cualquier módulo del sistema central.
        self.escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.escape_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.escape_shortcut.activated.connect(self.handle_escape)

        # V19 · escucha pedidos Web nuevos en la misma base.
        with db() as conn:
            row = conn.execute("SELECT COALESCE(MAX(id),0) max_id FROM orders WHERE COALESCE(source,'MANUAL')='WEB'").fetchone()
            self._last_web_order_id = int(row['max_id'] or 0) if row else 0
        self.web_order_monitor = QTimer(self)
        self.web_order_monitor.setInterval(1600)
        self.web_order_monitor.timeout.connect(self.check_new_web_orders)
        self.web_order_monitor.start()
        self.mp_monitor = QTimer(self)
        self.mp_monitor.setInterval(4500)
        self.mp_monitor.timeout.connect(self.sync_pending_mercadopago)
        self.mp_monitor.start()

    def handle_escape(self):
        # Los diálogos (gustos, cobro, etc.) manejan ESC por sí mismos.
        # En páginas del sistema, ESC siempre vuelve a la pantalla principal de Ventas.
        if self.stack.currentWidget() is not self.sales:
            self.show_sales()

    def _play_new_order_sound(self):
        if get_setting('web_order_sound_enabled', '1') != '1':
            return
        try:
            import winsound
            winsound.Beep(1250, 180)
            winsound.Beep(1550, 220)
        except Exception:
            try:
                QApplication.beep(); QApplication.beep()
            except Exception:
                pass

    def check_new_web_orders(self):
        try:
            with db() as conn:
                rows = conn.execute("""SELECT o.id,o.total,o.order_type,o.reception_printed_at,o.central_notified_at,o.status,
                                      COALESCE(c.name,'Cliente') customer_name
                                      FROM orders o LEFT JOIN customers c ON c.id=o.customer_id
                                      WHERE COALESCE(o.source,'MANUAL')='WEB'
                                        AND (o.id>? OR (o.central_notified_at IS NULL
                                             AND UPPER(COALESCE(o.status,'')) NOT IN ('ENTREGADO','CANCELADO','RECHAZADO')
                                             AND datetime(COALESCE(o.created_at,datetime('now','localtime'))) >= datetime('now','localtime','-12 hours')))
                                      ORDER BY o.id""", (int(self._last_web_order_id),)).fetchall()
            if not rows:
                return
            for row in rows:
                order = dict(row)
                self._last_web_order_id = max(self._last_web_order_id, int(order['id']))
                self._play_new_order_sound()
                try:
                    self.sales.show_web_order_notification(order)
                except Exception:
                    pass
                try:
                    QApplication.alert(self, 5000)
                except Exception:
                    pass
                printed = bool(order.get('reception_printed_at'))
                if (not printed and get_setting('web_order_central_auto_print','1') == '1'):
                    try:
                        print_order_ticket(int(order['id']), parent=self)
                        with db() as conn:
                            conn.execute("UPDATE orders SET reception_printed_at=? WHERE id=?",
                                         (__import__('datetime').datetime.now().isoformat(timespec='seconds'), int(order['id'])))
                    except Exception as exc:
                        with db() as conn:
                            conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (datetime('now','localtime'),?,?,?)",
                                         (self.current_user.get('name','SISTEMA CENTRAL'),'IMPRESION_PEDIDO_WEB_FALLO',f"Pedido #{order['id']}: {exc}"))
                with db() as conn:
                    conn.execute("UPDATE orders SET central_notified_at=? WHERE id=?",
                                 (__import__('datetime').datetime.now().isoformat(timespec='seconds'), int(order['id'])))
        except Exception:
            # El monitor nunca debe cerrar la caja si hay un error de base/impresora.
            return

    def sync_pending_mercadopago(self):
        try:
            with db() as conn:
                rows = conn.execute("""SELECT id FROM orders
                                     WHERE UPPER(COALESCE(payment_method,'')) IN ('MERCADO PAGO','MERCADOPAGO','MERCADO_PAGO')
                                     AND COALESCE(payment_status,'') IN ('PENDIENTE_MERCADOPAGO','MP_ERROR_GENERACION')
                                     AND UPPER(COALESCE(status,'')) NOT IN ('ENTREGADO','CANCELADO','RECHAZADO')
                                     AND COALESCE(mercadopago_order_id,'')<>''
                                     ORDER BY id DESC LIMIT 10""").fetchall()
            for row in rows:
                try:
                    sync_local_order(int(row['id']), auto_transition=True)
                except Exception:
                    pass
        except Exception:
            pass

    def show_sales(self):
        self.sales.load_products()
        self.sales.refresh_business_name()
        self.setWindowTitle('Heladería · ' + get_setting('store_name', 'Dulces Momentos'))
        self.stack.setCurrentWidget(self.sales)

    def ask_admin(self):
        if str(self.current_user.get('role','')).upper() != 'ADMIN':
            QMessageBox.warning(self, 'Acceso restringido',
                                f"{self.current_user.get('name','Operador')} no tiene permisos de administración.")
            return
        self.stack.setCurrentWidget(self.options)

    def show_options(self):
        self.stack.setCurrentWidget(self.options)



    def open_cash_from_sales(self):
        limited = str(self.current_user.get('role','')).upper() != 'ADMIN'
        page = CajaPage(self.show_sales, current_user=self.current_user, limited=limited)
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

    def open_chat_from_sales(self):
        page = ChatPage(self.show_sales, self.current_user)
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

    def open_orders_from_sales(self):
        page = PedidosPage(self.show_sales, current_user=self.current_user)
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

    def open_module(self, key):
        if str(self.current_user.get('role','')).upper() != 'ADMIN':
            QMessageBox.warning(self, 'Acceso restringido', 'Este módulo requiere permisos de administrador.')
            return
        factories = {
            "productos": ProductosPage,
            "sabores": SaboresPage,
            "stock": StockPage,
            "ofertas": OfertasPage,
            "pedidos": PedidosPage,
            "fidelidad": FidelidadPage,
            "clientes": ClientesPage,
            "proveedores": ProveedoresPage,
            "compras": ComprasPage,
            "gastos": GastosPage,
            "caja": CajaPage,
            "reportes": ReportesPage,
            "usuarios": UsuariosPage,
            "configuracion": ConfiguracionPage,
            "impresora": ImpresoraPage,
        }
        if key == "web":
            page = WebPanelPage(self.show_options, self.web_manager)
        elif key == "caja":
            page = CajaPage(self.show_options, current_user=self.current_user, limited=False)
        elif key == "pedidos":
            page = PedidosPage(self.show_options, current_user=self.current_user)
        else:
            page = factories[key](self.show_options)
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

    def closeEvent(self, event):
        try:
            self.web_manager.stop()
        finally:
            event.accept()
