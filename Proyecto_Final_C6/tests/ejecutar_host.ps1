param([Parameter(Mandatory=$true)][string]$Compilador)
$ErrorActionPreference = 'Stop'
$raizPrueba = Split-Path $PSScriptRoot -Parent
$salidaPrueba = Join-Path $PSScriptRoot 'salida'
New-Item -ItemType Directory -Force -Path $salidaPrueba | Out-Null
$ejecutablePrueba = Join-Path $salidaPrueba 'pruebas.exe'
$argumentosPrueba = @('-std=c99','-Wall','-Werror',('-I' + (Join-Path $raizPrueba 'main')),
    (Join-Path $PSScriptRoot 'pruebas_controlador.c'),
    (Join-Path $raizPrueba 'main/controlador_semaforos.c'),
    (Join-Path $raizPrueba 'main/semaforo_gpio.c'), '-o', $ejecutablePrueba)
& $Compilador @argumentosPrueba
if ($LASTEXITCODE -ne 0) { throw 'Falló compilación de pruebas C' }
& $ejecutablePrueba
if ($LASTEXITCODE -ne 0) { throw 'Fallaron pruebas C' }
