# Línea base de rendimiento (RNF01)

Medición de los tiempos de la línea de comandos el 2026-10-30. Sirve de referencia para comparar futuras versiones; el proyecto no
fijó umbrales de aceptación, así que estas cifras **establecen** la línea base y no demuestran el cumplimiento de un tiempo previo.

## Condiciones

- Equipo: Windows 10, procesador AMD de 4 núcleos y 8 hilos, 13,9 GiB de RAM (unos 8 GiB libres al medir), disco de salida distinto del del sistema.
- Comando: `python -m mri_dataset_tool.presentation.cli --quiet ...`, configuración `config/stage3_bids.yaml`, una `MRI_ANON_KEY` de prueba.
- Tiempo: de reloj, desde que arranca el proceso hasta que termina (incluye unos 2 s de arranque). Memoria: pico del proceso y sus hijos.
- Todos los comandos terminaron con código 0, salvo el caso indicado.

## Muestras públicas (`data/samples/`, 88 MB), mediana de 3 repeticiones

| Caso | Entrada | Tiempo | Pico de memoria | Salida |
|---|---|---|---|---|
| `inspect --format bids` | 6 sujetos, imágenes pequeñas | 2,3 s | 89 MB | — |
| `inspect --format nifti` | 6 volúmenes 192×256×256 `int16` (66 MB) | 5,0 s | 372 MB | — |
| `inspect --format dicom` | 154 cortes | 2,0 s | 87 MB | — |
| `convert dicom-to-nifti` | 154 cortes | 2,8 s | 205 MB | — |
| `dataset build --format bids` | 6 sujetos | 2,7 s | 93 MB | 8 MB |
| `dataset build --format nifti` | 6 volúmenes | 18,9 s | 357 MB | 189 MB |
| `dataset build --format dicom` | 154 cortes | 6,5 s | 356 MB | 53 MB |

Los rangos entre repeticiones fueron de menos de 0,2 s, salvo el primer `inspect` BIDS (1,9–2,4 s).

## Datos reales grandes (una sola pasada)

| Caso | Entrada | Tiempo | Pico de memoria | Resultado |
|---|---|---|---|---|
| `inspect --format dicom` | 43.719 archivos DICOM (perfusión DSC, 343 series) | 359 s (6,0 min) | 286 MB | código 0 |
| `convert dicom-to-nifti` | los mismos | 280 s (4,7 min) | 456 MB | código 0, 6,0 GB de salida |
| `dataset build --format dicom` | los mismos | 138 s hasta abortar | 288 MB | código 2: `No input series could be mapped to a BIDS suffix.` |
| `inspect --format bids` | BIDS completo ds005299 (1 sujeto, varias sesiones con difusión 4D, 2,1 GB de imágenes) | 66 s | 579 MB | código 0 |
| `dataset build --format bids` | el mismo | 376 s (6,3 min) | 1,9 GB | código 0, 4,9 GB de salida |

## Lectura de los resultados

- El arranque cuesta unos 2 s; con datos pequeños casi todo el tiempo es eso.
- El pipeline completo (validar, anonimizar, reorientar, remuestrear, normalizar y escribir `.nii.gz`) cuesta unos 3 s por volumen de 192×256×256. En el BIDS grande, la difusión 4D remuestreada a 2 mm domina el tiempo y la memoria.
- La memoria se mantiene acotada por el procesamiento de un estudio a la vez (RNF02): el pico fue de 1,9 GB incluso con la difusión 4D, y de 456 MB al convertir 43.719 archivos DICOM.
- El `dataset build --format dicom` sobre el árbol de perfusión aborta por diseño: ninguna serie coincide con la lista cerrada de sufijos (la perfusión está excluida). Lo que tardó fue la lectura de cabeceras y la planificación, antes de crear nada. Ese caso no tiene tiempo de construcción.

## Límites de la medición

- Un solo equipo; una sola pasada en los datos grandes (sin repeticiones).
- Solo la línea de comandos: no se midieron la GUI ni el ejecutable.
- La velocidad del disco, el estado de la caché y la RAM libre cambian los tiempos; los de los datos grandes son orientativos.
- No hay umbrales de aceptación: para decidir si un tiempo es «aceptable» hay que fijarlos antes.
