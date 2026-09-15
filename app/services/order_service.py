from datetime import datetime, timedelta

from app.database import db
from app.services.loyalty_service import points_for_amount

ACTIVE_STATUSES = ['EN PROCESO', 'EN PREPARACIÓN', 'PREPARADO', 'ENVIADO']
TERMINAL_STATUSES = ['ENTREGADO', 'RECHAZADO', 'CANCELADO']
TRACKING_STEPS = ['EN PROCESO', 'EN PREPARACIÓN', 'PREPARADO', 'ENVIADO', 'ENTREGADO']
ALLOWED_NEXT = {
    'NUEVO': {'EN PROCESO', 'CANCELADO'},
    'EN PROCESO': {'EN PREPARACIÓN', 'CANCELADO', 'RECHAZADO'},
    'APROBADO': {'EN PREPARACIÓN', 'CANCELADO'},
    'EN PREPARACIÓN': {'PREPARADO', 'CANCELADO'},
    'LISTO': {'PREPARADO', 'CANCELADO'},
    'PREPARADO': {'ENVIADO', 'CANCELADO'},
    'EN REPARTO': {'ENVIADO', 'ENTREGADO', 'CANCELADO'},
    'ENVIADO': {'ENTREGADO', 'CANCELADO'},
}
FRAUD_BLOCK_HOURS = 2


def _now_dt():
    return datetime.now()


def _now():
    return _now_dt().isoformat(timespec='seconds')


def _event(conn, order_id, status, payment_status, actor, note=''):
    conn.execute(
        '''INSERT INTO order_status_events(order_id,status,payment_status,created_at,actor,note)
           VALUES (?,?,?,?,?,?)''',
        (int(order_id), status or '', payment_status or '', _now(), actor or 'SISTEMA', note or '')
    )


def _parse_dt(value):
    try:
        return datetime.fromisoformat(str(value or '').replace('Z', '+00:00')).replace(tzinfo=None)
    except Exception:
        return None


def _is_fraud_reason(reason):
    text = str(reason or '').upper()
    return any(word in text for word in ('FRAUD', 'TRUCHO', 'ALTERADO', 'FALSO', 'ADULTERADO'))


def customer_order_access(customer_id, clear_expired=True):
    """Devuelve el estado efectivo para crear pedidos desde el Portal.

    El cliente puede seguir entrando al Club para consultar puntos aunque esté
    BLOQUEADO/SUSPENDIDO; lo que se impide es generar nuevos pedidos.
    """
    now = _now_dt()
    with db() as conn:
        c = conn.execute(
            '''SELECT c.id,c.name,c.active,COALESCE(c.customer_status,'ACTIVO') customer_status,
                      c.order_blocked_until,c.order_block_reason,
                      COALESCE(pa.active,0) portal_active
               FROM customers c LEFT JOIN portal_accounts pa ON pa.customer_id=c.id
               WHERE c.id=? LIMIT 1''',
            (int(customer_id),)
        ).fetchone()
        if not c:
            return {'allowed': False, 'kind': 'NO_EXISTE', 'message': 'Cliente inexistente.'}
        if not int(c['active'] or 0):
            return {'allowed': False, 'kind': 'INACTIVO', 'message': 'La cuenta del cliente está inactiva. Contactá al local.'}
        if not int(c['portal_active'] or 0):
            return {'allowed': False, 'kind': 'PORTAL_INACTIVO', 'message': 'El acceso al Portal está deshabilitado. Contactá al local.'}
        status = str(c['customer_status'] or 'ACTIVO').strip().upper()
        if status in ('BLOQUEADO', 'SUSPENDIDO'):
            reason = str(c['order_block_reason'] or '').strip()
            msg = ('La cuenta está bloqueada y no puede generar pedidos.' if status=='BLOQUEADO' else 'La cuenta está suspendida y no puede generar pedidos.')
            if reason:
                msg += f' Motivo: {reason}'
            return {'allowed': False, 'kind': status, 'message': msg, 'reason': reason}
        until = _parse_dt(c['order_blocked_until'])
        if until and until > now:
            seconds = max(int((until - now).total_seconds()), 0)
            minutes = (seconds + 59) // 60
            reason = str(c['order_block_reason'] or '').strip()
            return {
                'allowed': False,
                'kind': 'BLOQUEO_TEMPORAL',
                'until': until.isoformat(timespec='seconds'),
                'remaining_seconds': seconds,
                'remaining_minutes': minutes,
                'reason': reason,
                'message': f'Los pedidos están bloqueados temporalmente hasta las {until.strftime("%H:%M")}. ' + (f'Motivo: {reason}' if reason else '')
            }
        if until and clear_expired:
            conn.execute('UPDATE customers SET order_blocked_until=NULL,order_block_reason=NULL WHERE id=?', (int(customer_id),))
        return {'allowed': True, 'kind': 'ACTIVO', 'message': 'Habilitado para realizar pedidos.'}


