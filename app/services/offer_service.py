from collections import Counter
from datetime import datetime, date
from app.database import db


def _offer_is_valid(row, now):
    weekday = now.weekday()
    today = now.date()
    current_time = now.strftime('%H:%M')
    if row['start_date'] and date.fromisoformat(row['start_date']) > today:
        return False
    if row['end_date'] and date.fromisoformat(row['end_date']) < today:
        return False
    days = {int(x) for x in (row['days_csv'] or '').split(',') if x.strip().isdigit()}
    if days and weekday not in days:
        return False
    if row['start_time'] and current_time < row['start_time']:
        return False
    if row['end_time'] and current_time > row['end_time']:
        return False
    return True


def active_offers(now=None):
    now = now or datetime.now()
    with db() as conn:
        rows = conn.execute('SELECT * FROM offers WHERE active=1 ORDER BY priority DESC, id DESC').fetchall()
    return [dict(r) for r in rows if _offer_is_valid(r, now)]


def active_offer_for_product(product_id, now=None):
    for row in active_offers(now):
        if row['product_id'] in (None, product_id) and row['offer_type'] in ('PRECIO_FIJO','PORCENTAJE','DESCUENTO_MONTO'):
            return row
    return None


def price_with_offer(product):
    base = float(product['price'])
    offer = active_offer_for_product(product['id'])
    if not offer:
        return base, None
    typ = offer['offer_type']
    value = float(offer['value'])
    if typ == 'PRECIO_FIJO':
        final = value
    elif typ == 'PORCENTAJE':
        final = base * (1 - value / 100)
    elif typ == 'DESCUENTO_MONTO':
        final = max(0, base - value)
    else:
        final = base
    return round(final, 2), offer


def apply_cart_offers(cart):
    """Recalcula ofertas sobre una copia lógica del carrito.

    Soporta precio fijo/porcentaje/monto por unidad, 2x1/NxM,
    cantidad por precio (ej. 2 por $10.000) y combo de varios productos.
    """
    # reset a precio individual vigente
    for item in cart:
        product = {'id': item['product_id'], 'price': item['base_price']}
        final, offer = price_with_offer(product)
        item['final_price'] = float(final)
        item['offer_id'] = offer['id'] if offer else None
        item['offer_name'] = offer['name'] if offer else None

    offers = active_offers()

    # Agrupadas por mismo producto: 2x1/NxM y N por precio fijo.
    by_product = {}
    for idx, item in enumerate(cart):
        by_product.setdefault(item['product_id'], []).append(idx)

    for offer in offers:
        typ = offer['offer_type']
        pid = offer['product_id']
        if typ not in ('2X1','NXM','CANTIDAD_PRECIO') or not pid or pid not in by_product:
            continue
        indexes = by_product[pid]
        if typ in ('2X1','NXM'):
            trigger = max(1, int(offer.get('trigger_qty') or 2))
            pay_qty = max(0, min(trigger, int(offer.get('pay_qty') or 1)))
            groups = len(indexes) // trigger
            for g in range(groups):
                group = indexes[g*trigger:(g+1)*trigger]
                # Cobra las primeras pay_qty y deja gratis el resto.
                for pos, idx in enumerate(group):
                    if pos >= pay_qty:
                        cart[idx]['final_price'] = 0.0
                    cart[idx]['offer_id'] = offer['id']
                    cart[idx]['offer_name'] = offer['name']
        elif typ == 'CANTIDAD_PRECIO':
            qty = max(1, int(offer.get('bundle_qty') or 2))
            groups = len(indexes) // qty
            per_unit = float(offer['value']) / qty
            for g in range(groups):
                for idx in indexes[g*qty:(g+1)*qty]:
                    cart[idx]['final_price'] = per_unit
                    cart[idx]['offer_id'] = offer['id']
                    cart[idx]['offer_name'] = offer['name']

    # Combo de productos distintos por precio total fijo.
    with db() as conn:
        combo_offers = [o for o in offers if o['offer_type'] == 'COMBO_PRECIO']
        for offer in combo_offers:
            req_rows = conn.execute('SELECT product_id, quantity FROM offer_items WHERE offer_id=?', (offer['id'],)).fetchall()
            if not req_rows:
                continue
            needed = Counter()
            for r in req_rows:
                needed[r['product_id']] += int(r['quantity'])
            available = Counter(item['product_id'] for item in cart)
            possible = min((available[pid] // qty for pid, qty in needed.items()), default=0)
            if possible < 1:
                continue
            # Aplica un combo por cada grupo posible, tomando los primeros ítems libres de esos productos.
            used = set()
            for _ in range(possible):
                combo_indexes = []
                for pid, qty in needed.items():
                    candidates = [i for i,item in enumerate(cart) if item['product_id']==pid and i not in used][:qty]
                    if len(candidates) < qty:
                        combo_indexes = []
                        break
                    combo_indexes.extend(candidates)
                if not combo_indexes:
                    break
                base_sum = sum(float(cart[i]['final_price']) for i in combo_indexes)
                target = float(offer['value'])
                # Distribución proporcional para que el total final coincida exactamente.
                if base_sum <= 0:
                    continue
                assigned = 0.0
                for pos, idx in enumerate(combo_indexes):
                    if pos == len(combo_indexes)-1:
                        new_price = max(0.0, target - assigned)
                    else:
                        new_price = round(target * (float(cart[idx]['final_price']) / base_sum), 2)
                        assigned += new_price
                    cart[idx]['final_price'] = new_price
                    cart[idx]['offer_id'] = offer['id']
                    cart[idx]['offer_name'] = offer['name']
                    used.add(idx)
    return cart


def display_offer_for_product(product_id, now=None):
    """Devuelve la oferta más prioritaria relacionada con el producto, para mostrar una etiqueta en POS."""
    offers = active_offers(now)
    for offer in offers:
        if offer['product_id'] == product_id:
            return offer
    with db() as conn:
        for offer in offers:
            if offer['offer_type'] == 'COMBO_PRECIO':
                row = conn.execute('SELECT 1 FROM offer_items WHERE offer_id=? AND product_id=?', (offer['id'], product_id)).fetchone()
                if row:
                    return offer
    return None
