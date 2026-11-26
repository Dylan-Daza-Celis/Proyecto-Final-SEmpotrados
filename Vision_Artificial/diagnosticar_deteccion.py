"""Diagnóstico local PyTorch FP32: versiones, parámetros y anotaciones separadas."""
import argparse
from dataclasses import asdict
import importlib.util
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess
import time

import cv2
import numpy as np

from benchmark_inferencia import resumen
from comparar_motores import correspondencias
from contador_vehiculos import contar_vehiculos,asignar_roi
from detector_vehiculos import CLASES_COCO, Deteccion, DetectorVehiculos
from evaluar import huella_archivo, leer_escenas, evaluar_escenas, calcular_metricas
from main import RAIZ, cargar_configuracion
from roi_manager import GestorROI

CONFIGURACIONES = {
    'A': dict(imgsz=960,confianza=.15,iou=.45), 'B': dict(imgsz=960,confianza=.10,iou=.45),
    'C': dict(imgsz=960,confianza=.15,iou=.60), 'D': dict(imgsz=1280,confianza=.15,iou=.45),
    'E': dict(imgsz=1280,confianza=.10,iou=.45)}


def comparar_registros(registros):
    comparaciones=[]
    for r in registros:
        for s in registros:
            if (r['sha256'],r['repeticion'])!=(s['sha256'],s['repeticion']): continue
            tipo=None
            if (r['revision']=='cb305f7' and s['revision']!='cb305f7' and
                r['configuracion']==s['configuracion'] and r['parametros']==s['parametros']): tipo='version'
            if (r['revision']==s['revision']=='actual' and r['configuracion']=='A' and
                s['configuracion'] in ('B','C','D','E') and
                r['parametros']['agnostic_nms']==s['parametros']['agnostic_nms']): tipo='parametros'
            if (r['revision']==s['revision'] and r['configuracion']==s['configuracion'] and
                not r['parametros']['agnostic_nms'] and s['parametros']['agnostic_nms']): tipo='nms'
            if tipo:
                comparaciones.append(dict(tipo=tipo,referencia=r['revision']+':'+r['configuracion'],
                    alternativa=s['revision']+':'+s['configuracion'],sha256=r['sha256'],
                    repeticion=r['repeticion'],variables_modificadas=[k for k in r['parametros'] if r['parametros'][k]!=s['parametros'][k]],
                    **correspondencias(r['detecciones'],s['detecciones'])))
    return comparaciones


def instrumentar(modelo, informacion):
    """Observar tensor real sin cambiar ni reemplazar el preprocesamiento original."""
    def inicio(predictor):
        if getattr(predictor,'_diagnostico_observado',False): return
        original = predictor.preprocess
        def observar(imagenes):
            tensor = original(imagenes)
            informacion['forma_tensor'] = list(tensor.shape)
            informacion['dtype'] = str(tensor.dtype)
            if str(tensor.dtype) != 'torch.float32': raise ValueError('Se exige FP32')
            return tensor
        predictor.preprocess = observar
        predictor._diagnostico_observado = True
    modelo.add_callback('on_predict_start',inicio)


def cargar_version(revision, salida):
    contenido = subprocess.check_output(['git','show',revision+':Vision_Artificial/detector_vehiculos.py'],cwd=RAIZ.parent)
    ruta=salida/('detector_'+revision+'.py'); ruta.write_bytes(contenido)
    spec=importlib.util.spec_from_file_location('detector_'+revision,ruta)
    modulo=importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name]=modulo; spec.loader.exec_module(modulo)
    return modulo


def dibujar(imagen, detecciones, regiones=None, valido=False):
    salida=regiones.dibujar(imagen) if regiones else imagen.copy()
    resolucion=(imagen.shape[1],imagen.shape[0])
    for d in detecciones:
        deteccion = Deteccion(tuple(d['caja']),d['clase'],d['nombre'],d['confianza'])
        x1,y1,x2,y2=map(round,deteccion.caja)
        centro=tuple(map(round,deteccion.centro))  # Redondear solo para dibujar.
        carril = asignar_roi(deteccion,regiones,resolucion) if regiones and valido else ''
        cv2.rectangle(salida,(x1,y1),(x2,y2),(30,220,220),2)
        cv2.circle(salida,centro,3,(0,0,255),-1)
        cv2.putText(salida,f"{d['nombre']} {d['confianza']:.3f} {carril}",(x1,max(15,y1-3)),
                    cv2.FONT_HERSHEY_SIMPLEX,.4,(20,220,220),1)
    if regiones and not valido:
        cv2.putText(salida,'ROI INVALIDAS: conteos no disponibles',(10,25),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,0,255),2)
    return salida


