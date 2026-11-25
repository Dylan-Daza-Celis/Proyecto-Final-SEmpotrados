"""Contrasta informes de benchmark por SHA-256, sin seleccionar por velocidad sola."""
import argparse
import json
from pathlib import Path


def iou(a, b):
    x1,y1,x2,y2=a; u1,v1,u2,v2=b
    inter=max(0,min(x2,u2)-max(x1,u1))*max(0,min(y2,v2)-max(y1,v1))
    return inter/((x2-x1)*(y2-y1)+(u2-u1)*(v2-v1)-inter)


def correspondencias(referencia, alternativa, umbral=.5):
    candidatos=sorted(((iou(a['caja'],b['caja']), i,j) for i,a in enumerate(referencia)
        for j,b in enumerate(alternativa) if a['clase']==b['clase']), reverse=True)
    usados_a,usados_b,pares=set(),set(),[]
    for valor,i,j in candidatos:
        if valor>=umbral and i not in usados_a and j not in usados_b:
            usados_a.add(i); usados_b.add(j)
            pares.append(dict(referencia=i, alternativa=j, iou=valor,
                diferencia_confianza=alternativa[j]['confianza']-referencia[i]['confianza']))
    return dict(pares=pares, faltantes=[i for i in range(len(referencia)) if i not in usados_a],
                adicionales=[j for j in range(len(alternativa)) if j not in usados_b])


def comparar(a,b):
    for clave in ('imgsz','confianza','iou','clases','agnostic_nms'):
        if a['parametros'][clave]!=b['parametros'][clave]:
            raise ValueError('Parámetros de detección diferentes: '+clave)
    if a['pesos_sha256']!=b['pesos_sha256']:
        raise ValueError('Pesos diferentes')
    primeros={s['sha256']:s for s in a['muestras']}
    segundos={s['sha256']:s for s in b['muestras']}
    if set(primeros)!=set(segundos):
        raise ValueError('Se requieren exactamente las mismas fotografías')
    escenas=[]
    for huella,r in primeros.items():
        s=segundos[huella]
        if r['forma_entrada']!=s['forma_entrada']:
            raise ValueError('Formas efectivas distintas; comparación no equivalente')
        escenas.append(dict(sha256=huella, referencia=r['detecciones'], alternativa=s['detecciones'],
                            **correspondencias(r['detecciones'],s['detecciones'])))
    evaluacion_a=a.get('evaluacion'); evaluacion_b=b.get('evaluacion')
    if evaluacion_a and evaluacion_b:
        if evaluacion_a['calibracion_sha256']!=evaluacion_b['calibracion_sha256']:
            raise ValueError('Calibraciones distintas')
        real_a={s['sha256']:(s['n1_real'],s['n2_real']) for s in evaluacion_a['escenas']}
        real_b={s['sha256']:(s['n1_real'],s['n2_real']) for s in evaluacion_b['escenas']}
        if real_a!=real_b or set(real_a)!=set(primeros):
            raise ValueError('Verdad manual o escenas de evaluación diferentes')
    return dict(escenas=escenas, evaluacion_referencia=evaluacion_a, evaluacion_alternativa=evaluacion_b,
        tiempos_referencia=a['sostenido'], tiempos_alternativa=b['sostenido'],
        seleccion_definitiva='PENDIENTE: revisar diferencias individuales y exactitud/MAE en grupos finales independientes; no se selecciona automáticamente')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('referencia',type=Path); parser.add_argument('alternativa',type=Path)
    parser.add_argument('--salida',type=Path,required=True)
    args=parser.parse_args()
    informe=comparar(json.loads(args.referencia.read_text()),json.loads(args.alternativa.read_text()))
    args.salida.parent.mkdir(parents=True,exist_ok=True)
    args.salida.write_text(json.dumps(informe,indent=2),encoding='utf-8')
    print(informe['seleccion_definitiva'])


if __name__=='__main__': main()
