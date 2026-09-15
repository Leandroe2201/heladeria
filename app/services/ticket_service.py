import textwrap
from app.database import db
from app.settings_service import get_setting


def money(value):
    try:
        n=float(value)
        if abs(n-round(n)) < 0.005:
            return f"$ {n:,.0f}".replace(',', '.')
        txt=f"{n:,.2f}".replace(',', '#').replace('.', ',').replace('#', '.')
        return '$ ' + txt
    except Exception:
        return '$ 0'


def _chars(width_mm):
    width_mm = int(width_mm)
    if width_mm <= 58:
        return 32
    if width_mm <= 80:
        return 46
    return 50


def _center(text, width):
    text = str(text or '')
    return text[:width].center(width)


def _two(left, right, width):
    left, right = str(left), str(right)
    gap = max(1, width - len(left) - len(right))
    if gap == 1 and len(left) + len(right) + 1 > width:
        left = left[:max(1, width - len(right) - 1)]
    return left + (' ' * max(1, width - len(left) - len(right))) + right


def _wrap(text, width, prefix=''):
    available = max(8, width - len(prefix))
    chunks = textwrap.wrap(str(text or ''), width=available, break_long_words=False, break_on_hyphens=False) or ['']
    return [prefix + c for c in chunks]


def _header_lines(title, number, created_at, width):
    store = get_setting('store_name', 'Dulces Momentos') or 'Dulces Momentos'
    address = get_setting('store_address', '')
    phone = get_setting('store_phone', '')
    lines = [
        {'text': store, 'align': 'center', 'bold': True, 'scale': 1.35},
    ]
    if address:
        lines += [{'text': x, 'align': 'center'} for x in _wrap(address, width)]
    if phone:
        lines.append({'text': f'Tel. {phone}', 'align': 'center'})
    lines += [
        {'text': '-' * width},
        {'text': f'{title} #{number}', 'align': 'center', 'bold': True, 'scale': 1.12},
        {'text': str(created_at or '').replace('T', ' '), 'align': 'center', 'scale': .9},
        {'text': '-' * width},
    ]
    return lines


def sale_ticket_lines(sale_id, width_mm=None):
    width_mm = int(width_mm or get_setting('ticket_width_mm', '58'))
    width = _chars(width_mm)
    with db() as conn:
        sale = conn.execute('''SELECT s.*, COALESCE(c.name,'') customer_name,
                               COALESCE(c.dni,'') customer_dni,
                               COALESCE(c.loyalty_card_number,'') loyalty_card_number,
                               COALESCE(c.points,0) customer_points,
                               COALESCE(r.name,'') loyalty_reward_name
                               FROM sales s
                               LEFT JOIN customers c ON c.id=s.customer_id
                               LEFT JOIN loyalty_rewards r ON r.id=s.loyalty_reward_id
                               WHERE s.id=?''', (sale_id,)).fetchone()
        items = conn.execute('''SELECT si.*, p.name product_name, COALESCE(o.name,'') offer_name
                              FROM sale_items si JOIN products p ON p.id=si.product_id
                              LEFT JOIN offers o ON o.id=si.offer_id WHERE si.sale_id=? ORDER BY si.id''', (sale_id,)).fetchall()
    if not sale:
        raise ValueError(f'Venta #{sale_id} inexistente')
    lines = _header_lines('TICKET DE VENTA', sale_id, sale['created_at'], width)
    if str(sale['payment_method'] or '').upper() == 'CANJE DE PUNTOS':
        lines.append({'text': '*** CANJE DE PUNTOS ***', 'align': 'center', 'bold': True, 'scale': 1.12})
        if sale['loyalty_reward_name']:
            lines += [{'text': x, 'align': 'center', 'bold': True} for x in _wrap('Beneficio: ' + sale['loyalty_reward_name'], width)]
        lines.append({'text': '-' * width})
    if sale['customer_name']:
        lines += [{'text': x} for x in _wrap(f"Cliente: {sale['customer_name']}", width)]
    if sale['customer_dni']:
        lines.append({'text': f"DNI: {sale['customer_dni']}"})
    if sale['loyalty_card_number']:
        lines.append({'text': f"Fidelidad: {sale['loyalty_card_number']}"})
    if sale['customer_name']:
        lines.append({'text': '-' * width})
    for it in items:
        qty = f"{float(it['quantity']):g}x "
        amount = money(it['line_total'])
        max_name = max(8, width - len(qty) - len(amount) - 1)
        name_chunks = textwrap.wrap(it['product_name'], width=max_name, break_long_words=False) or [it['product_name']]
        lines.append({'text': _two(qty + name_chunks[0], amount, width), 'bold': True})
        for extra in name_chunks[1:]:
            lines.append({'text': '   ' + extra})
        if it['flavor_text']:
            lines += [{'text': x, 'scale': .92} for x in _wrap('Sabores: ' + it['flavor_text'], width, '   ')]
        if it['offer_name']:
            lines += [{'text': x, 'bold': True, 'scale': .9} for x in _wrap('OFERTA: ' + it['offer_name'], width, '   ')]
    lines.append({'text': '-' * width})
    lines.append({'text': _two('Subtotal', money(sale['subtotal']), width)})
    if float(sale['manual_discount_amount'] or 0) > 0:
        label = f"Descuento {float(sale['manual_discount_percent'] or 0):g}%"
        lines.append({'text': _two(label, '- ' + money(sale['manual_discount_amount']), width), 'bold': True})
    other_discount = float(sale['discount'] or 0) - float(sale['manual_discount_amount'] or 0)
    if other_discount > 0.01:
        lines.append({'text': _two('Otros descuentos', '- ' + money(other_discount), width)})
    lines.append({'text': _two('TOTAL', money(sale['total']), width), 'bold': True, 'scale': 1.3})
    lines.append({'text': f"Pago: {sale['payment_method']}", 'bold': True})
    earned = int(sale['loyalty_points_earned'] or 0)
    redeemed = int(sale['loyalty_points_redeemed'] or 0)
    if redeemed:
        lines.append({'text': f'Puntos canjeados: {redeemed}', 'bold': True})
    if earned:
        lines.append({'text': f'Puntos sumados: +{earned}', 'bold': True})
    if sale['customer_name']:
        lines.append({'text': f"Saldo de puntos: {int(sale['customer_points'] or 0)}", 'bold': True})
    footer = get_setting('store_footer', '¡Gracias por su compra!')
    lines += [
        {'text': '-' * width},
        {'text': footer, 'align': 'center', 'bold': True},
        {'text': 'Sistema Heladería', 'align': 'center', 'scale': .8},
        {'text': ''}, {'text': ''},
    ]
    return lines


