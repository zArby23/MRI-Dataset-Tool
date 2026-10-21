# Geometría: base común y pasos de geometría

Algoritmos en `infrastructure/processing/` (solo `numpy`, `nibabel`, `scipy`; no importan
`application`) y pasos registrados en `application/pipeline/steps/`. Todo el proyecto usa
**RAS+** (convención NIfTI); para affines DICOM (LPS) están `lps_to_ras`/`ras_to_lps` en
`infrastructure/dicom/volume_builder.py`.

## Base común (`geometry.py`)

| Función | Qué hace |
|---|---|
| `replace_volume(series, volume, affine)` | Serie nueva con `volume` y la geometría canónica recalculada: `shape` (tupla de `int`), `voxel_size` (norma de las columnas 3×3 del affine; solo espacial en 4D), `affine` (copia `float`) y `orientation` (`nib.aff2axcodes`). El resto de `metadata` se copia en profundidad (`bids`, `sidecar`, `provenance` no se comparten con la entrada); `files` se copia. **Único punto** del procesamiento que escribe esos cuatro campos. |
| `validate_geometry(series)` | `ValueError` de mensaje fijo, sin causa ni valores, si falta `volume` o `affine`, si el affine no es 4×4 numérico, finito, con última fila `[0, 0, 0, 1]` e invertible, o si `metadata["shape"]` no coincide con `volume.shape` (también si no es iterable). Solo lee `volume.shape`: no materializa un volumen perezoso. |
| `check_modalities(modalities)` | `None` o lista/tupla de `str`; si no, `ValueError("Modalities must be a list of strings.")`. Los pasos lo llaman al construirse. |
| `apply_to_series(study, transform, modalities=None)` | Devuelve `(estudio_nuevo, outputs)`. Aplica `transform(series) -> (serie, valores)` a las series con `volume` y, si hay filtro (Q12), `modality` en `modalities` (`modality=None` queda fuera; `[]` no selecciona ninguna). Las demás series se devuelven como el mismo objeto, sin mutar. `outputs = {"series": [{"index": i, **valores}]}`, con `i` la posición en `study.series`, solo para las transformadas (convención de `StepRecord.outputs`). |

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
| dtype | Se conserva (con un volumen perezoso, el que da `load_array`: el de disco o `float` si la cabecera escala). |
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

Algoritmo (`resample.py`), decisiones Q5:

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
- **Límite de tamaño:** si la salida supera `MAX_OUTPUT_VOXELS = 2**28` voxels (1 GiB en `float32`,
  contando el eje temporal), lanza `ValueError("Resampled volume would be too large.")` antes de
  reservar memoria.

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
  Q5), no la caja envolvente del volumen rotado. Las esquinas del FOV rotado que caen fuera de
  esa caja se pierden, y las zonas de la caja sin datos de entrada valen `0`.
- **`cubic`:** puede producir sobreoscilación (valores fuera del rango de entrada) cerca de bordes
  marcados.
- **Memoria:** 4D volumen a volumen con `iter_volumes_3d` en `float32`. El pico es la salida
  completa más un volumen 3D de entrada y sus copias de trabajo (suavizado y relleno), que se
  liberan antes de leer el siguiente.
- **`outputs`:** `{"series": [{"index": i, "shape": [...], "spacing": [...]}]}` (`int`/`float`
  nativos; `spacing` sale del affine resultante).
