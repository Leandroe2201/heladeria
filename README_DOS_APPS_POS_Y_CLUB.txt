HELADERÍA LOS NIETOS - DOS APPS ANDROID DESDE EL MISMO REPOSITORIO

Esta actualización genera DOS APK distintas y se pueden instalar al mismo tiempo:

1) POS / VENTAS
   Nombre: Heladería Los Nietos POS
   Package: ar.com.heladerialosnietos.app
   URL: http://200.234.232.76/login

2) CLIENTES / CLUB
   Nombre: Los Nietos Club
   Package: ar.com.heladerialosnietos.club
   URL: http://200.234.232.76/club
   Push Firebase: ACTIVADO

GITHUB > SETTINGS > SECRETS AND VARIABLES > ACTIONS > VARIABLES
Crear/editar:
  POS_PORTAL_URL  = http://200.234.232.76/login
  CLUB_PORTAL_URL = http://200.234.232.76/club

FIREBASE
- La app POS conserva el Secret actual GOOGLE_SERVICES_JSON_B64.
- Para Club, en el MISMO proyecto Firebase agregá una nueva app Android con package:
    ar.com.heladerialosnietos.club
- Descargá su google-services.json.
- Convertí ese JSON a Base64 y guardalo en GitHub Actions Secrets como:
    GOOGLE_SERVICES_CLUB_B64

Luego hacé git add ., commit y push.
GitHub Actions genera dos artefactos:
  Heladeria-Los-Nietos-POS-APK
  Los-Nietos-Club-APK