def order_ticket_lines(order_id, width_mm=None):
    width_mm = int(width_mm or get_setting('ticket_width_mm', '58'))
    width = _chars(width_mm)
    with db() as conn:
        order = conn.execute('''SELECT o.*,COALESCE(c.name,'') customer_name,COALESCE(c.dni,'') customer_dni
                                FROM orders o LEFT JOIN customers c ON c.id=o.customer_id WHERE o.id=?''', (order_id,)).fetchone()
        items = conn.execute('SELECT * FROM order_items WHERE order_id=? ORDER BY id', (order_id,)).fetchall()
    if not order:
        raise ValueError(f'Pedido #{order_id} inexistente')
    source = str(order['source'] or 'MANUAL').upper() if 'source' in order.keys() else 'MANUAL'
    payment_status = str(order['payment_status'] or '') if 'payment_status' in order.keys() else ''
    pending_transfer = str(order['payment_method'] or '').upper() == 'TRANSFERENCIA' and payment_status == 'PENDIENTE_VERIFICACION'
    pending_mp = str(order['payment_method'] or '').upper() in ('MERCADO PAGO','MERCADOPAGO','MERCADO_PAGO') and payment_status != 'PAGO_APROBADO'
    state = str(order['status'] or '').upper()
    if source == 'WEB':
        if pending_transfer:
            title = 'PEDIDO WEB - PAGO A VERIFICAR'
        elif pending_mp:
            title = 'PEDIDO WEB - MERCADO PAGO PEND.'
        elif state == 'EN PREPARACIÓN':
            title = 'PEDIDO WEB - EN PREPARACION'
        elif state == 'PREPARADO':
            title = 'PEDIDO WEB - PREPARADO'
        elif state == 'ENVIADO':
            title = 'PEDIDO WEB - ENVIADO'
        elif state == 'ENTREGADO':
            title = 'PEDIDO WEB - ENTREGADO'
        elif state in ('RECHAZADO','CANCELADO'):
            title = 'PEDIDO WEB - ' + state
        else:
            title = 'PEDIDO WEB'
    else:
        title = 'PEDIDO'
    lines = _header_lines(title, order_id, order['created_at'], width)
    lines.append({'text': f"TIPO: {order['order_type']}", 'bold': True, 'scale': 1.08})
    lines.append({'text': f"Estado: {order['status']}", 'bold': True})
    if source == 'WEB':
        lines.append({'text': 'Origen: PORTAL WEB', 'bold': True})
    if payment_status:
        lines += [{'text': x, 'bold': (pending_transfer or pending_mp)} for x in _wrap('Pago: ' + payment_status.replace('_',' '), width)]
    if order['customer_name']:
        lines += [{'text': x} for x in _wrap('Cliente: ' + order['customer_name'], width)]
    if order['customer_dni']:
        lines.append({'text': 'DNI: ' + order['customer_dni']})
    if order['phone']:
        lines.append({'text': 'Tel: ' + order['phone']})
    if order['address']:
        lines += [{'text': x, 'bold': True} for x in _wrap('Dirección: ' + order['address'], width)]
    if 'zone_status' in order.keys() and order['zone_status']:
        zone = str(order['zone_status']).replace('_',' ')
        dist = ''
        if 'delivery_distance_km' in order.keys() and order['delivery_distance_km'] is not None:
            dist = f" · {float(order['delivery_distance_km']):.2f} km"
        lines.append({'text': f'Zona: {zone}{dist}', 'bold': True})
    lines.append({'text': '-' * width})
    for it in items:
        qty = f"{float(it['quantity']):g}x "
        amount = money(it['line_total'])
        max_name = max(8, width - len(qty) - len(amount) - 1)
        chunks = textwrap.wrap(it['product_name'], width=max_name, break_long_words=False) or [it['product_name']]
        lines.append({'text': _two(qty + chunks[0], amount, width), 'bold': True})
        for extra in chunks[1:]:
            lines.append({'text': '   ' + extra})
        if it['flavor_text']:
            lines += [{'text': x, 'bold': True} for x in _wrap('Sabores: ' + it['flavor_text'], width, '   ')]
    lines.append({'text': '-' * width})
    merchandise = float(order['merchandise_subtotal'] or 0) if 'merchandise_subtotal' in order.keys() else 0.0
    delivery_fee = float(order['delivery_fee'] or 0) if 'delivery_fee' in order.keys() else 0.0
    loyalty_discount = float(order['loyalty_discount'] or 0) if 'loyalty_discount' in order.keys() else 0.0
    points_redeemed = int(order['loyalty_points_redeemed'] or 0) if 'loyalty_points_redeemed' in order.keys() else 0
    if merchandise > 0:
        lines.append({'text': _two('Productos', money(merchandise), width)})
    if loyalty_discount > 0:
        label = 'Canje puntos'
        if points_redeemed:
            label += f' ({points_redeemed} pts)'
        lines.append({'text': _two(label, '- ' + money(loyalty_discount), width), 'bold': True})
    if str(order['order_type'] or '').upper() == 'DELIVERY':
        lines.append({'text': _two('Envío', money(delivery_fee), width), 'bold': bool(delivery_fee)})
    elif source == 'WEB':
        lines.append({'text': _two('Retiro en local', money(delivery_fee), width), 'bold': bool(delivery_fee)})
    lines += [
        {'text': _two('TOTAL', money(order['total']), width), 'bold': True, 'scale': 1.3},
        {'text': f"Pago: {order['payment_method'] or 'A DEFINIR'}", 'bold': True},
    ]
    if str(order['payment_method'] or '').upper() == 'EFECTIVO' and 'cash_tendered' in order.keys() and float(order['cash_tendered'] or 0) > 0:
        lines.append({'text': _two('Paga con', money(order['cash_tendered']), width)})
        lines.append({'text': _two('Vuelto', money(order['change_due']), width), 'bold': True})
    if pending_transfer:
        lines += [
            {'text': '-' * width},
            {'text': 'TRANSFERENCIA A VERIFICAR', 'align': 'center', 'bold': True, 'scale': 1.15},
            {'text': 'NO PREPARAR HASTA APROBAR PAGO', 'align': 'center', 'bold': True},
        ]
    if pending_mp:
        lines += [
            {'text': '-' * width},
            {'text': 'MERCADO PAGO PENDIENTE', 'align': 'center', 'bold': True, 'scale': 1.15},
            {'text': 'NO PREPARAR HASTA ACREDITACION', 'align': 'center', 'bold': True},
        ]
    if order['notes']:
        lines += [{'text': '-' * width}, {'text': 'OBSERVACIONES', 'bold': True}]
        lines += [{'text': x} for x in _wrap(order['notes'], width)]
    if pending_transfer:
        final_label = f'VERIFICAR PAGO PEDIDO #{order_id}'
    elif pending_mp:
        final_label = f'ESPERAR PAGO MP · PEDIDO #{order_id}'
    elif state == 'EN PREPARACIÓN':
        final_label = f'PREPARAR PEDIDO #{order_id}'
    elif state == 'PREPARADO':
        final_label = f'PEDIDO #{order_id} PREPARADO'
    elif state == 'ENVIADO':
        final_label = f'PEDIDO #{order_id} ENVIADO'
    elif state == 'ENTREGADO':
        final_label = f'PEDIDO #{order_id} ENTREGADO'
    else:
        final_label = f'PEDIDO #{order_id} · {state or "RECIBIDO"}'
    lines += [
        {'text': '-' * width},
        {'text': final_label, 'align': 'center', 'bold': True, 'scale': 1.15},
        {'text': ''}, {'text': ''},
    ]
    return lines


