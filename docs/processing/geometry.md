# Geometría: base común y pasos de geometría

Algoritmos en `infrastructure/processing/` (solo `numpy`, `nibabel`, `scipy`; no importan
`application`) y pasos registrados en `application/pipeline/steps/`. Todo el proyecto usa
**RAS+** (convención NIfTI); para affines DICOM (LPS) están `lps_to_ras`/`ras_to_lps` en
`infrastructure/dicom/volume_builder.py`.

## Parámetros por defecto

| Paso | Parámetro | Defecto | Valores admitidos | Error al construir (mensaje fijo) |
|---|---|---|---|---|
| `reorient` | `target` | `"RAS"` | 3 códigos en mayúsculas, uno por eje (`L/R`, `P/A`, `I/S`) | `Invalid target orientation.` |
| `reorient` | `modalities` | `None` (todas) | lista de `str` | `Modalities must be a list of strings.` |
| `resample` | `spacing` | `[1.0, 1.0, 1.0]` (mm) | 3 números finitos positivos (no `bool`) | `Spacing must be three finite positive numbers.` |
| `resample` | `interpolation` | `"linear"` | `"nearest"`, `"linear"`, `"cubic"` | `Unknown interpolation.` |
| `resample` | `modalities` | `None` (todas) | lista de `str` | `Modalities must be a list of strings.` |
| `resample` | `max_output_voxels` | `4294967296` (`2**32`) | entero positivo (no `bool` ni `float`) | `Max output voxels must be a positive integer.` |
| `resample` | `allow_insufficient_memory` | `false` | `true`/`false` (solo `bool`) | `Allow insufficient memory must be a boolean.` |

Errores al aplicar (el runner marca el estudio `failed` y el lote sigue): los de `validate_geometry`,
`Unsupported volume dimensionality.` (ni 3D ni 4D) y, en `resample`,
`Resampled volume would be too large.` y `Insufficient available memory for the resampled volume.`.

## Qué conserva cada paso

| Propiedad | `reorient` | `resample` |
|---|---|---|
| Shape | Permutada con los ejes; eje temporal intacto | `ceil(shape * voxel / spacing)`; eje temporal intacto |
| Affine | Nuevo; mismo punto del mundo por voxel | Nuevo, alineado a RAS (`diag(spacing)`), centrado en el FOV de entrada |
| Orientación | `target` (la más cercana si es oblicua) | `RAS` |
| Spacing | Conservado (permutado) | `spacing` |
| dtype | El de entrada (proxy: ver limitaciones) | `float32` |
| Unidades | mm; intensidades sin cambios | mm; intensidades interpoladas, sin reescalar |

## Base común (`geometry.py`)

| Función | Qué hace |
|---|---|
| `replace_volume(series, volume, affine)` | Serie nueva con `volume` y la geometría canónica recalculada: `shape` (tupla de `int`), `voxel_size` (norma de las columnas 3×3 del affine; solo espacial en 4D), `affine` (copia `float`) y `orientation` (`nib.aff2axcodes`). El resto de `metadata` se copia en profundidad (`bids`, `sidecar`, `provenance` no se comparten con la entrada); `files` se copia. **Único punto** del procesamiento que escribe esos cuatro campos. |
| `validate_geometry(series)` | `ValueError` de mensaje fijo, sin causa ni valores, si falta `volume` o `affine`, si el affine no es 4×4 numérico, finito, con última fila `[0, 0, 0, 1]` e invertible, o si `metadata["shape"]` no coincide con `volume.shape` (también si no es iterable). Solo lee `volume.shape`: no materializa un volumen perezoso. |
| `check_modalities(modalities)` | `None` o lista/tupla de `str`; si no, `ValueError("Modalities must be a list of strings.")`. Los pasos lo llaman al construirse. |
| `apply_to_series(study, transform, modalities=None)` | Devuelve `(estudio_nuevo, outputs)`. Aplica `transform(series) -> (serie, valores)` a las series con `volume` y, si hay filtro, `modality` en `modalities` (`modality=None` queda fuera; `[]` no selecciona ninguna). Las demás series se devuelven como el mismo objeto, sin mutar. `outputs = {"series": [{"index": i, **valores}]}`, con `i` la posición en `study.series`, solo para las transformadas (convención de `StepRecord.outputs`). |

