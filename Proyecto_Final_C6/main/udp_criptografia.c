#include "protocolo_udp.h"
#include "psa/crypto.h"
static psa_status_t importar(const uint8_t clave[32],psa_key_id_t *id)
{
    psa_status_t estado=psa_crypto_init();if(estado!=PSA_SUCCESS)return estado;
    psa_key_attributes_t atributos=PSA_KEY_ATTRIBUTES_INIT;
    psa_set_key_type(&atributos,PSA_KEY_TYPE_HMAC);
    psa_set_key_bits(&atributos,256);
    psa_set_key_usage_flags(&atributos,PSA_KEY_USAGE_SIGN_MESSAGE|PSA_KEY_USAGE_VERIFY_MESSAGE);
    psa_set_key_algorithm(&atributos,PSA_ALG_HMAC(PSA_ALG_SHA_256));
    estado=psa_import_key(&atributos,clave,32,id);psa_reset_key_attributes(&atributos);return estado;
}
bool udp_firmar_psa(const uint8_t clave[32],const uint8_t *datos,size_t n,uint8_t tag[32])
{
    psa_key_id_t id=0;size_t escritos=0;if(importar(clave,&id)!=PSA_SUCCESS)return false;
    psa_status_t estado=psa_mac_compute(id,PSA_ALG_HMAC(PSA_ALG_SHA_256),datos,n,tag,32,&escritos);
    psa_destroy_key(id);return estado==PSA_SUCCESS && escritos==32;
}
bool udp_verificar_psa(const uint8_t clave[32],const uint8_t *datos,size_t n,const uint8_t tag[32])
{
    psa_key_id_t id=0;if(importar(clave,&id)!=PSA_SUCCESS)return false;
    psa_status_t estado=psa_mac_verify(id,PSA_ALG_HMAC(PSA_ALG_SHA_256),datos,n,tag,32);
    psa_destroy_key(id);return estado==PSA_SUCCESS;
}
