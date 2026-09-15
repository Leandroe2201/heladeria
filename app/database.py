import sqlite3
import secrets
from datetime import datetime
from contextlib import contextmanager
from .config import DB_PATH, DATA_DIR


def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _ensure_column(conn, table, column_sql):
    name = column_sql.split()[0]
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_sql}")



def _normalize_dni_value(value):
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    return digits or None


def _next_random_card(conn, used=None):
    used = used or set()
    for _ in range(300):
        card = str(10_000_000 + secrets.randbelow(90_000_000))
        if card in used:
            continue
        if not conn.execute("SELECT 1 FROM customers WHERE loyalty_card_number=? LIMIT 1", (card,)).fetchone():
            return card
    raise RuntimeError('No se pudo generar una tarjeta de fidelidad única.')


def _migrate_customers_v10(conn):
    conn.execute("DROP INDEX IF EXISTS idx_customers_dni_unique")
    seen = {}
    rows = conn.execute("SELECT id,dni,notes FROM customers ORDER BY id").fetchall()
    for row in rows:
        dni = _normalize_dni_value(row['dni'])
        if not dni:
            conn.execute("UPDATE customers SET dni=NULL WHERE id=?", (row['id'],))
            continue
        if dni in seen:
            note = str(row['notes'] or '').strip()
            extra = f"DNI duplicado {dni} detectado en migración V10; revisar registro."
            note = (note + (' | ' if note else '') + extra)[:1800]
            conn.execute("UPDATE customers SET dni=NULL, notes=? WHERE id=?", (note, row['id']))
            conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (datetime('now','localtime'),'SISTEMA','DNI_DUPLICADO_V10',?)", (f"Cliente ID {row['id']} quedó sin DNI; el DNI {dni} permanece en cliente ID {seen[dni]}",))
        else:
            seen[dni] = row['id']
            conn.execute("UPDATE customers SET dni=? WHERE id=?", (dni, row['id']))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_dni_unique ON customers(dni) WHERE dni IS NOT NULL AND TRIM(dni) <> ''")

    conn.execute("DROP INDEX IF EXISTS idx_customers_card_unique")
    used = set()
    rows = conn.execute("SELECT id,loyalty_card_number,dni FROM customers ORDER BY id").fetchall()
    for row in rows:
        current = str(row['loyalty_card_number'] or '').strip()
        valid = len(current) == 8 and current.isdigit() and current not in used
        wants_card = bool(row['dni']) or bool(current)
        if wants_card and not valid:
            card = _next_random_card(conn, used)
            conn.execute("UPDATE customers SET loyalty_card_number=?, loyalty_joined_at=COALESCE(loyalty_joined_at,datetime('now','localtime')) WHERE id=?", (card, row['id']))
            used.add(card)
        elif valid:
            used.add(current)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_card_unique ON customers(loyalty_card_number) WHERE loyalty_card_number IS NOT NULL AND TRIM(loyalty_card_number) <> ''")


