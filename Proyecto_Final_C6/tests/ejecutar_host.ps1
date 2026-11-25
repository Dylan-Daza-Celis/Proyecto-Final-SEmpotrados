param([Parameter(Mandatory=$true)][string]$Compilador)
$ErrorActionPreference = 'Stop'
$raizPrueba = Split-Path $PSScriptRoot -Parent
$salidaPrueba = Join-Path $PSScriptRoot 'salida'
New-Item -ItemType Directory -Force -Path $salidaPrueba | Out-Null
$ejecutablePrueba = Join-Path $salidaPrueba 'pruebas.exe'
$argumentosPrueba = @('-std=c99','-Wall','-Werror',('-I' + (Join-Path $raizPrueba 'main')),
    (Join-Path $PSScriptRoot 'pruebas_controlador.c'),
    (Join-Path $raizPrueba 'main/controlador_semaforos.c'),
    (Join-Path $raizPrueba 'main/semaforo_gpio.c'),
    (Join-Path $raizPrueba 'main/prioridad_vehicular.c'),
    (Join-Path $raizPrueba 'main/gestor_demanda.c'), '-o', $ejecutablePrueba)
& $Compilador @argumentosPrueba
if ($LASTEXITCODE -ne 0) { throw 'Falló compilación de pruebas C' }
& $ejecutablePrueba
if ($LASTEXITCODE -ne 0) { throw 'Fallaron pruebas C' }
$argumentosPrioridad = @('-std=c99','-Wall','-Werror',('-I' + (Join-Path $raizPrueba 'main')),
    (Join-Path $PSScriptRoot 'pruebas_prioridad.c'),
    (Join-Path $raizPrueba 'main/controlador_semaforos.c'),
    (Join-Path $raizPrueba 'main/prioridad_vehicular.c'),
    (Join-Path $raizPrueba 'main/gestor_demanda.c'), '-o', (Join-Path $salidaPrueba 'prioridad.exe'))
& $Compilador @argumentosPrioridad
if ($LASTEXITCODE -ne 0) { throw 'Falló compilación de prioridad' }
& (Join-Path $salidaPrueba 'prioridad.exe')
if ($LASTEXITCODE -ne 0) { throw 'Fallaron pruebas de prioridad' }
