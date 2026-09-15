import os
import io
import html
import json
import socket
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, date, timedelta
from functools import wraps
from flask import Flask, request, redirect, url_for, session, render_template_string, jsonify, Response, send_file
from werkzeug.security import generate_password_hash, check_password_hash

from app.database import init_database, db
from app.config import DATA_DIR
from app.settings_service import get_setting, set_setting
from app.services.loyalty_service import create_or_update_customer, normalize_dni, ensure_customer_card, regenerate_customer_card, points_for_amount, reward_discount
from app.services.offer_service import price_with_offer
from app.services.ticket_service import print_order_ticket
from app.services.delivery_service import check_delivery_zone, save_customer_delivery_address, google_maps_embed_url, google_maps_link
from app.services.order_service import approve_transfer, reject_transfer, transition_order, cancel_order, mark_refunded, tracking_payload, customer_order_access
from app.services.mercadopago_service import configuration_status as mp_configuration_status, attach_qr_to_order, sync_local_order, create_online_card_order, create_checkout_pro_order

app = Flask(__name__)
app.secret_key = os.environ.get('HELADERIA_WEB_SECRET', 'heladeria-local-panel-change-me-v14')
app.config['MAX_CONTENT_LENGTH'] = 6 * 1024 * 1024


def h(v):
    return html.escape(str(v if v is not None else ''), quote=True)


def money(v):
    try:
        n=float(v)
        if abs(n-round(n)) < 0.005:
            return f"$ {n:,.0f}".replace(',', '.')
        txt=f"{n:,.2f}".replace(',', '#').replace('.', ',').replace('#', '.')
        return '$ ' + txt
    except Exception:
        return '$ 0'



def _birth_to_iso(value, required=False):
    text=str(value or '').strip()
    if not text:
        return None if required else ''
    for fmt in ('%d/%m/%Y','%Y-%m-%d'):
        try:
            parsed=datetime.strptime(text,fmt).date()
            if parsed > date.today():
                return None
            return parsed.isoformat()
        except Exception:
            pass
    return None


def _birth_display(value):
    text=str(value or '').strip()
    if not text:
        return ''
    try:
        return datetime.strptime(text[:10],'%Y-%m-%d').strftime('%d/%m/%Y')
    except Exception:
        try:
            return datetime.strptime(text,'%d/%m/%Y').strftime('%d/%m/%Y')
        except Exception:
            return text

def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return '127.0.0.1'


def portal_registration_url():
    configured = get_setting('portal_base_url', '').strip()
    if configured:
        return configured.rstrip('/') + '/club/registro'
    host = request.host.split(':')[0]
    port = request.host.split(':')[1] if ':' in request.host else get_setting('web_port', '5050')
    if host in ('127.0.0.1', 'localhost', '0.0.0.0'):
        host = local_ip()
    return f'http://{host}:{port}/club/registro'


def _public_request_base():
    """Base pública actual para volver desde Mercado Pago. Respeta proxies/túneles HTTPS."""
    configured=(get_setting('portal_base_url','') or '').strip()
    if configured and '://' in configured:
        # portal_base_url puede venir con /club o /club/registro; nos quedamos con origen.
        from urllib.parse import urlsplit
        parts=urlsplit(configured)
        if parts.scheme and parts.netloc:
            return f'{parts.scheme}://{parts.netloc}'
    proto=(request.headers.get('X-Forwarded-Proto') or request.scheme or 'http').split(',')[0].strip()
    host=(request.headers.get('X-Forwarded-Host') or request.host).split(',')[0].strip()
    return f'{proto}://{host}'.rstrip('/')