def set_customer_status(customer_id, status='ACTIVO', reason='', actor='ADMIN'):
    status = str(status or 'ACTIVO').strip().upper()
    if status not in ('ACTIVO', 'BLOQUEADO', 'SUSPENDIDO'):
        raise ValueError('Estado de cliente inválido.')
    now = _now()
    reason = str(reason or '').strip()
    with db() as conn:
        c = conn.execute('SELECT id,name FROM customers WHERE id=?', (int(customer_id),)).fetchone()
        if not c:
            raise ValueError('Cliente inexistente.')
        conn.execute(
            '''UPDATE customers SET customer_status=?,order_block_reason=?,
               order_blocked_until=CASE WHEN ?='ACTIVO' THEN NULL ELSE order_blocked_until END
               WHERE id=?''',
            (status, reason or None, status, int(customer_id))
        )
        conn.execute(
            'INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)',
            (now, actor, 'ESTADO_CLIENTE', f'{c["name"]}: {status}' + (f' · {reason}' if reason else ''))
        )
    return customer_order_access(customer_id)


def get_order(order_id):
    with db() as conn:
        row = conn.execute('SELECT * FROM orders WHERE id=?', (int(order_id),)).fetchone()
        return dict(row) if row else None


def approve_transfer(order_id, actor='SISTEMA CENTRAL'):
    now = _now()
    with db() as conn:
        o = conn.execute('SELECT * FROM orders WHERE id=?', (int(order_id),)).fetchone()
        if not o:
            raise ValueError('Pedido inexistente.')
        if str(o['status'] or '').upper() in TERMINAL_STATUSES:
            raise ValueError('El pedido ya está cerrado y no admite gestiones.')
        if str(o['payment_method'] or '').upper() != 'TRANSFERENCIA':
            raise ValueError('El pedido no fue pagado por transferencia.')
        if str(o['payment_status'] or '').upper() not in ('PENDIENTE_VERIFICACION', 'PENDIENTE DE VERIFICACION'):
            raise ValueError('La transferencia ya fue procesada.')
        conn.execute(
            '''UPDATE orders SET payment_status='PAGO_APROBADO',status='EN PREPARACIÓN',
               approved_at=?,approved_by=?,status_updated_at=?,payment_rejection_reason=NULL
               WHERE id=?''',
            (now, actor, now, int(order_id))
        )
        _event(conn, order_id, 'EN PREPARACIÓN', 'PAGO_APROBADO', actor, 'Transferencia verificada y aprobada.')
        conn.execute(
            "INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",
            (now, actor, 'TRANSFERENCIA_APROBADA', f'Pedido #{order_id} · pasa a EN PREPARACIÓN')
        )
    return get_order(order_id)


