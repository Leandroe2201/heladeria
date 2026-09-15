from app.database import db

DEFAULTS = {
    'store_name': 'Heladería Los Nietos',
    'store_address': '',
    'store_phone': '',
    'store_footer': '¡Gracias por su compra!',
    'admin_pin': '2580',
    'ticket_width_mm': '58',
    'printer_name': '',
    'auto_print_sale': '0',
    'auto_print_order': '0',
    'print_backend': 'RAW_ESC_POS',
    'thermal_auto_cut': '0',
    'thermal_feed_lines': '4',
    'web_port': '5050',
    'web_pin': '2580',
    'web_auto_start': '1',
    'loyalty_enabled': '1',
    'loyalty_amount_per_point': '1000',
    'loyalty_points_per_step': '1',
    'auto_print_loyalty_receipt': '1',
    'portal_base_url': '',
    # V13 · Pedidos Web / Delivery / Transferencia
    'transfer_alias': 'heladeriapope',
    'transfer_cbu': '',
    'transfer_holder': 'ENCINAS, leandro ezequiel',
    'transfer_tax_id': '20372019485',
    'transfer_entity': 'Personal Pay',
    'google_maps_api_key': '',
    'delivery_center_address': '',
    'delivery_radius_km': '5',
    'delivery_fee': '2500',
    # V22 · retiro en local siempre sin cargo.
    'pickup_fee': '0.00',
    'web_order_auto_print_pending': '0',
    'web_order_auto_print_approved': '1',
    'mercadopago_enabled': '0',
    # V21 · Mercado Pago Online usa Checkout Pro vía Orders API (redirect a Mercado Pago).
    'mercadopago_public_key': '',  # opcional/legado; no es requisito para el redirect V21
    'mercadopago_access_token': '',
    # QR presencial se configura aparte y recién ahí requiere External POS ID.
    'mercadopago_external_pos_id': '',
    'mercadopago_qr_mode': 'dynamic',
    'web_order_sound_enabled': '1',
    'web_order_central_auto_print': '1',
}


def get_setting(key, default=None):
    with db() as conn:
        row = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    if row is not None:
        return row['value']
    if default is not None:
        return default
    return DEFAULTS.get(key, '')


def set_setting(key, value):
    with db() as conn:
        conn.execute('''
            INSERT INTO settings(key,value) VALUES (?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        ''', (key, str(value)))


def ensure_default_settings():
    with db() as conn:
        for key, value in DEFAULTS.items():
            conn.execute('INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)', (key, value))
