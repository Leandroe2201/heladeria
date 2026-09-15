import json
import os
import uuid
import urllib.request
import urllib.error
from datetime import datetime

from app.database import db
from app.settings_service import get_setting

API_BASE = 'https://api.mercadopago.com'


def _token():
    return (os.environ.get('MERCADOPAGO_ACCESS_TOKEN') or get_setting('mercadopago_access_token', '') or '').strip()


def _public_key():
    return (get_setting('mercadopago_public_key', '') or '').strip()


def _external_pos_id():
    return (get_setting('mercadopago_external_pos_id', '') or '').strip()


def online_configured():
    # V22: Checkout Pro vía Orders API. Producción se determina por el Access Token productivo cargado.
    # Para crear la order desde backend solo se requiere Access Token.
    return get_setting('mercadopago_enabled', '0') == '1' and bool(_token())


def qr_configured():
    # El QR presencial es una segunda configuración y sí requiere caja/POS.
    return get_setting('mercadopago_enabled', '0') == '1' and bool(_token()) and bool(_external_pos_id())


def configured():
    # Compatibilidad: las funciones que crean QR deben usar configuración QR completa.
    return qr_configured()


def configuration_status():
    enabled = get_setting('mercadopago_enabled', '0') == '1'
    token = bool(_token())
    public_key = bool(_public_key())
    pos = bool(_external_pos_id())
    return {
        'enabled': enabled,
        'has_token': token,
        'has_public_key': public_key,
        'public_key': _public_key(),
        'external_pos_id': _external_pos_id(),
        'mode': (get_setting('mercadopago_qr_mode', 'dynamic') or 'dynamic').strip().lower(),
        'credentials_saved': token,
        'online_ready': enabled and token,
        'qr_ready': enabled and token and pos,
        # ready significa listo para Mercado Pago Web; Public Key no es necesaria en el redirect V21.
        'ready': enabled and token,
    }