def _refund_order_redemption(conn, order, actor, reason, now):
    points=int(order['loyalty_points_redeemed'] or 0) if 'loyalty_points_redeemed' in order.keys() else 0
    refunded=int(order['loyalty_redemption_refunded'] or 0) if 'loyalty_redemption_refunded' in order.keys() else 0
    if points<=0 or refunded or not order['customer_id']:
        return 0
    cust=conn.execute('SELECT points FROM customers WHERE id=?',(int(order['customer_id']),)).fetchone()
    if not cust:
        return 0
    balance=int(cust['points'] or 0)+points
    conn.execute('UPDATE customers SET points=? WHERE id=?',(balance,int(order['customer_id'])))
    conn.execute('''INSERT INTO loyalty_movements(created_at,customer_id,sale_id,movement_type,points,description,balance_after,order_id)
                    VALUES (?,?,?,?,?,?,?,?)''',
                 (now,int(order['customer_id']),None,'REINTEGRO_CANJE',points,
                  f'Reintegro de canje · Pedido #{order["id"]} · {reason}',balance,int(order['id'])))
    conn.execute('UPDATE orders SET loyalty_redemption_refunded=1 WHERE id=?',(int(order['id']),))
    conn.execute('INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)',
                 (now,actor,'REINTEGRO_PUNTOS_CANJE',f'Pedido #{order["id"]} · +{points} puntos · {reason}'))
    return points


def reject_transfer(order_id, reason, actor='SISTEMA CENTRAL'):
    reason = str(reason or '').strip()
    if not reason:
        raise ValueError('El motivo del rechazo es obligatorio.')
    now_dt = _now_dt()
    now = now_dt.isoformat(timespec='seconds')
    fraud = _is_fraud_reason(reason)
    with db() as conn:
        o = conn.execute('SELECT * FROM orders WHERE id=?', (int(order_id),)).fetchone()
        if not o:
            raise ValueError('Pedido inexistente.')
        if str(o['status'] or '').upper() in TERMINAL_STATUSES:
            raise ValueError('El pedido ya está cerrado.')
        if str(o['payment_method'] or '').upper() != 'TRANSFERENCIA':
            raise ValueError('El pedido no fue pagado por transferencia.')
        restored=_refund_order_redemption(conn,o,actor,'pedido rechazado',now)
        conn.execute(
            '''UPDATE orders SET payment_status='RECHAZADO',status='RECHAZADO',
               payment_rejection_reason=?,approved_at=?,approved_by=?,status_updated_at=? WHERE id=?''',
            (reason, now, actor, now, int(order_id))
        )
        block_note = ''
        if fraud and o['customer_id']:
            until = (now_dt + timedelta(hours=FRAUD_BLOCK_HOURS)).isoformat(timespec='seconds')
            block_reason = f'Bloqueo automático por transferencia/comprobante fraudulento en pedido #{order_id}'
            conn.execute(
                '''UPDATE customers SET order_blocked_until=?,order_block_reason=? WHERE id=?''',
                (until, block_reason, int(o['customer_id']))
            )
            block_note = f' · pedidos bloqueados hasta {until}'
            conn.execute(
                "INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",
                (now, actor, 'BLOQUEO_PEDIDOS_FRAUDE', f'Cliente #{o["customer_id"]} · pedido #{order_id} · hasta {until}')
            )
        if restored:
            block_note += f' · +{restored} puntos reintegrados'
        _event(conn, order_id, 'RECHAZADO', 'RECHAZADO', actor, reason + block_note)
        conn.execute(
            "INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",
            (now, actor, 'TRANSFERENCIA_RECHAZADA', f'Pedido #{order_id} · {reason}{block_note}')
        )
    return get_order(order_id)


