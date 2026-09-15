import json
import math
import urllib.parse
import urllib.request
from datetime import datetime

from app.database import db
from app.settings_service import get_setting


def google_maps_link(address):
    q = urllib.parse.quote_plus(str(address or '').strip())
    return f'https://www.google.com/maps/search/?api=1&query={q}' if q else 'https://www.google.com/maps/'


def google_maps_embed_url(address):
    q = urllib.parse.quote_plus(str(address or '').strip())
    return f'https://www.google.com/maps?q={q}&output=embed' if q else ''


def _geocode_google(address, api_key):
    address = str(address or '').strip()
    api_key = str(api_key or '').strip()
    if not address or not api_key:
        return None
    query = urllib.parse.urlencode({'address': address, 'key': api_key})
    url = 'https://maps.googleapis.com/maps/api/geocode/json?' + query
    try:
        with urllib.request.urlopen(url, timeout=7) as response:
            payload = json.loads(response.read().decode('utf-8', errors='replace'))
    except Exception:
        return None
    if payload.get('status') != 'OK' or not payload.get('results'):
        return None
    result = payload['results'][0]
    loc = result.get('geometry', {}).get('location', {})
    if 'lat' not in loc or 'lng' not in loc:
        return None
    return {
        'lat': float(loc['lat']),
        'lng': float(loc['lng']),
        'formatted_address': result.get('formatted_address') or address,
    }


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def check_delivery_zone(address):
    """Valida la dirección contra un radio usando Google Geocoding cuando hay API key.

    Sin API key deja el pedido como A_VERIFICAR en vez de bloquearlo. El mapa visual
    sigue pudiéndose abrir mediante Google Maps.
    """
    address = str(address or '').strip()
    if not address:
        return {'status': 'SIN_DIRECCION', 'distance_km': None, 'lat': None, 'lng': None,
                'formatted_address': '', 'message': 'Ingresá una dirección de entrega.'}
    api_key = get_setting('google_maps_api_key', '').strip()
    center = (get_setting('delivery_center_address', '').strip()
              or get_setting('store_address', '').strip())
    try:
        radius = max(float(get_setting('delivery_radius_km', '5') or 5), 0.1)
    except Exception:
        radius = 5.0
    if not api_key or not center:
        return {'status': 'A_VERIFICAR', 'distance_km': None, 'lat': None, 'lng': None,
                'formatted_address': address,
                'message': 'Dirección cargada. Falta configurar Google Maps/centro de reparto para validar el radio automáticamente.'}
    dest = _geocode_google(address, api_key)
    origin = _geocode_google(center, api_key)
    if not dest:
        return {'status': 'NO_ENCONTRADA', 'distance_km': None, 'lat': None, 'lng': None,
                'formatted_address': address, 'message': 'Google Maps no pudo ubicar esa dirección. Revisala.'}
    if not origin:
        return {'status': 'A_VERIFICAR', 'distance_km': None, 'lat': dest['lat'], 'lng': dest['lng'],
                'formatted_address': dest['formatted_address'],
                'message': 'No se pudo ubicar el centro de reparto configurado.'}
    distance = _haversine_km(origin['lat'], origin['lng'], dest['lat'], dest['lng'])
    inside = distance <= radius
    return {
        'status': 'EN_ZONA' if inside else 'FUERA_DE_ZONA',
        'distance_km': round(distance, 2),
        'lat': dest['lat'], 'lng': dest['lng'],
        'formatted_address': dest['formatted_address'],
        'message': (f'Dirección dentro de zona · {distance:.2f} km del local.' if inside
                    else f'Dirección fuera de zona · {distance:.2f} km (radio configurado {radius:g} km).')
    }


def save_customer_delivery_address(customer_id, address):
    result = check_delivery_zone(address)
    now = datetime.now().isoformat(timespec='seconds')
    with db() as conn:
        conn.execute('''UPDATE customers SET address=?,address_lat=?,address_lng=?,
                        address_verified_at=?,address_zone_status=? WHERE id=?''',
                     (result.get('formatted_address') or address,
                      result.get('lat'), result.get('lng'), now,
                      result.get('status'), int(customer_id)))
    return result