## Paso `reorient` (RF07)

`params`: `target` (por defecto `"RAS"`; tres códigos en mayúsculas, uno por eje del mundo:
`L/R`, `P/A`, `I/S`) y `modalities` (por defecto todas). Un `target` inválido lanza
`ValueError("Invalid target orientation.")` al construir el paso.

Algoritmo (`reorient.py`): `io_orientation` → `ornt_transform` hacia `axcodes2ornt(target)` →
`apply_orientation`; affine nuevo = `affine @ inv_ornt_aff(transform, shape)`. **Solo permuta y
voltea ejes; no interpola.**

| Propiedad | Qué pasa |
|---|---|
| Valores | El multiconjunto de valores no cambia (sin interpolación). |
| Affine | Cambia de forma que el punto del mundo de cada voxel (`affine @ ijk`) es el mismo. |
| Orientación | Pasa a `target`. Ya en destino → mismo volumen y affine; aplicarlo dos veces = una. |
| Spacing | Se conserva, permutado junto con los ejes. |
| Shape | Se permuta con los ejes espaciales; en 4D el eje temporal no se toca. |
| dtype | Se conserva. Con un volumen perezoso es el que da `load_array(volume)`: el de disco, o `float64` si la cabecera escala intensidades (`scl_slope`/`scl_inter`). |
| Unidades | Sin cambios. |

- **Affine oblicuo:** se alcanza la orientación *más cercana*; la oblicuidad residual queda en el
  affine. Solo `resample` la elimina (interpolando).
- **Memoria:** 3D, un volumen de entrada y uno de salida; 4D, volumen a volumen con
  `iter_volumes_3d` (pico ≈ salida + un volumen 3D de entrada).
- **`outputs`:** `{"series": [{"index": i, "source": "LPS", "target": "RAS"}]}` (códigos de
  orientación calculados del affine de entrada y de salida).
- Entrada 2D o 5D: `ValueError("Unsupported volume dimensionality.")`. Geometría inválida:
  los errores de `validate_geometry`; el runner marca el estudio como `failed` y el lote sigue.

## Paso `resample` (RF08)

`params`: `spacing` (por defecto `[1.0, 1.0, 1.0]` mm; tres números finitos positivos, se guardan
como `float`), `interpolation` (`"linear"` por defecto, `"nearest"`, `"cubic"`) y `modalities`.
Parámetros inválidos lanzan `ValueError` de mensaje fijo al construir el paso
(`"Spacing must be three finite positive numbers."`, `"Unknown interpolation."`).

Algoritmo (`resample.py`), decisiones de diseño:

- **Malla de salida alineada con los ejes RAS:** `affine` de salida = `diag(spacing)` con origen
  propio; la oblicuidad desaparece y `orientation` pasa a `RAS`.
- **FOV físico conservado:** cada eje del mundo toma la extensión física (`shape * voxel`) del eje
  de entrada más cercano (`io_orientation`): `shape_nueva = ceil(shape * voxel_vieja / spacing)`,
  con una tolerancia de `1e-6` para que un error de redondeo no sume un voxel.
- **Convención de centro de voxel:** los centros están en los índices enteros (convención NIfTI);
  el FOV de un eje va de `-0.5` a `shape - 0.5` voxels. La malla nueva se centra en el centro del
  FOV de entrada (`affine @ (shape - 1) / 2`), así que con `spacing` igual al actual y entrada RAS
  la salida coincide con la entrada.