def _finalize_web_order_sale(conn, order, actor, now):
    # Convierte un pedido WEB entregado en venta y acredita puntos una sola vez.
    if str(order['source'] or '').upper() != 'WEB' or not order['customer_id']:
        return None, 0
    if order['sale_id']:
        existing = conn.execute('SELECT loyalty_points_earned FROM sales WHERE id=?', (int(order['sale_id']),)).fetchone()
        return int(order['sale_id']), int(existing['loyalty_points_earned'] or 0) if existing else int(order['loyalty_points_earned'] or 0)

    items = conn.execute('SELECT * FROM order_items WHERE order_id=? ORDER BY id', (int(order['id']),)).fetchall()
    item_subtotal = sum(float(i['line_total'] or 0) for i in items)
    merchandise_subtotal = float(order['merchandise_subtotal'] or 0) if 'merchandise_subtotal' in order.keys() else 0.0
    if merchandise_subtotal <= 0:
        merchandise_subtotal = item_subtotal
    delivery_fee = float(order['delivery_fee'] or 0) if 'delivery_fee' in order.keys() else 0.0
    fee_label = 'Envío' if str(order['order_type'] or '').upper() == 'DELIVERY' else 'Retiro local'
    loyalty_discount = float(order['loyalty_discount'] or 0) if 'loyalty_discount' in order.keys() else 0.0
    points_redeemed = int(order['loyalty_points_redeemed'] or 0) if 'loyalty_points_redeemed' in order.keys() else 0
    reward_id = order['loyalty_reward_id'] if 'loyalty_reward_id' in order.keys() else None
    total = max(float(order['total'] or 0), 0.0)
    subtotal = max(merchandise_subtotal + delivery_fee, total)
    discount = max(loyalty_discount, 0.0)
    points_base = max(merchandise_subtotal - loyalty_discount, 0.0)
    points = points_for_amount(points_base)
    session_row = conn.execute("SELECT id FROM cash_sessions WHERE status='ABIERTA' ORDER BY id DESC LIMIT 1").fetchone()
    cash_session_id = session_row['id'] if session_row else None
    cur = conn.execute(
        '''INSERT INTO sales(created_at,user_id,customer_id,cash_session_id,subtotal,discount,total,payment_method,status,order_type,notes,
                            loyalty_points_earned,loyalty_points_redeemed,loyalty_reward_id,loyalty_discount,manual_discount_percent,manual_discount_amount)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (now, order['user_id'], order['customer_id'], cash_session_id, subtotal, discount, total,
         str(order['payment_method'] or 'A DEFINIR'), 'CONFIRMADA', str(order['order_type'] or 'DELIVERY'),
         f'Venta online · Pedido Web #{order["id"]} · {fee_label} ${delivery_fee:,.2f}', points, points_redeemed, reward_id, loyalty_discount, 0.0, 0.0)
    )
    sale_id = cur.lastrowid
    for i in items:
        conn.execute(
            '''INSERT INTO sale_items(sale_id,product_id,quantity,unit_price,line_total,offer_id,flavor_text)
               VALUES (?,?,?,?,?,?,?)''',
            (sale_id, i['product_id'], i['quantity'], i['unit_price'], i['line_total'], None, i['flavor_text'])
        )
    conn.execute(
        '''INSERT INTO cash_movements(created_at,session_id,movement_type,concept,amount,payment_method,reference_type,reference_id,user_id,notes)
           VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (now, cash_session_id, 'VENTA', f'Venta online · Pedido #{order["id"]}', total,
         str(order['payment_method'] or 'A DEFINIR'), 'SALE', sale_id, order['user_id'], f'Generada al entregar pedido WEB · {fee_label.lower()} ${delivery_fee:,.2f}')
    )
    if points_redeemed:
        conn.execute('''UPDATE loyalty_movements SET sale_id=?,movement_type='CANJE',
                        description=CASE WHEN description LIKE 'Canje online reservado%' THEN REPLACE(description,'Canje online reservado','Canje online') ELSE description END
                        WHERE order_id=? AND customer_id=? AND movement_type='CANJE_WEB_RESERVA' ''',
                     (sale_id,int(order['id']),int(order['customer_id'])))
    cust = conn.execute('SELECT points FROM customers WHERE id=?', (int(order['customer_id']),)).fetchone()
    balance = int(cust['points'] or 0) if cust else 0
    if points:
        balance += int(points)
        conn.execute('UPDATE customers SET points=? WHERE id=?', (balance, int(order['customer_id'])))
        conn.execute(
            '''INSERT INTO loyalty_movements(created_at,customer_id,sale_id,movement_type,points,description,balance_after,order_id)
               VALUES (?,?,?,?,?,?,?,?)''',
            (now, int(order['customer_id']), sale_id, 'ACUMULACION', int(points),
             f'Puntos por pedido online #{order["id"]} · venta #{sale_id}', balance, int(order['id']))
        )
    conn.execute('UPDATE orders SET sale_id=?,loyalty_points_earned=? WHERE id=?', (sale_id, int(points), int(order['id'])))
    conn.execute(
        'INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)',
        (now, actor, 'VENTA_ONLINE_FINALIZADA', f'Pedido #{order["id"]} → venta #{sale_id} · canje {points_redeemed} pts · +{points} puntos · {fee_label.lower()} ${delivery_fee:,.2f}')
    )
    return sale_id, int(points)