def _request(method, path, payload=None, idempotency_key=None, timeout=20):
    token = _token()
    if not token:
        raise RuntimeError('Falta configurar el Access Token de Mercado Pago.')
    data = None
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    if idempotency_key:
        headers['X-Idempotency-Key'] = str(idempotency_key)
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(API_BASE + path, data=data, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        try:
            detail = json.loads(body)
        except Exception:
            detail = body
        raise RuntimeError(f'Mercado Pago respondió HTTP {exc.code}: {detail}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'No se pudo conectar con Mercado Pago: {exc.reason}') from exc


def _find_qr_data(obj):
    if isinstance(obj, dict):
        for key in ('qr_data', 'qr_code'):
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in obj.values():
            found = _find_qr_data(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_qr_data(value)
            if found:
                return found
    return ''





def create_checkout_pro_order(local_order_id, success_url, failure_url, pending_url, payer_email='', recreate=False):
    """Crea una order ONLINE en modo manual y devuelve ``checkout_url``.

    Es el flujo Checkout Pro sobre Orders API. El comprador es enviado al
    entorno oficial de Mercado Pago con el importe exacto ya asociado a la
    order. En celular, Mercado Pago decide si continúa en web o deriva a su app.
    """
    if not online_configured():
        raise RuntimeError('Mercado Pago Online no está listo. Cargá y habilitá el Access Token PRODUCTIVO en Delivery / Pagos.')
    with db() as conn:
        row = conn.execute('SELECT * FROM orders WHERE id=?', (int(local_order_id),)).fetchone()
        if not row:
            raise RuntimeError('Pedido inexistente.')
        if str(row['payment_method'] or '').upper() not in ('MERCADO PAGO','MERCADOPAGO','MERCADO_PAGO'):
            raise RuntimeError('El pedido no está configurado para Mercado Pago.')
        if str(row['status'] or '').upper() in ('ENTREGADO','CANCELADO','RECHAZADO'):
            raise RuntimeError('El pedido ya está cerrado.')
        if str(row['payment_status'] or '').upper() == 'PAGO_APROBADO':
            return {
                'order_id': str(row['mercadopago_order_id'] or ''),
                'checkout_url': str(row['mercadopago_checkout_url'] or ''),
                'accredited': True,
                'payment_status': 'PAGO_APROBADO',
            }
        existing_url = str(row['mercadopago_checkout_url'] or '') if 'mercadopago_checkout_url' in row.keys() else ''
        existing_id = str(row['mercadopago_order_id'] or '') if 'mercadopago_order_id' in row.keys() else ''
        existing_flow = str(row['mercadopago_flow'] or '') if 'mercadopago_flow' in row.keys() else ''
        if existing_url and existing_id and existing_flow == 'CHECKOUT_PRO_ORDERS' and not recreate:
            return {
                'order_id': existing_id,
                'checkout_url': existing_url,
                'payment_status': str(row['payment_status'] or 'PENDIENTE_MERCADOPAGO'),
                'accredited': False,
            }
        amount = round(float(row['total'] or 0), 2)
        if amount <= 0:
            raise RuntimeError('El importe a cobrar por Mercado Pago debe ser mayor a $0.')

    ext_ref = f'LOSNIETOS_WEB_{int(local_order_id)}'
    payload = {
        'type': 'online',
        'total_amount': f'{amount:.2f}',
        'external_reference': ext_ref,
        'processing_mode': 'manual',
        'capture_mode': 'automatic_async',
        'expiration_time': 'P1D',
        'description': f'Heladeria Los Nietos pedido {int(local_order_id)}',
        'config': {
            'online': {
                'success_url': str(success_url),
                'failure_url': str(failure_url),
                'pending_url': str(pending_url),
                'auto_return': 'approved',
            }
        },
        'items': [
            {
                'external_code': f'PEDIDO-{int(local_order_id)}',
                'title': f'Pedido #{int(local_order_id)} - Heladeria Los Nietos',
                'description': 'Pedido web Heladeria Los Nietos',
                'quantity': 1,
                'unit_price': f'{amount:.2f}',
            }
        ],
    }
    payer_email = str(payer_email or '').strip()
    if payer_email:
        payload['payer'] = {'email': payer_email}
    idem = str(uuid.uuid4())
    try:
        result = _request('POST', '/v1/orders', payload, idempotency_key=idem)
    except RuntimeError as exc:
        # En sandbox Mercado Pago puede exigir email @testuser.com.
        text = str(exc)
        if payer_email and 'invalid_email_for_sandbox' in text:
            payload.pop('payer', None)
            idem = str(uuid.uuid4())
            result = _request('POST', '/v1/orders', payload, idempotency_key=idem)
        elif 'invalid_credentials' in text or 'no hay soporte para credenciales de prueba' in text.lower():
            raise RuntimeError(
                'Mercado Pago no admite estas credenciales de prueba para Checkout Pro vía Orders. '
                'Para probar, usá el flujo sandbox con usuario vendedor de prueba y las credenciales que Mercado Pago '
                'indique para ese usuario; para producción, cargá las credenciales productivas. '
                'No compartas el Access Token.'
            ) from exc
        else:
            raise
    order_id = str(result.get('id') or '')
    checkout_url = str(result.get('checkout_url') or '')
    if not order_id or not checkout_url:
        raise RuntimeError('Mercado Pago creó una respuesta sin checkout_url. Revisá las credenciales y la aplicación Checkout Pro / Orders.')
    now = datetime.now().isoformat(timespec='seconds')
    with db() as conn:
        conn.execute("""UPDATE orders SET mercadopago_order_id=?,mercadopago_checkout_url=?,mercadopago_flow='CHECKOUT_PRO_ORDERS',
                        mercadopago_qr_data=NULL,mercadopago_status=?,mercadopago_status_detail=?,mercadopago_synced_at=?,
                        mercadopago_idempotency_key=?,payment_method='MERCADO PAGO',payment_status='PENDIENTE_MERCADOPAGO' WHERE id=?""",
                     (order_id, checkout_url, str(result.get('status') or 'created'), str(result.get('status_detail') or ''),
                      now, idem, int(local_order_id)))
        conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",
                     (now, 'MERCADO PAGO', 'MP_CHECKOUT_PRO_ORDER',
                      f'Pedido #{local_order_id} · Order {order_id} · redirect creado'))
    return {
        'order_id': order_id,
        'checkout_url': checkout_url,
        'payment_status': 'PENDIENTE_MERCADOPAGO',
        'accredited': False,
        'raw': result,
    }

def create_online_card_order(local_order_id, card_token, payment_method_id, payment_type, installments, payer_email, identification_type='DNI', identification_number=''):
    """Procesa un pedido Web con Checkout API vía Orders.

    Los datos sensibles de tarjeta nunca llegan en claro al backend: MercadoPago.js
    genera ``card_token`` en el navegador y aquí solo se recibe ese token temporal.
    """
    if not online_configured():
        raise RuntimeError('Mercado Pago Online no está listo. Configurá Access Token y Public Key en Delivery / Pagos.')
    card_token = str(card_token or '').strip()
    payment_method_id = str(payment_method_id or '').strip()
    payment_type = str(payment_type or '').strip() or 'credit_card'
    payer_email = str(payer_email or '').strip()
    identification_type = str(identification_type or 'DNI').strip() or 'DNI'
    identification_number = ''.join(ch for ch in str(identification_number or '') if ch.isdigit())
    try:
        installments = max(int(installments or 1), 1)
    except Exception:
        installments = 1
    if not card_token or not payment_method_id or not payer_email:
        raise RuntimeError('Mercado Pago no recibió todos los datos necesarios del formulario de pago.')
    with db() as conn:
        row = conn.execute('SELECT * FROM orders WHERE id=?', (int(local_order_id),)).fetchone()
        if not row:
            raise RuntimeError('Pedido inexistente.')
        if str(row['payment_method'] or '').upper() not in ('MERCADO PAGO','MERCADOPAGO','MERCADO_PAGO'):
            raise RuntimeError('El pedido no está configurado para Mercado Pago.')
        amount = round(float(row['total'] or 0), 2)
        if amount <= 0:
            raise RuntimeError('El importe a cobrar por Mercado Pago debe ser mayor a $0.')
        existing = str(row['mercadopago_order_id'] or '') if 'mercadopago_order_id' in row.keys() else ''
        if existing and str(row['payment_status'] or '').upper() == 'PAGO_APROBADO':
            return {'order_id': existing, 'accredited': True, 'payment_status': 'PAGO_APROBADO'}
    ext_ref = f'LOSNIETOS_WEB_{int(local_order_id)}'
    payment = {
        'amount': f'{amount:.2f}',
        'payment_method': {
            'id': payment_method_id,
            'type': payment_type,
            'token': card_token,
            'installments': installments,
        }
    }
    payer = {'email': payer_email}
    if identification_number:
        payer['identification'] = {'type': identification_type, 'number': identification_number}
    payload = {
        'type': 'online',
        'processing_mode': 'automatic',
        'total_amount': f'{amount:.2f}',
        'external_reference': ext_ref,
        'description': f'Heladeria Los Nietos pedido {int(local_order_id)}',
        'payer': payer,
        'transactions': {'payments': [payment]},
    }
    idem = str(uuid.uuid4())
    result = _request('POST', '/v1/orders', payload, idempotency_key=idem)
    state = _payment_state(result)
    payments = ((result.get('transactions') or {}).get('payments') or []) if isinstance(result, dict) else []
    payment_id = state.get('payment_id') or ''
    if not payment_id and payments and isinstance(payments[0], dict):
        payment_id = str(payments[0].get('id') or '')
    order_id = str(result.get('id') or '')
    raw_status = str(result.get('status') or '')
    raw_detail = str(result.get('status_detail') or '')
    if state['accredited']:
        local_payment_status = 'PAGO_APROBADO'
    elif state['expired']:
        local_payment_status = 'MP_EXPIRADO'
    elif state['canceled']:
        local_payment_status = 'MP_CANCELADO'
    elif state.get('rejected'):
        local_payment_status = 'MP_RECHAZADO'
    else:
        local_payment_status = 'PENDIENTE_MERCADOPAGO'
    now = datetime.now().isoformat(timespec='seconds')
    with db() as conn:
        conn.execute('''UPDATE orders SET mercadopago_order_id=?,mercadopago_payment_id=?,mercadopago_qr_data=NULL,
                        mercadopago_status=?,mercadopago_status_detail=?,mercadopago_synced_at=?,mercadopago_idempotency_key=?,
                        payment_method='MERCADO PAGO',payment_status=? WHERE id=?''',
                     (order_id, payment_id, raw_status, raw_detail or state.get('payment_status_detail',''), now, idem,
                      local_payment_status, int(local_order_id)))
        conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",
                     (now, 'MERCADO PAGO', 'MP_ONLINE_ORDER',
                      f'Pedido #{local_order_id} · Order {order_id} · {local_payment_status}'))
    if state['accredited']:
        from app.services.order_service import transition_order
        try:
            transition_order(int(local_order_id), 'EN PREPARACIÓN', actor='MERCADO PAGO', note='Pago online acreditado automáticamente por Mercado Pago.')
        except Exception:
            pass
    return {
        'order_id': order_id,
        'payment_id': payment_id,
        'status': raw_status,
        'status_detail': raw_detail,
        'payment_status': local_payment_status,
        'accredited': bool(state['accredited']),
        'raw': result,
    }

def create_dynamic_qr(amount, external_reference, description='Pedido Heladería Los Nietos', expiration='PT15M'):
    if not qr_configured():
        raise RuntimeError('Mercado Pago QR presencial no está listo. Configurá Access Token y External POS ID en Delivery / Pagos.')
    amount = round(float(amount), 2)
    if amount <= 0:
        raise RuntimeError('El importe a cobrar por Mercado Pago debe ser mayor a $0.')
    mode = (get_setting('mercadopago_qr_mode', 'dynamic') or 'dynamic').strip().lower()
    if mode not in ('dynamic', 'hybrid', 'static'):
        mode = 'dynamic'
    payload = {
        'type': 'qr',
        'total_amount': f'{amount:.2f}',
        'description': str(description or 'Pedido Heladería Los Nietos')[:150],
        'external_reference': str(external_reference)[:64],
        'expiration_time': expiration,
        'config': {
            'qr': {
                'external_pos_id': _external_pos_id(),
                'mode': mode,
            }
        },
        'transactions': {
            'payments': [
                {'amount': f'{amount:.2f}'}
            ]
        },
    }
    idem = str(uuid.uuid4())
    result = _request('POST', '/v1/orders', payload, idempotency_key=idem)
    payments = ((result.get('transactions') or {}).get('payments') or []) if isinstance(result, dict) else []
    payment_id = ''
    if payments and isinstance(payments[0], dict):
        payment_id = str(payments[0].get('id') or '')
    return {
        'order_id': str(result.get('id') or ''),
        'payment_id': payment_id,
        'qr_data': _find_qr_data(result),
        'status': str(result.get('status') or ''),
        'status_detail': str(result.get('status_detail') or ''),
        'idempotency_key': idem,
        'raw': result,
    }


def get_mp_order(mp_order_id):
    mp_order_id = str(mp_order_id or '').strip()
    if not mp_order_id:
        raise RuntimeError('El pedido no tiene una order de Mercado Pago asociada.')
    return _request('GET', f'/v1/orders/{mp_order_id}')


def _payment_state(data):
    status = str((data or {}).get('status') or '').lower()
    detail = str((data or {}).get('status_detail') or '').lower()
    payments = (((data or {}).get('transactions') or {}).get('payments') or [])
    pstatus = ''
    pdetail = ''
    pid = ''
    if payments and isinstance(payments[0], dict):
        pid = str(payments[0].get('id') or '')
        pstatus = str(payments[0].get('status') or '').lower()
        pdetail = str(payments[0].get('status_detail') or '').lower()
    accredited = (
        status in ('processed', 'approved', 'accredited') and detail in ('processed', 'approved', 'accredited', '')
    ) or (
        pstatus in ('processed', 'approved', 'accredited') and pdetail in ('accredited', 'approved', 'processed', '')
    )
    expired = status == 'expired' or pstatus == 'expired'
    canceled = status == 'canceled' or pstatus == 'canceled'
    refunded = status == 'refunded' or pstatus == 'refunded'
    rejected = status in ('rejected','failed') or pstatus in ('rejected','failed')
    return {
        'status': status,
        'status_detail': detail,
        'payment_status': pstatus,
        'payment_status_detail': pdetail,
        'payment_id': pid,
        'accredited': accredited,
        'expired': expired,
        'canceled': canceled,
        'refunded': refunded,
        'rejected': rejected,
    }


def attach_qr_to_order(local_order_id, recreate=False):
    with db() as conn:
        row = conn.execute('SELECT * FROM orders WHERE id=?', (int(local_order_id),)).fetchone()
        if not row:
            raise RuntimeError('Pedido inexistente.')
        existing = str(row['mercadopago_order_id'] or '') if 'mercadopago_order_id' in row.keys() else ''
        if existing and not recreate:
            return {
                'order_id': existing,
                'payment_id': str(row['mercadopago_payment_id'] or ''),
                'qr_data': str(row['mercadopago_qr_data'] or ''),
                'status': str(row['mercadopago_status'] or ''),
                'status_detail': str(row['mercadopago_status_detail'] or ''),
            }
        amount = float(row['total'] or 0)
        ext_ref = f'LOSNIETOS_WEB_{int(local_order_id)}_{uuid.uuid4().hex[:8]}'
        description = f'Heladeria Los Nietos pedido {int(local_order_id)}'
    result = create_dynamic_qr(amount, ext_ref, description)
    now = datetime.now().isoformat(timespec='seconds')
    with db() as conn:
        conn.execute('''UPDATE orders SET mercadopago_order_id=?,mercadopago_payment_id=?,mercadopago_qr_data=?,
                        mercadopago_status=?,mercadopago_status_detail=?,mercadopago_synced_at=?,mercadopago_idempotency_key=?,
                        payment_method='MERCADO PAGO',payment_status='PENDIENTE_MERCADOPAGO' WHERE id=?''',
                     (result['order_id'], result['payment_id'], result['qr_data'], result['status'], result['status_detail'],
                      now, result['idempotency_key'], int(local_order_id)))
        conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",
                     (now, 'MERCADO PAGO', 'MP_QR_GENERADO', f'Pedido #{local_order_id} · MP {result["order_id"]}'))
    return result


