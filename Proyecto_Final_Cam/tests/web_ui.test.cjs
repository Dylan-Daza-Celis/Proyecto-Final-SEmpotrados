// Pruebas sin navegador ni dependencias: ejecutan el JavaScript real del HTML.
// Comprueban secuenciación de peticiones, parada, errores y ciclo de vida de blobs.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');

const html = readFileSync(join(__dirname, '../main/web/index.html'), 'utf8');
const codigo = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const resolver = () => new Promise(resolve => setImmediate(resolve));

async function crearEntorno() {
  const elementos = new Map();
  const temporizadores = new Map();
  const llamadas = [];
  const liberados = [];
  let numero = 0, blobs = 0, errorDecodificacion = false, errorHttp = false;
  let retenerCaptura = null;
  let terminarCaptura;
  const estado = {camera_ready:true,sensor:'OV3660',width:320,height:240,quality:12,
    captures:1,capture_errors:0,internal_free:200000,psram_free:4000000};
  function elemento(id) {
    if (!elementos.has(id)) elementos.set(id, {value: id === 'resolucion' ? 'QVGA' : '12',
      textContent:'', disabled:false, eventos:{}, addEventListener(tipo, fn) { this.eventos[tipo] = fn; }});
    return elementos.get(id);
  }
  const contexto = vm.createContext({
    document:{getElementById:elemento,createElement:() => ({click(){}})},
    window:{addEventListener(){}},
    AbortController,Date,console,
    setTimeout(fn, demora) { const id = ++numero; temporizadores.set(id,{fn,demora}); return id; },
    clearTimeout(id) { temporizadores.delete(id); },
    setInterval() {},
    URL:{createObjectURL:() => `blob:${++blobs}`,revokeObjectURL:url => liberados.push(url)},
    Image:class { naturalWidth=320; naturalHeight=240; async decode(){ if(errorDecodificacion) throw Error('JPEG inválido'); } },
    async fetch(ruta, opciones) {
      llamadas.push({ruta,opciones});
      const esCaptura = ruta.startsWith('/capture');
      if (esCaptura && retenerCaptura) await retenerCaptura;
      return {ok:!errorHttp,status:errorHttp ? 503 : 200,
        text:async () => 'Cámara ocupada',json:async () => estado,
        blob:async () => ({type:'image/jpeg',size:10000}),headers:{get:() => '5'}};
    },
  });
  vm.runInContext(codigo, contexto);
  await resolver();
  return {
    elemento,llamadas,temporizadores,liberados,
    click(id) { elemento(id).eventos.click(); },
    retener() { retenerCaptura = new Promise(resolve => { terminarCaptura = resolve; }); },
    soltar() { terminarCaptura(); retenerCaptura = null; },
    errorJPEG() { errorDecodificacion = true; },
    errorServidor() { errorHttp = true; },
  };
}

test('Una captura lenta no acumula peticiones y detener impide otra captura', async () => {
  const entorno = await crearEntorno();
  entorno.retener();
  entorno.click('iniciar');
  entorno.click('iniciar'); // Incluso si se despacha un click estando deshabilitado.
  await resolver();
  assert.equal(entorno.llamadas.filter(x => x.ruta.startsWith('/capture')).length, 1);
  assert.equal([...entorno.temporizadores.values()].filter(x => x.demora === 1000).length, 0);
  entorno.click('detener');
  entorno.soltar();
  await resolver();
  assert.equal([...entorno.temporizadores.values()].filter(x => x.demora === 1000).length, 0);
  assert.equal(entorno.elemento('descargar').disabled, false);
});

test('La vista continua programa la siguiente solicitud solo después de terminar', async () => {
  const entorno = await crearEntorno();
  entorno.click('iniciar');
  await resolver();
  assert.equal([...entorno.temporizadores.values()].filter(x => x.demora === 1000).length, 1);
  entorno.click('detener');
  assert.equal([...entorno.temporizadores.values()].filter(x => x.demora === 1000).length, 0);
});

test('La imagen anterior se libera y una imagen no decodificable no reemplaza la última válida', async () => {
  const entorno = await crearEntorno();
  entorno.click('capturar'); await resolver();
  entorno.click('capturar'); await resolver();
  assert.equal(entorno.elemento('foto').src, 'blob:2');
  assert.deepEqual(entorno.liberados, ['blob:1']);
  entorno.errorJPEG();
  entorno.click('capturar'); await resolver();
  assert.equal(entorno.elemento('foto').src, 'blob:2');
  assert.deepEqual(entorno.liberados, ['blob:1','blob:3']);
  assert.match(entorno.elemento('error').textContent, /decodificar/);
});

test('Un error HTTP detiene la vista y muestra el motivo al usuario', async () => {
  const entorno = await crearEntorno();
  entorno.errorServidor();
  entorno.click('iniciar'); await resolver();
  assert.match(entorno.elemento('error').textContent, /HTTP 503/);
  assert.equal(entorno.elemento('detener').disabled, true);
  assert.equal([...entorno.temporizadores.values()].filter(x => x.demora === 1000).length, 0);
});

test('Los controles envían un cuerpo validado y no aceptan calidad fuera del rango', async () => {
  const entorno = await crearEntorno();
  entorno.elemento('calidad').value = '9';
  entorno.elemento('ajustes').eventos.submit({preventDefault(){}});
  await resolver();
  assert.equal(entorno.llamadas.filter(x => x.ruta === '/control').length, 0);
  entorno.elemento('calidad').value = '20';
  entorno.elemento('resolucion').value = 'SVGA';
  entorno.elemento('ajustes').eventos.submit({preventDefault(){}});
  await resolver();
  const peticion = entorno.llamadas.find(x => x.ruta === '/control');
  assert.equal(peticion.opciones.method, 'POST');
  assert.equal(peticion.opciones.body, 'resolution=SVGA&quality=20');
});