def transition_order(order_id, new_status, actor='SISTEMA CENTRAL', note=''):
    new_status = str(new_status or '').strip().upper()
    aliases = {'LISTO': 'PREPARADO', 'EN REPARTO': 'ENVIADO', 'APROBADO': 'EN PREPARACIÓN'}
    new_status = aliases.get(new_status, new_status)
    now = _now()
    with db() as conn:
        o = conn.execute('SELECT * FROM orders WHERE id=?', (int(order_id),)).fetchone()
        if not o:
            raise ValueError('Pedido inexistente.')
        current = aliases.get(str(o['status'] or '').upper(), str(o['status'] or '').upper())
        if current in TERMINAL_STATUSES:
            raise ValueError('El pedido ya está cerrado y no admite más cambios.')
        if new_status == 'CANCELADO':
            # Evita abrir una segunda transacción dentro de la actual.
            raise ValueError('Usá la acción Cancelar pedido para cancelar.')
        allowed = ALLOWED_NEXT.get(current, set())
        if new_status not in allowed:
            raise ValueError(f'No se puede pasar de {current} a {new_status}.')
        if (current == 'EN PROCESO' and new_status == 'EN PREPARACIÓN' and
                str(o['payment_method'] or '').upper() == 'TRANSFERENCIA' and
                str(o['payment_status'] or '').upper() != 'PAGO_APROBADO'):
            raise ValueError('Primero tenés que aprobar la transferencia.')

        if (current == 'EN PROCESO' and new_status == 'EN PREPARACIÓN' and
                str(o['payment_method'] or '').upper() in ('MERCADO PAGO','MERCADOPAGO','MERCADO_PAGO') and
                str(o['payment_status'] or '').upper() != 'PAGO_APROBADO'):
            raise ValueError('Mercado Pago todavía no acreditó el pago.')

        points = 0
        sale_id = o['sale_id']
        payment_status = str(o['payment_status'] or '')
        if new_status == 'ENTREGADO':
            if str(o['payment_method'] or '').upper() == 'EFECTIVO':
                payment_status = 'PAGO_COBRADO'
            sale_id, points = _finalize_web_order_sale(conn, o, actor, now)

        delivered_at = now if new_status == 'ENTREGADO' else None
        conn.execute(
            '''UPDATE orders SET status=?,status_updated_at=?,delivered_at=COALESCE(?,delivered_at),
               payment_status=?,sale_id=COALESCE(?,sale_id),loyalty_points_earned=CASE WHEN ?>0 THEN ? ELSE loyalty_points_earned END
               WHERE id=?''',
            (new_status, now, delivered_at, payment_status, sale_id, points, points, int(order_id))
        )
        extra = f' · +{points} puntos acreditados' if points else ''
        _event(conn, order_id, new_status, payment_status, actor, (note or '') + extra)
        conn.execute(
            "INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",
            (now, actor, 'ESTADO_PEDIDO', f'Pedido #{order_id}: {current} → {new_status}' + (f' · {note}' if note else '') + extra)
        )
    return get_order(order_id)


def cancel_order(order_id, reason, actor='SISTEMA CENTRAL'):
    reason = str(reason or '').strip()
    if not reason:
        raise ValueError('El motivo de cancelación es obligatorio.')
    now = _now()
    with db() as conn:
        o = conn.execute('SELECT * FROM orders WHERE id=?', (int(order_id),)).fetchone()
        if not o:
            raise ValueError('Pedido inexistente.')
        if str(o['status'] or '').upper() in TERMINAL_STATUSES:
            raise ValueError('El pedido ya está cerrado.')
        restored=_refund_order_redemption(conn,o,actor,'pedido cancelado',now)
        paid_method = str(o['payment_method'] or '').upper()
        paid_online = (paid_method in ('TRANSFERENCIA','MERCADO PAGO','MERCADOPAGO','MERCADO_PAGO') and
                       str(o['payment_status'] or '').upper() == 'PAGO_APROBADO')
        refund_status = 'PENDIENTE_REINTEGRO' if paid_online else 'NO_CORRESPONDE'
        conn.execute(
            '''UPDATE orders SET status='CANCELADO',cancellation_reason=?,refund_status=?,
               status_updated_at=? WHERE id=?''',
            (reason, refund_status, now, int(order_id))
        )
        extra=f' · +{restored} puntos reintegrados' if restored else ''
        _event(conn, order_id, 'CANCELADO', o['payment_status'], actor,
               reason + (f' · {refund_status}' if refund_status else '') + extra)
        conn.execute(
            "INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",
            (now, actor, 'PEDIDO_CANCELADO', f'Pedido #{order_id} · {reason} · {refund_status}{extra}')
        )
    return get_order(order_id)