- **Interpolación:** `scipy.ndimage.affine_transform` (`nearest` = orden 0, `linear` = 1,
  `cubic` = 3), con la matriz `inv(affine) @ affine_nuevo` (índice de salida → índice de entrada).
- **Bordes:** la entrada se rellena con 1 voxel de su borde (`np.pad(mode="edge")`), así que la
  media celda exterior del FOV toma el valor del borde; lo que queda fuera vale `0`.
- **Antialiasing:** al reducir resolución en un eje (factor `spacing / voxel > 1`), se suaviza antes
  con un gaussiano de `sigma = (factor - 1) / 2` voxels de entrada (`mode="nearest"`). No se aplica
  con `nearest`, para conservar el conjunto de valores.
- **Límite de tamaño:** si la salida supera `max_output_voxels` voxels (contando el eje temporal;
  por defecto `MAX_OUTPUT_VOXELS = 2**32`, 16 GiB en `float32`), lanza
  `ValueError("Resampled volume would be too large.")` antes de reservar memoria. Es una red de
  seguridad contra un `spacing` diminuto, no un control de la RAM disponible: se sube o baja desde el
  YAML (`params: {max_output_voxels: ...}`). Antes valía `2**28` y rechazaba una difusión real
  (144×144×78×140 a 1,8 mm → 260×260×141×140 ≈ 1.330 millones de voxels a 1 mm). Los manifiestos
  anteriores, sin este parámetro, se reconstruyen con el defecto nuevo (la versión del paso sigue en `"1"`).
- **Comprobación de RAM** (`infrastructure/processing/memory.py`, `check_available_memory`): justo
  antes de reservar la salida compara los bytes necesarios
  (`4 × (salida + un frame de salida + 3 frames de entrada)`, un poco por encima del pico medido) con
  `psutil.virtual_memory().available`. Si no caben, lanza
  `ValueError("Insufficient available memory for the resampled volume.")` (el runner marca el estudio
  `failed` y el lote sigue), salvo que el usuario dé su consentimiento explícito con
  `allow_insufficient_memory: true`. Con consentimiento continúa y registra un WARNING sin cifras.
  Si `psutil` falla, la comprobación no bloquea (WARNING con el tipo de error) y la red queda en `MemoryError`.
  Los mensajes y logs nunca incluyen cifras de memoria. El parámetro queda en `params` y en el manifiesto.
  Los manifiestos sin él se reconstruyen con `false`.

| Propiedad | Qué pasa |
|---|---|
| Valores | Interpolados (`linear`/`cubic`); con `nearest` solo valores de entrada o `0` fuera del FOV. Una rampa lineal se reproduce en el interior. |
| Affine | Nuevo, alineado a RAS; el punto del mundo de cada estructura se conserva (centro de masa dentro de medio voxel). |
| Orientación | `RAS`. |
| Spacing | `voxel_size` = `spacing`. |
| Shape | `ceil(shape * voxel / spacing)` por eje; en 4D el eje temporal no se toca. |
| dtype | `float32`. |
| Unidades | mm (las del affine); intensidades sin reescalar. |

- **Affine oblicuo:** la caja de salida tiene la extensión de los ejes más cercanos (fórmula de
  la malla de salida), no la caja envolvente del volumen rotado. Las esquinas del FOV rotado que caen fuera de
  esa caja se pierden, y las zonas de la caja sin datos de entrada valen `0`.
- **`cubic`:** puede producir sobreoscilación (valores fuera del rango de entrada) cerca de bordes
  marcados.
