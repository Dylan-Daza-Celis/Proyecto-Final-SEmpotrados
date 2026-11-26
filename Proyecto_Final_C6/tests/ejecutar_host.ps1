param([Parameter(Mandatory=$true)][string]$Compilador, [switch]$EnMemoria)
$ErrorActionPreference='Stop'
$raizPrueba=Split-Path $PSScriptRoot -Parent
$salidaPrueba=Join-Path $PSScriptRoot 'salida'
New-Item -ItemType Directory -Force -Path $salidaPrueba | Out-Null
$basePrueba=@('-std=c99','-Wall','-Werror',('-I'+(Join-Path $raizPrueba 'main').Replace('\','/')))
$nucleoPrueba=@('controlador_semaforos.c','prioridad_vehicular.c','gestor_demanda.c') |
    ForEach-Object { (Join-Path $raizPrueba "main/$_").Replace('\','/') }
function Ejecutar-Prueba([string]$Nombre,[string[]]$Extras) {
    $fuentesPrueba=@($nucleoPrueba)+@($Extras | ForEach-Object { (Join-Path $raizPrueba "main/$_").Replace('\','/') })
    $testPrueba=(Join-Path $PSScriptRoot "$Nombre.c").Replace('\','/')
    if($EnMemoria) {
        & $Compilador @basePrueba @fuentesPrueba -run $testPrueba
    } else {
        $ejecutablePrueba=Join-Path $salidaPrueba "$Nombre.exe"
        & $Compilador @basePrueba @fuentesPrueba $testPrueba -o $ejecutablePrueba
        if($LASTEXITCODE -ne 0){throw "Fallo compilando $Nombre"}
        & $ejecutablePrueba
    }
    if($LASTEXITCODE -ne 0){throw "Fallo prueba $Nombre"}
}
Ejecutar-Prueba 'pruebas_controlador' @('semaforo_gpio.c')
Ejecutar-Prueba 'pruebas_prioridad' @()
Ejecutar-Prueba 'pruebas_udp' @('demanda_conectada.c','control_conectado.c')
Ejecutar-Prueba 'pruebas_gpio_conectado' @('demanda_conectada.c','control_conectado.c','aplicacion_conectada.c','semaforo_gpio.c')