BASE = r'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="theme-color" content="#4d2034">
<title>{{ title }} · {{ store }}</title>
<style>
:root{--pink:#e94f86;--pink2:#ff7daa;--ink:#35262e;--muted:#75636d;--bg:#f7f4f6;--card:#fff;--line:#eadfe4;--green:#20ae6c;--blue:#3b91e8;--orange:#f28b32;--purple:#8059c8;--red:#c83556;--yellow:#f1b83b;--nav:#321d28}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;background:var(--bg);color:var(--ink);min-width:0}a{color:inherit}
.mobilebar{display:none}.nav-overlay{display:none}
nav.admin-nav{position:sticky;top:0;z-index:30;background:#fff;border-bottom:1px solid var(--line);padding:9px max(12px,env(safe-area-inset-left));display:flex;gap:7px;align-items:center;box-shadow:0 3px 16px #4d20340d;overflow-x:auto;-webkit-overflow-scrolling:touch}nav.admin-nav b{font-size:18px;white-space:nowrap;margin-right:8px}.navlink{color:var(--ink);text-decoration:none;padding:9px 10px;border-radius:10px;background:#f5edf1;font-weight:750;white-space:nowrap;font-size:13px}.navlink:hover{background:#eedde5}.navlink.logout{background:#493842;color:white}.navlink.portal{background:#dcf6e7;color:#17633d}.nav-section{display:none}
main{max-width:1440px;margin:auto;padding:18px;min-width:0}.hero{background:linear-gradient(135deg,#4d2034,#8e355d);color:#fff;border-radius:20px;padding:22px;margin-bottom:16px;box-shadow:0 10px 30px #4d203426}.hero h1{margin:0 0 5px;font-size:29px}.hero p{margin:0;opacity:.85}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px}.two{display:grid;grid-template-columns:1.25fr 1fr;gap:14px}.three{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.card{background:var(--card);border:1px solid var(--line);border-radius:17px;padding:16px;box-shadow:0 4px 18px #4d20340b;min-width:0}.kpi small{color:var(--muted);font-weight:850;font-size:11px;letter-spacing:.04em}.kpi strong{display:block;font-size:27px;margin-top:5px}.kpi .sub{color:var(--muted);font-size:12px;margin-top:5px}.status{display:inline-flex;align-items:center;gap:6px;padding:6px 9px;border-radius:999px;font-weight:850;font-size:12px}.good{background:#dcf7e8;color:#16693e}.bad{background:#ffe0e4;color:#942640}.warn{background:#fff1ce;color:#795a0b}.bluepill{background:#e3f1ff;color:#235f96}
h1,h2,h3{margin-top:0}h1{font-size:27px}.muted{color:var(--muted)}.scroll{overflow:auto;-webkit-overflow-scrolling:touch;max-width:100%}table{width:100%;border-collapse:separate;border-spacing:0;background:#fff;min-width:640px}th,td{padding:10px;border-bottom:1px solid #eee4e8;text-align:left;font-size:13px;vertical-align:top}th{background:#f8edf2;color:#503a45;font-size:12px;position:sticky;top:0}tr:hover td{background:#fffafd}.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}.num{text-align:right;white-space:nowrap}.btn{display:inline-flex;align-items:center;justify-content:center;gap:5px;text-decoration:none;border:0;border-radius:11px;padding:10px 13px;background:var(--pink);color:white;font-weight:850;cursor:pointer;font-size:13px;min-height:40px}.btn.blue{background:var(--blue)}.btn.green{background:var(--green)}.btn.orange{background:var(--orange)}.btn.purple{background:var(--purple)}.btn.gray{background:#66545d}.btn.red{background:var(--red)}.btn.yellow{background:var(--yellow);color:#4f3b08}.btn.big{font-size:16px;padding:14px 18px}.btn.block{width:100%}
.field{margin-bottom:13px}.field label{display:block;font-weight:850;margin-bottom:6px;font-size:13px}.field input,.field textarea,.field select,input.search,select,input[type=date],input[type=number]{width:100%;padding:11px;border:1px solid #d9cbd2;border-radius:10px;background:#fff;font-size:15px;max-width:100%}.field textarea{min-height:92px;resize:vertical}.formgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.quick{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.quick>*{flex:0 0 auto}.quick input{flex:1 1 220px}.notice{padding:12px 14px;border-radius:12px;background:#e5f7ed;color:#17613b;font-weight:750;margin-bottom:14px}.notice.error{background:#ffe0e4;color:#9a263e}.notice.info{background:#e5f2ff;color:#235f96}.login{max-width:400px;margin:10vh auto}.login input{width:100%;padding:15px;border:1px solid #dbcbd2;border-radius:12px;font-size:22px;margin:10px 0;text-align:center}.login button{width:100%;padding:14px;border:0;border-radius:12px;background:var(--pink);color:white;font-weight:900;font-size:17px}.sale-items{margin-top:10px}.sale-items td{font-size:12px}.badge{background:#f4edf1;border-radius:8px;padding:3px 6px;font-size:11px;font-weight:800;white-space:nowrap}.product-card{background:#fff;border:1px solid var(--line);border-radius:17px;padding:14px;display:flex;flex-direction:column;gap:6px;min-width:0}.product-card .price{font-size:22px;font-weight:950;color:#e94f86}.product-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.chatbox{height:55vh;overflow:auto;background:#faf7f9;border:1px solid var(--line);border-radius:15px;padding:12px}.msg{max-width:80%;padding:10px 12px;border-radius:14px;margin:8px 0;background:#fff;border:1px solid var(--line);overflow-wrap:anywhere}.msg.web{margin-left:auto;background:#e5f2ff;border-color:#c8e1fb}.msg small{display:block;color:var(--muted);margin-bottom:4px}.bottom-space{height:70px}
@media(max-width:900px){
 body{padding-top:0}.mobilebar{position:sticky;top:0;z-index:45;display:flex;align-items:center;gap:10px;min-height:58px;padding:calc(8px + env(safe-area-inset-top)) 12px 8px;background:linear-gradient(135deg,#3d2130,#6e304d);color:#fff;box-shadow:0 4px 18px #321d2833}.mobile-menu-btn{width:44px;height:44px;flex:0 0 44px;border:0;border-radius:12px;background:#ffffff1c;color:#fff;font-size:26px;font-weight:900;line-height:1;display:flex;align-items:center;justify-content:center}.mobile-title{min-width:0;flex:1}.mobile-title b{display:block;font-size:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.mobile-title span{display:block;font-size:11px;opacity:.8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.mobile-page-icon{font-size:23px}
 nav.admin-nav{position:fixed;display:flex;left:0;top:0;bottom:0;width:min(86vw,340px);height:100dvh;z-index:60;flex-direction:column;align-items:stretch;gap:7px;padding:calc(16px + env(safe-area-inset-top)) 14px calc(20px + env(safe-area-inset-bottom));background:#fff;overflow-y:auto;overflow-x:hidden;border-right:1px solid var(--line);box-shadow:18px 0 40px #321d2833;transform:translateX(-105%);transition:transform .22s ease;-webkit-overflow-scrolling:touch}.menu-open nav.admin-nav{transform:translateX(0)}nav.admin-nav b{font-size:19px;margin:0 0 6px;padding:8px 8px 12px;border-bottom:1px solid var(--line);white-space:normal}.nav-section{display:block;padding:8px 9px 2px;color:#9b8791;font-size:10px;font-weight:900;letter-spacing:.08em;text-transform:uppercase}.navlink{display:flex;align-items:center;width:100%;padding:12px 13px;border-radius:12px;font-size:14px;white-space:normal;min-height:45px}.navlink.logout{margin-top:7px}.navlink.portal{margin-top:4px}.nav-overlay{position:fixed;inset:0;z-index:55;background:#1b0f1766;backdrop-filter:blur(2px);-webkit-backdrop-filter:blur(2px)}.menu-open .nav-overlay{display:block}.menu-open{overflow:hidden}
 main{padding:12px;max-width:100%;overflow-x:hidden}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.two,.three,.formgrid{grid-template-columns:1fr}.product-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.hero{border-radius:15px;padding:18px}.hero h1{font-size:24px}.card{padding:13px}.kpi strong{font-size:23px}.btn.big{font-size:15px}.msg{max-width:94%}.field input,.field textarea,.field select,input.search,select,input[type=date],input[type=number]{font-size:16px}.quick{align-items:stretch}.quick>*{min-width:0}.quick input,.quick select{flex:1 1 100%}.quick .btn,.quick button.btn{flex:1 1 calc(50% - 5px)}
 .scroll{overflow:visible}.scroll table{min-width:0}
}
@media(max-width:700px){
 h1{font-size:23px}.grid{grid-template-columns:1fr 1fr;gap:9px}.product-grid{grid-template-columns:1fr 1fr;gap:9px}.card{border-radius:14px}.kpi strong{font-size:20px}.hero{margin-bottom:10px}.hero h1{font-size:21px}.product-card .price{font-size:19px}.btn{min-height:44px}.quick .btn,.quick button.btn{flex:1 1 100%}
 table.mobile-cards{display:block;width:100%;min-width:0;background:transparent;border-collapse:separate}table.mobile-cards tbody{display:block;width:100%}table.mobile-cards tr{display:block;width:100%}table.mobile-cards tr.table-head-row{display:none}table.mobile-cards tr:not(.table-head-row){background:#fff;border:1px solid var(--line);border-radius:14px;margin:0 0 10px;overflow:hidden;box-shadow:0 3px 13px #4d20340a}table.mobile-cards td{display:grid;grid-template-columns:minmax(105px,38%) minmax(0,1fr);gap:10px;width:100%;padding:9px 11px;border-bottom:1px solid #f0e7eb;text-align:left!important;white-space:normal!important;overflow-wrap:anywhere;min-height:38px;align-items:start}table.mobile-cards td:last-child{border-bottom:0}table.mobile-cards td:before{content:attr(data-label);font-size:10px;font-weight:900;letter-spacing:.03em;color:#846c78;text-transform:uppercase;line-height:1.35}table.mobile-cards td[data-label=""]:before{display:none}table.mobile-cards td[data-label=""]{display:block}table.mobile-cards td .btn,table.mobile-cards td>a.btn{width:100%;margin:2px 0}.sale-items.mobile-cards td{font-size:12px}
}
@media(max-width:430px){main{padding:9px}.grid{grid-template-columns:1fr 1fr}.product-grid{grid-template-columns:1fr}.hero{padding:15px}.card{padding:12px}.mobilebar{padding-left:9px;padding-right:9px}.mobile-title b{font-size:15px}.kpi strong{font-size:18px}table.mobile-cards td{grid-template-columns:100px minmax(0,1fr);padding:9px}.btn.big{width:100%}}
@media print{.mobilebar,.nav-overlay,nav,.no-print,.btn{display:none!important}body{background:white}main{max-width:none;padding:0}.card{box-shadow:none;border:0;padding:0}.report-head{display:block!important}table,table.mobile-cards{display:table!important;min-width:0!important}table.mobile-cards tbody{display:table-row-group!important}table.mobile-cards tr,table.mobile-cards tr.table-head-row{display:table-row!important;box-shadow:none!important;border:0!important}table.mobile-cards td{display:table-cell!important}table.mobile-cards td:before{display:none!important}th{position:static;background:#eee}tr{break-inside:avoid}.hero{background:white;color:black;border:1px solid #ddd}}
</style></head><body>
{% if session.get('ok') %}
<div class="mobilebar"><button class="mobile-menu-btn" type="button" aria-label="Abrir menú" aria-controls="adminNav" aria-expanded="false" onclick="toggleAdminMenu()">☰</button><div class="mobile-title"><b>🍦 {{ store }}</b><span>{{ title }}</span></div><div class="mobile-page-icon">⚙️</div></div>
<div class="nav-overlay" onclick="closeAdminMenu()"></div>
<nav class="admin-nav" id="adminNav"><b>🍦 {{ store }}<br><small style="font-size:11px;color:#8d7782">Panel de administración</small></b><span class="nav-section">Operación</span><a class="navlink" href="{{url_for('dashboard')}}">🏠 Inicio</a><a class="navlink" href="{{url_for('sales')}}">🧾 Ventas</a><a class="navlink" href="{{url_for('sales_report')}}">📊 Reportes</a><a class="navlink" href="{{url_for('orders')}}">🛵 Pedidos Web</a><a class="navlink" href="{{url_for('cash')}}">💵 Caja</a><span class="nav-section">Catálogo y clientes</span><a class="navlink" href="{{url_for('catalog')}}">🍦 Productos</a><a class="navlink" href="{{url_for('stock')}}">📦 Stock</a><a class="navlink" href="{{url_for('loyalty')}}">⭐ Puntos</a><a class="navlink" href="{{url_for('customers')}}">👥 Clientes</a><span class="nav-section">Herramientas</span><a class="navlink" href="{{url_for('delivery_config')}}">📍 Delivery / Pagos</a><a class="navlink" href="{{url_for('chat')}}">💬 Chat</a><a class="navlink portal" href="{{url_for('portal_qr')}}">📱 QR Clientes</a><a class="navlink logout" href="{{url_for('logout')}}">🚪 Salir</a></nav>
{% endif %}
<main>{{ body|safe }}</main>
<script>
(function(){
  function applyTableLabels(){
    document.querySelectorAll('table').forEach(function(table){
      if(table.dataset.mobileReady==='1') return;
      var rows=Array.from(table.querySelectorAll('tr'));
      if(!rows.length) return;
      var headerRow=rows.find(function(r){return r.querySelector('th')});
      if(!headerRow) return;
      var headers=Array.from(headerRow.querySelectorAll('th')).map(function(th){return (th.innerText||'').trim()});
      headerRow.classList.add('table-head-row');
      rows.forEach(function(row){
        if(row===headerRow) return;
        Array.from(row.querySelectorAll('td')).forEach(function(td,i){if(!td.hasAttribute('data-label')) td.setAttribute('data-label', headers[i] || '');});
      });
      table.classList.add('mobile-cards');
      table.dataset.mobileReady='1';
    });
  }
  window.toggleAdminMenu=function(){var open=document.body.classList.toggle('menu-open');var b=document.querySelector('.mobile-menu-btn');if(b)b.setAttribute('aria-expanded',open?'true':'false')};
  window.closeAdminMenu=function(){document.body.classList.remove('menu-open');var b=document.querySelector('.mobile-menu-btn');if(b)b.setAttribute('aria-expanded','false')};
  function setDevice(){var mobile=window.matchMedia('(max-width: 900px)').matches || (window.matchMedia('(pointer: coarse)').matches && window.innerWidth<1100);document.body.classList.toggle('mobile-admin',mobile);if(!mobile)closeAdminMenu()}
  document.addEventListener('DOMContentLoaded',function(){applyTableLabels();setDevice();document.querySelectorAll('#adminNav a').forEach(function(a){a.addEventListener('click',closeAdminMenu)});var main=document.querySelector('main');if(main){new MutationObserver(applyTableLabels).observe(main,{childList:true,subtree:true})}});
  window.addEventListener('resize',setDevice,{passive:true});document.addEventListener('keydown',function(e){if(e.key==='Escape')closeAdminMenu()});
})();
</script></body></html>'''

PORTAL_BASE = r'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#4f2bd8"><title>{{ title }} · {{ store }}</title><style>
:root{--violet:#4f2bd8;--violet2:#7a5cff;--orange:#ff6b00;--cyan:#00a8e8;--ink:#17172a;--muted:#6f7181;--bg:#f4f7ff;--card:#fff;--green:#16a66a;--red:#cf304a;--yellow:#f4b72f;--line:#e2e7f5}*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;background:linear-gradient(180deg,#eef2ff 0,#f8faff 170px,#f4f7ff 100%);color:var(--ink)}header{background:linear-gradient(135deg,#32158f 0%,#5c38e6 48%,#ff6b00 130%);color:white;padding:30px 18px 24px;text-align:center;border-radius:0 0 28px 28px;box-shadow:0 14px 40px #4424b833}header h1{margin:0;font-size:28px;font-weight:950}header p{margin:6px 0 0;opacity:.9;font-weight:700}.wrap{max-width:820px;margin:auto;padding:14px 14px calc(32px + env(safe-area-inset-bottom))}.card{background:white;border:1px solid var(--line);border-radius:20px;padding:17px;margin:12px 0;box-shadow:0 8px 26px #29336d12}.btn{display:block;width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(135deg,var(--violet),var(--violet2));color:white;font-weight:950;text-align:center;text-decoration:none;font-size:16px;box-shadow:0 8px 20px #5538dd2a;cursor:pointer}.btn.green{background:linear-gradient(135deg,#0d9a5d,#20c77b)}.btn.orange{background:linear-gradient(135deg,#f25a00,#ff8b22)}.btn.red{background:linear-gradient(135deg,#b91f3a,#e34c63)}.btn.gray{background:#53576a;box-shadow:none}.field{margin:12px 0}.field label{display:block;font-weight:900;margin-bottom:6px}.field input,.field select,.field textarea{width:100%;padding:13px;border:1px solid #cfd7ee;border-radius:12px;font-size:16px;background:#fff}.field textarea{min-height:100px}.product-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.product{background:#fff;border:1px solid var(--line);border-radius:17px;padding:14px;box-shadow:0 4px 16px #26346d0b}.product strong{display:block;font-size:16px}.price{font-size:21px;font-weight:950;color:var(--orange);margin-top:6px}.points{font-size:46px;font-weight:950;color:var(--violet);text-align:center}.muted{color:var(--muted);font-size:13px}.notice{padding:12px;border-radius:12px;background:#e3f8ed;color:#17613b;font-weight:800}.error{background:#ffe2e8;color:#962640}.clubnav{display:flex;gap:8px;overflow-x:auto;-webkit-overflow-scrolling:touch;margin:12px 0;padding-bottom:2px}.clubnav a{flex:0 0 auto;text-decoration:none;text-align:center;padding:10px 12px;border-radius:12px;background:#fff;border:1px solid var(--line);font-weight:900;font-size:13px;box-shadow:0 3px 12px #26346d0b}.clubnav a.primary{background:var(--violet);color:#fff;border-color:var(--violet)}.clubnav a.dark{background:#242539;color:#fff;border-color:#242539}.mapframe{width:100%;height:260px;border:0;border-radius:15px}.paybox{background:#f6f7ff;border:1px solid #dce2fa;border-radius:15px;padding:14px;margin:10px 0}.copyrow{display:flex;gap:8px;align-items:center}.copyrow code{flex:1;background:#fff;border:1px solid #dce2fa;border-radius:10px;padding:12px;word-break:break-all}.copyrow button{border:0;border-radius:10px;background:var(--violet);color:#fff;padding:11px 13px;font-weight:900}.flavors{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.flavor{display:block;border:1px solid #dce2fa;border-radius:12px;padding:10px;background:#fff}.orderline{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid #edf0f9}.goodzone{background:#e5f7ed;color:#17613b}.badzone{background:#ffe0e4;color:#962640}.warnzone{background:#fff1ce;color:#795a0b}.statushero{padding:18px;border-radius:18px;color:#fff;background:linear-gradient(135deg,#3f25b8,#6750e8)}.statushero.pending{background:linear-gradient(135deg,#d47a00,#ffac22)}.statushero.done{background:linear-gradient(135deg,#0c8d57,#23bd79)}.statushero.bad{background:linear-gradient(135deg,#a91f38,#e64d64)}.timeline{display:grid;grid-template-columns:repeat(5,1fr);gap:5px;margin:18px 0 5px}.step{text-align:center;position:relative;color:#9da1b4;font-size:11px;font-weight:850}.step .dot{width:36px;height:36px;margin:0 auto 7px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:#e9ecf5;color:#7d8295;font-size:17px;border:3px solid #fff;box-shadow:0 0 0 2px #e0e5f3}.step.active{color:var(--violet)}.step.active .dot{background:var(--violet);color:#fff;box-shadow:0 0 0 2px #b9abff}.step.done{color:#148453}.step.done .dot{background:var(--green);color:white;box-shadow:0 0 0 2px #9ce0bd}.pulse{animation:pulse 1.4s infinite}@keyframes pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.08)}}.livepill{display:inline-flex;gap:6px;align-items:center;background:#e9fff3;color:#137648;border-radius:999px;padding:6px 9px;font-size:12px;font-weight:900}.claimbox{border:2px solid #ffd5a8;background:#fff8ef}.loyalty-card{position:relative;overflow:hidden;border-radius:24px;padding:20px;color:#fff;background:linear-gradient(135deg,#31138f 0%,#5a31db 50%,#ff6b00 145%);box-shadow:0 16px 34px #3d22a63a;margin:12px 0}.loyalty-card:after{content:"";position:absolute;width:180px;height:180px;border-radius:50%;right:-70px;top:-75px;background:#ffffff18}.loyalty-brand{display:flex;align-items:center;gap:11px;position:relative;z-index:1}.loyalty-logo{width:52px;height:52px;border-radius:17px;background:#fff;color:#4f2bd8;display:flex;align-items:center;justify-content:center;font-size:31px;box-shadow:0 5px 16px #1d126b38}.loyalty-brand b{font-size:20px;letter-spacing:.02em}.loyalty-brand small{display:block;opacity:.82;font-weight:800;margin-top:2px}.loyalty-number{position:relative;z-index:1;font-size:28px;font-weight:950;letter-spacing:5px;text-align:center;margin:20px 0 6px}.loyalty-owner{position:relative;z-index:1;text-align:center;font-weight:850;opacity:.92}.barcode-wrap{position:relative;z-index:1;background:#fff;border-radius:13px;padding:8px 10px 5px;margin-top:15px}.barcode-wrap img{display:block;width:100%;height:72px;object-fit:contain}.reward-ready{border:2px solid #20b96f;background:#f2fff8}.fee-line{display:flex;justify-content:space-between;gap:12px;padding:7px 0}.fee-line.total{border-top:2px solid #e6e9f6;margin-top:6px;padding-top:12px;font-size:20px;font-weight:950}.hidden{display:none!important}
@media(min-width:700px){.product-grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:500px){.flavors{grid-template-columns:1fr}.copyrow{align-items:stretch}.copyrow code{font-size:13px}.timeline{gap:2px}.step{font-size:9px}.step .dot{width:31px;height:31px;font-size:14px}.wrap{padding-left:10px;padding-right:10px}.card{border-radius:16px;padding:14px}}
</style></head><body><header><h1>🍦 {{ store }}</h1><p>Pedidos & Club de Fidelidad</p></header><div class="wrap"><div class="clubnav"><a href="{{url_for('client_portal')}}">Productos</a>{% if session.get('client_customer_id') %}<a class="primary" href="{{url_for('client_order_catalog')}}">Hacer pedido</a><a href="{{url_for('client_orders')}}">Mis pedidos</a><a href="{{url_for('client_profile')}}">Mi perfil</a><a href="{{url_for('client_account')}}">Puntos</a><a class="dark" href="{{url_for('client_logout')}}">Salir</a>{% else %}<a class="primary" href="{{url_for('client_login')}}">Ingresar</a><a href="{{url_for('client_register')}}">Registrarme</a>{% endif %}</div>{{ body|safe }}</div></body></html>'''


def page(title, body):
    return render_template_string(BASE, title=title, body=body, store=get_setting('store_name','Dulces Momentos'))


def portal_page(title, body):
    return render_template_string(PORTAL_BASE, title=title, body=body, store=get_setting('store_name','Dulces Momentos'))



def _code39_svg(value):
    value=''.join(ch for ch in str(value or '') if ch.isdigit())
    if not value:
        value='00000000'
    patterns={
        '0':'nnnwwnwnn','1':'wnnwnnnnw','2':'nnwwnnnnw','3':'wnwwnnnnn','4':'nnnwwnnnw',
        '5':'wnnwwnnnn','6':'nnwwwnnnn','7':'nnnwnnwnw','8':'wnnwnnwnn','9':'nnwwnnwnn','*':'nwnnwnwnn'
    }
    narrow=2; wide=5; quiet=12; height=58; text_h=16
    seq='*'+value+'*'; x=quiet; rects=[]
    for ci,ch in enumerate(seq):
        pat=patterns[ch]
        for i,kind in enumerate(pat):
            w=wide if kind=='w' else narrow
            if i%2==0:
                rects.append(f'<rect x="{x}" y="2" width="{w}" height="{height}" fill="#111"/>')
            x+=w
        if ci != len(seq)-1:
            x+=narrow
    width=x+quiet
    svg=(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height+text_h}" '
         f'viewBox="0 0 {width} {height+text_h}" role="img" aria-label="Tarjeta {value}">'
         f'<rect width="100%" height="100%" fill="white"/>{"".join(rects)}'
         f'<text x="{width/2}" y="{height+13}" text-anchor="middle" font-family="Arial, sans-serif" '
         f'font-size="12" letter-spacing="2" fill="#111">{value}</text></svg>')
    return svg


def _loyalty_card_html(customer):
    if not customer:
        return ''
    card=h(customer['loyalty_card_number'] or '')
    owner=h(customer['name'] or 'Cliente')
    store=h(get_setting('store_name','Heladería Los Nietos') or 'Heladería Los Nietos')
    return (f'<div class="loyalty-card"><div class="loyalty-brand"><div class="loyalty-logo">🍦</div>'
            f'<div><b>{store}</b><small>TARJETA DIGITAL · CLUB DE FIDELIDAD</small></div></div>'
            f'<div class="loyalty-number">{card}</div><div class="loyalty-owner">{owner}</div>'
            f'<div class="barcode-wrap"><img src="{url_for("client_loyalty_barcode")}" alt="Código de barras de la tarjeta"></div></div>')


def _reward_for_customer(conn, customer_id, reward_id):
    if not reward_id:
        return None
    reward=conn.execute('''SELECT r.*,COALESCE(p.name,'') product_name
                           FROM loyalty_rewards r LEFT JOIN products p ON p.id=r.product_id
                           WHERE r.id=? AND r.active=1''',(int(reward_id),)).fetchone()
    if not reward:
        return None
    c=conn.execute('SELECT points FROM customers WHERE id=?',(int(customer_id),)).fetchone()
    if not c or int(c['points'] or 0)<int(reward['points_cost'] or 0):
        return None
    return reward


def _reward_discount_for_cart(reward, details, cart_total):
    items=[{'product_id':x['product']['id'],'final_price':x['unit_price'],'quantity':x['qty']} for x in details]
    return reward_discount(reward,items,cart_total) if reward else (0.0,'')


def auth_required(fn):
    @wraps(fn)
    def inner(*a, **kw):
        if not session.get('ok'):
            return redirect(url_for('login', next=request.path))
        return fn(*a, **kw)
    return inner


def client_auth_required(fn):
    @wraps(fn)
    def inner(*a, **kw):
        if not session.get('client_customer_id'):
            return redirect(url_for('client_login', next=request.path))
        return fn(*a, **kw)
    return inner


@app.route('/login', methods=['GET','POST'])
def login():
    error=''
    if request.method=='POST':
        if request.form.get('pin','') == get_setting('web_pin','2580'):
            session['ok']=True
            return redirect(request.args.get('next') or url_for('dashboard'))
        error='<div class="notice error">PIN incorrecto</div>'
    return page('Ingreso', f'<div class="login card"><h1>🍦 Panel de administración</h1><p class="muted">Control de ventas, stock, clientes y fidelidad.</p>{error}<form method="post"><input name="pin" type="password" inputmode="numeric" autofocus placeholder="PIN"><button>INGRESAR</button></form></div>')


@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))


@app.route('/')
@auth_required
def dashboard():
    with db() as conn:
        today=conn.execute("SELECT COALESCE(SUM(total),0) total,COUNT(*) tickets,COALESCE(AVG(total),0) avg FROM sales WHERE date(created_at)=date('now','localtime') AND status='CONFIRMADA'").fetchone()
        month=conn.execute("SELECT COALESCE(SUM(total),0) total FROM sales WHERE strftime('%Y-%m',created_at)=strftime('%Y-%m','now','localtime') AND status='CONFIRMADA'").fetchone()
        sess=conn.execute("SELECT cs.*,COALESCE(u.name,'') user_name FROM cash_sessions cs LEFT JOIN users u ON u.id=cs.user_id WHERE cs.status='ABIERTA' ORDER BY cs.id DESC LIMIT 1").fetchone()
        latest=conn.execute("SELECT s.id,s.created_at,s.total,s.payment_method,COALESCE(u.name,'') user_name FROM sales s LEFT JOIN users u ON u.id=s.user_id ORDER BY s.id DESC LIMIT 10").fetchall()
        low=conn.execute("SELECT COUNT(*) c FROM flavors WHERE active=1 AND (available=0 OR stock_kg<=min_stock_kg)").fetchone()['c']
        points=conn.execute("SELECT COALESCE(SUM(CASE WHEN points>0 THEN points ELSE 0 END),0) p FROM loyalty_movements WHERE date(created_at)=date('now','localtime')").fetchone()['p']
        unread=conn.execute("SELECT COUNT(*) c FROM internal_messages WHERE sender_type='SISTEMA' AND read_at IS NULL").fetchone()['c']
        pending_orders=conn.execute("SELECT COUNT(*) c FROM orders WHERE COALESCE(source,'MANUAL')='WEB' AND status NOT IN ('ENTREGADO','CANCELADO')").fetchone()['c']
    state='ABIERTA' if sess else 'CERRADA'; cls='good' if sess else 'bad'
    rows=''.join(f"<tr><td><a class='btn blue' href='{url_for('sale_detail',sale_id=r['id'])}'>#{r['id']}</a></td><td class='mono'>{h(str(r['created_at']).replace('T',' '))}</td><td>{h(r['user_name'])}</td><td>{h(r['payment_method'])}</td><td class='num'><b>{money(r['total'])}</b></td></tr>" for r in latest)
    body=f'''<div class="hero"><h1>Panel de Control</h1><p>Información en vivo de la heladería · misma base que el sistema de caja.</p></div>
    <div class="grid"><div class="card kpi"><small>VENTAS HOY</small><strong>{money(today['total'])}</strong><div class="sub">{today['tickets']} tickets</div></div><div class="card kpi"><small>TICKET PROMEDIO</small><strong>{money(today['avg'])}</strong></div><div class="card kpi"><small>VENTAS DEL MES</small><strong>{money(month['total'])}</strong></div><div class="card kpi"><small>CAJA</small><strong><span class="status {cls}">{state}</span></strong><div class="sub">{h(sess['user_name']) if sess else 'Sin sesión abierta'}</div></div></div>
    <div class="grid" style="margin-top:13px"><div class="card kpi"><small>PEDIDOS WEB ACTIVOS</small><strong>{pending_orders}</strong><div class="sub"><a href="{url_for('orders')}?source=WEB">Abrir pedidos</a></div></div><div class="card kpi"><small>ALERTAS STOCK</small><strong>{low}</strong></div><div class="card kpi"><small>PUNTOS GENERADOS HOY</small><strong>{points}</strong></div><div class="card kpi"><small>CHAT DESDE CAJA</small><strong>{unread}</strong><div class="sub"><a href="{url_for('chat')}">Abrir chat</a></div></div></div><div class="grid" style="margin-top:13px"><div class="card kpi"><small>PORTAL CLIENTE</small><strong>QR</strong><div class="sub"><a href="{url_for('portal_qr')}">Mostrar código</a></div></div></div>
    <div class="card" style="margin-top:14px"><div class="quick"><form class="quick" action="{url_for('customers')}" method="get" style="width:100%"><input class="search" name="q" placeholder="🔎 DNI, nombre o teléfono"><button class="btn blue">BUSCAR CLIENTE</button><a class="btn green" href="{url_for('customer_new')}">＋ CLIENTE</a><a class="btn purple" href="{url_for('loyalty_exception')}">⭐ EXCEPCIÓN PUNTOS</a></form></div></div>
    <div class="card" style="margin-top:14px"><h3>Últimas ventas · hora exacta y operador</h3><div class="scroll"><table><tr><th>Venta</th><th>Fecha / Hora</th><th>Operador</th><th>Pago</th><th class="num">Total</th></tr>{rows}</table></div></div>'''
    return page('Inicio',body)


@app.route('/ventas')
@auth_required
def sales():
    day=request.args.get('fecha',date.today().isoformat())
    q=request.args.get('q','').strip()
    where="date(s.created_at)=?"; params=[day]
    if q:
        where += " AND (CAST(s.id AS TEXT) LIKE ? OR COALESCE(c.dni,'') LIKE ? OR COALESCE(c.name,'') LIKE ?)"
        like=f'%{q}%'; params += [like,like,like]
    with db() as conn:
        rows=conn.execute(f'''SELECT s.*,COALESCE(c.name,'') customer_name,COALESCE(c.dni,'') customer_dni,COALESCE(u.name,'') user_name
                             FROM sales s LEFT JOIN customers c ON c.id=s.customer_id LEFT JOIN users u ON u.id=s.user_id
                             WHERE {where} ORDER BY s.id DESC LIMIT 600''',params).fetchall()
        totals=conn.execute("SELECT COALESCE(SUM(total),0) total,COUNT(*) c FROM sales WHERE date(created_at)=? AND status='CONFIRMADA'",(day,)).fetchone()
    trs=''.join(f"<tr><td><a class='btn blue' href='{url_for('sale_detail',sale_id=r['id'])}'>#{r['id']}</a></td><td class='mono'>{h(str(r['created_at']).replace('T',' '))}</td><td>{h(r['user_name'])}</td><td>{h(r['customer_dni'])}<br><span class='muted'>{h(r['customer_name'])}</span></td><td>{h(r['payment_method'])}</td><td>{float(r['manual_discount_percent'] or 0):g}%</td><td>+{int(r['loyalty_points_earned'] or 0)} / -{int(r['loyalty_points_redeemed'] or 0)}</td><td class='num'><b>{money(r['total'])}</b></td></tr>" for r in rows)
    body=f'''<div class="hero"><h1>Ventas</h1><p>Detalle por operación con hora exacta, operador, descuentos y fidelidad.</p></div><div class="card no-print"><form class="quick"><input type="date" name="fecha" value="{h(day)}"><input class="search" name="q" value="{h(q)}" placeholder="Venta, DNI o cliente"><button class="btn blue">FILTRAR</button><a class="btn purple" href="{url_for('sales_report')}?desde={h(day)}&hasta={h(day)}">🖨 REPORTE DEL DÍA</a></form></div><div class="grid" style="margin:13px 0"><div class="card kpi"><small>TOTAL</small><strong>{money(totals['total'])}</strong></div><div class="card kpi"><small>TICKETS</small><strong>{totals['c']}</strong></div></div><div class="card scroll"><table><tr><th>Venta</th><th>Fecha / hora</th><th>Operador</th><th>Cliente</th><th>Pago</th><th>Dto.%</th><th>Puntos</th><th class="num">Total</th></tr>{trs}</table></div>'''
    return page('Ventas',body)


@app.route('/ventas/<int:sale_id>')
@auth_required
def sale_detail(sale_id):
    with db() as conn:
        sale=conn.execute('''SELECT s.*,COALESCE(c.name,'') customer_name,COALESCE(c.dni,'') customer_dni,COALESCE(c.loyalty_card_number,'') card,COALESCE(u.name,'') user_name
                            FROM sales s LEFT JOIN customers c ON c.id=s.customer_id LEFT JOIN users u ON u.id=s.user_id WHERE s.id=?''',(sale_id,)).fetchone()
        items=conn.execute('''SELECT si.*,p.name product_name,COALESCE(o.name,'') offer_name FROM sale_items si JOIN products p ON p.id=si.product_id LEFT JOIN offers o ON o.id=si.offer_id WHERE si.sale_id=? ORDER BY si.id''',(sale_id,)).fetchall()
        movements=conn.execute("SELECT * FROM loyalty_movements WHERE sale_id=? ORDER BY id",(sale_id,)).fetchall()
    if not sale:return page('Venta','<h1>Venta inexistente</h1>'),404
    item_rows=''.join(f"<tr><td>{float(x['quantity']):g}</td><td><b>{h(x['product_name'])}</b>{('<br><span class=\"badge\">'+h(x['offer_name'])+'</span>') if x['offer_name'] else ''}</td><td>{h(x['flavor_text'])}</td><td class='num'>{money(x['unit_price'])}</td><td class='num'>{money(x['line_total'])}</td></tr>" for x in items)
    mov_rows=''.join(f"<tr><td class='mono'>{h(str(x['created_at']).replace('T',' '))}</td><td>{h(x['movement_type'])}</td><td>{int(x['points']):+d}</td><td>{x['balance_after']}</td><td>{h(x['description'])}</td></tr>" for x in movements) or '<tr><td colspan="5" class="muted">Sin movimientos de puntos</td></tr>'
    body=f'''<div class="hero"><h1>Venta #{sale_id}</h1><p>{h(str(sale['created_at']).replace('T',' '))} · Operador: {h(sale['user_name'])}</p></div><div class="grid"><div class="card kpi"><small>TOTAL</small><strong>{money(sale['total'])}</strong></div><div class="card kpi"><small>PAGO</small><strong style="font-size:18px">{h(sale['payment_method'])}</strong></div><div class="card kpi"><small>DESCUENTO MANUAL</small><strong>{float(sale['manual_discount_percent'] or 0):g}%</strong><div class="sub">{money(sale['manual_discount_amount'])}</div></div><div class="card kpi"><small>FIDELIDAD</small><strong>+{int(sale['loyalty_points_earned'] or 0)} / -{int(sale['loyalty_points_redeemed'] or 0)}</strong></div></div><div class="two" style="margin-top:14px"><div class="card"><h3>Cliente</h3><p><b>{h(sale['customer_name']) or 'Sin identificar'}</b><br>DNI: {h(sale['customer_dni']) or '-'}<br>Tarjeta: {h(sale['card']) or '-'}</p></div><div class="card"><h3>Importes</h3><p>Subtotal: <b>{money(sale['subtotal'])}</b><br>Descuentos: <b>- {money(sale['discount'])}</b><br>Total: <b>{money(sale['total'])}</b></p></div></div><div class="card scroll" style="margin-top:14px"><h3>Productos / gustos</h3><table><tr><th>Cant.</th><th>Producto</th><th>Sabores</th><th class="num">Unit.</th><th class="num">Total</th></tr>{item_rows}</table></div><div class="card scroll" style="margin-top:14px"><h3>Movimientos de puntos asociados</h3><table><tr><th>Fecha / hora</th><th>Tipo</th><th>Puntos</th><th>Saldo</th><th>Detalle</th></tr>{mov_rows}</table></div>'''
    return page(f'Venta #{sale_id}',body)


@app.route('/reportes/ventas')
@auth_required
def sales_report():
    today=date.today().isoformat(); desde=request.args.get('desde',today); hasta=request.args.get('hasta',today)
    with db() as conn:
        rows=conn.execute('''SELECT s.*,COALESCE(u.name,'') user_name,COALESCE(c.name,'') customer_name,COALESCE(c.dni,'') customer_dni
                             FROM sales s LEFT JOIN users u ON u.id=s.user_id LEFT JOIN customers c ON c.id=s.customer_id
                             WHERE date(s.created_at) BETWEEN ? AND ? ORDER BY s.created_at,s.id''',(desde,hasta)).fetchall()
        pay=conn.execute('''SELECT payment_method,COUNT(*) c,COALESCE(SUM(total),0) total FROM sales WHERE date(created_at) BETWEEN ? AND ? AND status='CONFIRMADA' GROUP BY payment_method ORDER BY total DESC''',(desde,hasta)).fetchall()
    total=sum(float(r['total'] or 0) for r in rows if r['status']=='CONFIRMADA')
    trs=''.join(f"<tr><td>#{r['id']}</td><td class='mono'>{h(str(r['created_at']).replace('T',' '))}</td><td>{h(r['user_name'])}</td><td>{h(r['customer_dni'])} {h(r['customer_name'])}</td><td>{h(r['payment_method'])}</td><td class='num'>{money(r['discount'])}</td><td class='num'><b>{money(r['total'])}</b></td></tr>" for r in rows)
    payrows=''.join(f"<tr><td>{h(r['payment_method'])}</td><td>{r['c']}</td><td class='num'>{money(r['total'])}</td></tr>" for r in pay)
    body=f'''<div class="report-head hero"><h1>Reporte de Ventas</h1><p>{h(desde)} al {h(hasta)} · Generado {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p></div><div class="card no-print"><form class="quick"><div><small>Desde</small><input type="date" name="desde" value="{h(desde)}"></div><div><small>Hasta</small><input type="date" name="hasta" value="{h(hasta)}"></div><button class="btn blue">GENERAR</button><button type="button" class="btn purple" onclick="window.print()">🖨 IMPRIMIR / PDF</button></form></div><div class="grid" style="margin:14px 0"><div class="card kpi"><small>TOTAL VENDIDO</small><strong>{money(total)}</strong></div><div class="card kpi"><small>OPERACIONES</small><strong>{len(rows)}</strong></div></div><div class="two"><div class="card scroll"><h3>Resumen por medio de pago</h3><table><tr><th>Medio</th><th>Tickets</th><th class="num">Total</th></tr>{payrows}</table></div><div class="card"><h3>Período</h3><p><b>Desde:</b> {h(desde)} 00:00:00<br><b>Hasta:</b> {h(hasta)} 23:59:59</p><p class="muted">Cada venta se muestra con fecha y hora exactas.</p></div></div><div class="card scroll" style="margin-top:14px"><table><tr><th>#</th><th>Fecha / Hora</th><th>Operador</th><th>Cliente</th><th>Pago</th><th class="num">Dto.</th><th class="num">Total</th></tr>{trs}</table></div>'''
    return page('Reporte de ventas',body)


def category_options(selected=None):
    with db() as conn: cats=conn.execute("SELECT id,name FROM categories WHERE active=1 ORDER BY name").fetchall()
    return ''.join(f"<option value='{r['id']}' {'selected' if str(r['id'])==str(selected) else ''}>{h(r['name'])}</option>" for r in cats)


@app.route('/productos')
@auth_required
def catalog():
    with db() as conn: rows=conn.execute("SELECT p.*,COALESCE(c.name,'') category_name FROM products p LEFT JOIN categories c ON c.id=p.category_id ORDER BY p.sort_order,p.name").fetchall()
    trs=''.join(f"<tr><td>{h(r['code'])}</td><td><b>{h(r['name'])}</b></td><td>{h(r['category_name'])}</td><td class='num'>{money(r['price'])}</td><td>{r['max_flavors']}</td><td>{'Sí' if r['show_in_sales'] else 'No'}</td><td>{'Sí' if r['active'] else 'No'}</td><td><a class='btn blue' href='{url_for('product_edit',product_id=r['id'])}'>EDITAR</a></td></tr>" for r in rows)
    return page('Productos',f'''<div class="hero"><h1>Productos</h1><p>Alta y modificación directa desde el panel web.</p></div><p><a class="btn green big" href="{url_for('product_new')}">＋ NUEVO PRODUCTO</a></p><div class="card scroll"><table><tr><th>Código</th><th>Producto</th><th>Categoría</th><th class="num">Precio</th><th>Gustos</th><th>En ventas</th><th>Activo</th><th></th></tr>{trs}</table></div>''')


def product_form(product=None,error=''):
    p=product or {}; edit=bool(product); err=f'<div class="notice error">{h(error)}</div>' if error else ''
    checked=lambda key,default=1: 'checked' if int(p[key] if edit else default) else ''
    return f'''<div class="hero"><h1>{'Editar' if edit else 'Nuevo'} producto</h1><p>Los cambios aparecen en la caja al refrescar la pantalla.</p></div>{err}<div class="card"><form method="post"><div class="formgrid"><div class="field"><label>Código</label><input name="code" value="{h(p['code'] if edit else '')}"></div><div class="field"><label>Nombre *</label><input name="name" required value="{h(p['name'] if edit else '')}"></div><div class="field"><label>Categoría</label><select name="category_id"><option value="">Sin categoría</option>{category_options(p['category_id'] if edit else None)}</select></div><div class="field"><label>Precio</label><input name="price" type="number" step="0.01" value="{h(p['price'] if edit else 0)}"></div><div class="field"><label>Costo</label><input name="cost" type="number" step="0.01" value="{h(p['cost'] if edit else 0)}"></div><div class="field"><label>Máximo de gustos</label><input name="max_flavors" type="number" min="0" max="12" value="{h(p['max_flavors'] if edit else 0)}"></div></div><p><label><input type="checkbox" name="show_in_sales" value="1" {checked('show_in_sales')}> Mostrar en Ventas</label> &nbsp; <label><input type="checkbox" name="active" value="1" {checked('active')}> Activo</label></p><button class="btn green big">💾 GUARDAR PRODUCTO</button> <a class="btn gray" href="{url_for('catalog')}">CANCELAR</a></form></div>'''


def save_product(product_id=None):
    f=request.form
    name=f.get('name','').strip()
    if not name:return False,'El nombre es obligatorio.'
    try: price=float(f.get('price') or 0); cost=float(f.get('cost') or 0); mf=int(f.get('max_flavors') or 0)
    except ValueError:return False,'Precio/costo/gustos inválidos.'
    vals=(f.get('code','').strip() or None,name,int(f['category_id']) if f.get('category_id') else None,price,cost,mf,1 if f.get('active') else 0,1 if f.get('show_in_sales') else 0)
    try:
        with db() as conn:
            if product_id: conn.execute("UPDATE products SET code=?,name=?,category_id=?,price=?,cost=?,max_flavors=?,active=?,show_in_sales=? WHERE id=?",vals+(product_id,))
            else: conn.execute("INSERT INTO products(code,name,category_id,price,cost,max_flavors,active,show_in_sales) VALUES (?,?,?,?,?,?,?,?)",vals)
            conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",(datetime.now().isoformat(timespec='seconds'),'WEB ADMIN','PRODUCTO_WEB',f'{"Editó" if product_id else "Creó"} {name}'))
        return True,''
    except Exception as e:return False,str(e)


@app.route('/productos/nuevo',methods=['GET','POST'])
@auth_required
def product_new():
    if request.method=='POST':
        ok,err=save_product()
        if ok:return redirect(url_for('catalog'))
        return page('Nuevo producto',product_form(None,err))
    return page('Nuevo producto',product_form())


@app.route('/productos/<int:product_id>',methods=['GET','POST'])
@auth_required
def product_edit(product_id):
    with db() as conn:p=conn.execute("SELECT * FROM products WHERE id=?",(product_id,)).fetchone()
    if not p:return page('Producto','<h1>Producto inexistente</h1>'),404
    if request.method=='POST':
        ok,err=save_product(product_id)
        if ok:return redirect(url_for('catalog'))
        with db() as conn:p=conn.execute("SELECT * FROM products WHERE id=?",(product_id,)).fetchone()
        return page('Editar producto',product_form(p,err))
    return page('Editar producto',product_form(p))


@app.route('/stock',methods=['GET','POST'])
@auth_required
def stock():
    if request.method=='POST':
        action=request.form.get('action')
        with db() as conn:
            if action=='flavor':
                fid=int(request.form['id']); qty=max(float(request.form.get('stock_kg') or 0),0); available=1 if request.form.get('available') else 0
                conn.execute("UPDATE flavors SET stock_kg=?,available=? WHERE id=?",(qty,available,fid))
            elif action=='item':
                sid=request.form.get('id'); name=request.form.get('name','').strip(); unit=request.form.get('unit','u').strip(); qty=float(request.form.get('quantity') or 0); minimum=float(request.form.get('minimum') or 0)
                if name:
                    if sid: conn.execute("UPDATE stock_items SET name=?,unit=?,quantity=?,minimum=?,active=1 WHERE id=?",(name,unit,qty,minimum,int(sid)))
                    else: conn.execute("INSERT INTO stock_items(name,unit,quantity,minimum,active) VALUES (?,?,?,?,1)",(name,unit,qty,minimum))
        return redirect(url_for('stock'))
    with db() as conn:
        flavors=conn.execute("SELECT * FROM flavors WHERE active=1 ORDER BY name").fetchall(); items=conn.execute("SELECT * FROM stock_items WHERE active=1 ORDER BY name").fetchall()
    frows=''.join(f"<tr><td><b>{h(x['name'])}</b></td><td>{h(x['category'])}</td><td><form method='post' class='quick'><input type='hidden' name='action' value='flavor'><input type='hidden' name='id' value='{x['id']}'><input style='width:110px' type='number' step='0.001' name='stock_kg' value='{x['stock_kg']}'><label><input type='checkbox' name='available' value='1' {'checked' if x['available'] else ''}> Disponible</label><button class='btn green'>GUARDAR</button></form></td><td><span class='status {'bad' if not x['available'] else ('warn' if x['stock_kg']<=x['min_stock_kg'] else 'good')}'>{'AGOTADO' if not x['available'] else ('BAJO' if x['stock_kg']<=x['min_stock_kg'] else 'OK')}</span></td></tr>" for x in flavors)
    irows=''.join(f"<tr><td>{h(x['name'])}</td><td>{h(x['unit'])}</td><td>{x['quantity']:g}</td><td>{x['minimum']:g}</td><td><a class='btn blue' href='{url_for('stock')}?edit={x['id']}#insumo'>Editar</a></td></tr>" for x in items)
    edit_id=request.args.get('edit'); edit=None
    if edit_id:
        with db() as conn:edit=conn.execute("SELECT * FROM stock_items WHERE id=?",(edit_id,)).fetchone()
    body=f'''<div class="hero"><h1>Stock</h1><p>Actualización directa de sabores e insumos desde Web.</p></div><div class="card scroll"><h3>Sabores</h3><table><tr><th>Sabor</th><th>Grupo</th><th>Cantidad / disponibilidad</th><th>Estado</th></tr>{frows}</table></div><div class="two" style="margin-top:14px"><div class="card scroll"><h3>Insumos</h3><table><tr><th>Insumo</th><th>Unidad</th><th>Cantidad</th><th>Mínimo</th><th></th></tr>{irows}</table></div><div class="card" id="insumo"><h3>{'Editar' if edit else 'Nuevo'} insumo</h3><form method="post"><input type="hidden" name="action" value="item"><input type="hidden" name="id" value="{h(edit['id'] if edit else '')}"><div class="field"><label>Nombre</label><input name="name" required value="{h(edit['name'] if edit else '')}"></div><div class="field"><label>Unidad</label><input name="unit" value="{h(edit['unit'] if edit else 'u')}"></div><div class="field"><label>Cantidad</label><input type="number" step="0.001" name="quantity" value="{h(edit['quantity'] if edit else 0)}"></div><div class="field"><label>Mínimo</label><input type="number" step="0.001" name="minimum" value="{h(edit['minimum'] if edit else 0)}"></div><button class="btn green big">GUARDAR STOCK</button></form></div></div>'''
    return page('Stock',body)


@app.route('/puntos')
@auth_required
def loyalty():
    q=request.args.get('q','').strip(); params=[]; where="WHERE COALESCE(c.dni,'')<>''"
    if q: where += " AND (c.dni LIKE ? OR c.name LIKE ? OR c.loyalty_card_number LIKE ?)"; like=f'%{q}%';params=[like,like,like]
    with db() as conn:
        customers=conn.execute(f"SELECT * FROM customers c {where} ORDER BY points DESC,name LIMIT 500",params).fetchall()
        movements=conn.execute("SELECT lm.*,c.name,c.dni FROM loyalty_movements lm JOIN customers c ON c.id=lm.customer_id ORDER BY lm.id DESC LIMIT 200").fetchall()
        rewards=conn.execute("SELECT r.*,COALESCE(p.name,'') product_name FROM loyalty_rewards r LEFT JOIN products p ON p.id=r.product_id ORDER BY r.points_cost").fetchall()
    crows=''.join(f"<tr><td>{h(r['dni'])}</td><td><a href='{url_for('customer_edit',customer_id=r['id'])}'><b>{h(r['name'])}</b></a><br><span class='muted'>{h(r['loyalty_card_number'])}</span></td><td><b>{r['points']}</b></td><td>{h(r['phone'])}</td></tr>" for r in customers)
    mrows=''.join(f"<tr><td class='mono'>{h(str(r['created_at']).replace('T',' '))}</td><td>{h(r['dni'])}<br>{h(r['name'])}</td><td>{h(r['movement_type'])}</td><td class='num'><b>{int(r['points']):+d}</b></td><td>{r['balance_after']}</td><td>{h(r['description'])}</td></tr>" for r in movements)
    rrows=''.join(f"<tr><td>{h(r['name'])}</td><td>{r['points_cost']}</td><td>{h(r['reward_type'])}</td><td>{h(r['product_name'])}</td></tr>" for r in rewards)
    body=f'''<div class="hero"><h1>Fidelidad / Puntos</h1><p>Saldos, movimientos, beneficios y correcciones por excepción.</p></div><div class="card no-print"><form class="quick"><input class="search" name="q" value="{h(q)}" placeholder="DNI, cliente o tarjeta"><button class="btn blue">BUSCAR</button><a class="btn purple" href="{url_for('loyalty_exception')}">＋ CARGA POR EXCEPCIÓN</a></form></div><div class="two" style="margin-top:14px"><div class="card scroll"><h3>Clientes</h3><table><tr><th>DNI</th><th>Cliente / tarjeta</th><th>Puntos</th><th>Teléfono</th></tr>{crows}</table></div><div class="card scroll"><h3>Beneficios</h3><table><tr><th>Beneficio</th><th>Puntos</th><th>Tipo</th><th>Producto</th></tr>{rrows}</table></div></div><div class="card scroll" style="margin-top:14px"><h3>Últimos movimientos</h3><table><tr><th>Fecha / hora</th><th>Cliente</th><th>Tipo</th><th class="num">Puntos</th><th>Saldo</th><th>Motivo</th></tr>{mrows}</table></div>'''
    return page('Puntos',body)


@app.route('/puntos/excepcion',methods=['GET','POST'])
@auth_required
def loyalty_exception():
    notice=''
    if request.method=='POST':
        dni=normalize_dni(request.form.get('dni')); reason=request.form.get('reason','').strip()
        try: pts=int(request.form.get('points') or 0)
        except ValueError: pts=0
        if not dni or pts==0 or not reason:
            notice='<div class="notice error">DNI, puntos distintos de cero y motivo son obligatorios.</div>'
        else:
            with db() as conn:
                c=conn.execute("SELECT * FROM customers WHERE dni=?",(dni,)).fetchone()
                if not c: notice='<div class="notice error">No existe un cliente con ese DNI.</div>'
                else:
                    new=max(0,int(c['points'] or 0)+pts); applied=new-int(c['points'] or 0)
                    conn.execute("UPDATE customers SET points=? WHERE id=?",(new,c['id']))
                    conn.execute("INSERT INTO loyalty_movements(created_at,customer_id,movement_type,points,description,balance_after) VALUES (?,?,?,?,?,?)",(datetime.now().isoformat(timespec='seconds'),c['id'],'EXCEPCION',applied,'WEB · '+reason,new))
                    conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",(datetime.now().isoformat(timespec='seconds'),'WEB ADMIN','PUNTOS_EXCEPCION',f'DNI {dni}: {applied:+d} · {reason}'))
                    notice=f'<div class="notice">✓ Ajuste aplicado a {h(c["name"])}. Nuevo saldo: <b>{new} puntos</b>.</div>'
    return page('Excepción de puntos',f'''<div class="hero"><h1>Carga de puntos por excepción</h1><p>Usar cuando una venta no generó los puntos correctamente. Todo queda auditado.</p></div>{notice}<div class="card"><form method="post"><div class="formgrid"><div class="field"><label>DNI del cliente</label><input name="dni" inputmode="numeric" required></div><div class="field"><label>Puntos a sumar o restar</label><input name="points" type="number" required placeholder="Ej.: 10 o -5"></div></div><div class="field"><label>Motivo obligatorio</label><textarea name="reason" required placeholder="Ej.: Venta #123 no acreditó puntos"></textarea></div><button class="btn purple big">⭐ APLICAR EXCEPCIÓN</button> <a class="btn gray" href="{url_for('loyalty')}">VOLVER</a></form></div>''')


@app.route('/clientes')
@auth_required
def customers():
    q=request.args.get('q','').strip(); params=[]; where=''
    if q: where="WHERE c.name LIKE ? OR COALESCE(c.dni,'') LIKE ? OR COALESCE(c.phone,'') LIKE ?"; like=f'%{q}%';params=[like,like,like]
    with db() as conn: rows=conn.execute(f'''SELECT c.*,COUNT(s.id) purchases,COALESCE(SUM(CASE WHEN s.status='CONFIRMADA' THEN s.total ELSE 0 END),0) spent,MAX(s.created_at) last_sale FROM customers c LEFT JOIN sales s ON s.customer_id=c.id {where} GROUP BY c.id ORDER BY c.name LIMIT 600''',params).fetchall()
    trs=''
    for r in rows:
        st=str(r['customer_status'] or 'ACTIVO').upper(); stcls='good' if st=='ACTIVO' else ('bad' if st=='BLOQUEADO' else 'warn')
        blocked=h(str(r['order_blocked_until'] or '').replace('T',' ')) or '—'
        trs+=f"<tr><td>{h(r['dni'])}</td><td><b>{h(r['name'])}</b><br><span class='muted'>{h(r['loyalty_card_number'])}</span></td><td><span class='status {stcls}'>{h(st)}</span><br><span class='muted'>Bloqueo pedidos: {blocked}</span></td><td>{h(r['phone'])}</td><td>{r['points']}</td><td>{r['purchases']}</td><td class='num'>{money(r['spent'])}</td><td>{h(str(r['last_sale'] or '').replace('T',' '))}</td><td><a class='btn blue' href='{url_for('customer_edit',customer_id=r['id'])}'>ABRIR</a></td></tr>"
    return page('Clientes',f'''<div class="hero"><h1>Clientes / CRM</h1><p>Datos, historial, fidelidad y habilitación para pedidos Web.</p></div><div class="card"><form class="quick"><input class="search" name="q" value="{h(q)}" placeholder="DNI, nombre o teléfono"><button class="btn blue">BUSCAR</button><a class="btn green" href="{url_for('customer_new')}">＋ NUEVO</a></form></div><div class="card scroll" style="margin-top:14px"><table><tr><th>DNI</th><th>Cliente / tarjeta</th><th>Estado pedidos</th><th>Teléfono</th><th>Puntos</th><th>Compras</th><th class="num">Total comprado</th><th>Última compra</th><th></th></tr>{trs}</table></div>''')


def customer_form(c=None,error=''):
    edit=bool(c); c=c or {}; err=f'<div class="notice error">{h(error)}</div>' if error else ''
    def raw(k,default=''):
        if not edit:return default
        try:return c[k] if c[k] is not None else default
        except Exception:return default
    val=lambda k: h(raw(k,''))
    birth=h(_birth_display(raw('birth_date','')))
    st=str(raw('customer_status','ACTIVO') or 'ACTIVO').upper()
    active=int(raw('active',1) or 0)
    opts=''.join(f'<option value="{x}" {"selected" if st==x else ""}>{x}</option>' for x in ('ACTIVO','SUSPENDIDO','BLOQUEADO'))
    active_opts=f'<option value="1" {"selected" if active else ""}>ACTIVO</option><option value="0" {"selected" if not active else ""}>INACTIVO</option>'
    return f'''{err}<div class="card"><form method="post"><div class="formgrid"><div class="field"><label>DNI</label><input name="dni" inputmode="numeric" value="{val('dni')}"></div><div class="field"><label>Nombre *</label><input name="name" required value="{val('name')}"></div><div class="field"><label>Teléfono</label><input name="phone" value="{val('phone')}"></div><div class="field"><label>Fecha de nacimiento · DD/MM/AAAA</label><input name="birth_date" inputmode="numeric" placeholder="31/12/1990" pattern="[0-3][0-9]/[0-1][0-9]/[0-9]{{4}}" value="{birth}"></div><div class="field"><label>Estado para pedidos Web</label><select name="customer_status">{opts}</select></div><div class="field"><label>Estado general del cliente</label><select name="active">{active_opts}</select></div></div><div class="field"><label>Motivo de bloqueo/suspensión</label><input name="order_block_reason" value="{val('order_block_reason')}" placeholder="Opcional. Ej.: revisión administrativa"></div><div class="field"><label>Dirección</label><input name="address" value="{val('address')}"></div><div class="field"><label>Notas</label><textarea name="notes">{val('notes')}</textarea></div><button class="btn green big">💾 GUARDAR CLIENTE</button> <a class="btn gray" href="{url_for('customers')}">CANCELAR</a></form></div>'''


@app.route('/clientes/nuevo',methods=['GET','POST'])
@auth_required
def customer_new():
    if request.method=='POST':
        f=request.form; name=f.get('name','').strip(); dni=normalize_dni(f.get('dni')) or None
        status=f.get('customer_status','ACTIVO').upper();status=status if status in ('ACTIVO','SUSPENDIDO','BLOQUEADO') else 'ACTIVO'
        active=1 if f.get('active','1')=='1' else 0
        birth=_birth_to_iso(f.get('birth_date',''),required=False)
        if not name:return page('Nuevo cliente',customer_form(None,'Nombre obligatorio.'))
        if f.get('birth_date','').strip() and birth is None:return page('Nuevo cliente',customer_form(None,'Fecha de nacimiento inválida. Usá DD/MM/AAAA.'))
        try:
            with db() as conn:
                cur=conn.execute("INSERT INTO customers(dni,name,phone,address,birth_date,notes,active,customer_status,order_block_reason) VALUES (?,?,?,?,?,?,?,?,?)",(dni,name,f.get('phone','').strip(),f.get('address','').strip(),birth or '',f.get('notes','').strip(),active,status,f.get('order_block_reason','').strip() or None)); cid=cur.lastrowid
                if dni: ensure_customer_card(cid,conn)
            return redirect(url_for('customer_edit',customer_id=cid))
        except sqlite3.IntegrityError:return page('Nuevo cliente',customer_form(None,'Ese DNI ya existe.'))
    return page('Nuevo cliente','<div class="hero"><h1>Nuevo cliente</h1></div>'+customer_form())


@app.route('/clientes/<int:customer_id>',methods=['GET','POST'])
@auth_required
def customer_edit(customer_id):
    if request.method=='POST':
        f=request.form; name=f.get('name','').strip();dni=normalize_dni(f.get('dni')) or None
        status=f.get('customer_status','ACTIVO').upper();status=status if status in ('ACTIVO','SUSPENDIDO','BLOQUEADO') else 'ACTIVO'
        active=1 if f.get('active','1')=='1' else 0
        birth=_birth_to_iso(f.get('birth_date',''),required=False)
        if f.get('birth_date','').strip() and birth is None:
            with db() as conn:c=conn.execute("SELECT * FROM customers WHERE id=?",(customer_id,)).fetchone()
            return page('Cliente','<div class="hero"><h1>Fecha inválida</h1></div>'+customer_form(c,'Usá el formato DD/MM/AAAA.'))
        try:
            with db() as conn:
                conn.execute("UPDATE customers SET dni=?,name=?,phone=?,address=?,birth_date=?,notes=?,active=?,customer_status=?,order_block_reason=? WHERE id=?",(dni,name,f.get('phone','').strip(),f.get('address','').strip(),birth or '',f.get('notes','').strip(),active,status,f.get('order_block_reason','').strip() or None,customer_id))
                if dni: ensure_customer_card(customer_id,conn)
        except sqlite3.IntegrityError:
            with db() as conn: c=conn.execute("SELECT * FROM customers WHERE id=?",(customer_id,)).fetchone()
            return page('Cliente','<div class="hero"><h1>DNI duplicado</h1></div>'+customer_form(c,'Ese DNI ya está registrado en otro cliente.'))
        return redirect(url_for('customer_edit',customer_id=customer_id,saved=1))
    with db() as conn:
        c=conn.execute("SELECT * FROM customers WHERE id=?",(customer_id,)).fetchone(); salesrows=conn.execute("SELECT * FROM sales WHERE customer_id=? ORDER BY id DESC LIMIT 50",(customer_id,)).fetchall(); movs=conn.execute("SELECT * FROM loyalty_movements WHERE customer_id=? ORDER BY id DESC LIMIT 100",(customer_id,)).fetchall(); portal=conn.execute("SELECT id,email,active,last_login_at,updated_at FROM portal_accounts WHERE customer_id=? LIMIT 1",(customer_id,)).fetchone()
    if not c:return page('Cliente','<h1>Cliente inexistente</h1>'),404
    access=customer_order_access(customer_id)
    sr=''.join(f"<tr><td><a href='{url_for('sale_detail',sale_id=r['id'])}'>#{r['id']}</a></td><td class='mono'>{h(str(r['created_at']).replace('T',' '))}</td><td>{h(r['payment_method'])}</td><td class='num'>{money(r['total'])}</td></tr>" for r in salesrows)
    mr=''.join(f"<tr><td class='mono'>{h(str(r['created_at']).replace('T',' '))}</td><td>{h(r['movement_type'])}</td><td>{int(r['points']):+d}</td><td>{r['balance_after']}</td><td>{h(r['description'])}</td></tr>" for r in movs)
    saved='<div class="notice">✓ Datos guardados.</div>' if request.args.get('saved') else ''
    reset_ok='<div class="notice">✓ Contraseña del Portal actualizada.</div>' if request.args.get('password_reset') else ''
    portal_created='<div class="notice">✓ Acceso al Portal creado por administración.</div>' if request.args.get('portal_created') else ''
    card_regenerated='<div class="notice">✓ Tarjeta de fidelidad regenerada. El número anterior quedó invalidado y los puntos se conservaron.</div>' if request.args.get('card_regenerated') else ''
    unblock_ok='<div class="notice">✓ Bloqueo temporal de pedidos eliminado.</div>' if request.args.get('unblocked') else ''
    if portal:
        portal_user=('DNI del cliente' if str(portal['email'] or '').endswith('@portal.local') else str(portal['email'] or ''))
        portal_card=f'''<div class="card"><h3>🔐 Acceso al Portal</h3><p><b>Usuario:</b> {h(portal_user)}<br><b>Estado:</b> {'ACTIVO' if portal['active'] else 'INACTIVO'}<br><b>Último ingreso:</b> {h(str(portal['last_login_at'] or 'Nunca').replace('T',' '))}</p><form method="post" action="{url_for('admin_reset_client_password',customer_id=customer_id)}"><div class="formgrid"><div class="field"><label>Nueva contraseña</label><input name="password" type="password" minlength="6" autocomplete="new-password" required></div><div class="field"><label>Repetir contraseña</label><input name="confirm_password" type="password" minlength="6" autocomplete="new-password" required></div></div><button class="btn red big">🔑 RESETEAR CONTRASEÑA DEL PORTAL</button></form><p class="muted" style="margin-bottom:0">El cambio queda registrado en auditoría. La clave actual nunca se muestra.</p></div>'''
    else:
        portal_card=f'''<div class="card"><h3>🔐 Crear acceso al Portal</h3><div class="notice info">Este cliente todavía no tiene usuario. El operador puede crearlo sin que el cliente tenga que registrarse desde el teléfono.</div><form method="post" action="{url_for('admin_create_client_portal',customer_id=customer_id)}"><div class="field"><label>Correo electrónico (opcional)</label><input name="email" type="email" autocomplete="off" placeholder="Si lo dejás vacío, podrá ingresar con DNI"></div><div class="formgrid"><div class="field"><label>Contraseña provisoria</label><input name="password" type="password" minlength="6" required></div><div class="field"><label>Repetir contraseña</label><input name="confirm_password" type="password" minlength="6" required></div></div><button class="btn green big">＋ CREAR USUARIO DEL PORTAL</button></form><p class="muted" style="margin-bottom:0">El cliente siempre puede ingresar usando su DNI. Si tiene correo, también podrá usarlo. Después puede usar “Olvidé mi contraseña” o administración puede resetearla.</p></div>'''
    access_cls='notice' if access.get('allowed') else 'notice error'
    until=''
    if c['order_blocked_until']:
        until=f'<p><b>Bloqueo temporal hasta:</b> {h(str(c["order_blocked_until"]).replace("T"," "))}</p><form method="post" action="{url_for("customer_clear_order_block",customer_id=customer_id)}"><button class="btn yellow">LEVANTAR BLOQUEO TEMPORAL</button></form>'
    order_access_card=f'''<div class="card"><h3>🛡 Habilitación de pedidos Web</h3><div class="{access_cls}">{h(access.get('message'))}</div><p><b>Estado administrativo:</b> {h(c['customer_status'] or 'ACTIVO')}</p>{until}</div>'''
    loyalty_admin=f'''<div class="card"><h3>💳 Tarjeta de fidelidad</h3><p><b>Número actual:</b> <span class="mono" style="font-size:20px">{h(c['loyalty_card_number'])}</span><br><b>Puntos:</b> {int(c['points'] or 0)}</p><p class="muted">Si la tarjeta física se pierde, el cliente no recuerda el número o necesitás invalidarla, generá una nueva. Los puntos y el historial no se pierden.</p><form method="post" action="{url_for('admin_regenerate_loyalty_card',customer_id=customer_id)}" onsubmit="return confirm('¿Invalidar la tarjeta actual y generar una nueva? Los puntos se conservarán.');"><div class="field"><label>Motivo</label><select name="reason"><option>EXTRAVÍO / PÉRDIDA</option><option>CLIENTE NO RECUERDA TARJETA</option><option>TARJETA DETERIORADA</option><option>REEMPLAZO ADMINISTRATIVO</option></select></div><button class="btn orange big">♻ REGENERAR TARJETA</button></form></div>'''
    return page('Cliente',f'''<div class="hero"><h1>{h(c['name'])}</h1><p>DNI {h(c['dni'])} · {h(c['loyalty_card_number'])} · ⭐ {c['points']} puntos</p></div>{saved}{reset_ok}{portal_created}{card_regenerated}{unblock_ok}{customer_form(c)}<div class="two" style="margin-top:14px">{order_access_card}{portal_card}</div><div style="margin-top:14px">{loyalty_admin}</div><div class="two" style="margin-top:14px"><div class="card scroll"><h3>Ventas</h3><table><tr><th>#</th><th>Fecha/hora</th><th>Pago</th><th class="num">Total</th></tr>{sr}</table></div><div class="card scroll"><h3>Puntos</h3><table><tr><th>Fecha/hora</th><th>Tipo</th><th>Puntos</th><th>Saldo</th><th>Detalle</th></tr>{mr}</table></div></div>''')


@app.route('/clientes/<int:customer_id>/desbloquear-pedidos',methods=['POST'])
@auth_required
def customer_clear_order_block(customer_id):
    now=datetime.now().isoformat(timespec='seconds')
    with db() as conn:
        c=conn.execute("SELECT id,name FROM customers WHERE id=?",(customer_id,)).fetchone()
        if not c:return Response('Cliente inexistente',404)
        conn.execute("UPDATE customers SET order_blocked_until=NULL,order_block_reason=CASE WHEN customer_status='ACTIVO' THEN NULL ELSE order_block_reason END WHERE id=?",(customer_id,))
        conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",(now,'WEB ADMIN','DESBLOQUEO_PEDIDOS',f'Cliente {c["name"]} · bloqueo temporal levantado manualmente'))
    return redirect(url_for('customer_edit',customer_id=customer_id,unblocked=1))


@app.route('/clientes/<int:customer_id>/crear-portal', methods=['POST'])
@auth_required
def admin_create_client_portal(customer_id):
    email=request.form.get('email','').strip().lower()
    password=request.form.get('password','')
    confirm=request.form.get('confirm_password','')
    if email and ('@' not in email or '.' not in email.split('@')[-1]):
        return page('Crear acceso','<div class="notice error">Ingresá un correo electrónico válido o dejalo vacío para acceso por DNI.</div><a class="btn" href="'+url_for('customer_edit',customer_id=customer_id)+'">VOLVER</a>'),400
    if len(password)<6 or password!=confirm:
        return page('Crear acceso','<div class="notice error">La contraseña debe tener al menos 6 caracteres y ambas deben coincidir.</div><a class="btn" href="'+url_for('customer_edit',customer_id=customer_id)+'">VOLVER</a>'),400
    now=datetime.now().isoformat(timespec='seconds')
    try:
        with db() as conn:
            c=conn.execute('SELECT id,name,dni FROM customers WHERE id=?',(customer_id,)).fetchone()
            if not c:return Response('Cliente inexistente',404)
            if not email:
                email=f'cliente{customer_id}@portal.local'
            if conn.execute('SELECT 1 FROM portal_accounts WHERE customer_id=?',(customer_id,)).fetchone():
                return redirect(url_for('customer_edit',customer_id=customer_id))
            if conn.execute('SELECT 1 FROM portal_accounts WHERE lower(email)=lower(?)',(email,)).fetchone():
                return page('Crear acceso','<div class="notice error">Ese correo ya está asociado a otra cuenta del Portal.</div><a class="btn" href="'+url_for('customer_edit',customer_id=customer_id)+'">VOLVER</a>'),409
            conn.execute('INSERT INTO portal_accounts(customer_id,email,password_hash,created_at,updated_at,active) VALUES (?,?,?,?,?,1)', (customer_id,email,generate_password_hash(password),now,now))
            conn.execute('INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)', (now,'WEB ADMIN','CREAR_PORTAL_CLIENTE',f'Cliente {c["name"]} · DNI {c["dni"] or ""} · {email}'))
    except sqlite3.IntegrityError:
        return page('Crear acceso','<div class="notice error">No se pudo crear el acceso. Revisá que el correo no esté usado.</div><a class="btn" href="'+url_for('customer_edit',customer_id=customer_id)+'">VOLVER</a>'),409
    return redirect(url_for('customer_edit',customer_id=customer_id,portal_created=1))


@app.route('/clientes/<int:customer_id>/regenerar-tarjeta', methods=['POST'])
@auth_required
def admin_regenerate_loyalty_card(customer_id):
    reason=request.form.get('reason','REEMPLAZO ADMINISTRATIVO').strip() or 'REEMPLAZO ADMINISTRATIVO'
    try:
        regenerate_customer_card(customer_id,reason,actor='WEB ADMIN')
    except Exception as exc:
        return page('Tarjeta de fidelidad',f'<div class="notice error">{h(exc)}</div><a class="btn" href="{url_for("customer_edit",customer_id=customer_id)}">VOLVER</a>'),400
    return redirect(url_for('customer_edit',customer_id=customer_id,card_regenerated=1))


@app.route('/clientes/<int:customer_id>/reset-clave', methods=['POST'])
@auth_required
def admin_reset_client_password(customer_id):
    password=request.form.get('password','')
    confirm=request.form.get('confirm_password','')
    if len(password) < 6:
        return page('Resetear contraseña','<div class="hero"><h1>Contraseña inválida</h1></div><div class="notice error">La contraseña debe tener al menos 6 caracteres.</div><a class="btn" href="'+url_for('customer_edit',customer_id=customer_id)+'">VOLVER AL CLIENTE</a>'),400
    if password != confirm:
        return page('Resetear contraseña','<div class="hero"><h1>Las contraseñas no coinciden</h1></div><div class="notice error">Repetí exactamente la misma contraseña.</div><a class="btn" href="'+url_for('customer_edit',customer_id=customer_id)+'">VOLVER AL CLIENTE</a>'),400
    now=datetime.now().isoformat(timespec='seconds')
    with db() as conn:
        c=conn.execute("SELECT id,dni,name FROM customers WHERE id=? LIMIT 1",(customer_id,)).fetchone()
        account=conn.execute("SELECT id,email FROM portal_accounts WHERE customer_id=? LIMIT 1",(customer_id,)).fetchone()
        if not c:
            return page('Resetear contraseña','<h1>Cliente inexistente</h1>'),404
        if not account:
            return page('Resetear contraseña','<div class="hero"><h1>Sin cuenta de Portal</h1></div><div class="notice error">Este cliente todavía no tiene usuario de Portal para resetear.</div><a class="btn" href="'+url_for('customer_edit',customer_id=customer_id)+'">VOLVER AL CLIENTE</a>'),400
        conn.execute("UPDATE portal_accounts SET password_hash=?,updated_at=?,active=1 WHERE id=?",(generate_password_hash(password),now,account['id']))
        conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",(now,'WEB ADMIN','RESET_CLAVE_PORTAL',f"Cliente {c['name']} · DNI {c['dni']} · {account['email']}"))
    return redirect(url_for('customer_edit',customer_id=customer_id,password_reset=1))


def _safe_print_order(order_id, setting_key='web_order_auto_print_pending', action='IMPRESION_PEDIDO_WEB'):
    # V19: si la impresión inicial está asignada al sistema central, el proceso Web
    # no toma la impresora. Así evitamos tickets duplicados y la comanda sale del POS.
    if action == 'IMPRESION_PEDIDO_WEB' and get_setting('web_order_central_auto_print', '1') == '1':
        return
    if get_setting(setting_key, '1') != '1':
        return
    try:
        print_order_ticket(order_id, parent=None)
        if action == 'IMPRESION_PEDIDO_WEB':
            with db() as conn:
                conn.execute("UPDATE orders SET reception_printed_at=COALESCE(reception_printed_at,?) WHERE id=?",
                             (datetime.now().isoformat(timespec='seconds'), int(order_id)))
    except Exception as exc:
        with db() as conn:
            conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",
                         (datetime.now().isoformat(timespec='seconds'),'WEB',action,
                          f'Pedido #{order_id}: no se pudo imprimir: {exc}'))


def _proof_dir():
    folder = DATA_DIR / 'comprobantes_web'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@app.route('/pedidos')
@auth_required
def orders():
    source=request.args.get('source','TODOS').upper()
    where='1=1'; params=[]
    if source in ('WEB','MANUAL'):
        where="COALESCE(o.source,'MANUAL')=?";params=[source]
    with db() as conn:
        rows=conn.execute(f'''SELECT o.*,COALESCE(c.name,'') customer_name,COALESCE(c.dni,'') customer_dni
                             FROM orders o LEFT JOIN customers c ON c.id=o.customer_id
                             WHERE {where} ORDER BY o.id DESC LIMIT 500''',params).fetchall()
    trs=''
    for r in rows:
        paystatus=h((r['payment_status'] or '').replace('_',' '))
        status_cls='warn' if r['payment_status']=='PENDIENTE_VERIFICACION' else ('good' if r['payment_status'] in ('APROBADO','PAGO_APROBADO','PAGO_EN_ENTREGA') else 'bad' if r['payment_status']=='RECHAZADO' else 'bluepill')
        trs+=f'''<tr><td><a class="btn blue" href="{url_for('order_detail_admin',order_id=r['id'])}">#{r['id']}</a></td>
        <td class="mono">{h(str(r['created_at']).replace('T',' '))}</td><td><b>{h(r['customer_name'])}</b><br><span class="muted">DNI {h(r['customer_dni'])}</span></td>
        <td>{h(r['source'] or 'MANUAL')}</td><td>{h(r['order_type'])}</td><td><b>{h(r['status'])}</b></td>
        <td><span class="status {status_cls}">{paystatus or h(r['payment_method'] or 'A DEFINIR')}</span></td><td class="num"><b>{money(r['total'])}</b></td></tr>'''
    return page('Pedidos Web',f'''<div class="hero"><h1>📲 Pedidos Web / Delivery</h1><p>Pedidos del portal, comprobantes de transferencia y pedidos manuales.</p></div>
    <div class="card no-print"><div class="quick"><a class="btn {'purple' if source=='TODOS' else 'gray'}" href="{url_for('orders')}?source=TODOS">TODOS</a><a class="btn {'purple' if source=='WEB' else 'gray'}" href="{url_for('orders')}?source=WEB">SOLO WEB</a><a class="btn {'purple' if source=='MANUAL' else 'gray'}" href="{url_for('orders')}?source=MANUAL">MANUALES</a></div></div>
    <div class="card scroll" style="margin-top:14px"><table><tr><th>#</th><th>Fecha/hora</th><th>Cliente</th><th>Origen</th><th>Tipo</th><th>Estado</th><th>Pago</th><th class="num">Total</th></tr>{trs}</table></div>''')


@app.route('/pedidos/<int:order_id>')
@auth_required
def order_detail_admin(order_id):
    # Si es Mercado Pago, consultar primero a MP. Un pago acreditado pasa solo a EN PREPARACIÓN.
    try: sync_local_order(int(order_id),auto_transition=True)
    except Exception: pass
    with db() as conn:
        o=conn.execute('''SELECT o.*,COALESCE(c.name,'') customer_name,COALESCE(c.dni,'') customer_dni,
                          COALESCE(c.loyalty_card_number,'') card FROM orders o LEFT JOIN customers c ON c.id=o.customer_id WHERE o.id=?''',(order_id,)).fetchone()
        items=conn.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY id",(order_id,)).fetchall()
        events=conn.execute("SELECT * FROM order_status_events WHERE order_id=? ORDER BY id DESC LIMIT 20",(order_id,)).fetchall()
        claims=conn.execute("SELECT * FROM order_claims WHERE order_id=? ORDER BY id DESC",(order_id,)).fetchall()
    if not o:return page('Pedido','<h1>Pedido inexistente</h1>'),404
    ir=''.join(f"<tr><td>{float(x['quantity']):g}</td><td><b>{h(x['product_name'])}</b></td><td>{h(x['flavor_text'])}</td><td class='num'>{money(x['unit_price'])}</td><td class='num'>{money(x['line_total'])}</td></tr>" for x in items)
    ev=''.join(f"<tr><td class='mono'>{h(str(x['created_at']).replace('T',' '))}</td><td><b>{h(x['status'])}</b></td><td>{h((x['payment_status'] or '').replace('_',' '))}</td><td>{h(x['actor'])}</td><td>{h(x['note'])}</td></tr>" for x in events) or '<tr><td colspan="5" class="muted">Sin movimientos registrados.</td></tr>'
    cl=''.join(f'''<tr><td>#{x['id']}</td><td><b>{h(x['status'])}</b></td><td>{h(x['expected_flavors'])}</td><td>{h(x['received_flavor'])}</td><td>{h(x['description'])}</td><td><form method="post" action="{url_for('order_claim_status_admin',order_id=order_id,claim_id=x['id'])}"><select name="status"><option>PENDIENTE</option><option {'selected' if x['status']=='EN REVISION' else ''}>EN REVISION</option><option {'selected' if x['status']=='RESUELTO' else ''}>RESUELTO</option><option {'selected' if x['status']=='RECHAZADO' else ''}>RECHAZADO</option></select><button class="btn blue">GUARDAR</button></form></td></tr>''' for x in claims) or '<tr><td colspan="6" class="muted">Sin reclamos.</td></tr>'
    proof=(f'<a class="btn purple" target="_blank" href="{url_for("order_payment_proof",order_id=order_id)}">📎 VER COMPROBANTE</a>' if o['payment_proof_path'] else '<span class="muted">Sin comprobante adjunto</span>')
    actions=''
    closed=str(o['status'] or '').upper() in ('ENTREGADO','RECHAZADO','CANCELADO')
    if o['payment_method']=='TRANSFERENCIA' and o['payment_status']=='PENDIENTE_VERIFICACION' and not closed:
        actions=f'''<form method="post" action="{url_for('order_approve_transfer',order_id=order_id)}" style="margin-bottom:10px"><button class="btn green big block">✓ APROBAR PAGO → EN PREPARACIÓN</button></form>
        <form method="post" action="{url_for('order_reject_transfer',order_id=order_id)}"><div class="field"><label>Motivo de rechazo</label><select name="reason"><option>TRANSFERENCIA FRAUDULENTA</option><option>COMPROBANTE TRUCHO / ALTERADO</option><option>DATOS O IMPORTE NO COINCIDEN</option><option>TRANSFERENCIA NO RECIBIDA</option><option>OTRO</option></select></div><div class="field"><label>Detalle (obligatorio si elegís Otro)</label><textarea name="detail"></textarea></div><button class="btn red block">✕ RECHAZAR TRANSFERENCIA</button></form>'''
    current_state={'APROBADO':'EN PREPARACIÓN','LISTO':'PREPARADO','EN REPARTO':'ENVIADO'}.get(str(o['status'] or '').upper(),str(o['status'] or '').upper())
    next_state={'EN PROCESO':'EN PREPARACIÓN','EN PREPARACIÓN':'PREPARADO','PREPARADO':'ENVIADO','ENVIADO':'ENTREGADO'}.get(current_state)
    if closed:
        stateform='<div class="notice info">Pedido cerrado. Ya no admite cambios operativos.</div>'
    else:
        advance=''
        if next_state:
            advance=f'''<form method="post" action="{url_for('order_change_status_admin',order_id=order_id)}"><input type="hidden" name="status" value="{h(next_state)}"><button class="btn blue big block">➡ AVANZAR A {h(next_state)}</button></form>'''
        stateform=advance+f'''<hr><form method="post" action="{url_for('order_cancel_admin',order_id=order_id)}"><div class="field"><label>Cancelar pedido · motivo obligatorio</label><textarea name="reason" required></textarea></div><button class="btn orange">🚫 CANCELAR PEDIDO</button></form>'''
    refund=''
    if o['refund_status']=='PENDIENTE_REINTEGRO':
        refund=f'''<div class="notice error"><b>REINTEGRO PENDIENTE</b><br>La transferencia fue aprobada antes de cancelar. Realizá la devolución y luego confirmala acá.</div><form method="post" action="{url_for('order_refund_admin',order_id=order_id)}"><div class="field"><label>Referencia / observación</label><input name="note"></div><button class="btn purple">💸 MARCAR COMO REINTEGRADO</button></form>'''
    elif o['refund_status']=='REINTEGRADO':refund='<div class="notice"><b>REINTEGRO CONFIRMADO</b></div>'
    cash=''
    if o['payment_method']=='EFECTIVO':cash=f"<p>Paga con: <b>{money(o['cash_tendered'])}</b><br>Vuelto: <b>{money(o['change_due'])}</b></p>"
    zone=f"{h(o['zone_status'] or 'A VERIFICAR')}"+(f" · {float(o['delivery_distance_km']):.2f} km" if o['delivery_distance_km'] is not None else '')
    reasons=''
    if o['payment_rejection_reason']:reasons+=f"<div class='notice error'><b>Motivo de rechazo:</b> {h(o['payment_rejection_reason'])}</div>"
    if o['cancellation_reason']:reasons+=f"<div class='notice error'><b>Motivo de cancelación:</b> {h(o['cancellation_reason'])}</div>"
    breakdown=f'''<div class="paybox"><div class="fee-line"><span>Productos</span><b>{money(o['merchandise_subtotal'] or sum(float(x['line_total'] or 0) for x in items))}</b></div>{('<div class="fee-line"><span>Canje '+h(o['loyalty_reward_name'] or '')+'</span><b>- '+money(o['loyalty_discount'])+' · '+str(int(o['loyalty_points_redeemed'] or 0))+' pts</b></div>') if float(o['loyalty_discount'] or 0)>0 else ''}<div class="fee-line"><span>{'Envío' if o['order_type']=='DELIVERY' else 'Retiro en local'}</span><b>{money(o['delivery_fee'] or 0)}</b></div><div class="fee-line total"><span>TOTAL</span><b>{money(o['total'])}</b></div></div>'''
    return page(f'Pedido #{order_id}',f'''<div class="hero"><h1>Pedido #{order_id}</h1><p>{h(str(o['created_at']).replace('T',' '))} · {h(o['source'] or 'MANUAL')} · {h(o['order_type'])}</p></div>
    <div class="grid"><div class="card kpi"><small>ESTADO</small><strong style="font-size:18px">{h(o['status'])}</strong></div><div class="card kpi"><small>PAGO</small><strong style="font-size:18px">{h((o['payment_status'] or o['payment_method'] or '').replace('_',' '))}</strong></div><div class="card kpi"><small>TOTAL</small><strong>{money(o['total'])}</strong></div><div class="card kpi"><small>ZONA</small><strong style="font-size:16px">{zone}</strong></div></div>{reasons}
    <div class="two" style="margin-top:14px"><div class="card"><h3>Cliente / entrega</h3><p><b>{h(o['customer_name'])}</b><br>DNI {h(o['customer_dni'])}<br>Tarjeta {h(o['card'])}<br>Tel. {h(o['phone'])}</p><p><b>Dirección:</b><br>{h(o['address'])}</p>{cash}{breakdown}</div><div class="card"><h3>Pago / operación</h3>{proof}<div style="height:12px"></div>{actions}<hr>{stateform}{refund}</div></div>
    <div class="card scroll" style="margin-top:14px"><h3>Productos y gustos</h3><table><tr><th>Cant.</th><th>Producto</th><th>Gustos</th><th class="num">Unit.</th><th class="num">Total</th></tr>{ir}</table></div>
    <div class="card scroll" style="margin-top:14px"><h3>Historial del pedido</h3><table><tr><th>Fecha/hora</th><th>Estado</th><th>Pago</th><th>Actor</th><th>Detalle</th></tr>{ev}</table></div>
    <div class="card scroll" style="margin-top:14px"><h3>Reclamos del cliente</h3><table><tr><th>#</th><th>Estado</th><th>Gustos pedidos</th><th>Gusto recibido</th><th>Detalle</th><th>Gestión</th></tr>{cl}</table></div>''')


@app.route('/pedidos/<int:order_id>/comprobante')
@auth_required
def order_payment_proof(order_id):
    with db() as conn:o=conn.execute("SELECT payment_proof_path FROM orders WHERE id=?",(order_id,)).fetchone()
    if not o or not o['payment_proof_path']:return Response('Sin comprobante',404)
    path=(_proof_dir()/Path(o['payment_proof_path']).name).resolve()
    if not path.exists() or path.parent!=_proof_dir().resolve():return Response('Archivo inexistente',404)
    return send_file(path,as_attachment=False)


@app.route('/pedidos/<int:order_id>/aprobar-transferencia',methods=['POST'])
@auth_required
def order_approve_transfer(order_id):
    try:
        approve_transfer(order_id,'WEB ADMIN')
        _safe_print_order(order_id,'web_order_auto_print_approved','IMPRESION_PEDIDO_APROBADO')
        return redirect(url_for('order_detail_admin',order_id=order_id,ok='pago-aprobado'))
    except Exception as exc:
        return page('Error al aprobar pago',f'<div class="hero"><h1>No se pudo aprobar el pago</h1></div><div class="card"><div class="notice error">{h(exc)}</div><a class="btn blue" href="{url_for("order_detail_admin",order_id=order_id)}">VOLVER AL PEDIDO</a></div>'),400


@app.route('/pedidos/<int:order_id>/rechazar-transferencia',methods=['POST'])
@auth_required
def order_reject_transfer(order_id):
    reason=request.form.get('reason','').strip();detail=request.form.get('detail','').strip()
    if reason=='OTRO':reason=detail
    elif detail:reason=f'{reason} · {detail}'
    try:
        reject_transfer(order_id,reason,'WEB ADMIN')
        return redirect(url_for('order_detail_admin',order_id=order_id))
    except Exception as exc:
        return page('Error al rechazar',f'<div class="card"><div class="notice error">{h(exc)}</div><a class="btn blue" href="{url_for("order_detail_admin",order_id=order_id)}">VOLVER</a></div>'),400


@app.route('/pedidos/<int:order_id>/estado',methods=['POST'])
@auth_required
def order_change_status_admin(order_id):
    status=request.form.get('status','').strip().upper()
    try:
        with db() as conn:o=conn.execute('SELECT status,payment_method,payment_status FROM orders WHERE id=?',(order_id,)).fetchone()
        if not o:return Response('Pedido inexistente',404)
        current=str(o['status'] or '').upper()
        if current=='EN PROCESO' and str(o['payment_method'] or '').upper()=='TRANSFERENCIA' and str(o['payment_status'] or '').upper()!='PAGO_APROBADO':
            raise ValueError('Primero aprobá la transferencia.')
        if status==current:return redirect(url_for('order_detail_admin',order_id=order_id))
        transition_order(order_id,status,'WEB ADMIN')
        return redirect(url_for('order_detail_admin',order_id=order_id))
    except Exception as exc:
        return page('Estado de pedido',f'<div class="card"><div class="notice error">{h(exc)}</div><a class="btn blue" href="{url_for("order_detail_admin",order_id=order_id)}">VOLVER</a></div>'),400


@app.route('/pedidos/<int:order_id>/cancelar',methods=['POST'])
@auth_required
def order_cancel_admin(order_id):
    try:
        cancel_order(order_id,request.form.get('reason',''),'WEB ADMIN')
        return redirect(url_for('order_detail_admin',order_id=order_id))
    except Exception as exc:
        return page('Cancelar pedido',f'<div class="card"><div class="notice error">{h(exc)}</div><a class="btn blue" href="{url_for("order_detail_admin",order_id=order_id)}">VOLVER</a></div>'),400


@app.route('/pedidos/<int:order_id>/reintegro',methods=['POST'])
@auth_required
def order_refund_admin(order_id):
    try:
        mark_refunded(order_id,request.form.get('note',''),'WEB ADMIN')
        return redirect(url_for('order_detail_admin',order_id=order_id))
    except Exception as exc:
        return page('Reintegro',f'<div class="card"><div class="notice error">{h(exc)}</div><a class="btn blue" href="{url_for("order_detail_admin",order_id=order_id)}">VOLVER</a></div>'),400


@app.route('/pedidos/<int:order_id>/reclamo/<int:claim_id>/estado',methods=['POST'])
@auth_required
def order_claim_status_admin(order_id,claim_id):
    status=request.form.get('status','').strip().upper()
    if status not in ('PENDIENTE','EN REVISION','RESUELTO','RECHAZADO'):
        return Response('Estado inválido',400)
    now=datetime.now().isoformat(timespec='seconds')
    with db() as conn:
        row=conn.execute('SELECT id FROM order_claims WHERE id=? AND order_id=?',(claim_id,order_id)).fetchone()
        if not row:return Response('Reclamo inexistente',404)
        conn.execute('UPDATE order_claims SET status=?,updated_at=? WHERE id=?',(status,now,claim_id))
        conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",(now,'WEB ADMIN','RECLAMO_PEDIDO',f'Reclamo #{claim_id} pedido #{order_id} → {status}'))
    return redirect(url_for('order_detail_admin',order_id=order_id))


@app.route('/caja')
@auth_required
def cash():
    with db() as conn:
        sess=conn.execute("SELECT cs.*,COALESCE(u.name,'') user_name FROM cash_sessions cs LEFT JOIN users u ON u.id=cs.user_id ORDER BY cs.id DESC LIMIT 1").fetchone(); rows=conn.execute("SELECT cm.*,COALESCE(u.name,'') user_name FROM cash_movements cm LEFT JOIN users u ON u.id=cm.user_id WHERE date(cm.created_at)=date('now','localtime') ORDER BY cm.id DESC").fetchall(); totals=conn.execute("SELECT payment_method,COUNT(*) c,SUM(total) total FROM sales WHERE date(created_at)=date('now','localtime') AND status='CONFIRMADA' GROUP BY payment_method").fetchall()
    state='SIN SESIÓN' if not sess else sess['status']; cls='good' if state=='ABIERTA' else 'bad'; cards=''.join(f"<div class='card kpi'><small>{h(r['payment_method'])}</small><strong>{money(r['total'])}</strong><div class='sub'>{r['c']} tickets</div></div>" for r in totals); trs=''.join(f"<tr><td class='mono'>{h(str(r['created_at']).replace('T',' '))}</td><td>{h(r['movement_type'])}</td><td>{h(r['concept'])}</td><td>{h(r['user_name'])}</td><td>{h(r['payment_method'])}</td><td class='num'>{money(r['amount'])}</td></tr>" for r in rows)
    return page('Caja',f'''<div class="hero"><h1>Caja</h1><p>Estado y movimientos del día.</p></div><div class="two"><div class="card"><h3>Estado actual</h3><p><span class="status {cls}">{h(state)}</span></p><p>Operador: <b>{h(sess['user_name']) if sess else '-'}</b><br>Apertura: {h(str(sess['opened_at']).replace('T',' ')) if sess else '-'}</p></div><div class="grid">{cards}</div></div><div class="card scroll" style="margin-top:14px"><table><tr><th>Fecha/hora</th><th>Tipo</th><th>Concepto</th><th>Usuario</th><th>Medio</th><th class="num">Monto</th></tr>{trs}</table></div>''')


@app.route('/chat')
@auth_required
def chat():
    with db() as conn:conn.execute("UPDATE internal_messages SET read_at=? WHERE sender_type='SISTEMA' AND read_at IS NULL",(datetime.now().isoformat(timespec='seconds'),))
    return page('Chat',f'''<div class="hero"><h1>💬 Chat interno</h1><p>Comunicación entre administración Web y la caja.</p></div><div class="card"><div id="messages" class="chatbox"></div><form id="chatForm" class="quick" style="margin-top:10px"><input id="chatText" class="search" maxlength="1000" placeholder="Mensaje para el operador de caja…" autocomplete="off"><button class="btn blue big">ENVIAR</button></form></div><script>
    let last=0;function esc(s){{return String(s??'').replace(/[&<>\"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}}[c]))}}
    async function load(){{let r=await fetch('/api/chat?after=0');let d=await r.json();let box=document.getElementById('messages');box.innerHTML=d.messages.map(m=>`<div class="msg ${{m.sender_type==='WEB'?'web':''}}"><small>${{esc(m.sender)}} · ${{esc(m.created_at.replace('T',' '))}}</small>${{esc(m.message)}}</div>`).join('');box.scrollTop=box.scrollHeight;}}
    document.getElementById('chatForm').onsubmit=async(e)=>{{e.preventDefault();let t=document.getElementById('chatText');if(!t.value.trim())return;await fetch('/api/chat/send',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{message:t.value}})}});t.value='';load();}};load();setInterval(load,3000);
    </script>''')


@app.route('/api/chat')
@auth_required
def api_chat():
    with db() as conn: rows=conn.execute("SELECT * FROM internal_messages ORDER BY id DESC LIMIT 150").fetchall()[::-1]
    return jsonify(messages=[dict(r) for r in rows])


@app.route('/api/chat/send',methods=['POST'])
@auth_required
def api_chat_send():
    text=(request.get_json(silent=True) or {}).get('message','').strip()
    if text:
        with db() as conn:conn.execute("INSERT INTO internal_messages(created_at,sender,sender_type,message) VALUES (?,?,?,?)",(datetime.now().isoformat(timespec='seconds'),'ADMINISTRACIÓN WEB','WEB',text[:1000]))
    return jsonify(ok=True)


@app.route('/delivery-config',methods=['GET','POST'])
@auth_required
def delivery_config():
    notice=''
    if request.method=='POST':
        keys=['transfer_alias','transfer_cbu','transfer_holder','transfer_tax_id','transfer_entity','google_maps_api_key','delivery_center_address','delivery_radius_km','delivery_fee','web_order_auto_print_pending','web_order_auto_print_approved','web_order_sound_enabled','web_order_central_auto_print','mercadopago_enabled','mercadopago_public_key','mercadopago_external_pos_id','mercadopago_qr_mode']
        for key in keys:
            if key in ('web_order_auto_print_pending','web_order_auto_print_approved','web_order_sound_enabled','web_order_central_auto_print','mercadopago_enabled'):
                set_setting(key,'1' if request.form.get(key) else '0')
            else:
                set_setting(key,request.form.get(key,'').strip())
        # V22: retiro en local no tiene cargo.
        set_setting('pickup_fee','0.00')
        token=(request.form.get('mercadopago_access_token') or '').strip()
        if token:
            set_setting('mercadopago_access_token',token)
        notice='<div class="notice">✓ Configuración guardada.</div>'
    def v(k,d=''):return h(get_setting(k,d))
    mp=mp_configuration_status()
    if mp.get('online_ready'):
        mp_status='ONLINE HABILITADO'
        mp_cls='good'
    elif mp.get('has_token'):
        mp_status='ACCESS TOKEN GUARDADO'
        mp_cls='good'
    else:
        mp_status='FALTA CONFIGURAR'
        mp_cls='warn'
    qr_status='QR PRESENCIAL LISTO' if mp.get('qr_ready') else ('FALTA EXTERNAL POS ID' if mp.get('has_token') else 'FALTA CONFIGURAR')
    qr_cls='good' if mp.get('qr_ready') else 'warn'
    return page('Delivery / Pagos',f'''<div class="hero"><h1>🚚 Delivery / Pagos Web</h1><p>Transferencia, Mercado Pago QR, zona de reparto y avisos del sistema central.</p></div>{notice}
    <form method="post"><div class="two"><div class="card"><h3>Transferencia</h3><div class="field"><label>Alias</label><input name="transfer_alias" value="{v('transfer_alias')}"></div><div class="field"><label>CBU/CVU (opcional)</label><input name="transfer_cbu" value="{v('transfer_cbu')}"></div><div class="field"><label>Titular</label><input name="transfer_holder" value="{v('transfer_holder')}"></div><div class="field"><label>CUIL/CUIT</label><input name="transfer_tax_id" value="{v('transfer_tax_id')}"></div><div class="field"><label>Entidad</label><input name="transfer_entity" value="{v('transfer_entity')}"></div></div>
    <div class="card"><h3>Google Maps / zona</h3><div class="field"><label>Dirección del local / centro de reparto</label><input name="delivery_center_address" value="{v('delivery_center_address',get_setting('store_address',''))}"></div><div class="field"><label>Radio máximo (km)</label><input name="delivery_radius_km" type="number" min="0.1" step="0.1" value="{v('delivery_radius_km','5')}"></div><div class="field"><label>Costo de envío delivery</label><input name="delivery_fee" type="number" min="0" step="100" value="{v('delivery_fee','2500')}"></div><div class="notice info"><b>Retiro en local: SIN CARGO · $ 0,00</b><br>No se agrega ningún importe técnico ni de prueba.</div><div class="field"><label>Google Maps API Key</label><input name="google_maps_api_key" type="password" value="{v('google_maps_api_key')}"></div></div></div>
    <div class="two" style="margin-top:14px"><div class="card"><h3>💙 Mercado Pago Online · PRODUCCIÓN / PAGOS REALES</h3><p><span class="status {mp_cls}">{mp_status}</span></p><label><input type="checkbox" name="mercadopago_enabled" {'checked' if get_setting('mercadopago_enabled','0')=='1' else ''}> Habilitar Mercado Pago en pedidos Web</label><div class="field"><label>Access Token PRODUCTIVO</label><input name="mercadopago_access_token" type="password" value="" placeholder="{'✓ Access Token guardado · dejá vacío para conservarlo' if mp['has_token'] else 'APP_USR-...'}"></div><div class="field"><label>Public Key PRODUCTIVA (opcional para este redirect)</label><input name="mercadopago_public_key" value="{v('mercadopago_public_key')}" placeholder="Opcional para el redirect actual"></div><p class="muted"><b>Producción:</b> cargá el Access Token de <b>Producción → Credenciales de producción</b> de la aplicación Heladería Los Nietos. El sistema crea la order por el importe exacto y redirige al checkout oficial de Mercado Pago. Las credenciales de prueba no sirven para cobrar a una cuenta real.</p><p class="muted">Estado credencial privada: <b>{'GUARDADA ✓' if mp.get('has_token') else 'NO CARGADA'}</b><br>Para pasar de prueba a real, pegá aquí el <b>Access Token PRODUCTIVO</b> y guardá: reemplaza la credencial anterior.</p></div>
    <div class="card"><h3>📱 Mercado Pago QR presencial</h3><p><span class="status {qr_cls}">{qr_status}</span></p><div class="field"><label>External POS ID (caja)</label><input name="mercadopago_external_pos_id" value="{v('mercadopago_external_pos_id')}" placeholder="Se completa cuando creemos la caja QR"></div><div class="field"><label>Modo QR</label><select name="mercadopago_qr_mode"><option value="dynamic" {'selected' if v('mercadopago_qr_mode','dynamic')=='dynamic' else ''}>Dinámico · recomendado</option><option value="hybrid" {'selected' if v('mercadopago_qr_mode','dynamic')=='hybrid' else ''}>Híbrido</option></select></div><p class="muted">Esta sección es independiente del cobro online. El External POS ID se completa recién después de crear la sucursal/caja QR en Mercado Pago; mientras esté vacío, solo queda pendiente el QR presencial.</p></div>
    <div class="card"><h3>🔔 Pedidos Web en sistema central</h3><label><input type="checkbox" name="web_order_sound_enabled" {'checked' if get_setting('web_order_sound_enabled','1')=='1' else ''}> Sonido al entrar un pedido Web</label><br><label><input type="checkbox" name="web_order_central_auto_print" {'checked' if get_setting('web_order_central_auto_print','1')=='1' else ''}> Imprimir desde el sistema central si todavía no se imprimió</label><br><label><input type="checkbox" name="web_order_auto_print_pending" {'checked' if get_setting('web_order_auto_print_pending','1')=='1' else ''}> Permitir impresión automática desde el servidor Web</label><br><label><input type="checkbox" name="web_order_auto_print_approved" {'checked' if get_setting('web_order_auto_print_approved','1')=='1' else ''}> Imprimir también al aprobar pago</label><p class="muted">Con impresión central activa, la comanda inicial queda a cargo del sistema de caja: suena, muestra aviso y la imprime una sola vez. La impresión Web queda como alternativa.</p></div></div>
    <div class="card" style="margin-top:14px"><button class="btn green big">💾 GUARDAR CONFIGURACIÓN</button></div></form>''')


@app.route('/portal/qr')
@auth_required
def portal_qr():
    url=portal_registration_url()
    return page('QR Clientes',f'''<div class="hero"><h1>QR · Alta al programa de fidelidad</h1><p>El cliente lo escanea con su iPhone/Android y completa sus datos.</p></div><div class="two"><div class="card" style="text-align:center"><img src="{url_for('portal_qr_png')}" style="width:min(340px,90%);border-radius:14px"><p class="muted">Dejá esta pantalla visible en el mostrador o imprimí el QR.</p><button class="btn purple big" onclick="window.print()">🖨 IMPRIMIR QR</button></div><div class="card"><h3>Dirección del portal</h3><p class="mono" style="word-break:break-all">{h(url)}</p><p>Para usar este QR, el teléfono tiene que poder acceder al servidor Web. En red local, debe estar conectado al mismo Wi‑Fi.</p><a class="btn green" href="{url_for('client_portal')}" target="_blank">ABRIR PORTAL CLIENTE</a></div></div>''')


@app.route('/portal/qr.png')
@auth_required
def portal_qr_png():
    try:
        import qrcode
    except ImportError:
        return Response('Falta qrcode. Ejecutá instalar_dependencias.bat',status=500,mimetype='text/plain')
    img=qrcode.make(portal_registration_url()); out=io.BytesIO(); img.save(out,format='PNG'); return Response(out.getvalue(),mimetype='image/png')


@app.route('/club')
def client_portal():
    cid=session.get('client_customer_id')
    with db() as conn:
        products=conn.execute("SELECT p.*,COALESCE(c.name,'OTROS') category_name FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE p.active=1 AND p.show_in_sales=1 ORDER BY p.sort_order,p.name LIMIT 100").fetchall()
        offers=conn.execute("SELECT * FROM offers WHERE active=1 ORDER BY priority DESC,id DESC LIMIT 12").fetchall()
        customer=None
        if cid:
            ensure_customer_card(int(cid),conn)
            customer=conn.execute("SELECT * FROM customers WHERE id=?",(int(cid),)).fetchone()
    cards=''.join(f"<div class='product'><span class='muted'>{h(r['category_name'])}</span><strong>{h(r['name'])}</strong><div class='price'>{money(r['price'])}</div>{('<div class=\"muted\">Hasta '+str(r['max_flavors'])+' gustos</div>') if r['max_flavors'] else ''}</div>" for r in products)
    off=''.join(f"<div class='card'><strong>🔥 {h(r['name'])}</strong><div class='muted'>{h(r['notes'])}</div></div>" for r in offers)
    if customer:
        intro=(f'''{_loyalty_card_html(customer)}<div class="card"><div class="orderline"><div><b>⭐ Tus puntos</b><div class="muted">Disponibles para compras y canjes online</div></div><div class="points" style="font-size:34px">{int(customer['points'] or 0)}</div></div><div class="quick"><a class="btn green" href="{url_for('client_order_catalog')}">🛒 HACER PEDIDO</a><a class="btn" href="{url_for('client_account')}">VER PUNTOS Y BENEFICIOS</a></div></div>''')
    else:
        intro=f'''<div class="card"><h2>Club de Fidelidad</h2><p>Registrate para sumar puntos y consultar tus movimientos. Después podés ingresar con <b>correo o DNI + contraseña</b>.</p><a class="btn green" href="{url_for('client_register')}">⭐ REGISTRARME</a><div style="height:8px"></div><a class="btn" href="{url_for('client_login')}">INGRESAR A MI CUENTA</a></div>'''
    return portal_page('Inicio',intro+off+'<h2>Productos</h2><div class="product-grid">'+cards+'</div>')


def _normalize_phone(value):
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


@app.route('/club/registro',methods=['GET','POST'])
def client_register():
    notice=''
    values={k:request.form.get(k,'').strip() for k in ['dni','name','phone','email','birth_date','address']}
    if request.method=='POST':
        dni=normalize_dni(values['dni']); name=values['name']; phone=values['phone']; email=values['email'].lower(); birth=_birth_to_iso(values['birth_date'],required=True); address=values['address']
        password=request.form.get('password',''); confirm=request.form.get('confirm_password','')
        if not dni or not name or not phone or not email or not values['birth_date'] or not password:
            notice='<div class="notice error">DNI, nombre, teléfono, correo, fecha de nacimiento y contraseña son obligatorios.</div>'
        elif birth is None:
            notice='<div class="notice error">Fecha de nacimiento inválida. Usá DD/MM/AAAA.</div>'
        elif '@' not in email or '.' not in email.split('@')[-1]:
            notice='<div class="notice error">Ingresá un correo electrónico válido.</div>'
        elif len(password) < 6:
            notice='<div class="notice error">La contraseña debe tener al menos 6 caracteres.</div>'
        elif password != confirm:
            notice='<div class="notice error">Las contraseñas no coinciden.</div>'
        else:
            try:
                now=datetime.now().isoformat(timespec='seconds')
                with db() as conn:
                    email_used=conn.execute("SELECT 1 FROM portal_accounts WHERE lower(email)=lower(?) LIMIT 1",(email,)).fetchone()
                    if email_used:
                        raise ValueError('Ese correo ya está registrado. Iniciá sesión o usá otro correo.')
                    c=conn.execute("SELECT * FROM customers WHERE dni=? LIMIT 1",(dni,)).fetchone()
                    if c:
                        account=conn.execute("SELECT 1 FROM portal_accounts WHERE customer_id=? LIMIT 1",(c['id'],)).fetchone()
                        if account:
                            raise ValueError('Ese DNI ya tiene una cuenta del portal. No se puede duplicar. Iniciá sesión.')
                        saved_phone=_normalize_phone(c['phone'])
                        if saved_phone and saved_phone != _normalize_phone(phone):
                            raise ValueError('El DNI ya existe y el teléfono no coincide con el registrado. Pedí que actualicen tus datos en la heladería.')
                        conn.execute('''UPDATE customers SET name=?,phone=?,address=CASE WHEN ?<>'' THEN ? ELSE address END,birth_date=CASE WHEN ?<>'' THEN ? ELSE birth_date END WHERE id=?''',(name,phone,address,address,birth,birth,c['id']))
                        cid=c['id']
                    else:
                        cur=conn.execute('''INSERT INTO customers(dni,name,phone,address,birth_date,points,active,loyalty_joined_at) VALUES (?,?,?,?,?,0,1,?)''',(dni,name,phone,address,birth,now))
                        cid=cur.lastrowid
                    ensure_customer_card(cid,conn)
                    conn.execute('''INSERT INTO portal_accounts(customer_id,email,password_hash,created_at,updated_at,active) VALUES (?,?,?,?,?,1)''',(cid,email,generate_password_hash(password),now,now))
                    conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",(now,'PORTAL CLIENTE','ALTA_PORTAL',f'DNI {dni} · {email}'))
                session['client_customer_id']=cid
                session.permanent=True
                return redirect(url_for('client_account'))
            except (ValueError,sqlite3.IntegrityError) as e:
                msg=str(e) if str(e) else 'El DNI o correo ya está registrado.'
                notice=f'<div class="notice error">{h(msg)}</div>'
    v=lambda k:h(values.get(k,''))
    return portal_page('Registro',f'''<div class="card"><h2>⭐ Crear mi cuenta</h2><p class="muted">El DNI es único y no puede registrarse dos veces. Tu tarjeta será un número aleatorio único de 8 dígitos.</p>{notice}<form method="post"><div class="field"><label>DNI *</label><input name="dni" inputmode="numeric" required value="{v('dni')}"></div><div class="field"><label>Nombre y apellido *</label><input name="name" required value="{v('name')}"></div><div class="field"><label>Teléfono *</label><input name="phone" inputmode="tel" required value="{v('phone')}"></div><div class="field"><label>Correo electrónico *</label><input name="email" type="email" autocomplete="email" required value="{v('email')}"></div><div class="field"><label>Contraseña *</label><input name="password" type="password" minlength="6" autocomplete="new-password" required></div><div class="field"><label>Repetir contraseña *</label><input name="confirm_password" type="password" minlength="6" autocomplete="new-password" required></div><div class="field"><label>Fecha de nacimiento * · DD/MM/AAAA</label><input name="birth_date" inputmode="numeric" placeholder="31/12/1990" pattern="[0-3][0-9]/[0-1][0-9]/[0-9]{{4}}" required value="{v('birth_date')}"></div><div class="field"><label>Dirección</label><input name="address" value="{v('address')}"></div><button class="btn green">CREAR CUENTA Y TARJETA</button></form></div><div class="card"><b>¿Ya estás registrado?</b><div style="height:8px"></div><a class="btn" href="{url_for('client_login')}">INGRESAR CON CORREO O DNI</a></div>''')


@app.route('/club/login',methods=['GET','POST'])
def client_login():
    error=''
    identifier=request.form.get('identifier','').strip()
    if request.method=='POST':
        password=request.form.get('password','')
        with db() as conn:
            if '@' in identifier:
                row=conn.execute('''SELECT pa.*,c.dni,c.name FROM portal_accounts pa JOIN customers c ON c.id=pa.customer_id WHERE lower(pa.email)=lower(?) AND pa.active=1 AND c.active=1 LIMIT 1''',(identifier,)).fetchone()
            else:
                dni=normalize_dni(identifier)
                row=conn.execute('''SELECT pa.*,c.dni,c.name FROM portal_accounts pa JOIN customers c ON c.id=pa.customer_id WHERE c.dni=? AND pa.active=1 AND c.active=1 LIMIT 1''',(dni,)).fetchone() if dni else None
            if row and check_password_hash(row['password_hash'],password):
                session['client_customer_id']=row['customer_id'];session.permanent=True
                now=datetime.now().isoformat(timespec='seconds')
                conn.execute("UPDATE portal_accounts SET last_login_at=?,updated_at=? WHERE id=?",(now,now,row['id']))
                return redirect(request.args.get('next') or url_for('client_account'))
        error='<div class="notice error">Correo/DNI o contraseña incorrectos.</div>'
    return portal_page('Ingresar',f'''<div class="card"><h2>Ingresar a mi cuenta</h2><p class="muted">Podés usar tu <b>correo electrónico</b> o tu <b>DNI</b>.</p>{error}<form method="post"><div class="field"><label>Correo electrónico o DNI</label><input name="identifier" autocomplete="username" required value="{h(identifier)}"></div><div class="field"><label>Contraseña</label><input name="password" type="password" autocomplete="current-password" required></div><button class="btn green">INGRESAR</button></form><div style="height:10px"></div><a class="btn" href="{url_for('client_forgot_password')}">¿OLVIDASTE TU CONTRASEÑA?</a></div><div class="card"><span class="muted">¿Todavía no tenés cuenta?</span><div style="height:8px"></div><a class="btn" href="{url_for('client_register')}">REGISTRARME</a></div>''')


@app.route('/club/olvide-clave',methods=['GET','POST'])
def client_forgot_password():
    notice=''
    dni_value=request.form.get('dni','').strip()
    birth_value=request.form.get('birth_date','').strip()
    last4_value=''.join(ch for ch in request.form.get('card_last4','') if ch.isdigit())[-4:]
    if request.method=='POST':
        dni=normalize_dni(dni_value)
        birth_iso=_birth_to_iso(birth_value,required=True)
        if not dni or not birth_value or len(last4_value)!=4:
            notice='<div class="notice error">Completá DNI, fecha de nacimiento y los últimos 4 dígitos de tu tarjeta.</div>'
        else:
            with db() as conn:
                row=conn.execute('''SELECT c.id,c.dni,c.birth_date,c.loyalty_card_number,c.active,pa.id account_id,pa.active account_active FROM customers c JOIN portal_accounts pa ON pa.customer_id=c.id WHERE c.dni=? LIMIT 1''',(dni,)).fetchone()
            valid=bool(row and birth_iso and row['active'] and row['account_active'] and str(row['birth_date'] or '')==birth_iso and str(row['loyalty_card_number'] or '')[-4:]==last4_value)
            now=datetime.now().isoformat(timespec='seconds')
            if valid:
                session['client_reset_customer_id']=int(row['id'])
                session['client_reset_verified_at']=now
                session.pop('client_reset_failures',None)
                with db() as conn:
                    conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",(now,'PORTAL CLIENTE','VALIDACION_RESET_CLAVE',f'DNI {dni} · validación correcta'))
                return redirect(url_for('client_new_password'))
            failures=int(session.get('client_reset_failures',0))+1
            session['client_reset_failures']=failures
            with db() as conn:
                conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",(now,'PORTAL CLIENTE','RESET_CLAVE_FALLIDO',f'DNI {dni or "SIN_DNI"} · intento {failures}'))
            notice='<div class="notice error">No pudimos validar los datos. Revisá el DNI, la fecha de nacimiento y la terminación de tu tarjeta. Si no los recordás, pedí el reseteo en la heladería.</div>'
    return portal_page('Recuperar contraseña',f'''<div class="card"><h2>🔐 ¿Olvidaste tu contraseña?</h2><p class="muted">Para proteger tu cuenta necesitamos validar tres datos.</p>{notice}<form method="post"><div class="field"><label>DNI</label><input name="dni" inputmode="numeric" autocomplete="off" required value="{h(dni_value)}"></div><div class="field"><label>Fecha de nacimiento · DD/MM/AAAA</label><input name="birth_date" inputmode="numeric" placeholder="31/12/1990" pattern="[0-3][0-9]/[0-1][0-9]/[0-9]{{4}}" required value="{h(birth_value)}"></div><div class="field"><label>Últimos 4 dígitos de la tarjeta de fidelidad</label><input name="card_last4" inputmode="numeric" pattern="[0-9]{{4}}" maxlength="4" required value="{h(last4_value)}" placeholder="Ej.: 2915"></div><button class="btn green">VALIDAR MIS DATOS</button></form></div><div class="card"><a class="btn" href="{url_for('client_login')}">VOLVER A INICIAR SESIÓN</a><p class="muted" style="margin-bottom:0">Si no recordás la terminación de tu tarjeta o tus datos no coinciden, solicitá el reseteo en la heladería.</p></div>''')


@app.route('/club/nueva-clave',methods=['GET','POST'])
def client_new_password():
    cid=session.get('client_reset_customer_id')
    verified_at=session.get('client_reset_verified_at')
    if not cid or not verified_at:
        return redirect(url_for('client_forgot_password'))
    try:
        verified=datetime.fromisoformat(verified_at)
    except Exception:
        session.pop('client_reset_customer_id',None);session.pop('client_reset_verified_at',None)
        return redirect(url_for('client_forgot_password'))
    if datetime.now()-verified > timedelta(minutes=10):
        session.pop('client_reset_customer_id',None);session.pop('client_reset_verified_at',None)
        return portal_page('Recuperar contraseña','<div class="card"><div class="notice error">La validación venció. Volvé a verificar tus datos.</div><a class="btn" href="'+url_for('client_forgot_password')+'">VOLVER A VALIDAR</a></div>')
    notice=''
    if request.method=='POST':
        password=request.form.get('password','')
        confirm=request.form.get('confirm_password','')
        if len(password)<6:
            notice='<div class="notice error">La contraseña debe tener al menos 6 caracteres.</div>'
        elif password!=confirm:
            notice='<div class="notice error">Las contraseñas no coinciden.</div>'
        else:
            now=datetime.now().isoformat(timespec='seconds')
            with db() as conn:
                c=conn.execute("SELECT id,dni,name FROM customers WHERE id=? LIMIT 1",(int(cid),)).fetchone()
                account=conn.execute("SELECT id FROM portal_accounts WHERE customer_id=? AND active=1 LIMIT 1",(int(cid),)).fetchone()
                if not c or not account:
                    session.pop('client_reset_customer_id',None);session.pop('client_reset_verified_at',None)
                    return portal_page('Recuperar contraseña','<div class="card"><div class="notice error">La cuenta ya no está disponible.</div></div>'),400
                conn.execute("UPDATE portal_accounts SET password_hash=?,updated_at=? WHERE id=?",(generate_password_hash(password),now,account['id']))
                conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",(now,'PORTAL CLIENTE','RESET_CLAVE_AUTOGESTION',f"Cliente {c['name']} · DNI {c['dni']}"))
            session.pop('client_reset_customer_id',None);session.pop('client_reset_verified_at',None);session.pop('client_reset_failures',None)
            return portal_page('Contraseña actualizada',f'''<div class="card" style="text-align:center"><h2>✓ Contraseña actualizada</h2><p>Ya podés ingresar con tu correo electrónico o DNI y la nueva contraseña.</p><a class="btn green" href="{url_for('client_login')}">INICIAR SESIÓN</a></div>''')
    return portal_page('Nueva contraseña',f'''<div class="card"><h2>Elegí una nueva contraseña</h2><p class="muted">La validación es válida durante 10 minutos.</p>{notice}<form method="post"><div class="field"><label>Nueva contraseña</label><input name="password" type="password" minlength="6" autocomplete="new-password" required></div><div class="field"><label>Repetir contraseña</label><input name="confirm_password" type="password" minlength="6" autocomplete="new-password" required></div><button class="btn green">GUARDAR NUEVA CONTRASEÑA</button></form></div>''')


@app.route('/club/salir')
def client_logout():
    session.pop('client_customer_id',None)
    return redirect(url_for('client_portal'))


@app.route('/club/tarjeta/barcode.svg')
@client_auth_required
def client_loyalty_barcode():
    cid=int(session['client_customer_id'])
    with db() as conn:
        ensure_customer_card(cid,conn)
        c=conn.execute('SELECT loyalty_card_number FROM customers WHERE id=?',(cid,)).fetchone()
    if not c:
        return Response('',status=404,mimetype='image/svg+xml')
    return Response(_code39_svg(c['loyalty_card_number']),mimetype='image/svg+xml',headers={'Cache-Control':'no-store, max-age=0'})


@app.route('/club/tarjeta/regenerar',methods=['POST'])
@client_auth_required
def client_regenerate_loyalty_card():
    cid=int(session['client_customer_id'])
    try:
        regenerate_customer_card(cid,'EXTRAVÍO / REEMPLAZO DESDE PORTAL',actor='PORTAL CLIENTE')
    except Exception as exc:
        return portal_page('Tarjeta de fidelidad',f'<div class="card"><div class="notice error">{h(exc)}</div><a class="btn" href="{url_for("client_account")}">VOLVER</a></div>'),400
    return redirect(url_for('client_account',card_regenerated=1))


@app.route('/club/cuenta')
@client_auth_required
def client_account():
    cid=int(session['client_customer_id'])
    with db() as conn:
        c=conn.execute('''SELECT c.*,pa.email,pa.last_login_at FROM customers c JOIN portal_accounts pa ON pa.customer_id=c.id WHERE c.id=? AND c.active=1 AND pa.active=1''',(cid,)).fetchone()
        if not c:
            session.pop('client_customer_id',None);return redirect(url_for('client_login'))
        ensure_customer_card(cid,conn)
        c=conn.execute('''SELECT c.*,pa.email,pa.last_login_at FROM customers c JOIN portal_accounts pa ON pa.customer_id=c.id WHERE c.id=?''',(cid,)).fetchone()
        moves=conn.execute("SELECT * FROM loyalty_movements WHERE customer_id=? ORDER BY id DESC LIMIT 50",(cid,)).fetchall()
        rewards=conn.execute('''SELECT r.*,COALESCE(p.name,'') product_name FROM loyalty_rewards r LEFT JOIN products p ON p.id=r.product_id WHERE r.active=1 ORDER BY r.points_cost,r.name''').fetchall()
        products=conn.execute("SELECT name,price FROM products WHERE active=1 AND show_in_sales=1 ORDER BY sort_order,name LIMIT 30").fetchall()
    access=customer_order_access(cid)
    if access.get('allowed'):
        order_state='<div class="notice">✓ Tu cuenta está habilitada para realizar pedidos.</div>'
    else:
        order_state=f'<div class="notice error">⛔ {h(access.get("message"))}</div>'
    mr=''.join(f"<div class='card'><b>{int(r['points']):+d} pts · {h(r['movement_type'])}</b><div class='muted'>{h(str(r['created_at']).replace('T',' '))}<br>{h(r['description'])}<br>Saldo después: {r['balance_after']} pts</div></div>" for r in moves) or '<div class="card muted">Todavía no tenés movimientos.</div>'
    reward_cards=[]
    for r in rewards:
        ready=int(c['points'] or 0)>=int(r['points_cost'] or 0)
        action=(f'<a class="btn green" style="margin-top:10px" href="{url_for("client_reward_start",reward_id=r["id"])}">🎁 CANJEAR ONLINE</a>' if ready and access.get('allowed') else '')
        need='' if ready else f'<div class="muted" style="margin-top:7px">Te faltan {max(0,int(r["points_cost"] or 0)-int(c["points"] or 0))} puntos.</div>'
        cls='card reward-ready' if ready else 'card'
        reward_cards.append(f'<div class="{cls}"><b>{h(r["name"])}</b><div class="muted">{r["points_cost"]} puntos · {h(r["product_name"] or r["reward_type"])}</div>{("<div style=\"margin-top:6px;color:#168a56;font-weight:900\">✓ DISPONIBLE PARA CANJEAR</div>" if ready else "")}{need}{action}</div>')
    rr=''.join(reward_cards) or '<div class="card muted">No hay beneficios configurados.</div>'
    pc=''.join(f"<div class='product'><strong>{h(r['name'])}</strong><div class='price'>{money(r['price'])}</div></div>" for r in products)
    card_notice='<div class="notice">✓ Se generó una nueva tarjeta de fidelidad. La anterior quedó invalidada y tus puntos se conservaron.</div>' if request.args.get('card_regenerated') else ''
    card_manage=f'''<div class="card"><h3>💳 ¿Perdiste o no recordás tu tarjeta?</h3><p class="muted">Podés denunciar/reemplazar tu tarjeta digital. Se genera un nuevo número de 8 dígitos; la tarjeta anterior deja de ser válida y tus puntos e historial se conservan.</p><form method="post" action="{url_for('client_regenerate_loyalty_card')}" onsubmit="return confirm('¿Generar una nueva tarjeta? La tarjeta actual quedará invalidada.');"><button class="btn orange">♻ REGENERAR MI TARJETA</button></form></div>'''
    return portal_page('Mi cuenta',f'''{card_notice}{_loyalty_card_html(c)}<div class="card"><h2>Hola, {h(c['name'])}</h2><div class="muted">DNI {h(c['dni'])} · {h(c['email'])}</div><div class="points">{c['points']}</div><div style="text-align:center;font-weight:900">PUNTOS DISPONIBLES</div></div>{card_manage}{order_state}<h2>Beneficios y canjes</h2>{rr}<h2>Movimientos de puntos</h2>{mr}<h2>Productos</h2><div class="product-grid">{pc}</div>''')


@app.route('/club/canje/<int:reward_id>')
@client_auth_required
def client_reward_start(reward_id):
    cid=int(session['client_customer_id'])
    access=_portal_order_access()
    if not access.get('allowed'):
        return _portal_order_blocked(access)
    with db() as conn:
        reward=_reward_for_customer(conn,cid,reward_id)
    if not reward:
        return portal_page('Canje','<div class="card"><div class="notice error">Este beneficio no está disponible o no tenés puntos suficientes.</div><a class="btn" href="'+url_for('client_account')+'">VOLVER</a></div>'),400
    session['client_pending_reward_id']=int(reward_id)
    if str(reward['reward_type'] or '').upper()=='PRODUCTO_GRATIS' and reward['product_id']:
        return redirect(url_for('client_order_product',product_id=int(reward['product_id']),reward=int(reward_id)))
    details,total=_portal_cart_details()
    if details:
        return redirect(url_for('client_checkout'))
    return redirect(url_for('client_order_catalog'))


def _portal_cart_raw():
    cart=session.get('client_cart') or []
    return cart if isinstance(cart,list) else []


def _portal_cart_details():
    raw=_portal_cart_raw(); details=[]; total=0.0
    if not raw:return details,total
    with db() as conn:
        for cart_index,entry in enumerate(raw):
            try: pid=int(entry.get('product_id'))
            except Exception: continue
            p=conn.execute("SELECT * FROM products WHERE id=? AND active=1 AND show_in_sales=1",(pid,)).fetchone()
            if not p:continue
            selected=[]
            for fid in entry.get('flavor_ids') or []:
                fl=conn.execute("SELECT id,name FROM flavors WHERE id=? AND active=1 AND available=1 AND stock_kg>0",(int(fid),)).fetchone()
                if fl:selected.append(dict(fl))
            final,offer=price_with_offer(dict(p))
            qty=max(1,min(int(entry.get('qty') or 1),20))
            line=float(final)*qty
            details.append({'cart_index':cart_index,'product':dict(p),'flavors':selected,'qty':qty,'unit_price':float(final),'line_total':line,'offer':offer})
            total+=line
    return details,total


def _portal_order_access():
    cid=session.get('client_customer_id')
    if not cid:
        return {'allowed':False,'kind':'SIN_SESION','message':'Iniciá sesión para hacer un pedido.'}
    return customer_order_access(int(cid))


def _portal_order_blocked(access):
    access=access or {}
    msg=h(access.get('message') or 'Tu cuenta no está habilitada para generar pedidos.')
    extra=''
    if access.get('kind')=='BLOQUEO_TEMPORAL' and access.get('until'):
        extra=f'''<div class="card" style="text-align:center"><div class="muted">TIEMPO RESTANTE</div><div id="blockCountdown" style="font-size:34px;font-weight:950;color:#cf304a;margin:8px 0">--:--:--</div><div class="muted">Bloqueo automático por seguridad. Al finalizar el plazo vas a poder volver a pedir.</div></div><script>(function(){{const end=new Date({access.get('until')!r});const el=document.getElementById('blockCountdown');function tick(){{let s=Math.max(0,Math.floor((end-new Date())/1000));let hh=String(Math.floor(s/3600)).padStart(2,'0'),mm=String(Math.floor((s%3600)/60)).padStart(2,'0'),ss=String(s%60).padStart(2,'0');el.textContent=hh+':'+mm+':'+ss;if(s<=0)setTimeout(()=>location.reload(),800);}}tick();setInterval(tick,1000);}})();</script>'''
    return portal_page('Pedidos no habilitados',f'''<div class="statushero bad"><h2 style="margin:0 0 6px">⛔ Pedidos temporalmente no disponibles</h2><p style="margin:0">{msg}</p></div>{extra}<div class="card"><p>Podés seguir consultando tus puntos, movimientos y pedidos anteriores.</p><a class="btn purple" href="{url_for('client_account')}">VER MI CUENTA</a> <a class="btn gray" href="{url_for('client_orders')}">MIS PEDIDOS</a></div>'''),403


@app.route('/club/perfil',methods=['GET','POST'])
@client_auth_required
def client_profile():
    cid=int(session['client_customer_id']); notice=''; result=None
    if request.method=='POST':
        address=request.form.get('address','').strip();phone=request.form.get('phone','').strip();birth_raw=request.form.get('birth_date','').strip()
        birth=_birth_to_iso(birth_raw,required=True)
        if not address:
            notice='<div class="notice error">Ingresá una dirección.</div>'
        elif birth is None:
            notice='<div class="notice error">Fecha de nacimiento inválida. Usá DD/MM/AAAA.</div>'
        else:
            with db() as conn:conn.execute("UPDATE customers SET phone=?,birth_date=? WHERE id=?",(phone,birth,cid))
            result=save_customer_delivery_address(cid,address)
            cls='goodzone' if result['status']=='EN_ZONA' else ('badzone' if result['status'] in ('FUERA_DE_ZONA','NO_ENCONTRADA') else 'warnzone')
            notice=f'<div class="notice {cls}">{h(result["message"])}</div>'
    with db() as conn:c=conn.execute("SELECT * FROM customers WHERE id=?",(cid,)).fetchone()
    address=c['address'] or ''
    embed=google_maps_embed_url(address)
    maphtml=f'<iframe class="mapframe" loading="lazy" src="{h(embed)}"></iframe><p><a class="btn" target="_blank" href="{h(google_maps_link(address))}">ABRIR EN GOOGLE MAPS</a></p>' if address else '<div class="notice">Todavía no cargaste una dirección.</div>'
    status=h((c['address_zone_status'] or 'SIN VALIDAR').replace('_',' '))
    birth_display=h(_birth_display(c['birth_date']))
    return portal_page('Mi perfil',f'''<div class="card"><h2>📍 Mi perfil y dirección</h2><p class="muted">Corroborá tu domicilio antes de pedir delivery.</p>{notice}<form method="post"><div class="field"><label>Teléfono</label><input name="phone" inputmode="tel" value="{h(c['phone'])}"></div><div class="field"><label>Fecha de nacimiento · DD/MM/AAAA</label><input name="birth_date" inputmode="numeric" placeholder="31/12/1990" pattern="[0-3][0-9]/[0-1][0-9]/[0-9]{{4}}" required value="{birth_display}"></div><div class="field"><label>Dirección completa</label><input name="address" required value="{h(address)}" placeholder="Calle 1234, ciudad, provincia"></div><button class="btn green">GUARDAR Y VERIFICAR DIRECCIÓN</button></form><p><b>Estado de zona:</b> {status}</p></div><div class="card"><h3>Mapa</h3>{maphtml}</div>''')

@app.route('/club/pedir')
@client_auth_required
def client_order_catalog():
    access=_portal_order_access()
    if not access.get('allowed'):
        return _portal_order_blocked(access)
    with db() as conn:
        products=conn.execute("SELECT p.*,COALESCE(c.name,'OTROS') category_name FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE p.active=1 AND p.show_in_sales=1 ORDER BY p.sort_order,p.name").fetchall()
        c=conn.execute("SELECT address,address_zone_status FROM customers WHERE id=?",(int(session['client_customer_id']),)).fetchone()
    cards=''.join(f'''<div class="product"><span class="muted">{h(p['category_name'])}</span><strong>{h(p['name'])}</strong><div class="price">{money(p['price'])}</div>{('<div class="muted">🍨 Elegí hasta '+str(p['max_flavors'])+' gustos disponibles</div>') if p['max_flavors'] else '<div class="muted">Listo para agregar</div>'}<div style="height:10px"></div><a class="btn green" href="{url_for('client_order_product',product_id=p['id'])}">＋ AGREGAR</a></div>''' for p in products)
    cart,cart_total=_portal_cart_details(); units=sum(int(x['qty']) for x in cart); badge=f'{units} unidad(es) · {len(cart)} línea(s)'
    addr='📍 Dirección cargada para delivery' if c and c['address'] else '⚠ Falta cargar una dirección para delivery'
    warning='' if c and c['address'] else f'<div class="notice error">Antes de pedir delivery cargá tu dirección en <a href="{url_for("client_profile")}">Mi perfil</a>. También podés elegir Retiro en local.</div>'
    return portal_page('Hacer pedido',f'''<div class="statushero"><h2 style="margin:0 0 5px">🛒 Armá tu pedido</h2><p style="margin:0">Podés agregar todos los productos que quieras. Cada helado conserva sus propios gustos.</p></div>{warning}<div class="card"><div class="orderline"><div><b>{h(addr)}</b><div class="muted">Carrito: {badge}</div></div><div><b>{money(cart_total)}</b></div></div><a class="btn orange" href="{url_for('client_cart')}">🛒 VER CARRITO ({units})</a></div><h2>Productos disponibles</h2><div class="product-grid">{cards}</div>''')


@app.route('/club/pedir/producto/<int:product_id>',methods=['GET','POST'])
@client_auth_required
def client_order_product(product_id):
    access=_portal_order_access()
    if not access.get('allowed'):
        return _portal_order_blocked(access)
    cid=int(session['client_customer_id'])
    reward_id=request.form.get('reward_id') if request.method=='POST' else request.args.get('reward')
    try: reward_id=int(reward_id or 0)
    except Exception: reward_id=0
    with db() as conn:
        p=conn.execute("SELECT * FROM products WHERE id=? AND active=1 AND show_in_sales=1",(product_id,)).fetchone()
        flavors=conn.execute("SELECT * FROM flavors WHERE active=1 AND available=1 AND stock_kg>0 ORDER BY premium,category,name").fetchall()
        reward=_reward_for_customer(conn,cid,reward_id) if reward_id else None
    if not p:return portal_page('Producto','<div class="card">Producto no disponible.</div>'),404
    if reward_id and (not reward or str(reward['reward_type'] or '').upper()!='PRODUCTO_GRATIS' or int(reward['product_id'] or 0)!=int(product_id)):
        return portal_page('Canje','<div class="card"><div class="notice error">Ese beneficio ya no puede aplicarse a este producto.</div><a class="btn" href="'+url_for('client_account')+'">VOLVER</a></div>'),400
    maxf=int(p['max_flavors'] or 0); notice=''
    if request.method=='POST':
        access=_portal_order_access()
        if not access.get('allowed'):
            return _portal_order_blocked(access)
        try:qty=max(1,min(int(request.form.get('qty') or 1),20))
        except Exception:qty=1
        if reward: qty=1
        ids=[]
        for x in request.form.getlist('flavors'):
            if str(x).isdigit():ids.append(int(x))
        if maxf>0 and not ids:
            notice='<div class="notice error">Seleccioná al menos un gusto.</div>'
        elif len(ids)>maxf:
            notice=f'<div class="notice error">Este producto admite hasta {maxf} gustos.</div>'
        else:
            valid={int(f['id']) for f in flavors};ids=[x for x in ids if x in valid][:maxf or None]
            cart=_portal_cart_raw();cart.append({'product_id':product_id,'flavor_ids':ids,'qty':qty});session['client_cart']=cart
            if reward:
                session['client_pending_reward_id']=int(reward['id'])
            return redirect(url_for('client_cart'))
    flhtml=''
    if maxf>0:
        flhtml='<div class="flavors">'+''.join(f'''<label class="flavor"><input class="flavorcheck" type="checkbox" name="flavors" value="{f['id']}" onchange="flavorChanged(this)"> <b>{h(f['name'])}</b><br><span class="muted">{h(('PREMIUM' if f['premium'] else f['category']))}</span></label>''' for f in flavors)+'</div>'
    counter=f'<div id="flavorCounter" class="notice" style="margin-bottom:10px">0 / {maxf} gustos seleccionados</div>' if maxf else ''
    script=f'''<script>const maxFlavors={maxf};function flavorChanged(el){{let checks=[...document.querySelectorAll('.flavorcheck')];let selected=checks.filter(x=>x.checked);if(selected.length>maxFlavors){{el.checked=false;selected=checks.filter(x=>x.checked);}}checks.forEach(x=>{{x.closest('.flavor').style.borderColor=x.checked?'#4f2bd8':'#dce2fa';x.closest('.flavor').style.background=x.checked?'#f0edff':'#fff';}});let c=document.getElementById('flavorCounter');if(c)c.textContent=selected.length+' / '+maxFlavors+' gustos seleccionados';}}</script>'''
    reward_box=(f'<div class="notice"><b>🎁 CANJE ONLINE</b><br>{h(reward["name"])} · se descontarán <b>{int(reward["points_cost"])} puntos</b> al confirmar el pedido.</div>' if reward else '')
    qty_html=('<input type="hidden" name="qty" value="1"><div class="field"><label>Cantidad</label><input value="1" disabled></div>' if reward else '<div class="field"><label>Cantidad</label><input name="qty" type="number" min="1" max="20" value="1"></div>')
    hidden=f'<input type="hidden" name="reward_id" value="{int(reward["id"])}">' if reward else ''
    button='🎁 AGREGAR Y CANJEAR' if reward else '✓ AGREGAR AL CARRITO'
    return portal_page('Elegir producto',f'''<div class="card"><h2>{h(p['name'])}</h2><div class="price">{money(p['price'])}</div>{reward_box}{notice}<form method="post">{hidden}{qty_html}{(counter+'<p><b>Elegí los gustos disponibles</b></p>'+flhtml) if maxf else ''}<div style="height:12px"></div><button class="btn green">{button}</button><div style="height:8px"></div><a class="btn gray" href="{url_for('client_order_catalog')}">VOLVER</a></form></div>{script}''')


@app.route('/club/carrito')
@client_auth_required
def client_cart():
    access=_portal_order_access()
    if not access.get('allowed'):
        return _portal_order_blocked(access)
    cid=int(session['client_customer_id'])
    details,total=_portal_cart_details()
    reward_notice=''
    pending_id=session.get('client_pending_reward_id')
    if pending_id:
        with db() as conn:
            reward=_reward_for_customer(conn,cid,pending_id)
        if reward:
            disc,_=_reward_discount_for_cart(reward,details,total)
            if disc>0:
                reward_notice=f'<div class="notice"><b>🎁 Canje seleccionado:</b> {h(reward["name"])} · {int(reward["points_cost"])} puntos · descuento estimado {money(disc)}. Se confirma al enviar el pedido.</div>'
            else:
                reward_notice=f'<div class="notice error"><b>🎁 {h(reward["name"])}</b> está seleccionado, pero todavía no aplica a los productos del carrito.</div>'
        else:
            session.pop('client_pending_reward_id',None)
    rows=''.join(f'''<div class="card"><div class="orderline"><div><b>{h(x['product']['name'])}</b><div class="muted">Cant. {x['qty']}{(' · Gustos: '+h(', '.join(f['name'] for f in x['flavors']))) if x['flavors'] else ''}</div></div><div style="text-align:right"><b>{money(x['line_total'])}</b><form method="post" action="{url_for('client_cart_remove',cart_index=x['cart_index'])}" style="margin-top:8px"><button class="btn red" type="submit">QUITAR</button></form></div></div></div>''' for x in details) or '<div class="card">Tu carrito está vacío.</div>'
    units=sum(int(x['qty']) for x in details)
    if details:
        buttons=f'''<div class="quick"><a class="btn purple big" href="{url_for('client_order_catalog')}">＋ SEGUIR AGREGANDO</a><a class="btn green big" href="{url_for('client_checkout')}">CONTINUAR AL PAGO · {money(total)}</a></div><div style="height:10px"></div><form method="post" action="{url_for('client_cart_clear')}"><button class="btn gray">VACIAR CARRITO</button></form>'''
    else:
        buttons=f'<a class="btn green" href="{url_for("client_order_catalog")}">ELEGIR PRODUCTOS</a>'
    fee=money(get_setting('delivery_fee','2500'))
    pickup=money(get_setting('pickup_fee','0.00'))
    return portal_page('Carrito',f'<div class="statushero"><h2 style="margin:0">🛒 Mi pedido</h2><p style="margin:5px 0 0">{units} unidad(es) · podés seguir agregando productos antes de pagar.</p></div>{reward_notice}{rows}<div class="card"><h3>Productos: {money(total)}</h3><p class="muted">Delivery: {fee} · Retiro en local: {pickup} (sin cargo). El total final se calcula en el próximo paso.</p>{buttons}</div>')


@app.route('/club/carrito/quitar/<int:cart_index>',methods=['POST'])
@client_auth_required
def client_cart_remove(cart_index):
    cart=_portal_cart_raw()
    if 0 <= int(cart_index) < len(cart):
        cart.pop(int(cart_index));session['client_cart']=cart
    return redirect(url_for('client_cart'))


@app.route('/club/carrito/vaciar',methods=['POST'])
@client_auth_required
def client_cart_clear():
    session['client_cart']=[]
    return redirect(url_for('client_order_catalog'))


def _save_payment_proof(fileobj):
    if not fileobj or not fileobj.filename:return None
    ext=Path(fileobj.filename).suffix.lower()
    if ext not in ('.jpg','.jpeg','.png','.webp','.pdf'):
        raise ValueError('El comprobante debe ser JPG, PNG, WEBP o PDF.')
    name=f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:12]}{ext}"
    fileobj.save(_proof_dir()/name)
    return name


@app.route('/club/checkout',methods=['GET','POST'])
@client_auth_required
def client_checkout():
    cid=int(session['client_customer_id'])
    access=_portal_order_access()
    if not access.get('allowed'):
        return _portal_order_blocked(access)
    details,merchandise_total=_portal_cart_details()
    if not details:return redirect(url_for('client_order_catalog'))
    with db() as conn:
        c=conn.execute("SELECT * FROM customers WHERE id=?",(cid,)).fetchone()
        rewards=conn.execute('''SELECT r.*,COALESCE(p.name,'') product_name FROM loyalty_rewards r
                                LEFT JOIN products p ON p.id=r.product_id
                                WHERE r.active=1 AND r.points_cost<=? ORDER BY r.points_cost,r.name''',(int(c['points'] or 0),)).fetchall()
    transfer={'alias':get_setting('transfer_alias','heladeriapope'),'cbu':get_setting('transfer_cbu',''),'holder':get_setting('transfer_holder','ENCINAS, leandro ezequiel'),'tax':get_setting('transfer_tax_id','20372019485'),'entity':get_setting('transfer_entity','Personal Pay')}
    try: delivery_fee=max(float(get_setting('delivery_fee','2500') or 2500),0.0)
    except Exception: delivery_fee=2500.0
    try: pickup_fee=max(float(get_setting('pickup_fee','0.00') or 0.0),0.0)
    except Exception: pickup_fee=0.0
    mp_cfg=mp_configuration_status()
    reward_data=[]
    for r in rewards:
        disc,_=_reward_discount_for_cart(r,details,merchandise_total)
        if disc>0:
            reward_data.append((r,float(disc)))
    pending_id=session.get('client_pending_reward_id')
    try: pending_id=int(pending_id or 0)
    except Exception: pending_id=0
    if pending_id and not any(int(r['id'])==pending_id for r,_ in reward_data):
        session.pop('client_pending_reward_id',None);pending_id=0
    notice=''
    selected_post=0
    if request.method=='POST':
        access=_portal_order_access()
        if not access.get('allowed'):
            return _portal_order_blocked(access)
        order_type=request.form.get('order_type','DELIVERY').upper();payment=request.form.get('payment_method','TRANSFERENCIA').upper();address=(c['address'] or '').strip()
        try:selected_post=int(request.form.get('loyalty_reward_id') or 0)
        except Exception:selected_post=0
        fee=delivery_fee if order_type=='DELIVERY' else pickup_fee
        zone=check_delivery_zone(address) if order_type=='DELIVERY' else {'status':'RETIRO','distance_km':0,'lat':None,'lng':None,'formatted_address':'Retiro en local','message':'Retiro en local'}
        chosen=None; loyalty_discount=0.0; points_redeemed=0; reward_name=''
        if selected_post:
            with db() as conn:
                chosen=_reward_for_customer(conn,cid,selected_post)
            if not chosen:
                notice='<div class="notice error">El beneficio seleccionado ya no está disponible o no tenés puntos suficientes.</div>'
            else:
                loyalty_discount,_=_reward_discount_for_cart(chosen,details,merchandise_total)
                if loyalty_discount<=0:
                    notice='<div class="notice error">Ese beneficio no puede aplicarse a los productos actuales del carrito.</div>'
                else:
                    points_redeemed=int(chosen['points_cost'] or 0);reward_name=str(chosen['name'] or '')
        final_total=max(float(merchandise_total)-float(loyalty_discount)+float(fee),0.0)
        if not notice and order_type=='DELIVERY' and not address:
            notice='<div class="notice error">Primero cargá tu dirección en Mi perfil.</div>'
        elif not notice and order_type=='DELIVERY' and zone['status']=='FUERA_DE_ZONA':
            notice=f'<div class="notice error">{h(zone["message"])}</div>'
        cash_tendered=0.0;change=0.0;proof=None
        if not notice and payment=='EFECTIVO':
            try:cash_tendered=float(request.form.get('cash_tendered') or 0)
            except Exception:cash_tendered=0
            if cash_tendered<final_total:
                notice=f'<div class="notice error">El importe con el que paga debe ser igual o mayor al total ({money(final_total)}).</div>'
            else:change=cash_tendered-final_total
        elif not notice and payment=='TRANSFERENCIA':
            try:proof=_save_payment_proof(request.files.get('payment_proof'))
            except ValueError as exc:notice=f'<div class="notice error">{h(exc)}</div>'
            if not notice and not proof:notice='<div class="notice error">Adjuntá el comprobante de transferencia.</div>'
        elif not notice and payment=='MERCADO PAGO' and not mp_cfg.get('ready'):
            notice='<div class="notice error">Mercado Pago todavía no está configurado por la heladería.</div>'
        elif not notice and payment not in ('EFECTIVO','TRANSFERENCIA','MERCADO PAGO'):
            notice='<div class="notice error">Medio de pago no habilitado.</div>'
        if not notice:
            now=datetime.now().isoformat(timespec='seconds');status='EN PROCESO';paystatus=('PENDIENTE_VERIFICACION' if payment=='TRANSFERENCIA' else ('PENDIENTE_MERCADOPAGO' if payment=='MERCADO PAGO' else 'PAGO_EN_ENTREGA'))
            try:
                with db() as conn:
                    c2=conn.execute("SELECT * FROM customers WHERE id=?",(cid,)).fetchone()
                    if not c2:
                        raise ValueError('El cliente ya no está disponible.')
                    # Revalidación atómica del canje para evitar doble uso de puntos.
                    chosen2=_reward_for_customer(conn,cid,selected_post) if selected_post else None
                    discount2=0.0;points2=0;reward_name2=''
                    if selected_post:
                        if not chosen2:raise ValueError('El beneficio ya no está disponible o el saldo de puntos cambió.')
                        discount2,_=_reward_discount_for_cart(chosen2,details,merchandise_total)
                        if discount2<=0:raise ValueError('El beneficio ya no aplica a este carrito.')
                        points2=int(chosen2['points_cost'] or 0);reward_name2=str(chosen2['name'] or '')
                    final2=max(float(merchandise_total)-float(discount2)+float(fee),0.0)
                    if payment=='EFECTIVO' and cash_tendered<final2:raise ValueError('El importe entregado no alcanza para cubrir el total actualizado.')
                    change2=max(cash_tendered-final2,0.0) if payment=='EFECTIVO' else 0.0
                    cur=conn.execute('''INSERT INTO orders(created_at,customer_id,user_id,order_type,status,total,address,phone,payment_method,notes,source,payment_status,payment_proof_path,cash_tendered,change_due,delivery_lat,delivery_lng,delivery_distance_km,zone_status,merchandise_subtotal,delivery_fee,loyalty_reward_id,loyalty_reward_name,loyalty_points_redeemed,loyalty_discount,loyalty_redemption_refunded)
                                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)''',(now,cid,None,order_type,status,final2,zone.get('formatted_address') or address,c2['phone'],payment,'Pedido generado desde Portal Web','WEB',paystatus,proof,cash_tendered,change2,zone.get('lat'),zone.get('lng'),zone.get('distance_km'),zone.get('status'),float(merchandise_total),float(fee),int(chosen2['id']) if chosen2 else None,reward_name2,points2,float(discount2)));oid=cur.lastrowid
                    for x in details:
                        conn.execute('''INSERT INTO order_items(order_id,product_id,product_name,quantity,unit_price,line_total,flavor_text) VALUES (?,?,?,?,?,?,?)''',(oid,x['product']['id'],x['product']['name'],x['qty'],x['unit_price'],x['line_total'],', '.join(f['name'] for f in x['flavors'])))
                    if points2:
                        upd=conn.execute('UPDATE customers SET points=points-? WHERE id=? AND points>=?',(points2,cid,points2))
                        if upd.rowcount!=1:raise ValueError('El saldo de puntos cambió. Volvé a intentar el canje.')
                        bal=conn.execute('SELECT points FROM customers WHERE id=?',(cid,)).fetchone()['points']
                        conn.execute('''INSERT INTO loyalty_movements(created_at,customer_id,sale_id,movement_type,points,description,balance_after,order_id)
                                      VALUES (?,?,?,?,?,?,?,?)''',(now,cid,None,'CANJE_WEB_RESERVA',-points2,f'Canje online reservado · Pedido #{oid} · {reward_name2}',int(bal),oid))
                    conn.execute("UPDATE orders SET status_updated_at=? WHERE id=?",(now,oid))
                    note=f'Pedido recibido desde el Portal · {len(details)} producto(s).'
                    if points2:note+=f' · Canje {reward_name2}: -{points2} pts / -${discount2:,.2f}'
                    if fee:note+=f" · {'Delivery' if order_type=='DELIVERY' else 'Retiro en local'} ${fee:,.2f}"
                    conn.execute("INSERT INTO order_status_events(order_id,status,payment_status,created_at,actor,note) VALUES (?,?,?,?,?,?)",(oid,status,paystatus,now,'PORTAL CLIENTE',note))
                    conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",(now,'PORTAL CLIENTE','PEDIDO_WEB',f'Pedido #{oid} · {payment} · ${final2:.2f} · {len(details)} línea(s)' + (f' · canje {points2} pts' if points2 else '') + (f' · delivery ${fee:.2f}' if order_type=='DELIVERY' else f' · retiro ${fee:.2f}')))
                session['client_cart']=[];session.pop('client_pending_reward_id',None)
                _safe_print_order(oid,'web_order_auto_print_pending','IMPRESION_PEDIDO_WEB')
                if payment=='MERCADO PAGO':
                    return redirect(url_for('client_mp_online_pay',order_id=oid))
                return redirect(url_for('client_order_success',order_id=oid))
            except Exception as exc:
                notice=f'<div class="notice error">No se pudo generar el pedido: {h(exc)}</div>'
    maphtml=''
    if c['address']:
        maphtml=f'<iframe class="mapframe" loading="lazy" src="{h(google_maps_embed_url(c["address"]))}"></iframe>'
    transferbox=f'''<div id="transferBox" class="paybox"><h3>Transferencia</h3><p><b>{h(transfer['entity'])}</b><br>A nombre de {h(transfer['holder'])}<br>CUIL {h(transfer['tax'])}</p><div class="muted">Alias</div><div class="copyrow"><code id="aliasValue">{h(transfer['alias'])}</code><button type="button" onclick="navigator.clipboard.writeText(document.getElementById('aliasValue').innerText)">COPIAR</button></div>{('<div class="muted" style="margin-top:8px">CBU/CVU</div><div class="copyrow"><code id="cbuValue">'+h(transfer['cbu'])+'</code><button type="button" onclick="navigator.clipboard.writeText(document.getElementById(\'cbuValue\').innerText)">COPIAR</button></div>') if transfer['cbu'] else ''}<div class="field"><label>Adjuntar comprobante *</label><input name="payment_proof" type="file" accept="image/*,.pdf"></div><p class="muted">El pedido queda EN PROCESO hasta que administración verifique la transferencia.</p></div>'''
    summary=''.join(f'''<div class="orderline"><div><b>{x['qty']} × {h(x['product']['name'])}</b><div class="muted">{('Gustos: '+h(', '.join(f['name'] for f in x['flavors']))) if x['flavors'] else ''}</div></div><b>{money(x['line_total'])}</b></div>''' for x in details)
    reward_options=['<option value="0" data-discount="0">No usar puntos</option>']
    discounts_js={'0':0.0}
    for r,disc in reward_data:
        sel=' selected' if int(r['id'])==(selected_post or pending_id) else ''
        reward_options.append(f'<option value="{r["id"]}" data-discount="{disc:.2f}"{sel}>{h(r["name"])} · {int(r["points_cost"])} pts · ahorrás {money(disc)}</option>')
        discounts_js[str(r['id'])]=float(disc)
    if reward_data:
        reward_select=f'''<div class="paybox"><h3>🎁 Canjear puntos online</h3><div class="field"><label>Beneficio</label><select name="loyalty_reward_id" id="rewardSelect" onchange="updateTotals()">{''.join(reward_options)}</select></div><p class="muted">Los puntos se descuentan al enviar el pedido. Si el pedido se rechaza o cancela, se reintegran automáticamente.</p></div>'''
    else:
        reward_select='<div class="notice info">Todavía no tenés un beneficio aplicable a este carrito. Podés seguir sumando puntos o agregar el producto correspondiente al beneficio.</div><input type="hidden" name="loyalty_reward_id" value="0">'
    default_discount=discounts_js.get(str(selected_post or pending_id),0.0)
    initial_total=max(merchandise_total-default_discount+delivery_fee,0.0)
    expected_points=points_for_amount(max(merchandise_total-default_discount,0.0))
    points_note=f'<div class="notice info">⭐ Al completar el pedido se acreditarán aproximadamente <b>{expected_points} puntos</b> por los productos pagados. El costo de envío no suma puntos.</div>' if expected_points else '<div class="notice info">El pedido quedará registrado como venta online al completarse.</div>'
    return portal_page('Finalizar pedido',f'''<div class="card"><h2>Finalizar pedido</h2>{points_note}{notice}<div style="margin:12px 0">{summary}</div><div class="paybox"><div class="fee-line"><span>Productos</span><b>{money(merchandise_total)}</b></div><div class="fee-line" id="discountLine"><span>Canje de puntos</span><b id="discountValue">- {money(default_discount)}</b></div><div class="fee-line"><span id="feeLabel">Envío</span><b id="deliveryValue">{money(delivery_fee)}</b></div><div class="fee-line total"><span>TOTAL</span><b id="grandTotal">{money(initial_total)}</b></div></div><p><b>Dirección:</b> {h(c['address']) or 'Sin dirección'} <a href="{url_for('client_profile')}">Modificar</a></p>{maphtml}<form method="post" enctype="multipart/form-data"><div class="field"><label>Entrega</label><select name="order_type" id="orderType" onchange="updateTotals()"><option value="DELIVERY">DELIVERY · {money(delivery_fee)}</option><option value="RETIRO EN LOCAL">RETIRO EN LOCAL · SIN CARGO</option></select></div>{reward_select}<div class="field"><label>Forma de pago</label><select name="payment_method" id="payMethod" onchange="togglePay()"><option>TRANSFERENCIA</option><option>EFECTIVO</option>{('<option>MERCADO PAGO</option>' if mp_cfg.get('online_ready') else '<option disabled>MERCADO PAGO · falta configurar</option>')}</select></div>{transferbox}<div id="mpBox" class="paybox" style="display:none"><h3>💙 Mercado Pago</h3><p>Al confirmar, el sistema crea una order por el importe exacto y te envía directamente al checkout oficial de Mercado Pago. En celular, Mercado Pago puede continuar en su app o en su entorno Web. No tenés que escribir el importe.</p></div><div id="cashBox" class="paybox" style="display:none"><h3>Efectivo</h3><div class="field"><label>¿Con cuánto vas a pagar?</label><input id="cashTendered" name="cash_tendered" type="number" min="0" step="1" placeholder="Ej. 25000"></div><p class="muted">El repartidor verá el vuelto que debe llevar.</p></div><button class="btn green big">ENVIAR PEDIDO</button></form></div><script>const merchandise={float(merchandise_total):.2f},deliveryFee={float(delivery_fee):.2f},pickupFee={float(pickup_fee):.2f};function rewardDiscount(){{let s=document.getElementById('rewardSelect');if(!s)return 0;let o=s.options[s.selectedIndex];return Number(o?.dataset?.discount||0);}}function ars(v){{let cents=Math.abs(v-Math.round(v))>0.004;return '$ '+Number(v).toLocaleString('es-AR',{{minimumFractionDigits:cents?2:0,maximumFractionDigits:cents?2:0}});}}function updateTotals(){{let isDelivery=document.getElementById('orderType').value==='DELIVERY';let d=isDelivery?deliveryFee:pickupFee;let lbl=document.getElementById('feeLabel');if(lbl)lbl.textContent=isDelivery?'Envío':'Retiro en local';let disc=rewardDiscount();let t=Math.max(0,merchandise-disc+d);document.getElementById('deliveryValue').textContent=ars(d);document.getElementById('discountValue').textContent='- '+ars(disc);document.getElementById('grandTotal').textContent=ars(t);let cash=document.getElementById('cashTendered');if(cash)cash.min=Math.ceil(t);}}function togglePay(){{let m=document.getElementById('payMethod').value;document.getElementById('transferBox').style.display=m==='TRANSFERENCIA'?'block':'none';document.getElementById('cashBox').style.display=m==='EFECTIVO'?'block':'none';let mp=document.getElementById('mpBox');if(mp)mp.style.display=m==='MERCADO PAGO'?'block':'none';}}togglePay();updateTotals();</script>''')


def _tracking_markup(payload):
    steps=[('EN PROCESO','⏳','Recibido'),('EN PREPARACIÓN','👨‍🍳','Preparando'),('PREPARADO','📦','Preparado'),('ENVIADO','🛵','Enviado'),('ENTREGADO','✓','Entregado')]
    idx=int(payload.get('progress_index',-1))
    status=payload.get('status','')
    html_steps=''
    for i,(key,icon,label) in enumerate(steps):
        cls='done' if idx>i else ('active' if idx==i else '')
        pulse=' pulse' if idx==i and status not in ('ENTREGADO','RECHAZADO','CANCELADO') else ''
        html_steps+=f'<div class="step {cls}" data-step="{i}"><div class="dot{pulse}">{icon}</div><div>{label}</div></div>'
    return f'<div class="timeline" id="orderTimeline">{html_steps}</div>'


def _tracking_message(payload):
    status=payload.get('status','')
    payment=payload.get('payment_status','')
    if status=='RECHAZADO':return 'Pedido rechazado. Revisá el motivo indicado abajo.'
    if status=='CANCELADO':return 'Pedido cancelado.'
    if status=='ENTREGADO':return '¡Pedido entregado! Gracias por elegirnos.'
    if payment=='PENDIENTE_VERIFICACION':return 'Estamos verificando tu transferencia. El pedido todavía no entró a preparación.'
    if payment=='PENDIENTE_MERCADOPAGO':return 'Esperando el pago por Mercado Pago. Completá el checkout online para que el pedido pase a preparación.'
    return {
        'EN PROCESO':'Recibimos tu pedido. En breve comenzamos a prepararlo.',
        'EN PREPARACIÓN':'Tu pago está aprobado y estamos preparando el pedido.',
        'PREPARADO':'Tu pedido ya está preparado.',
        'ENVIADO':'Tu pedido salió del local y está en camino.',
    }.get(status,'Tu pedido está siendo procesado.')


@app.route('/club/pedido/<int:order_id>/ok')
@client_auth_required
def client_order_success(order_id):
    cid=int(session['client_customer_id'])
    with db() as conn:o=conn.execute("SELECT id FROM orders WHERE id=? AND customer_id=?",(order_id,cid)).fetchone()
    if not o:return redirect(url_for('client_orders'))
    return redirect(url_for('client_order_detail',order_id=order_id))


@app.route('/club/pedidos')
@client_auth_required
def client_orders():
    cid=int(session['client_customer_id'])
    with db() as conn:rows=conn.execute("SELECT * FROM orders WHERE customer_id=? AND COALESCE(source,'MANUAL')='WEB' ORDER BY id DESC LIMIT 100",(cid,)).fetchall()
    cards=''
    for r in rows:
        state=str(r['status'] or '').upper(); icon='✅' if state=='ENTREGADO' else '❌' if state in ('RECHAZADO','CANCELADO') else '🛵' if state=='ENVIADO' else '📦' if state=='PREPARADO' else '👨‍🍳' if state=='EN PREPARACIÓN' else '⏳'
        cards+=f'''<a href="{url_for('client_order_detail',order_id=r['id'])}" style="text-decoration:none;color:inherit"><div class="card"><div class="orderline"><div><b>{icon} Pedido #{r['id']}</b><div class="muted">{h(str(r['created_at']).replace('T',' '))}<br><b>{h(state)}</b> · {h((r['payment_status'] or r['payment_method'] or '').replace('_',' '))}</div></div><div style="text-align:right"><b>{money(r['total'])}</b><div class="muted">VER ESTADO →</div></div></div></div></a>'''
    cards=cards or '<div class="card">Todavía no hiciste pedidos desde el Portal.</div>'
    return portal_page('Mis pedidos',f'<h2>Mis pedidos</h2><p class="muted">Tocá un pedido para seguirlo en tiempo real.</p>{cards}<a class="btn green" href="{url_for("client_order_catalog")}">HACER NUEVO PEDIDO</a>')


@app.route('/club/pedido/<int:order_id>')
@client_auth_required
def client_order_detail(order_id):
    cid=int(session['client_customer_id'])
    try:
        sync_local_order(order_id,auto_transition=True)
    except Exception:
        pass
    payload=tracking_payload(order_id,cid)
    if not payload:return redirect(url_for('client_orders'))
    with db() as conn:
        o=conn.execute("SELECT * FROM orders WHERE id=? AND customer_id=?",(order_id,cid)).fetchone()
        items=conn.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY id",(order_id,)).fetchall()
        claims=conn.execute("SELECT * FROM order_claims WHERE order_id=? AND customer_id=? ORDER BY id DESC",(order_id,cid)).fetchall()
    state=payload['status']; hero_cls='done' if state=='ENTREGADO' else 'bad' if state in ('RECHAZADO','CANCELADO') else 'pending' if payload['payment_status'] in ('PENDIENTE_VERIFICACION','PENDIENTE_MERCADOPAGO') else ''
    rows=''.join(f'''<div class="orderline"><div><b>{float(x['quantity']):g} × {h(x['product_name'])}</b><div class="muted">{('Gustos: '+h(x['flavor_text'])) if x['flavor_text'] else ''}</div></div><div><b>{money(x['line_total'])}</b></div></div>''' for x in items)
    claim_rows=''.join(f'''<div class="card claimbox"><b>Reclamo #{x['id']} · {h(x['status'])}</b><div class="muted">Gustos pedidos: {h(x['expected_flavors'])}<br>Recibido: {h(x['received_flavor'])}<br>{h(x['description'])}</div></div>''' for x in claims)
    reason=''
    if payload['rejection_reason']:reason+=f'<div class="notice error"><b>Motivo del rechazo:</b><br>{h(payload["rejection_reason"])}</div>'
    if payload['cancellation_reason']:reason+=f'<div class="notice error"><b>Motivo de cancelación:</b><br>{h(payload["cancellation_reason"])}</div>'
    if payload['refund_status']=='PENDIENTE_REINTEGRO':reason+='<div class="notice error"><b>Reintegro pendiente.</b><br>El local debe devolverte el importe de la transferencia.</div>'
    if payload['refund_status']=='REINTEGRADO':reason+='<div class="notice"><b>Reintegro confirmado por el local.</b></div>'
    claim_btn=f'<a id="claimButton" class="btn orange" href="{url_for("client_order_claim",order_id=order_id)}">⚠ GENERAR RECLAMO POR GUSTOS</a>' if state=='ENTREGADO' else f'<a id="claimButton" class="btn orange hidden" href="{url_for("client_order_claim",order_id=order_id)}">⚠ GENERAR RECLAMO POR GUSTOS</a>'
    expected_points=points_for_amount(max(float(o['merchandise_subtotal'] or 0)-float(o['loyalty_discount'] or 0),0.0))
    if int(payload.get('loyalty_points_earned') or 0)>0:
        points_info=f'<div id="pointsInfo" class="notice">⭐ <b>+{int(payload["loyalty_points_earned"])} puntos acreditados</b> por esta compra online.</div>'
    elif state not in ('RECHAZADO','CANCELADO','ENTREGADO') and expected_points>0:
        points_info=f'<div id="pointsInfo" class="notice info">⭐ Al completar el pedido se acreditarán <b>{expected_points} puntos</b>.</div>'
    else:
        points_info='<div id="pointsInfo" class="hidden"></div>'
    redeem_info=(f'<div class="notice">🎁 Usaste <b>{int(o["loyalty_points_redeemed"] or 0)} puntos</b> en {h(o["loyalty_reward_name"] or "un beneficio")} · ahorro {money(o["loyalty_discount"] or 0)}</div>' if int(o['loyalty_points_redeemed'] or 0)>0 else '')
    mp_box=''
    if str(o['payment_method'] or '').upper() in ('MERCADO PAGO','MERCADOPAGO','MERCADO_PAGO'):
        if str(o['payment_status'] or '').upper()=='PAGO_APROBADO':
            mp_box='<div class="notice">💙 <b>Pago de Mercado Pago acreditado.</b> Ya estamos procesando tu pedido.</div>'
        else:
            mp_box=f'''<div class="card" id="mpPayCard" style="text-align:center"><h3>💙 Mercado Pago Online</h3><p>Importe del pedido: <b>{money(o['total'])}</b></p><p class="muted">El pago se realiza dentro del checkout seguro de Mercado Pago.</p><a class="btn blue big" href="{url_for('client_mp_online_pay',order_id=order_id)}">PAGAR AHORA CON MERCADO PAGO</a></div>'''
    breakdown=f'''<div class="paybox"><div class="fee-line"><span>Productos</span><b>{money(o['merchandise_subtotal'] or sum(float(x['line_total'] or 0) for x in items))}</b></div>{('<div class="fee-line"><span>Canje de puntos</span><b>- '+money(o['loyalty_discount'])+'</b></div>') if float(o['loyalty_discount'] or 0)>0 else ''}<div class="fee-line"><span>{'Envío' if o['order_type']=='DELIVERY' else 'Retiro en local'}</span><b>{money(o['delivery_fee'] or 0)}</b></div><div class="fee-line total"><span>TOTAL</span><b>{money(o['total'])}</b></div></div>'''
    body=f'''<div id="statusHero" class="statushero {hero_cls}"><span class="livepill">● EN VIVO</span><h2 style="margin:10px 0 4px">Pedido #{order_id}</h2><div id="statusTitle" style="font-size:25px;font-weight:950">{h(state)}</div><p id="statusMessage" style="margin-bottom:0">{h(_tracking_message(payload))}</p></div>
    {_tracking_markup(payload)}<div class="card"><div class="orderline"><div><b>Pago</b><div id="paymentStatus" class="muted">{h(payload['payment_status'].replace('_',' ') or o['payment_method'])}</div></div><div><b>{money(o['total'])}</b></div></div><div class="orderline"><div><b>Entrega</b><div class="muted">{h(o['address']) if o['order_type']=='DELIVERY' else 'Retiro en local'}</div></div></div>{breakdown}<div id="statusUpdated" class="muted">Actualizado: {h(str(payload['updated_at']).replace('T',' '))}</div></div>{mp_box}{redeem_info}{points_info}<div id="terminalInfo">{reason}</div>
    <div class="card"><h3>Tu pedido</h3>{rows}</div>{claim_btn}{claim_rows}<p class="muted" style="text-align:center">El estado se actualiza automáticamente cada 2 segundos mientras tengas esta pantalla abierta.</p>
    <script>
    const orderId={int(order_id)};const icons=['⏳','👨‍🍳','📦','🛵','✓'];
    function messageFor(d){{if(d.status==='RECHAZADO')return 'Pedido rechazado. Revisá el motivo indicado.';if(d.status==='CANCELADO')return 'Pedido cancelado.';if(d.status==='ENTREGADO')return '¡Pedido entregado! Gracias por elegirnos.';if(d.payment_status==='PENDIENTE_VERIFICACION')return 'Estamos verificando tu transferencia. El pedido todavía no entró a preparación.';if(d.payment_status==='PENDIENTE_MERCADOPAGO')return 'Esperando el pago por Mercado Pago. Completá el checkout online para que el pedido pase a preparación.';return {{'EN PROCESO':'Recibimos tu pedido. En breve comenzamos a prepararlo.','EN PREPARACIÓN':'Tu pago está aprobado y estamos preparando el pedido.','PREPARADO':'Tu pedido ya está preparado.','ENVIADO':'Tu pedido salió del local y está en camino.'}}[d.status]||'Tu pedido está siendo procesado.';}}
    function paint(d){{document.getElementById('statusTitle').textContent=d.status;document.getElementById('statusMessage').textContent=messageFor(d);document.getElementById('paymentStatus').textContent=(d.payment_status||'').replaceAll('_',' ');document.getElementById('statusUpdated').textContent='Actualizado: '+String(d.updated_at||'').replace('T',' ');let hero=document.getElementById('statusHero');hero.className='statushero '+(d.status==='ENTREGADO'?'done':(['RECHAZADO','CANCELADO'].includes(d.status)?'bad':(['PENDIENTE_VERIFICACION','PENDIENTE_MERCADOPAGO'].includes(d.payment_status)?'pending':'')));document.querySelectorAll('.step').forEach((el,i)=>{{el.className='step '+(d.progress_index>i?'done':(d.progress_index===i?'active':''));let dot=el.querySelector('.dot');dot.className='dot '+(d.progress_index===i&&!d.terminal?'pulse':'');dot.textContent=icons[i];}});let cb=document.getElementById('claimButton');if(cb)cb.classList.toggle('hidden',d.status!=='ENTREGADO');let pi=document.getElementById('pointsInfo');if(pi){{if((d.loyalty_points_earned||0)>0){{pi.className='notice';pi.innerHTML='⭐ <b>+'+d.loyalty_points_earned+' puntos acreditados</b> por esta compra online.';}}else if(['RECHAZADO','CANCELADO','ENTREGADO'].includes(d.status)){{pi.className='hidden';pi.textContent='';}}}}let info=document.getElementById('terminalInfo');if(info){{info.innerHTML='';let notes=[];if(d.rejection_reason)notes.push(['Motivo del rechazo: '+d.rejection_reason,'error']);if(d.cancellation_reason)notes.push(['Motivo de cancelación: '+d.cancellation_reason,'error']);if(d.refund_status==='PENDIENTE_REINTEGRO')notes.push(['Reintegro pendiente. El local debe devolverte el importe transferido.','error']);if(d.refund_status==='REINTEGRADO')notes.push(['Reintegro confirmado por el local.','']);notes.forEach(n=>{{let x=document.createElement('div');x.className='notice '+n[1];x.textContent=n[0];info.appendChild(x);}});}}}}
    async function refreshStatus(){{try{{let r=await fetch('{url_for('client_order_status_api',order_id=order_id)}',{{cache:'no-store'}});if(!r.ok)return;paint(await r.json());}}catch(e){{}}}}refreshStatus();setInterval(refreshStatus,2000);
    </script>'''
    return portal_page(f'Pedido #{order_id}',body)



def _deep_find_value(obj, key):
    if isinstance(obj, dict):
        if key in obj and obj.get(key):
            return obj.get(key)
        for value in obj.values():
            found=_deep_find_value(value,key)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found=_deep_find_value(value,key)
            if found:
                return found
    return None


@app.route('/club/pedido/<int:order_id>/mercadopago')
@client_auth_required
def client_mp_online_pay(order_id):
    cid=int(session['client_customer_id'])
    mp=mp_configuration_status()
    with db() as conn:
        o=conn.execute("SELECT * FROM orders WHERE id=? AND customer_id=?",(order_id,cid)).fetchone()
        acct=conn.execute("SELECT email FROM portal_accounts WHERE customer_id=?",(cid,)).fetchone()
    if not o:
        return redirect(url_for('client_orders'))
    if str(o['payment_method'] or '').upper() not in ('MERCADO PAGO','MERCADOPAGO','MERCADO_PAGO'):
        return redirect(url_for('client_order_detail',order_id=order_id))
    if str(o['payment_status'] or '').upper()=='PAGO_APROBADO':
        return redirect(url_for('client_order_detail',order_id=order_id))
    if str(o['status'] or '').upper() in ('ENTREGADO','CANCELADO','RECHAZADO'):
        return redirect(url_for('client_order_detail',order_id=order_id))
    if not mp.get('online_ready'):
        return portal_page('Mercado Pago',f'''<div class="card"><h2>💙 Mercado Pago</h2><div class="notice error">Mercado Pago Online todavía no está habilitado. Falta guardar/activar el Access Token.</div><a class="btn" href="{url_for('client_order_detail',order_id=order_id)}">VOLVER AL PEDIDO</a></div>''')
    base=_public_request_base()
    success=f"{base}{url_for('client_order_detail',order_id=order_id)}?mp=success"
    failure=f"{base}{url_for('client_order_detail',order_id=order_id)}?mp=failure"
    pending=f"{base}{url_for('client_order_detail',order_id=order_id)}?mp=pending"
    try:
        result=create_checkout_pro_order(order_id,success,failure,pending,(acct['email'] if acct else '') or '', recreate=(request.args.get('recreate')=='1'))
    except Exception as exc:
        return portal_page('Mercado Pago',f'''<div class="card"><h2>💙 Mercado Pago</h2><div class="notice error">No se pudo abrir Mercado Pago:<br><b>{h(exc)}</b></div><a class="btn blue" href="{url_for('client_order_detail',order_id=order_id)}">VOLVER AL PEDIDO</a></div>'''),400
    checkout_url=str(result.get('checkout_url') or '').strip()
    if not checkout_url:
        return redirect(url_for('client_order_detail',order_id=order_id))
    return redirect(checkout_url,code=302)


@app.route('/club/pedido/<int:order_id>/mercadopago/procesar',methods=['POST'])
@client_auth_required
def client_mp_online_process(order_id):
    cid=int(session['client_customer_id'])
    with db() as conn:
        o=conn.execute("SELECT id,status,payment_method,payment_status FROM orders WHERE id=? AND customer_id=?",(order_id,cid)).fetchone()
        acct=conn.execute("SELECT email FROM portal_accounts WHERE customer_id=?",(cid,)).fetchone()
    if not o:
        return jsonify(ok=False,error='Pedido inexistente.'),404
    if str(o['status'] or '').upper() in ('ENTREGADO','CANCELADO','RECHAZADO'):
        return jsonify(ok=False,error='El pedido ya está cerrado.'),409
    if str(o['payment_status'] or '').upper()=='PAGO_APROBADO':
        return jsonify(ok=True,redirect=url_for('client_order_detail',order_id=order_id))
    data=request.get_json(silent=True) or {}
    form=data.get('formData') or {}
    additional=data.get('additionalData') or {}
    payer=form.get('payer') or {}
    ident=payer.get('identification') or {}
    try:
        result=create_online_card_order(
            order_id,
            form.get('token'),
            form.get('payment_method_id'),
            additional.get('paymentTypeId') or form.get('payment_type_id') or 'credit_card',
            form.get('installments') or 1,
            payer.get('email') or (acct['email'] if acct else ''),
            ident.get('type') or 'DNI',
            ident.get('number') or '',
        )
    except Exception as exc:
        return jsonify(ok=False,error=str(exc)),400
    raw=result.get('raw') or {}
    challenge_url=_deep_find_value(raw,'external_resource_url')
    creq=_deep_find_value(raw,'creq')
    if result.get('payment_status')=='MP_RECHAZADO':
        return jsonify(ok=False,error='Mercado Pago rechazó el pago. Revisá los datos o probá con otro medio.'),402
    return jsonify(ok=True,redirect=url_for('client_order_detail',order_id=order_id),challenge_url=challenge_url,creq=creq,
                   payment_status=result.get('payment_status'),accredited=bool(result.get('accredited')))

@app.route('/club/pedido/<int:order_id>/mercadopago-qr.png')
@client_auth_required
def client_mp_qr_png(order_id):
    cid=int(session['client_customer_id'])
    with db() as conn:
        o=conn.execute("SELECT mercadopago_qr_data FROM orders WHERE id=? AND customer_id=?",(order_id,cid)).fetchone()
    if not o or not o['mercadopago_qr_data']:
        return Response('QR no disponible',status=404,mimetype='text/plain')
    try:
        import qrcode
        img=qrcode.make(str(o['mercadopago_qr_data']));out=io.BytesIO();img.save(out,format='PNG')
        return Response(out.getvalue(),mimetype='image/png')
    except Exception as exc:
        return Response(str(exc),status=500,mimetype='text/plain')


@app.route('/club/pedido/<int:order_id>/mercadopago-reintentar',methods=['POST'])
@client_auth_required
def client_mp_retry(order_id):
    cid=int(session['client_customer_id'])
    with db() as conn:
        o=conn.execute("SELECT id,status,payment_method FROM orders WHERE id=? AND customer_id=?",(order_id,cid)).fetchone()
    if not o:
        return redirect(url_for('client_orders'))
    if str(o['status'] or '').upper() in ('ENTREGADO','CANCELADO','RECHAZADO'):
        return redirect(url_for('client_order_detail',order_id=order_id))
    if str(o['payment_method'] or '').upper() not in ('MERCADO PAGO','MERCADOPAGO','MERCADO_PAGO'):
        return redirect(url_for('client_order_detail',order_id=order_id))
    # V21: regenerar una order Online y volver a enviar al checkout oficial.
    return redirect(url_for('client_mp_online_pay',order_id=order_id,recreate='1'))


@app.route('/club/api/pedido/<int:order_id>/estado')
@client_auth_required
def client_order_status_api(order_id):
    try:
        sync_local_order(order_id,auto_transition=True)
    except Exception:
        pass
    payload=tracking_payload(order_id,int(session['client_customer_id']))
    if not payload:return jsonify(ok=False),404
    return jsonify(payload)


@app.route('/club/pedido/<int:order_id>/reclamo',methods=['GET','POST'])
@client_auth_required
def client_order_claim(order_id):
    cid=int(session['client_customer_id'])
    with db() as conn:
        o=conn.execute("SELECT * FROM orders WHERE id=? AND customer_id=?",(order_id,cid)).fetchone()
        items=conn.execute("SELECT * FROM order_items WHERE order_id=? AND COALESCE(flavor_text,'')<>'' ORDER BY id",(order_id,)).fetchall()
    if not o:return redirect(url_for('client_orders'))
    if str(o['status'] or '').upper()!='ENTREGADO':
        return portal_page('Reclamo',f'<div class="card"><div class="notice error">El reclamo por gustos se habilita solamente cuando el pedido figura ENTREGADO.</div><a class="btn" href="{url_for("client_order_detail",order_id=order_id)}">VOLVER</a></div>'),400
    if not items:
        return portal_page('Reclamo',f'<div class="card"><div class="notice error">Este pedido no contiene productos con selección de gustos.</div><a class="btn" href="{url_for("client_order_detail",order_id=order_id)}">VOLVER</a></div>')
    notice=''
    if request.method=='POST':
        try:item_id=int(request.form.get('order_item_id') or 0)
        except Exception:item_id=0
        received=request.form.get('received_flavor','').strip();desc=request.form.get('description','').strip()
        selected=next((x for x in items if int(x['id'])==item_id),None)
        if not selected or not received:
            notice='<div class="notice error">Elegí el producto e indicá qué gusto recibiste.</div>'
        else:
            now=datetime.now().isoformat(timespec='seconds')
            with db() as conn:
                duplicate=conn.execute("SELECT 1 FROM order_claims WHERE order_id=? AND customer_id=? AND order_item_id=? AND status IN ('PENDIENTE','EN REVISION')",(order_id,cid,item_id)).fetchone()
                if duplicate:
                    notice='<div class="notice error">Ya existe un reclamo abierto para ese producto.</div>'
                else:
                    conn.execute('''INSERT INTO order_claims(order_id,customer_id,order_item_id,claim_type,expected_flavors,received_flavor,description,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)''',(order_id,cid,item_id,'GUSTOS_INCORRECTOS',selected['flavor_text'],received,desc,'PENDIENTE',now,now))
                    conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",(now,'PORTAL CLIENTE','RECLAMO_GUSTOS',f'Pedido #{order_id} · {selected["product_name"]}'))
                    return redirect(url_for('client_order_detail',order_id=order_id))
    options=''.join(f'<option value="{x["id"]}">{h(x["product_name"])} · Pediste: {h(x["flavor_text"])}</option>' for x in items)
    return portal_page('Reclamo por gustos',f'''<div class="card claimbox"><h2>⚠ Reclamo por gustos</h2><p>Pedido #{order_id}. Este formulario es únicamente para informar que recibiste un gusto distinto al solicitado.</p>{notice}<form method="post"><div class="field"><label>Producto</label><select name="order_item_id" required>{options}</select></div><div class="field"><label>¿Qué gusto recibiste en su lugar?</label><input name="received_flavor" required placeholder="Ej. Banana"></div><div class="field"><label>Detalle adicional</label><textarea name="description" placeholder="Contanos brevemente qué pasó"></textarea></div><button class="btn orange">ENVIAR RECLAMO</button></form></div>''')


@app.route('/club/tarjeta/<token>')
def client_card(token):
    return redirect(url_for('client_login'))


@app.route('/api/dashboard')
@auth_required
def api_dashboard():
    with db() as conn:r=conn.execute("SELECT COALESCE(SUM(total),0) total,COUNT(*) tickets FROM sales WHERE date(created_at)=date('now','localtime') AND status='CONFIRMADA'").fetchone()
    return jsonify(dict(r))


def run():
    init_database()
    port=int(os.environ.get('HELADERIA_WEB_PORT') or get_setting('web_port','5050'))
    try:
        from waitress import serve
        serve(app,host='0.0.0.0',port=port,threads=8)
    except ImportError:
        app.run(host='0.0.0.0',port=port,debug=False,use_reloader=False)


if __name__=='__main__':
    run()
