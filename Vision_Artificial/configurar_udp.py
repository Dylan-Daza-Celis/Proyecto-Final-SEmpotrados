"""Genera solo archivos locales nuevos, sin imprimir la clave ni sobrescribirlos."""
import json
from pathlib import Path
import secrets
import uuid

def main():
    raiz=Path(__file__).resolve().parent
    configuracion=raiz/'udp.local.json';clave=raiz/'clave_udp.hex'
    if configuracion.exists() or clave.exists():raise ValueError('Ya existe configuracion o clave; conservarla')
    with clave.open('x',encoding='ascii') as f:f.write(secrets.token_hex(32)+'\n')
    with configuracion.open('x',encoding='utf-8') as f:
        json.dump(dict(emisor_id=uuid.uuid4().hex,archivo_clave=clave.name,direccion='0.0.0.0',puerto=5005,max_edad_ms=12000),f,indent=2)
    print('Configuracion y clave locales creadas. No compartir ni versionar la clave.')

if __name__=='__main__':main()
