HELADERIA LOS NIETOS - ANDROID V38 CLOUDING

Portal configurado por defecto:
http://200.234.232.76/club

GitHub Actions:
.github/workflows/build-apk.yml

La compilacion usa la variable CLOUDING_PORTAL_URL si existe.
Si no existe, app/build.gradle usa automaticamente:
http://200.234.232.76/club

El workflow espera el Secret:
GOOGLE_SERVICES_JSON_B64

No incluye google-services.json para no copiar credenciales al ZIP.
