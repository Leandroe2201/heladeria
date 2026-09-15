from datetime import datetime
from math import floor
import secrets
from app.database import db
from app.settings_service import get_setting


def normalize_dni(value):
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def _new_card_number(conn):
    for _ in range(200):
        card = str(10_000_000 + secrets.randbelow(90_000_000))
        exists = conn.execute('SELECT 1 FROM customers WHERE loyalty_card_number=? LIMIT 1', (card,)).fetchone()
        if not exists:
            return card
    raise RuntimeError('No se pudo generar un número de tarjeta único.')


def ensure_customer_card(customer_id, conn=None):
    own = conn is None
    if own:
        from app.database import connect
        conn = connect()
    try:
        row = conn.execute('SELECT id,loyalty_card_number,loyalty_joined_at FROM customers WHERE id=?', (customer_id,)).fetchone()
        if not row:
            raise ValueError('Cliente inexistente.')
        card = str(row['loyalty_card_number'] or '').strip()
        if len(card) == 8 and card.isdigit():
            return card
        card = _new_card_number(conn)
        now = datetime.now().isoformat(timespec='seconds')
        conn.execute('UPDATE customers SET loyalty_card_number=?, loyalty_joined_at=COALESCE(loyalty_joined_at,?) WHERE id=?', (card, now, customer_id))
        if own:
            conn.commit()
        return card
    finally:
        if own:
            conn.close()



def regenerate_customer_card(customer_id, reason='EXTRAVIO / REEMPLAZO', actor='SISTEMA'):
    customer_id = int(customer_id)
    reason = str(reason or 'EXTRAVIO / REEMPLAZO').strip()[:500]
    actor = str(actor or 'SISTEMA').strip()[:120]
    now = datetime.now().isoformat(timespec='seconds')
    with db() as conn:
        row = conn.execute('SELECT id,name,dni,loyalty_card_number,points FROM customers WHERE id=?', (customer_id,)).fetchone()
        if not row:
            raise ValueError('Cliente inexistente.')
        old_card = str(row['loyalty_card_number'] or '').strip()
        new_card = _new_card_number(conn)
        conn.execute('UPDATE customers SET loyalty_card_number=?, loyalty_joined_at=COALESCE(loyalty_joined_at,?) WHERE id=?', (new_card, now, customer_id))
        conn.execute('INSERT INTO loyalty_card_history(customer_id,old_card_number,new_card_number,reason,created_at,actor) VALUES (?,?,?,?,?,?)', (customer_id, old_card or None, new_card, reason, now, actor))
        conn.execute('INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)', (now, actor, 'REGENERAR_TARJETA_FIDELIDAD', f'Cliente {row["name"]} · DNI {row["dni"] or ""} · {old_card or "SIN TARJETA"} → {new_card} · {reason} · puntos conservados {int(row["points"] or 0)}'))
        points = int(row['points'] or 0)
    return {'customer_id': customer_id, 'old_card': old_card, 'new_card': new_card, 'points': points, 'reason': reason}

def get_customer_by_dni(dni):
    dni = normalize_dni(dni)
    if not dni:
        return None
    with db() as conn:
        return conn.execute('SELECT * FROM customers WHERE dni=? LIMIT 1', (dni,)).fetchone()


def create_or_update_customer(dni, name='', phone='', address=''):
    dni = normalize_dni(dni)
    if not dni:
        raise ValueError('Ingresá un DNI válido.')
    now = datetime.now().isoformat(timespec='seconds')
    with db() as conn:
        row = conn.execute('SELECT * FROM customers WHERE dni=? LIMIT 1', (dni,)).fetchone()
        if row:
            if name or phone or address:
                conn.execute('''UPDATE customers SET
                    name=CASE WHEN ?<>'' THEN ? ELSE name END,
                    phone=CASE WHEN ?<>'' THEN ? ELSE phone END,
                    address=CASE WHEN ?<>'' THEN ? ELSE address END
                    WHERE id=?''', (name, name, phone, phone, address, address, row['id']))
            cid = row['id']
        else:
            display_name = name.strip() or f'Cliente DNI {dni}'
            cur = conn.execute('''INSERT INTO customers(name,phone,address,dni,loyalty_joined_at,points)
                                  VALUES (?,?,?,?,?,0)''',
                               (display_name, phone.strip(), address.strip(), dni, now))
            cid = cur.lastrowid
        ensure_customer_card(cid, conn)
        return conn.execute('SELECT * FROM customers WHERE id=?', (cid,)).fetchone()


def points_for_amount(amount):
    if get_setting('loyalty_enabled', '1') != '1':
        return 0
    try:
        step_amount = max(float(get_setting('loyalty_amount_per_point', '1000')), 1.0)
        points_per_step = max(int(float(get_setting('loyalty_points_per_step', '1'))), 1)
        return int(floor(max(float(amount), 0.0) / step_amount) * points_per_step)
    except Exception:
        return 0


def list_rewards(active_only=True):
    where = 'WHERE r.active=1' if active_only else ''
    with db() as conn:
        return conn.execute(f'''SELECT r.*, COALESCE(p.name,'') product_name
                               FROM loyalty_rewards r
                               LEFT JOIN products p ON p.id=r.product_id
                               {where}
                               ORDER BY r.points_cost, r.name''').fetchall()


def eligible_rewards(customer_points):
    return [r for r in list_rewards(True) if int(r['points_cost']) <= int(customer_points)]


def reward_discount(reward, items, current_total):
    if not reward:
        return 0.0, ''
    total = max(float(current_total), 0.0)
    typ = str(reward['reward_type'] or '').upper()
    value = float(reward['value'] or 0)
    if typ == 'DESCUENTO_FIJO':
        discount = min(total, max(value, 0.0))
        return discount, reward['name']
    if typ == 'PORCENTAJE':
        discount = min(total, total * max(min(value, 100.0), 0.0) / 100.0)
        return discount, reward['name']
    if typ == 'PRODUCTO_GRATIS':
        pid = reward['product_id']
        matches = [float(i.get('final_price', 0)) for i in items if int(i.get('product_id') or 0) == int(pid or 0)]
        discount = min(total, min(matches) if matches else 0.0)
        return discount, reward['name']
    return 0.0, reward['name']


def ensure_seed_reward():
    with db() as conn:
        count = conn.execute('SELECT COUNT(*) n FROM loyalty_rewards').fetchone()['n']
        if count:
            return
        p = conn.execute("SELECT id FROM products WHERE name='1/4 KG' LIMIT 1").fetchone()
        if p:
            conn.execute('''INSERT INTO loyalty_rewards(name,points_cost,reward_type,value,product_id,active,notes)
                            VALUES (?,?,?,?,?,1,?)''',
                         ('1/4 KG sin cargo', 30, 'PRODUCTO_GRATIS', 0, p['id'], 'Ejemplo editable'))
        conn.execute('''INSERT INTO loyalty_rewards(name,points_cost,reward_type,value,active,notes)
                        VALUES (?,?,?,?,1,?)''', ('$ 3.000 de descuento', 20, 'DESCUENTO_FIJO', 3000, 'Ejemplo editable'))
