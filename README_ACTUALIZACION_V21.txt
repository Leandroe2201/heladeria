HELADERÍA LOS NIETOS · ACTUALIZACIÓN V21

1. Cerrá el sistema de escritorio y el servidor Web.
2. Extraé este ZIP directamente dentro de la carpeta donde está main.py.
3. Aceptá reemplazar los archivos existentes.
4. Volvé a ejecutar iniciar.bat e iniciar_web.bat.

ESTA ACTUALIZACIÓN NO INCLUYE data/heladeria.db.
No reemplaza clientes, ventas, pedidos, puntos ni configuraciones.

Cambios principales:
- Mercado Pago Web redirige al checkout oficial mediante API de Orders / checkout_url.
- Online requiere Access Token; External POS ID queda solamente para QR presencial.
- Retiro en local usa $ 0,01 de prueba, configurable a $ 0 para producción.
- Reintento de Mercado Pago regenera checkout Online.
- Pago acreditado actualiza PAGO APROBADO -> EN PREPARACIÓN.

Detalle: docs/CAMBIOS_V21.txt