def mark_refunded(order_id, note='', actor='WEB ADMIN'):
    now = _now()
    with db() as conn:
        o = conn.execute('SELECT * FROM orders WHERE id=?', (int(order_id),)).fetchone()
        if not o:
            raise ValueError('Pedido inexistente.')
        if str(o['status'] or '').upper() != 'CANCELADO':
            raise ValueError('Solo se puede marcar reintegro en pedidos cancelados.')
        if str(o['refund_status'] or '') != 'PENDIENTE_REINTEGRO':
            raise ValueError('Este pedido no tiene un reintegro pendiente.')
        conn.execute(
            '''UPDATE orders SET refund_status='REINTEGRADO',refund_completed_at=?,refund_notes=? WHERE id=?''',
            (now, str(note or '').strip(), int(order_id))
        )
        _event(conn, order_id, 'CANCELADO', o['payment_status'], actor, 'Reintegro confirmado. ' + str(note or '').strip())
        conn.execute(
            "INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",
            (now, actor, 'REINTEGRO_CONFIRMADO', f'Pedido #{order_id} · {note}')
        )
    return get_order(order_id)


def tracking_payload(order_id, customer_id=None):
    with db() as conn:
        params = [int(order_id)]
        where = 'o.id=?'
        if customer_id is not None:
            where += ' AND o.customer_id=?'
            params.append(int(customer_id))
        o = conn.execute(f'''SELECT o.*,COALESCE(c.name,'') customer_name FROM orders o
                             LEFT JOIN customers c ON c.id=o.customer_id WHERE {where}''', params).fetchone()
        if not o:
            return None
        events = conn.execute(
            '''SELECT status,payment_status,created_at,actor,note FROM order_status_events
               WHERE order_id=? ORDER BY id''', (int(order_id),)
        ).fetchall()
    status = str(o['status'] or '').upper()
    status = {'LISTO':'PREPARADO','EN REPARTO':'ENVIADO','APROBADO':'EN PREPARACIÓN'}.get(status,status)
    try:
        idx = TRACKING_STEPS.index(status)
    except ValueError:
        idx = -1
    return {
        'id': o['id'],
        'status': status,
        'payment_status': str(o['payment_status'] or ''),
        'updated_at': o['status_updated_at'] or o['created_at'],
        'progress_index': idx,
        'terminal': status in TERMINAL_STATUSES,
        'refund_status': str(o['refund_status'] or ''),
        'rejection_reason': str(o['payment_rejection_reason'] or ''),
        'cancellation_reason': str(o['cancellation_reason'] or ''),
        'loyalty_points_earned': int(o['loyalty_points_earned'] or 0),
        'loyalty_points_redeemed': int(o['loyalty_points_redeemed'] or 0) if 'loyalty_points_redeemed' in o.keys() else 0,
        'loyalty_redemption_refunded': int(o['loyalty_redemption_refunded'] or 0) if 'loyalty_redemption_refunded' in o.keys() else 0,
        'delivery_fee': float(o['delivery_fee'] or 0) if 'delivery_fee' in o.keys() else 0.0,
        'loyalty_discount': float(o['loyalty_discount'] or 0) if 'loyalty_discount' in o.keys() else 0.0,
        'sale_id': o['sale_id'],
        'events': [dict(e) for e in events],
    }
