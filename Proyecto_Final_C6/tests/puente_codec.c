/* Puente anfitrion: HMAC se inyecta desde hmac de Python, nunca se implementa aqui. */
#include "protocolo_udp.h"
#include <string.h>
#ifdef _WIN32
#define EXPORTAR __declspec(dllexport)
#else
#define EXPORTAR
#endif
EXPORTAR int codec_ida_vuelta(const uint8_t *entrada,size_t n,const uint8_t *clave,
    uint8_t *salida,udp_firmar_fn firmar,udp_verificar_fn verificar)
{
    mensaje_udp_t m;
    if(!protocolo_decodificar(entrada,n,clave,&m,verificar))return 0;
    return protocolo_codificar(&m,clave,salida,firmar);
}