def sale_ticket_text(sale_id, width_mm=None):
    return '\n'.join(x['text'] for x in sale_ticket_lines(sale_id, width_mm))


def order_ticket_text(order_id, width_mm=None):
    return '\n'.join(x['text'] for x in order_ticket_lines(order_id, width_mm))



def loyalty_ticket_lines(sale_id, width_mm=None):
    # Comprobante separado de fidelidad asociado a una venta.
    width_mm = int(width_mm or get_setting('ticket_width_mm', '58'))
    width = _chars(width_mm)
    with db() as conn:
        sale = conn.execute('''SELECT s.id,s.created_at,s.customer_id,
                              COALESCE(s.loyalty_points_earned,0) loyalty_points_earned,
                              COALESCE(s.loyalty_points_redeemed,0) loyalty_points_redeemed,
                              COALESCE(c.name,'') customer_name,
                              COALESCE(c.dni,'') customer_dni,
                              COALESCE(c.loyalty_card_number,'') loyalty_card_number,
                              COALESCE(c.points,0) current_customer_points,
                              COALESCE(r.name,'') loyalty_reward_name
                              FROM sales s
                              LEFT JOIN customers c ON c.id=s.customer_id
                              LEFT JOIN loyalty_rewards r ON r.id=s.loyalty_reward_id
                              WHERE s.id=?''', (sale_id,)).fetchone()
        movements = conn.execute('''SELECT * FROM loyalty_movements
                                    WHERE sale_id=? ORDER BY id''', (sale_id,)).fetchall()
    if not sale:
        raise ValueError(f'Venta #{sale_id} inexistente')
    if not sale['customer_id'] or not sale['loyalty_card_number']:
        raise ValueError('Esta venta no tiene una tarjeta de fidelidad asociada.')

    earned = int(sale['loyalty_points_earned'] or 0)
    redeemed = int(sale['loyalty_points_redeemed'] or 0)
    if not movements and earned == 0 and redeemed == 0:
        raise ValueError('Esta venta no generó movimientos de puntos.')

    if movements:
        final_balance = int(movements[-1]['balance_after'] or 0)
        delta = sum(int(m['points'] or 0) for m in movements)
        previous_balance = final_balance - delta
    else:
        final_balance = int(sale['current_customer_points'] or 0)
        previous_balance = final_balance - earned + redeemed

    store = get_setting('store_name', 'Dulces Momentos') or 'Dulces Momentos'
    lines = [
        {'text': store, 'align': 'center', 'bold': True, 'scale': 1.35},
        {'text': '-' * width},
        {'text': 'COMPROBANTE DE FIDELIDAD', 'align': 'center', 'bold': True, 'scale': 1.10},
        {'text': f'Venta #{sale_id}', 'align': 'center'},
        {'text': str(sale['created_at'] or '').replace('T', ' '), 'align': 'center', 'scale': .9},
        {'text': '-' * width},
    ]
    if sale['customer_name']:
        lines += [{'text': x} for x in _wrap('Cliente: ' + sale['customer_name'], width)]
    if sale['customer_dni']:
        lines.append({'text': 'DNI: ' + sale['customer_dni']})
    lines += [
        {'text': 'TARJETA', 'align': 'center', 'bold': True},
        {'text': sale['loyalty_card_number'], 'align': 'center', 'bold': True, 'scale': 1.20},
        {'text': '-' * width},
        {'text': _two('Saldo anterior', f'{previous_balance} pts', width)},
    ]
    if sale['loyalty_reward_name']:
        lines += [{'text': x, 'bold': True} for x in _wrap('Beneficio: ' + sale['loyalty_reward_name'], width)]
    if redeemed:
        lines.append({'text': _two('Puntos canjeados', f'-{redeemed} pts', width), 'bold': True})
    if earned:
        lines.append({'text': _two('Puntos sumados', f'+{earned} pts', width), 'bold': True})
    lines += [
        {'text': '-' * width},
        {'text': 'SALDO ACTUAL', 'align': 'center', 'bold': True},
        {'text': f'{final_balance} PUNTOS', 'align': 'center', 'bold': True, 'scale': 1.35},
        {'text': '-' * width},
        {'text': 'Tus puntos quedan asociados a tu DNI.', 'align': 'center'},
        {'text': 'Conservá este comprobante.', 'align': 'center', 'scale': .9},
        {'text': ''}, {'text': ''},
    ]
    return lines