- **Memoria:** 4D volumen a volumen con `iter_volumes_3d` en `float32`, pero la salida 4D se reserva
  entera en `float32` desde el principio. El pico es la salida completa más un volumen 3D de entrada
  y sus copias de trabajo (suavizado y relleno), que se liberan antes de leer el siguiente. Medido
  (QA1-07, entrada perezosa `int16` 144×144×78×T a 1,8 mm → 1 mm, `tracemalloc` y working set
  coinciden): pico = salida + ≈ 46 MiB constantes (T=5: 228 MiB; T=10: 410 MiB; T=20: 773 MiB),
  ≈ 1,6 s por volumen. Extrapolado a T=140: ≈ 5,0 GiB y ≈ 4 min. Pasos posteriores que crean otro
  volumen (p. ej. `normalize`) suman su propia salida mientras la anterior sigue viva.
- **`outputs`:** `{"series": [{"index": i, "shape": [...], "spacing": [...]}]}` (`int`/`float`
  nativos; `spacing` sale del affine resultante).
- **Spacing por modalidad** (`config/stage3_bids.yaml`): dos pasos `resample` con `modalities`
  disjuntas, anatómicas (`T1w`, `T2w`, `magnitude1`, `magnitude2`, `phasediff`) a 1 mm y `dwi` a 2 mm.
  Una difusión 144×144×78×140 ocupa ≈ 5,3 GiB en `float32` a 1 mm y ≈ 0,7 GiB a 2 mm (y `normalize`
  suma otra salida del mismo tamaño). **`modalities` solo incluye:** una serie cuya `modality` no está
  en ninguna de las dos listas, o es `None` (NIfTI sueltos fuera de BIDS), **no se remuestrea** y
  conserva su spacing original. Por eso ese archivo es solo para lotes BIDS; para NIfTI sueltos se usa
  `config/stage3_example.yaml`.

## Limitaciones

- **`reorient` con affine oblicuo:** solo llega a la orientación más cercana; la oblicuidad residual
  queda en el affine.
- **`reorient` con proxy escalado:** un NIfTI perezoso con `scl_slope`/`scl_inter` sale en `float64`
  (no en el dtype de disco), el doble de memoria que `float32`.
- **`resample` con affine oblicuo:** la caja de salida usa la extensión de los ejes más cercanos
  (como en la malla de salida), no la caja envolvente del volumen rotado: se pierden las esquinas del FOV rotado y las zonas
  sin datos valen `0`.
- **`resample` con `cubic`:** sobreoscilación (*ringing*) cerca de bordes marcados; puede dar valores
  fuera del rango de entrada.
- **`max_output_voxels`** (defecto `2**32` = 16 GiB en `float32`, eje temporal incluido): un `spacing`
  que pida más se rechaza antes de reservar memoria. El límite no mira la RAM libre: una salida
  permitida que no cabe da `MemoryError` al reservarla (el runner marca el estudio `failed` y sigue);
  en Linux con *overcommit* el proceso puede morir por OOM en vez de fallar.
- **Comprobación de RAM:** es una foto en un instante. No garantiza que la memoria siga libre al
  reservarla (otros procesos), no cuenta el pico de otros pasos (`normalize` crea otra salida
  `float32` completa mientras la anterior sigue viva; el lector puede tener el volumen materializado),
  y `available` es una estimación del sistema operativo (incluye caché reclamable; no cuenta el swap). En Linux con
  *overcommit*, con `allow_insufficient_memory: true` el proceso puede morir por OOM en lugar de fallar.
- **Reproducibilidad de la comprobación de RAM:** que un estudio salga `ok` o `failed` por memoria
  depende de la RAM libre en ese instante, y ese dato no se guarda en el manifiesto: reproducirlo en
  otra máquina, o en otro momento, puede dar otro `status`. Además, `allow_insufficient_memory: true`
  queda en `params`, así que al reproducir ese manifiesto el consentimiento se reutiliza sin volver a
  preguntar.
- **Memoria de `resample`:** el pico es la salida 4D completa en `float32` más un volumen 3D de
  entrada y sus copias de trabajo (≈ 5 GiB para una difusión 144×144×78×140 a 1 mm); no hay salida en
  disco ni por trozos, ni recorte o relleno a matriz fija (etapa 4).
