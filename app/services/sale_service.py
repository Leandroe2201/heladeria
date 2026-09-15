from datetime import datetime
from app.database import db
from app.services.offer_service import apply_cart_offers
from app.services.loyalty_service import points_for_amount


def current_open_session(conn):
    return conn.execute("SELECT * FROM cash_sessions WHERE status='ABIERTA' ORDER BY id DESC LIMIT 1").fetchone()


def save_sale(items, payment_method='EFECTIVO', user_id=1, notes='', customer_id=None,
              loyalty_reward_id=None, loyalty_points_redeemed=0, loyalty_discount=0.0,
              loyalty_description='', manual_discount_percent=0.0):
    apply_cart_offers(items)
    subtotal = sum(float(i['base_price']) * float(i.get('quantity', 1)) for i in items)
    cart_total = sum(float(i['final_price']) * float(i.get('quantity', 1)) for i in items)
    manual_discount_percent = max(0.0, min(float(manual_discount_percent or 0), 100.0))
    manual_discount_amount = min(cart_total, cart_total * manual_discount_percent / 100.0)
    after_manual = max(cart_total - manual_discount_amount, 0.0)
    loyalty_discount = min(max(float(loyalty_discount or 0), 0.0), after_manual)
    total = max(after_manual - loyalty_discount, 0.0)
    discount = subtotal - total
    points_earned = points_for_amount(total) if customer_id else 0
    points_redeemed = max(int(loyalty_points_redeemed or 0), 0)
    now = datetime.now().isoformat(timespec='seconds')
    with db() as conn:
        session = current_open_session(conn)
        session_id = session['id'] if session else None
        if customer_id:
            cust = conn.execute('SELECT points FROM customers WHERE id=?', (customer_id,)).fetchone()
            if not cust:
                raise ValueError('El cliente seleccionado ya no existe.')
            current_points = int(cust['points'] or 0)
            if points_redeemed > current_points:
                raise ValueError('El cliente no tiene puntos suficientes para ese canje.')
        cur = conn.execute('''
            INSERT INTO sales(created_at,user_id,customer_id,cash_session_id,subtotal,discount,total,payment_method,notes,
                              loyalty_points_earned,loyalty_points_redeemed,loyalty_reward_id,loyalty_discount,
                              manual_discount_percent,manual_discount_amount)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (now, user_id, customer_id, session_id, subtotal, discount, total, payment_method, notes,
              points_earned, points_redeemed, loyalty_reward_id, loyalty_discount,
              manual_discount_percent, manual_discount_amount))
        sale_id = cur.lastrowid
        for i in items:
            conn.execute('''
                INSERT INTO sale_items(sale_id,product_id,quantity,unit_price,line_total,offer_id,flavor_text)
                VALUES (?,?,?,?,?,?,?)
            ''', (
                sale_id, i['product_id'], i.get('quantity', 1), i['final_price'],
                i['final_price'] * i.get('quantity', 1),
                i.get('offer_id'), ', '.join(i.get('flavors', []))
            ))
        conn.execute('''INSERT INTO cash_movements(created_at,session_id,movement_type,concept,amount,payment_method,reference_type,reference_id,user_id)
                        VALUES (?,?,?,?,?,?,?,?,?)''',
                     (now, session_id, 'VENTA', f'Venta #{sale_id}', total, payment_method, 'SALE', sale_id, user_id))
        if customer_id:
            cust = conn.execute('SELECT points FROM customers WHERE id=?', (customer_id,)).fetchone()
            balance = int(cust['points'] or 0)
            if points_redeemed:
                balance -= points_redeemed
                conn.execute('UPDATE customers SET points=? WHERE id=?', (balance, customer_id))
                conn.execute('''INSERT INTO loyalty_movements(created_at,customer_id,sale_id,movement_type,points,description,balance_after)
                                VALUES (?,?,?,?,?,?,?)''',
                             (now, customer_id, sale_id, 'CANJE', -points_redeemed,
                              loyalty_description or 'Canje de beneficio', balance))
            if points_earned:
                balance += points_earned
                conn.execute('UPDATE customers SET points=? WHERE id=?', (balance, customer_id))
                conn.execute('''INSERT INTO loyalty_movements(created_at,customer_id,sale_id,movement_type,points,description,balance_after)
                                VALUES (?,?,?,?,?,?,?)''',
                             (now, customer_id, sale_id, 'ACUMULACION', points_earned,
                              f'Puntos por venta #{sale_id}', balance))
        u = conn.execute('SELECT name FROM users WHERE id=?', (user_id,)).fetchone()
        user_name = u['name'] if u else f'Usuario {user_id}'
        detail = f'Venta #{sale_id} por ${total:,.2f}'
        if manual_discount_percent:
            detail += f' · descuento {manual_discount_percent:g}%'
        conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",
                     (now, user_name, 'VENTA', detail))
    return sale_id, total, points_earned