def hipotesis(operativas, exploratorias, umbral):
    notas=[]
    for d in exploratorias:
        from comparar_motores import iou
        if any(iou(d['caja'],o['caja'])>=.5 for o in operativas): continue
        if d['clase'] not in CLASES_COCO:
            causa='clase no autorizada; clasificacion incorrecta del vehiculo es solo hipotesis sin verdad manual'
        elif d['confianza'] < umbral:
            causa='prediccion exploratoria por debajo del umbral operativo; no demuestra que sea un vehiculo real'
        else:
            causa='posible supresion NMS o cambio de orden; hipotesis, no prueba causal'
        notas.append(dict(deteccion=d,hipotesis=causa))
    return notas


def main(argumentos=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=RAIZ/'config.json')
    parser.add_argument('--archivos',type=Path,nargs='+')
    parser.add_argument('--escenas',type=Path)
    parser.add_argument('--uso',choices=['desarrollo','final'],default='desarrollo')
    parser.add_argument('--salida',type=Path,required=True,help='Directorio nuevo para no sobrescribir resultados')
    parser.add_argument('--barrido',action='store_true',help='A..E y config local; ambas opciones NMS por separado')
    parser.add_argument('--explorar',action='store_true',help='Todas las clases, conf .03; solo diagnóstico')
    parser.add_argument('--repeticiones',type=int,default=1)
    args=parser.parse_args(argumentos)
    if args.uso=='final' and (args.barrido or args.explorar):
        parser.error('Escenas finales reservadas: no se permite barrido ni exploracion para seleccionar parametros.')
    if args.repeticiones<1: parser.error('repeticiones debe ser positivo')
    config=cargar_configuracion(args.config,requiere_url=False)
    parametros=config['detector']
    if parametros['backend']!='pytorch' or parametros['dispositivo']!='cpu':
        parser.error('Usar configuración explícita PyTorch CPU; no se modifica config.json')
    escenas=[s for s in leer_escenas(args.escenas) if s['uso']==args.uso] if args.escenas else []
    fotos=[s['archivo'] for s in escenas] if args.escenas else args.archivos
    if not fotos: parser.error('Indicar JPEG SVGA con --archivos o --escenas')
    imagenes=[cv2.imdecode(np.frombuffer(p.read_bytes(),np.uint8),cv2.IMREAD_COLOR) for p in fotos]
    if any(i is None or i.shape[:2]!=(600,800) for i in imagenes): parser.error('Todas las fotos deben ser SVGA reales')
    args.salida.mkdir(parents=True,exist_ok=False)
    regiones=GestorROI.cargar(config['ruta_roi']) if config['ruta_roi'].exists() else GestorROI()
    motivo=regiones.estado_calibracion((800,600))
    calidad={}
    metadatos=config['directorio_almacenamiento']/'metadatos.jsonl'
    if metadatos.exists():
        for linea in metadatos.read_text(encoding='utf-8').splitlines():
            m=json.loads(linea); calidad[m['sha256']]=m.get('calidad_reportada_status')
    variantes=[('local',{})] + list(CONFIGURACIONES.items()) if args.barrido else [('local',{})]
    registros=[]
    for revision in ('cb305f7','75f1a0e','actual','convencional'):
        modulo=cargar_version(revision,args.salida) if revision in ('cb305f7','75f1a0e') else None
        p=parametros.copy()
        inicio=time.perf_counter()
        if revision=='convencional':
            from ultralytics import YOLO
            modelo=YOLO(str(p['pesos'])); detector=None
        else:
            clase=modulo.DetectorVehiculos if modulo else DetectorVehiculos
            aceptados=modulo.PARAMETROS_INICIALES if modulo else p
            detector=clase({k:v for k,v in p.items() if k in aceptados}); modelo=detector.modelo
        carga=time.perf_counter()-inicio
        informacion={}; instrumentar(modelo,informacion)
        variantes_revision=variantes if revision=='actual' else [('local',{})]
        for nombre,ajuste in variantes_revision:
            for agnostica in (False,True) if args.barrido else (p['agnostic_nms'],):
                elegidos=p|ajuste|{'agnostic_nms':agnostica}
                def detectar(imagen):
                    inicio=time.perf_counter()
                    if detector:
                        detector.parametros.update({k:v for k,v in elegidos.items() if k in detector.parametros})
                        cajas,_=detector.detectar(imagen)
                        return [asdict(d)|{'centro':d.centro} for d in cajas],time.perf_counter()-inicio
                    resultados=modelo.predict(imagen,imgsz=elegidos['imgsz'],conf=elegidos['confianza'],
                        iou=elegidos['iou'],classes=elegidos['clases'],agnostic_nms=agnostica,
                        device='cpu',verbose=False,save=False,stream=False)
                    return [dict(caja=list(map(float,f[:4])),clase=int(f[5]),nombre=modelo.names[int(f[5])],
                        confianza=float(f[4]),centro=[float((f[0]+f[2])/2),float((f[1]+f[3])/2)])
                        for f in resultados[0].boxes.data.cpu().numpy()],time.perf_counter()-inicio
                for _ in range(3): detectar(np.zeros((600,800,3),np.uint8))
                medidas=[]
                for repeticion in range(args.repeticiones):
                    for foto,imagen in zip(fotos,imagenes):
                        huella=huella_archivo(foto)
                        detecciones,segundos=detectar(imagen); medidas.append(segundos)
                        conteo=None
                        if not motivo:
                            convertidas=[Deteccion(tuple(d['caja']),d['clase'],d['nombre'],d['confianza']) for d in detecciones]
                            conteo=contar_vehiculos(convertidas,regiones,(800,600)).a_dict()
                            for d,convertida in zip(detecciones,convertidas):
                                d['roi_asignada']=asignar_roi(convertida,regiones,(800,600))
                        registro=dict(revision=revision,configuracion=nombre,repeticion=repeticion,
                            sha256=huella,calidad_reportada=calidad.get(huella),resolucion=[800,600],
                            parametros={k:str(v) if isinstance(v,Path) else v for k,v in elegidos.items()},
                            tensor=dict(informacion),inferencia_s=segundos,carga_s=carga,
                            detecciones=detecciones,conteo=conteo,motivo_invalidez=motivo,
                            valido_para_control=False,tipo='diagnostico_local_historico',
                            letterbox='rect=True por defecto Ultralytics; explicito en predictor optimizado; stride32 auto',
                            versiones=dict(python=platform.python_version(),torch=version('torch'),ultralytics=version('ultralytics')))
                        registro['causas']={
                            'no_detectado':'Requiere senalar vehiculos reales en el original; no demostrable sin verdad manual',
                            'clase_incorrecta':'Hipotesis: revisar exploracion de todas las clases',
                            'umbral':'Comparar confianzas exploratorias con el umbral; no prueba objeto real',
                            'nms':'Hipotesis: comparar IoU y agnostic_nms por separado',
                            'fuera_roi':conteo['n_fuera'] if conteo else None,
                            'antiguo_o_no_disponible':'JPEG local historico; no mide edad ni desconexion en vivo',
                            'roi_invalida':motivo}
                        import torch
                        registro['hilos_efectivos']=torch.get_num_threads()
                        base=args.salida/f'{revision}_{nombre}_{int(agnostica)}_{huella[:12]}_{repeticion}'
                        base.with_suffix('.jpg').write_bytes(foto.read_bytes())
                        cv2.imwrite(str(base)+'_detecciones.png',dibujar(imagen,detecciones))
                        cv2.imwrite(str(base)+'_roi.png',dibujar(imagen,detecciones,regiones,not bool(motivo)))
                        if args.explorar:
                            r=modelo.predict(imagen,imgsz=elegidos['imgsz'],conf=.03,iou=elegidos['iou'],
                                classes=None,agnostic_nms=agnostica,device='cpu',verbose=False,save=False)[0]
                            exploratorias=[dict(caja=list(map(float,f[:4])),clase=int(f[5]),nombre=modelo.names[int(f[5])],
                                confianza=float(f[4])) for f in r.boxes.data.cpu().numpy()]
                            registro['exploratorias']=exploratorias
                            registro['hipotesis']=hipotesis(detecciones,exploratorias,elegidos['confianza'])
                            cv2.imwrite(str(base)+'_exploracion.png',dibujar(imagen,exploratorias))
                        registros.append(registro)
                parciales=[r for r in registros if r['revision']==revision and r['configuracion']==nombre and r['parametros']['agnostic_nms']==agnostica]
                metricas=None
                if escenas and not motivo:
                    verdad={huella_archivo(s['archivo']):s for s in escenas}
                    datos=[dict(valido=True,n1=r['conteo']['n1'],n2=r['conteo']['n2'],
                        n1_real=verdad[r['sha256']]['n1_real'],n2_real=verdad[r['sha256']]['n2_real'],
                        inferencia_s=r['inferencia_s'],latencia_s=r['inferencia_s']) for r in parciales]
                    metricas=calcular_metricas(datos,sum(medidas))
                resumen_parcial=dict(revision=revision,configuracion=nombre,agnostic_nms=agnostica,
                    tiempos=resumen(medidas),metricas=metricas)
                print(json.dumps(resumen_parcial),flush=True)
                with (args.salida/'resumenes.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(resumen_parcial)+'\n')
                (args.salida/'informe.json').write_text(json.dumps(dict(pesos_sha256=huella_archivo(p['pesos']),
                    calibracion_sha256=huella_archivo(config['ruta_roi']) if config['ruta_roi'].exists() else None,
                    registros=registros,limitacion='Sin anotaciones de cajas no se calculan FP/FN. No detectado/clase incorrecta/NMS son hipotesis; antiguedad en vivo no se reproduce offline.'),indent=2),encoding='utf-8')
        del detector,modelo
        import gc
        gc.collect()
    comparaciones=comparar_registros(registros)
    (args.salida/'comparaciones.json').write_text(json.dumps(comparaciones,indent=2),encoding='utf-8')


if __name__=='__main__': main()