def loyalty_ticket_text(sale_id, width_mm=None):
    return '\n'.join(x['text'] for x in loyalty_ticket_lines(sale_id, width_mm))


def _make_printer(width_mm, height_mm, printer_name=''):
    from PyQt6.QtCore import QSizeF, QMarginsF
    from PyQt6.QtGui import QPageSize, QPageLayout
    from PyQt6.QtPrintSupport import QPrinter, QPrinterInfo
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    try:
        printer.setResolution(203)
    except Exception:
        pass
    name = printer_name or get_setting('printer_name', '')
    if name:
        info = QPrinterInfo.printerInfo(name)
        if not info.isNull():
            printer.setPrinterName(name)
    page_size = QPageSize(QSizeF(float(width_mm), float(height_mm)), QPageSize.Unit.Millimeter, f'Ticket {width_mm}mm')
    layout = QPageLayout(page_size, QPageLayout.Orientation.Portrait, QMarginsF(1.2, 1.2, 1.2, 1.2), QPageLayout.Unit.Millimeter)
    printer.setPageLayout(layout)
    return printer


def _estimate_height(lines, width_mm):
    base = 4.2 if int(width_mm) <= 58 else 4.5
    total = 8.0
    for line in lines:
        total += base * float(line.get('scale', 1.0))
    return max(65.0, min(520.0, total + 12.0))


