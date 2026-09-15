# Heladería Los Nietos · Android

Aplicación Android que abre el Portal del Cliente de Heladería Los Nietos en una WebView optimizada y agrega notificaciones push mediante Firebase Cloud Messaging (FCM).

## Qué incluye

- Nombre visible: **Heladería Los Nietos**.
- Package ID: `ar.com.heladerialosnietos.app`.
- Android 6.0+ (`minSdk 23`).
- Target Android 16 / API 36 para publicación actual en Google Play.
- Portal Web completo: login, productos, pedidos, puntos, tarjeta digital y recuperación de contraseña.
- Mercado Pago se abre fuera de la WebView para que Android pueda enviarlo a la app/browser oficial.
- Push de puntos acreditados mediante FCM.
- GitHub Actions: genera un APK instalable sin Android Studio.

## URL actual del portal

Por defecto:

`https://ckhgs28k-5050.brs.devtunnels.ms/club`

Dev Tunnels puede cambiar. En GitHub se recomienda crear una Variable del repositorio llamada `PORTAL_URL` con la URL HTTPS vigente terminada en `/club`.

## 1. Crear Firebase

1. Entrar a https://console.firebase.google.com/
2. Crear proyecto: `Heladeria Los Nietos`.
3. Agregar una aplicación Android.
4. Package name exacto: `ar.com.heladerialosnietos.app`.
5. Descargar `google-services.json`.

No hace falta subir ese archivo públicamente al repositorio. El workflow puede recibirlo como Secret.

## 2. Preparar el Secret de GitHub

Convertí `google-services.json` a Base64.

En Windows PowerShell:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("google-services.json")) | Set-Clipboard
```

En GitHub:

`Repositorio > Settings > Secrets and variables > Actions > New repository secret`

Nombre:

`GOOGLE_SERVICES_JSON_B64`

Pegá el texto Base64 como valor.

Después, en la pestaña **Variables**, crear:

`PORTAL_URL`

Ejemplo:

`https://ckhgs28k-5050.brs.devtunnels.ms/club`

## 3. Subir este proyecto a GitHub

Crear un repositorio vacío, por ejemplo:

`heladeria-los-nietos-android`

Subir **todo el contenido de esta carpeta**, no la carpeta contenedora.

La forma más simple desde la web de GitHub es:

`Add file > Upload files > arrastrar todos los archivos y carpetas > Commit changes`.

## 4. Crear el APK

En GitHub:

`Actions > Build Android APK > Run workflow`

Esperar a que termine en verde.

Entrar al workflow terminado y bajar el artefacto:

`Heladeria-Los-Nietos-APK`

Dentro estará:

`app-debug.apk`

Copiarlo al Android e instalarlo.

## 5. Habilitar push en el servidor

La app obtiene un token FCM y, después de que el cliente inicia sesión, lo registra automáticamente contra:

`POST /club/api/push/register`

Para que el servidor pueda enviar notificaciones, aplicar el ZIP de actualización backend entregado junto con este proyecto y configurar la credencial de servicio de Firebase.

En Firebase:

`Configuración del proyecto > Cuentas de servicio > Generar nueva clave privada`.

Guardar el JSON **solo en el servidor**, por ejemplo:

`data/firebase-service-account.json`

No debe subirse a GitHub.

También puede usarse la variable de entorno:

`GOOGLE_APPLICATION_CREDENTIALS=C:\ruta\firebase-service-account.json`

Cuando se acreditan puntos, la notificación queda como:

**⭐ Puntos acreditados**

`Se acreditaron 7 puntos por tu compra. Saldo actual: 43 puntos.`

Al tocarla abre la pantalla de puntos del Portal.

## Recuperación de contraseña

La aplicación usa la misma ruta Web ya incorporada en el Portal:

`/club/olvide-clave`

El cliente valida DNI + fecha de nacimiento + últimos 4 dígitos de la tarjeta de fidelidad y crea una nueva contraseña.

## Play Store

Este proyecto usa `targetSdk 36`, requerido para nuevas apps y actualizaciones de Google Play desde el 31/08/2026. Para Play Store no conviene subir el APK debug: hay que generar un **Android App Bundle (.aab) release firmado**. El siguiente paso es crear la clave de firma y agregar un workflow de release.
