/**
 * hapi_ordenes.gs — Copia las órdenes ejecutadas de Hapi (correo "Order Executed")
 * a esta hoja y las entrega al bot por una URL protegida con un token.
 *
 * Va pegado en la hoja de cálculo: Extensiones → Apps Script. Instrucciones en LEEME.md.
 *
 * Seguridad: ninguna credencial de Gmail sale de Google. La URL solo responde si
 * trae el token correcto, y solo devuelve las filas de esta hoja (órdenes de Hapi).
 */

const CONFIG = {
  HOJA: 'Ordenes',
  // Solo correos posteriores a la foto del portafolio (17/10/2026): los anteriores
  // ya están en portfolio.csv y se contarían dos veces.
  BUSQUEDA: 'subject:"Order Executed" from:hapi after:2026/10/17',
  ETIQUETA: 'Hapi/Procesado',
  COLUMNAS: ['id', 'fecha', 'operacion', 'ticker', 'cantidad', 'precio', 'costo', 'comision', 'estado', 'error'],
};

/** Lee los correos nuevos y agrega una fila por orden. Se puede correr a mano. */
function importarOrdenes() {
  const hoja = obtenerHoja_();
  const ultima = hoja.getLastRow();
  const ids = new Set(ultima > 1 ? hoja.getRange(2, 1, ultima - 1, 1).getValues().flat().map(String) : []);
  const etiqueta = GmailApp.getUserLabelByName(CONFIG.ETIQUETA) || GmailApp.createLabel(CONFIG.ETIQUETA);
  const hilos = GmailApp.search(CONFIG.BUSQUEDA + ' -label:' + CONFIG.ETIQUETA.replace('/', '-'), 0, 100);

  let nuevas = 0;
  hilos.forEach(function (hilo) {
    hilo.getMessages().forEach(function (msg) {
      const id = msg.getId();
      if (ids.has(id)) return;
      const o = parsear_(msg);
      hoja.appendRow([id, o.fecha, o.operacion, o.ticker, o.cantidad, o.precio, o.costo, o.comision, o.estado, o.error]);
      ids.add(id);
      nuevas++;
    });
    hilo.addLabel(etiqueta);
  });
  return nuevas;
}

/** URL del bot: /exec?token=XXXX → importa lo nuevo y devuelve todas las órdenes en JSON. */
function doGet(e) {
  const token = PropertiesService.getScriptProperties().getProperty('TOKEN');
  if (!token || !e || !e.parameter || e.parameter.token !== token) {
    return json_({ error: 'no autorizado' });
  }
  importarOrdenes();
  const hoja = obtenerHoja_();
  const ultima = hoja.getLastRow();
  const filas = ultima > 1 ? hoja.getRange(2, 1, ultima - 1, CONFIG.COLUMNAS.length).getValues() : [];
  const ordenes = filas.map(function (f) {
    const o = {};
    CONFIG.COLUMNAS.forEach(function (c, i) { o[c] = f[i] instanceof Date ? f[i].toISOString() : f[i]; });
    o.id = String(o.id);
    return o;
  });
  return json_({ ordenes: ordenes });
}

function parsear_(msg) {
  // Texto plano; si viene vacío, el HTML sin etiquetas
  let t = msg.getPlainBody();
  if (!t || !/Ticker/i.test(t)) t = msg.getBody().replace(/<[^>]+>/g, ' ');
  t = t.replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ');

  const num = function (re) {
    const m = t.match(re);
    return m ? Number(m[1].replace(/,/g, '')) : '';
  };
  const txt = function (re) {
    const m = t.match(re);
    return m ? m[1].trim() : '';
  };

  const o = {
    fecha: Utilities.formatDate(msg.getDate(), 'America/Bogota', "yyyy-MM-dd'T'HH:mm:ss"),
    operacion: txt(/Buy\/Sell:?\s*(Buy|Sell)/i),
    ticker: txt(/Ticker:?\s*([A-Z][A-Z0-9.\-]{0,9})\b/),
    cantidad: num(/Quantity Shares:?\s*([\d.,]+)/i),
    comision: num(/Quantity Shares:?\s*[\d.,]+\s*US\$\s*([\d.,]+)/i),
    precio: num(/Average price:?\s*US\$\s*([\d.,]+)/i),
    costo: num(/Cost:?\s*US\$\s*([\d.,]+)/i),
    estado: txt(/Status:?\s*(Order [A-Za-z]+)/i),
    error: '',
  };
  const faltan = ['operacion', 'ticker', 'cantidad', 'precio'].filter(function (k) { return o[k] === ''; });
  if (faltan.length) o.error = 'No se pudo leer: ' + faltan.join(', ');
  return o;
}

function obtenerHoja_() {
  const libro = SpreadsheetApp.getActiveSpreadsheet();
  let hoja = libro.getSheetByName(CONFIG.HOJA);
  if (!hoja) {
    hoja = libro.insertSheet(CONFIG.HOJA);
    hoja.appendRow(CONFIG.COLUMNAS);
    hoja.setFrozenRows(1);
  }
  return hoja;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

/** Corre esta una vez para crear el token. Lo copias al secreto de GitHub. */
function crearToken() {
  const token = Utilities.getUuid().replace(/-/g, '') + Utilities.getUuid().replace(/-/g, '');
  PropertiesService.getScriptProperties().setProperty('TOKEN', token);
  Logger.log('TOKEN (cópialo al secreto HAPI_ORDENES_TOKEN de GitHub): ' + token);
}