def _paint_lines(printer, lines, width_mm):
    """Impresión gráfica mediante el driver de Windows / Qt."""
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QPainter, QFont, QFontMetricsF
    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError('La impresora no aceptó el trabajo de impresión.')
    try:
        rect = printer.pageLayout().paintRectPixels(printer.resolution())
        margin = max(2, int(printer.resolution() / 25.4 * 0.8))
        x = rect.left() + margin
        y = rect.top() + margin
        w = rect.width() - margin * 2
        base_pt = 7.2 if int(width_mm) <= 58 else 8.4
        for entry in lines:
            scale = float(entry.get('scale', 1.0))
            font = QFont('Courier New')
            font.setStyleHint(QFont.StyleHint.Monospace)
            font.setPointSizeF(base_pt * scale)
            font.setBold(bool(entry.get('bold', False)))
            painter.setFont(font)
            fm = QFontMetricsF(font)
            h = max(fm.height() * 1.18, 8)
            align = entry.get('align', 'left')
            flags = Qt.AlignmentFlag.AlignVCenter
            if align == 'center':
                flags |= Qt.AlignmentFlag.AlignHCenter
            elif align == 'right':
                flags |= Qt.AlignmentFlag.AlignRight
            else:
                flags |= Qt.AlignmentFlag.AlignLeft
            painter.drawText(QRectF(x, y, w, h), int(flags), str(entry.get('text', '')))
            y += h
    finally:
        painter.end()


