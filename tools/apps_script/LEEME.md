# Órdenes de Hapi → portfolio.csv

El bot actualiza `portfolio.csv` con las órdenes que Hapi confirma por correo ("Order Executed").
Gmail no se conecta a GitHub: un Apps Script dentro de tu cuenta de Google copia las órdenes a una
hoja y las entrega por una URL que solo responde con un token.

## Instalación (una sola vez, ~10 minutos)

1. **Hoja**: crea una hoja de cálculo nueva en Google Drive, por ejemplo "Órdenes Hapi".
2. **Script**: en la hoja, *Extensiones → Apps Script*. Borra lo que haya y pega el contenido de
   `hapi_ordenes.gs`. Guarda.
3. **Token**: en el editor elige la función `crearToken` y pulsa *Ejecutar*. Google pedirá permisos
   (Gmail y Hojas de cálculo): acéptalos. En *Registro de ejecución* aparece el token; cópialo.
4. **Prueba**: ejecuta `importarOrdenes`. Si ya tienes órdenes posteriores al 17/10/2026 aparecen
   en la pestaña "Ordenes".
5. **Publicar**: *Implementar → Nueva implementación → Aplicación web*.
   - Ejecutar como: **Yo**
   - Quién tiene acceso: **Cualquier usuario**
   Copia la URL que termina en `/exec`.
6. **GitHub**: en el repositorio, *Settings → Secrets and variables → Actions*, crea:
   - `HAPI_ORDENES_URL` = la URL `/exec`
   - `HAPI_ORDENES_TOKEN` = el token del paso 3

"Cualquier usuario" significa que la URL responde sin iniciar sesión, pero sin el token devuelve
`no autorizado`. Si el token se filtra, solo se exponen las órdenes de esta hoja. Para revocarlo:
vuelve a correr `crearToken` y actualiza el secreto.

## Qué hace el bot cada domingo

Antes del análisis semanal (paso "Actualizar portafolio con órdenes de Hapi"):

- **Compra de algo que ya tienes**: suma la cantidad.
- **Venta**: resta la cantidad; si queda en cero, el activo vuelve a la Watchlist con su categoría.
- **Compra nueva**: si estaba en la Watchlist conserva su categoría. Si no, la clasifica con la ficha
  del universo de ETFs o con datos de Yahoo, y la marca "(auto)" en el subtipo para que la revises.
- Cada orden se aplica una sola vez (`data/ordenes_hapi.json`).
- El resumen va en una línea del mensaje semanal de Telegram y en la portada del PDF.

El efectivo (poder de compra) no se toca: Hapi no avisa los depósitos y retiros por correo.

## Si Hapi cambia el formato del correo

La fila queda con la columna `error` llena y el bot la reporta sin aplicarla. Corrige la fila a mano
en la hoja (y borra el error): el bot la toma en la siguiente corrida.