def sync_local_order(local_order_id, auto_transition=True):
    local_order_id=int(local_order_id)
    with db() as conn:
        row=conn.execute('SELECT * FROM orders WHERE id=?',(local_order_id,)).fetchone()
        if not row:
            raise RuntimeError('Pedido inexistente.')
        mp_order_id=str(row['mercadopago_order_id'] or '') if 'mercadopago_order_id' in row.keys() else ''
        if not mp_order_id:
            return {'changed':False,'reason':'sin_mp_order'}
        current_payment=str(row['payment_status'] or '')
        current_status=str(row['status'] or '')

    data=get_mp_order(mp_order_id)
    state=_payment_state(data)
    now=datetime.now().isoformat(timespec='seconds')
    if state['accredited']:
        new_payment='PAGO_APROBADO'
    elif state['expired']:
        new_payment='MP_EXPIRADO'
    elif state['canceled']:
        new_payment='MP_CANCELADO'
    elif state['refunded']:
        new_payment='REINTEGRADO'
    elif state.get('rejected'):
        new_payment='MP_RECHAZADO'
    else:
        new_payment='PENDIENTE_MERCADOPAGO'

    aliases={'APROBADO':'EN PREPARACIÓN','LISTO':'PREPARADO','EN REPARTO':'ENVIADO'}
    normalized_status=aliases.get(current_status.upper(),current_status.upper())
    auto_prepared=bool(state['accredited'] and auto_transition and normalized_status=='EN PROCESO')
    with db() as conn:
        if auto_prepared:
            conn.execute("UPDATE orders SET mercadopago_payment_id=COALESCE(NULLIF(?,''),mercadopago_payment_id), mercadopago_status=?,mercadopago_status_detail=?,mercadopago_synced_at=?,payment_status='PAGO_APROBADO',status='EN PREPARACIÓN',status_updated_at=?,approved_at=COALESCE(approved_at,?),approved_by=COALESCE(approved_by,'MERCADO PAGO') WHERE id=?",
                         (state['payment_id'],state['status'],state['status_detail'] or state['payment_status_detail'],now,now,now,local_order_id))
            conn.execute("INSERT INTO order_status_events(order_id,status,payment_status,created_at,actor,note) VALUES (?,?,?,?,?,?)",
                         (local_order_id,'EN PREPARACIÓN','PAGO_APROBADO',now,'MERCADO PAGO','Pago acreditado automáticamente por Mercado Pago.'))
            conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",
                         (now,'MERCADO PAGO','MP_PAGO_APROBADO_AUTO',f'Pedido #{local_order_id}: pago aprobado → EN PREPARACIÓN'))
        else:
            conn.execute("UPDATE orders SET mercadopago_payment_id=COALESCE(NULLIF(?,''),mercadopago_payment_id), mercadopago_status=?,mercadopago_status_detail=?,mercadopago_synced_at=?,payment_status=? WHERE id=?",
                         (state['payment_id'],state['status'],state['status_detail'] or state['payment_status_detail'],now,new_payment,local_order_id))
            if new_payment!=current_payment:
                conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",
                             (now,'MERCADO PAGO','MP_ESTADO',f'Pedido #{local_order_id}: {current_payment} → {new_payment}'))
    return {'changed':new_payment!=current_payment or auto_prepared,'state':state,'payment_status':new_payment,
            'auto_prepared':auto_prepared,'status':'EN PREPARACIÓN' if auto_prepared else current_status,'raw':data}


def cancel_mp_order(local_order_id):
    with db() as conn:
        row = conn.execute('SELECT mercadopago_order_id FROM orders WHERE id=?', (int(local_order_id),)).fetchone()
    if not row or not row['mercadopago_order_id']:
        return None
    return _request('POST', f'/v1/orders/{row["mercadopago_order_id"]}/cancel', {}, idempotency_key=str(uuid.uuid4()))