def _escpos_bytes(lines, width_mm):
    """Convierte el ticket a ESC/POS. Ideal para térmicas genéricas de 58/80 mm."""
    data = bytearray()
    data += b'\x1b@'                 # inicializar
    data += b'\x1b3\x18'            # interlineado razonable
    # CP850 suele funcionar bien con impresoras térmicas Windows y caracteres españoles.
    data += b'\x1bt\x02'
    current_align = None
    current_bold = None
    current_size = None
    for entry in lines:
        align = entry.get('align', 'left')
        if align != current_align:
            data += b'\x1ba' + bytes([1 if align == 'center' else 2 if align == 'right' else 0])
            current_align = align
        bold = bool(entry.get('bold', False))
        if bold != current_bold:
            data += b'\x1bE' + bytes([1 if bold else 0])
            current_bold = bold
        scale = float(entry.get('scale', 1.0))
        size = 0x11 if scale >= 1.25 else (0x01 if scale >= 1.08 else 0x00)
        if size != current_size:
            data += b'\x1d!' + bytes([size])
            current_size = size
        text = str(entry.get('text', ''))
        try:
            encoded = text.encode('cp850', errors='replace')
        except Exception:
            encoded = text.encode('ascii', errors='replace')
        data += encoded + b'\n'
    data += b'\x1bE\x00\x1d!\x00\x1ba\x00'
    feed = max(2, min(10, int(get_setting('thermal_feed_lines', '4') or 4)))
    data += b'\n' * feed
    if get_setting('thermal_auto_cut', '0') == '1':
        # Corte parcial. Si la impresora no tiene cutter, mantener esta opción desactivada.
        data += b'\x1dV\x42\x00'
    return bytes(data)


def _raw_windows_print(lines, width_mm, printer_name=''):
    """Envía el ticket como RAW al spooler de Windows evitando páginas gráficas vacías."""
    if __import__('os').name != 'nt':
        raise RuntimeError('La impresión RAW ESC/POS solo está disponible en Windows.')
    try:
        import win32print
    except ImportError as exc:
        raise RuntimeError('Falta pywin32. Ejecutá instalar_dependencias.bat y volvé a intentar.') from exc
    name = printer_name or get_setting('printer_name', '')
    if not name:
        name = win32print.GetDefaultPrinter()
    handle = win32print.OpenPrinter(name)
    try:
        job = win32print.StartDocPrinter(handle, 1, ('Heladeria - Ticket', None, 'RAW'))
        try:
            win32print.StartPagePrinter(handle)
            try:
                payload = _escpos_bytes(lines, width_mm)
                written = win32print.WritePrinter(handle, payload)
                if not written:
                    raise RuntimeError('Windows no envió bytes a la impresora.')
            finally:
                win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
    finally:
        win32print.ClosePrinter(handle)


def print_lines(lines, width_mm=None, printer_name=None, preview=False, parent=None, backend=None):
    """Imprime usando ESC/POS RAW o el driver gráfico.

    V13: el backend RAW no importa Qt, para que el servidor Web pueda imprimir
    pedidos automáticamente aun cuando se ejecuta sin QApplication.
    """
    width_mm = int(width_mm or get_setting('ticket_width_mm', '58'))
    printer_name = printer_name if printer_name is not None else get_setting('printer_name', '')
    backend = (backend or get_setting('print_backend', 'RAW_ESC_POS')).upper()

    if not preview and backend in ('RAW_ESC_POS', 'RAW', 'ESC_POS'):
        _raw_windows_print(lines, width_mm, printer_name)
        return

    if not preview and backend == 'AUTO':
        try:
            _raw_windows_print(lines, width_mm, printer_name)
            return
        except Exception:
            pass

    from PyQt6.QtPrintSupport import QPrintPreviewDialog, QPrinterInfo
    if preview:
        printer = _make_printer(width_mm, _estimate_height(lines, width_mm), printer_name)
        dlg = QPrintPreviewDialog(printer, parent)
        dlg.paintRequested.connect(lambda p: _paint_lines(p, lines, width_mm))
        dlg.exec()
        return

    if printer_name:
        info = QPrinterInfo.printerInfo(printer_name)
        if info.isNull() and __import__('os').name != 'nt':
            raise RuntimeError(f'No se encontró la impresora configurada: {printer_name}')

    printer = _make_printer(width_mm, _estimate_height(lines, width_mm), printer_name)
    _paint_lines(printer, lines, width_mm)


def print_sale_ticket(sale_id, preview=False, parent=None):
    width = int(get_setting('ticket_width_mm', '58'))
    print_lines(sale_ticket_lines(sale_id, width), width, preview=preview, parent=parent)


def print_order_ticket(order_id, preview=False, parent=None):
    width = int(get_setting('ticket_width_mm', '58'))
    print_lines(order_ticket_lines(order_id, width), width, preview=preview, parent=parent)


def print_loyalty_ticket(sale_id, preview=False, parent=None):
    width = int(get_setting('ticket_width_mm', '58'))
    print_lines(loyalty_ticket_lines(sale_id, width), width, preview=preview, parent=parent)