def reset_business_data_preserve_config():
    """Borra datos operativos y conserva configuración/credenciales y usuarios."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    backup_dir = DATA_DIR / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"heladeria_antes_de_limpiar_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"

    source = connect()
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()

    tables = [
        'order_claims', 'order_status_events', 'order_items', 'orders',
        'loyalty_card_history', 'loyalty_movements', 'portal_accounts',
        'sale_items', 'sales', 'offer_items', 'offers',
        'cash_movements', 'cash_sessions', 'purchases', 'expenses',
        'internal_messages', 'audit_log',
        'loyalty_rewards', 'products', 'flavors', 'stock_items',
        'categories', 'suppliers', 'customers',
    ]
    counts = {}
    conn = connect()
    try:
        conn.execute('PRAGMA foreign_keys = OFF')
        for table in tables:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists:
                continue
            counts[table] = int(conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] or 0)
            conn.execute(f'DELETE FROM {table}')
        try:
            placeholders = ','.join('?' for _ in tables)
            conn.execute(f'DELETE FROM sqlite_sequence WHERE name IN ({placeholders})', tables)
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.execute('PRAGMA foreign_keys = ON')
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    with db() as conn:
        mp = {r['key']: r['value'] for r in conn.execute(
            "SELECT key,value FROM settings WHERE key LIKE 'mercadopago_%' ORDER BY key"
        ).fetchall()}
    return {'backup_path': str(backup_path), 'counts': counts, 'mercadopago_preserved': mp}


def init_database():
    first_run = not DB_PATH.exists()
    with db() as conn:
        conn.executescript(SCHEMA)
        # Migraciones compatibles con la primera versión entregada.
        _ensure_column(conn, "offers", "trigger_qty INTEGER NOT NULL DEFAULT 2")
        _ensure_column(conn, "offers", "pay_qty INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "offers", "bundle_qty INTEGER NOT NULL DEFAULT 2")
        _ensure_column(conn, "sales", "cash_session_id INTEGER")
        _ensure_column(conn, "orders", "user_id INTEGER")
        # Fidelidad / puntos (migración V4).
        _ensure_column(conn, "customers", "dni TEXT")
        _ensure_column(conn, "customers", "loyalty_card_number TEXT")
        _ensure_column(conn, "customers", "loyalty_joined_at TEXT")
        _ensure_column(conn, "sales", "loyalty_points_earned INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "sales", "loyalty_points_redeemed INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "sales", "loyalty_reward_id INTEGER")
        _ensure_column(conn, "sales", "loyalty_discount REAL NOT NULL DEFAULT 0")
        # V9: descuentos manuales, portal cliente y chat interno.
        _ensure_column(conn, "sales", "manual_discount_percent REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "sales", "manual_discount_amount REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "customers", "portal_token TEXT")
        # V13: perfil de delivery y pedidos Web.
        _ensure_column(conn, "customers", "address_lat REAL")
        _ensure_column(conn, "customers", "address_lng REAL")
        _ensure_column(conn, "customers", "address_verified_at TEXT")
        _ensure_column(conn, "customers", "address_zone_status TEXT")
        # V16: estado comercial del cliente y bloqueos temporales de pedidos.
        _ensure_column(conn, "customers", "customer_status TEXT NOT NULL DEFAULT 'ACTIVO'")
        _ensure_column(conn, "customers", "order_blocked_until TEXT")
        _ensure_column(conn, "customers", "order_block_reason TEXT")
        _ensure_column(conn, "orders", "source TEXT NOT NULL DEFAULT 'MANUAL'")
        _ensure_column(conn, "orders", "payment_status TEXT")
        _ensure_column(conn, "orders", "payment_proof_path TEXT")
        _ensure_column(conn, "orders", "cash_tendered REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "orders", "change_due REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "orders", "delivery_lat REAL")
        _ensure_column(conn, "orders", "delivery_lng REAL")
        _ensure_column(conn, "orders", "delivery_distance_km REAL")
        _ensure_column(conn, "orders", "zone_status TEXT")
        _ensure_column(conn, "orders", "approved_at TEXT")
        _ensure_column(conn, "orders", "approved_by TEXT")
        _ensure_column(conn, "orders", "sale_id INTEGER")
        # V14: seguimiento en tiempo real, rechazos/cancelaciones y reintegros.
        _ensure_column(conn, "orders", "status_updated_at TEXT")
        _ensure_column(conn, "orders", "payment_rejection_reason TEXT")
        _ensure_column(conn, "orders", "cancellation_reason TEXT")
        _ensure_column(conn, "orders", "refund_status TEXT")
        _ensure_column(conn, "orders", "refund_completed_at TEXT")
        _ensure_column(conn, "orders", "refund_notes TEXT")
        _ensure_column(conn, "orders", "delivered_at TEXT")
        _ensure_column(conn, "orders", "loyalty_points_earned INTEGER NOT NULL DEFAULT 0")
        # V18: costo de delivery y canjes de fidelidad en pedidos Web.
        _ensure_column(conn, "orders", "merchandise_subtotal REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "orders", "delivery_fee REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "orders", "loyalty_reward_id INTEGER")
        _ensure_column(conn, "orders", "loyalty_reward_name TEXT")
        _ensure_column(conn, "orders", "loyalty_points_redeemed INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "orders", "loyalty_discount REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "orders", "loyalty_redemption_refunded INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "order_items", "is_loyalty_reward INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "order_items", "loyalty_reward_id INTEGER")
        _ensure_column(conn, "loyalty_movements", "order_id INTEGER")
        # V19: notificaciones del sistema central + Mercado Pago QR dinámico.
        _ensure_column(conn, "orders", "central_notified_at TEXT")
        _ensure_column(conn, "orders", "reception_printed_at TEXT")
        _ensure_column(conn, "orders", "mercadopago_order_id TEXT")
        _ensure_column(conn, "orders", "mercadopago_payment_id TEXT")
        _ensure_column(conn, "orders", "mercadopago_qr_data TEXT")
        _ensure_column(conn, "orders", "mercadopago_status TEXT")
        _ensure_column(conn, "orders", "mercadopago_status_detail TEXT")
        _ensure_column(conn, "orders", "mercadopago_synced_at TEXT")
        _ensure_column(conn, "orders", "mercadopago_idempotency_key TEXT")
        # V21: Checkout Pro vía Orders API (redirect / checkout_url).
        _ensure_column(conn, "orders", "mercadopago_checkout_url TEXT")
        _ensure_column(conn, "orders", "mercadopago_flow TEXT")
        conn.execute("UPDATE customers SET customer_status='ACTIVO' WHERE customer_status IS NULL OR TRIM(customer_status)=''")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_portal_token ON customers(portal_token) WHERE portal_token IS NOT NULL AND TRIM(portal_token) <> ''")
        conn.execute('''CREATE TABLE IF NOT EXISTS portal_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL UNIQUE,
            email TEXT NOT NULL COLLATE NOCASE UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_login_at TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
        )''')
        _migrate_customers_v10(conn)
        # V23: historial de reemplazos/denuncias de tarjeta de fidelidad.
        conn.execute('''CREATE TABLE IF NOT EXISTS loyalty_card_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            old_card_number TEXT,
            new_card_number TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL,
            actor TEXT,
            FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_loyalty_card_history_customer ON loyalty_card_history(customer_id,id)")
        conn.execute('''CREATE TABLE IF NOT EXISTS internal_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            sender TEXT NOT NULL,
            sender_type TEXT NOT NULL DEFAULT 'SISTEMA',
            message TEXT NOT NULL,
            read_at TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS order_status_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            payment_status TEXT,
            created_at TEXT NOT NULL,
            actor TEXT,
            note TEXT,
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS order_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            order_item_id INTEGER,
            claim_type TEXT NOT NULL DEFAULT 'GUSTOS_INCORRECTOS',
            expected_flavors TEXT,
            received_flavor TEXT,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'PENDIENTE',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY(customer_id) REFERENCES customers(id),
            FOREIGN KEY(order_item_id) REFERENCES order_items(id)
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_order_events_order ON order_status_events(order_id,id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_order_claims_order ON order_claims(order_id,id)")
        conn.execute("UPDATE orders SET status_updated_at=COALESCE(status_updated_at,created_at) WHERE status_updated_at IS NULL OR TRIM(status_updated_at)='' ")
        # Normaliza estados heredados sin perder pedidos existentes.
        conn.execute("UPDATE orders SET status='EN PREPARACIÓN' WHERE UPPER(status)='APROBADO'")
        conn.execute("UPDATE orders SET status='PREPARADO' WHERE UPPER(status)='LISTO'")
        conn.execute("UPDATE orders SET status='ENVIADO' WHERE UPPER(status)='EN REPARTO'")
        conn.execute("UPDATE orders SET payment_status='PAGO_APROBADO' WHERE UPPER(payment_status)='APROBADO'")
        conn.execute("""INSERT INTO order_status_events(order_id,status,payment_status,created_at,actor,note)
                        SELECT o.id,o.status,COALESCE(o.payment_status,''),COALESCE(o.status_updated_at,o.created_at),
                               'MIGRACION V14','Estado existente al actualizar a V14'
                        FROM orders o
                        WHERE NOT EXISTS (SELECT 1 FROM order_status_events e WHERE e.order_id=o.id)""")
        # Operador solicitado. Se crea/actualiza sin tocar el administrador existente.
        roman = conn.execute("SELECT id FROM users WHERE UPPER(name)=UPPER(?) LIMIT 1", ('ROMAN DANIELA MIRIAM',)).fetchone()
        if roman:
            conn.execute("UPDATE users SET pin='4750', role='OPERADOR', active=1 WHERE id=?", (roman['id'],))
        else:
            conn.execute("INSERT INTO users(name,role,pin,active) VALUES (?,?,?,1)", ('ROMAN DANIELA MIRIAM','OPERADOR','4750'))
    if first_run:
        seed_database()
    from app.settings_service import ensure_default_settings
    ensure_default_settings()
    # V22: retiro en local vuelve a ser siempre sin cargo.
    with db() as conn:
        conn.execute("INSERT INTO settings(key,value) VALUES ('pickup_fee','0.00') ON CONFLICT(key) DO UPDATE SET value='0.00'")
    from app.services.loyalty_service import ensure_seed_reward
    ensure_seed_reward()


SCHEMA = r'''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'CAJERO',
    pin TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE,
    name TEXT NOT NULL,
    category_id INTEGER,
    price REAL NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0,
    max_flavors INTEGER NOT NULL DEFAULT 0,
    stock_control INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    show_in_sales INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(category_id) REFERENCES categories(id)
);

CREATE TABLE IF NOT EXISTS flavors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT 'CREMAS',
    stock_kg REAL NOT NULL DEFAULT 0,
    min_stock_kg REAL NOT NULL DEFAULT 1,
    premium INTEGER NOT NULL DEFAULT 0,
    premium_extra REAL NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    available INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS stock_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    unit TEXT NOT NULL DEFAULT 'u',
    quantity REAL NOT NULL DEFAULT 0,
    minimum REAL NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    address TEXT,
    birth_date TEXT,
    points INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    tax_id TEXT,
    phone TEXT,
    email TEXT,
    notes TEXT,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    product_id INTEGER,
    offer_type TEXT NOT NULL DEFAULT 'PRECIO_FIJO',
    value REAL NOT NULL DEFAULT 0,
    trigger_qty INTEGER NOT NULL DEFAULT 2,
    pay_qty INTEGER NOT NULL DEFAULT 1,
    bundle_qty INTEGER NOT NULL DEFAULT 2,
    start_date TEXT,
    end_date TEXT,
    days_csv TEXT DEFAULT '0,1,2,3,4,5,6',
    start_time TEXT DEFAULT '00:00',
    end_time TEXT DEFAULT '23:59',
    active INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    FOREIGN KEY(product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS offer_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(offer_id) REFERENCES offers(id) ON DELETE CASCADE,
    FOREIGN KEY(product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS cash_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    opening_amount REAL NOT NULL DEFAULT 0,
    closing_amount REAL,
    user_id INTEGER,
    status TEXT NOT NULL DEFAULT 'ABIERTA',
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS cash_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    session_id INTEGER,
    movement_type TEXT NOT NULL,
    concept TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    payment_method TEXT NOT NULL DEFAULT 'EFECTIVO',
    reference_type TEXT,
    reference_id INTEGER,
    user_id INTEGER,
    notes TEXT,
    FOREIGN KEY(session_id) REFERENCES cash_sessions(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    user_id INTEGER,
    customer_id INTEGER,
    cash_session_id INTEGER,
    subtotal REAL NOT NULL DEFAULT 0,
    discount REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    payment_method TEXT NOT NULL DEFAULT 'EFECTIVO',
    status TEXT NOT NULL DEFAULT 'CONFIRMADA',
    order_type TEXT NOT NULL DEFAULT 'MOSTRADOR',
    notes TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(customer_id) REFERENCES customers(id),
    FOREIGN KEY(cash_session_id) REFERENCES cash_sessions(id)
);

CREATE TABLE IF NOT EXISTS sale_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity REAL NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL DEFAULT 0,
    line_total REAL NOT NULL DEFAULT 0,
    offer_id INTEGER,
    flavor_text TEXT,
    FOREIGN KEY(sale_id) REFERENCES sales(id) ON DELETE CASCADE,
    FOREIGN KEY(product_id) REFERENCES products(id),
    FOREIGN KEY(offer_id) REFERENCES offers(id)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    customer_id INTEGER,
    user_id INTEGER,
    order_type TEXT NOT NULL DEFAULT 'MOSTRADOR',
    status TEXT NOT NULL DEFAULT 'NUEVO',
    total REAL NOT NULL DEFAULT 0,
    address TEXT,
    phone TEXT,
    payment_method TEXT,
    notes TEXT,
    FOREIGN KEY(customer_id) REFERENCES customers(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    product_name TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL DEFAULT 0,
    line_total REAL NOT NULL DEFAULT 0,
    flavor_text TEXT,
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY(product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    supplier_id INTEGER,
    total REAL NOT NULL DEFAULT 0,
    payment_method TEXT,
    notes TEXT,
    FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    payment_method TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    user_name TEXT,
    action TEXT NOT NULL,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS loyalty_rewards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    points_cost INTEGER NOT NULL DEFAULT 0,
    reward_type TEXT NOT NULL DEFAULT 'DESCUENTO_FIJO',
    value REAL NOT NULL DEFAULT 0,
    product_id INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    FOREIGN KEY(product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS loyalty_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    customer_id INTEGER NOT NULL,
    sale_id INTEGER,
    movement_type TEXT NOT NULL,
    points INTEGER NOT NULL,
    description TEXT,
    balance_after INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(customer_id) REFERENCES customers(id),
    FOREIGN KEY(sale_id) REFERENCES sales(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
'''


def seed_database():
    from datetime import date
    with db() as conn:
        conn.execute("INSERT INTO users(name, role, pin) VALUES (?,?,?)", ("Administrador", "ADMIN", "2580"))
        for category in ["HELADOS POR PESO", "CUCURUCHOS", "VASITOS", "BEBIDAS", "POSTRES", "OTROS"]:
            conn.execute("INSERT INTO categories(name) VALUES (?)", (category,))

        cats = {r["name"]: r["id"] for r in conn.execute("SELECT id,name FROM categories")}
        products = [
            ("HEL025", "1/4 KG", cats["HELADOS POR PESO"], 6000, 2400, 2, 0, 1),
            ("HEL050", "1/2 KG", cats["HELADOS POR PESO"], 9500, 4200, 3, 0, 2),
            ("HEL100", "1 KG", cats["HELADOS POR PESO"], 17500, 7800, 4, 0, 3),
            ("CUC001", "Cucurucho 1 bocha", cats["CUCURUCHOS"], 3500, 1200, 1, 0, 4),
            ("CUC002", "Cucurucho 2 bochas", cats["CUCURUCHOS"], 5000, 1900, 2, 0, 5),
            ("VAS001", "Vasito", cats["VASITOS"], 3200, 1100, 1, 0, 6),
            ("BEB001", "Agua", cats["BEBIDAS"], 2200, 900, 0, 1, 7),
            ("BEB002", "Gaseosa", cats["BEBIDAS"], 2800, 1200, 0, 1, 8),
        ]
        conn.executemany('''
            INSERT INTO products(code,name,category_id,price,cost,max_flavors,stock_control,sort_order)
            VALUES (?,?,?,?,?,?,?,?)
        ''', products)

        flavors = [
            ("Chocolate", "CREMAS", 8.4, 2.0, 0, 0),
            ("Dulce de leche", "CREMAS", 7.2, 2.0, 0, 0),
            ("Frutilla", "FRUTALES", 4.1, 1.5, 0, 0),
            ("Tramontana", "CREMAS", 5.3, 1.5, 0, 0),
            ("Limón", "FRUTALES", 2.6, 1.0, 0, 0),
            ("Crema americana", "CREMAS", 6.0, 1.5, 0, 0),
            ("Pistacho", "PREMIUM", 3.0, 1.0, 1, 700),
        ]
        conn.executemany('''
            INSERT INTO flavors(name,category,stock_kg,min_stock_kg,premium,premium_extra)
            VALUES (?,?,?,?,?,?)
        ''', flavors)

        stock = [
            ("Potes 1/4 KG", "u", 150, 30),
            ("Potes 1/2 KG", "u", 120, 25),
            ("Potes 1 KG", "u", 80, 15),
            ("Cucuruchos", "u", 250, 50),
            ("Cucharitas", "u", 1000, 200),
            ("Servilletas", "u", 1500, 300),
        ]
        conn.executemany("INSERT INTO stock_items(name,unit,quantity,minimum) VALUES (?,?,?,?)", stock)

        product_1kg = conn.execute("SELECT id FROM products WHERE name='1 KG'").fetchone()["id"]
        today = date.today().isoformat()
        conn.execute('''
            INSERT INTO offers(name,product_id,offer_type,value,start_date,end_date,days_csv,active,priority,notes)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        ''', ("Oferta lanzamiento 1 KG", product_1kg, "PRECIO_FIJO", 15900, today, None, "0,1,2,3,4,5,6", 1, 10, "Oferta de ejemplo editable"))
