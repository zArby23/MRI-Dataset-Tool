# Procesamiento de intensidad

## Carga perezosa de volúmenes (M0)

Por defecto los lectores NIfTI cargan el volumen completo en `float64` (`image.get_fdata()`). Con
`lazy=True` dejan en `MRISeries.volume` el proxy de nibabel (`image.dataobj`, un `ArrayProxy`) y **no
leen ningún vóxel** hasta que algo lo materializa.

```python
from mri_dataset_tool.infrastructure.nifti.batch_reader import NIfTIBatchReader
from mri_dataset_tool.infrastructure.processing.arrays import iter_volumes_3d, load_array

for study in NIfTIBatchReader().iter_studies(root, lazy=True):
    volume = study.series[0].volume           # proxy: shape y dtype sin leer datos
    data = load_array(volume, "float32")      # lee todo el volumen
    for frame in iter_volumes_3d(volume, "float32"):  # 4D: un volumen 3D a la vez
        ...
```

| Parámetro | Defecto | Dónde |
|---|---|---|
| `lazy` | `False` | lectores NIfTI y BIDS (abajo) |
| `dtype` | `None` (dtype del volumen; en un proxy, el de disco o float si la cabecera escala) | `load_array`, `iter_volumes_3d` |

`lazy` existe en `NIfTIReader.load_study`, `NIfTIBatchReader.iter_studies/load_studies`,
`BIDSReader.load_study/load_files` y `BIDSBatchReader.iter_studies/load_studies`; por defecto es
`False` y el comportamiento no cambia.

### Contrato

- `MRISeries.volume: np.ndarray | VolumeLike | None`. `VolumeLike` (`domain/models/serie.py`) es un
  `Protocol` con `shape`, `dtype`, `__array__` y `__getitem__`; lo cumplen `ndarray` y `ArrayProxy`. El
  dominio no importa nibabel.
- La `metadata` (`shape`, `voxel_size`, `datatype`, `bitpix`, `affine`, `qform_code`, `sform_code`,
  `orientation`) sale de la cabecera y es idéntica a la de la carga eager.
- `infrastructure/processing/arrays.py` es el **único acceso al volumen** para los pasos:
  - `load_array(volume, dtype=None) -> np.ndarray`. Un `ndarray` que ya tiene ese `dtype` (o con
    `dtype=None`) se devuelve sin copiar. `load_array(proxy, "float64")` es igual a `get_fdata()`.
  - `iter_volumes_3d(volume, dtype=None)`: 3D cede un volumen; 4D cede `volume[..., t]` uno a uno (con
    un proxy solo se lee ese volumen). Es un generador: los errores salen en el primer `next()`.
  - Errores con mensaje fijo, sin rutas: `"Invalid volume dtype."` (solo enteros y flotantes reales),
    `"Unsupported volume dimensionality."` (no 3D/4D), `"Unable to read volume data."` (archivo
    truncado, corrupto o borrado al materializar) y `"Unsupported NIfTI data type."` (origen complejo:
    convertirlo a real perdería la parte imaginaria; `NIfTIReader` ya rechaza estos archivos al cargar, QA1-01).
- Extensiones (QA1-02): `is_nifti_file` no distingue mayúsculas, así que los lectores NIfTI y BIDS
  (`find_nifti_files`, `BIDSReader`, `BIDSBatchReader`) cargan `.NII`/`.nii.GZ`. BIDS exige minúsculas,
  pero el lector las tolera: `metadata["bids"]["extension"]` conserva la extensión tal como está escrita (p. ej. `.NII.GZ`).
- Con `lazy=True` el lector abre la imagen con `nib.load(path, mmap=False, keep_file_open=True)` (QA1-06).
  Cargar no abre el archivo. La primera lectura de vóxeles lo abre y queda abierto mientras viva el proxy,
  es decir, el estudio. Se cierra al soltar la última referencia (no hace falta `gc.collect()`). El runner
  y los lectores por lote sueltan cada estudio antes de leer el siguiente, así que solo queda abierto el
  archivo del estudio actual. Antes de la primera lectura el archivo se puede borrar o mover (también en
  Windows), y materializarlo después falla con `"Unable to read volume data."`. Después de leer, en
  Windows no se puede borrar ni mover mientras el estudio exista.
- **4D `.nii.gz` (QA1-06).** gzip no permite acceso aleatorio. Sin un archivo abierto persistente, cada
  `volume[..., t]` reabría y descomprimía desde el principio, así que la lectura era O(T²): con T=80,
  4,25 s en lazy frente a 0,25 s en eager. Con el archivo abierto, `iter_volumes_3d` lee los volúmenes
  en orden y avanza sobre el mismo flujo, así que la lectura es lineal en T (≈ eager). Un acceso en
  orden inverso o aleatorio sigue costando una descompresión desde el inicio, porque `indexed_gzip` no
  está instalado.

### Límites

- **Archivos truncados (decisión del humano).** Con `lazy=True` un `.nii.gz` truncado tiene la cabecera
  intacta: el lector lo carga y su `on_error` **no** lo reporta. Falla al materializar, con
  `ValueError("Unable to read volume data.")`, en el primer paso que lee el volumen; el runner lo
  reporta por su `on_error` y el lote sigue (RF16). Con `lazy=False` se sigue detectando al cargar.
- **dtype en disco.** El proxy conserva el dtype del archivo (p. ej. `int16`); nibabel aplica
  `scl_slope/scl_inter` al leer, así que `load_array(proxy)` sin `dtype` puede devolver el dtype en
  disco o un flotante si la cabecera escala. Los pasos deben pedir el `dtype` explícitamente. El dtype
  en disco se conoce sin leer datos (`volume.dtype`, `metadata["datatype"]`).
- **`.nii.gz` y 4D.** Leer `proxy[..., t]` descomprime el flujo desde el inicio hasta ese volumen. La
  memoria sigue acotada a un volumen, pero el tiempo crece: 4D sintético `96×96×60×30 int16`, lectura
  volumen a volumen `.nii` 0,07 s frente a `.nii.gz` 1,9 s (lectura completa del `.nii.gz`: 0,25 s). Sin
  dependencias nuevas (`indexed_gzip` queda fuera).
- **`NIfTIWriter`.** Acepta el proxy tal cual. Sin escalado en la cabecera el resultado es exacto; con
  `scl_slope/scl_inter` nibabel vuelve a cuantizar al dtype en disco (error ~1e-4 relativo). Si importan
  los valores exactos, materializar antes con `load_array(volume, dtype)`.
- Tras el primer paso que transforma el volumen, `series.volume` es un `ndarray`.

### Memoria medida

`scripts/memory_check_nifti_batch.py [--lazy]` sobre `data/raw/nifti_test_studies` (6 archivos
`.nii.gz` `192×256×256 int16`, Windows 10, nibabel 5.4.2), recorriendo el lote sin procesar:

| Modo | Pico sobre la línea base |
|---|---|
| eager (`float64`) | 97,3 MB |
| `lazy=True` | 1,3 MB |

Pendiente (verificación manual del humano): medir sobre la sesión con difusión de BIDS ds005299.

## Paso `validate` (RF03, I1)

| Parámetro | Defecto | Valores |
|---|---|---|
| `modalities` | `null` (todas las series con volumen) | lista de modalidades (Q12) |

Comprobaciones puras en `infrastructure/processing/validation.py` (`validate_series`); el paso
`validate` (`application/pipeline/steps/validate.py`, versión `1`) las aplica a las series con volumen
seleccionadas por `params.modalities` (por defecto todas). No cambia el volumen ni la geometría.

- **Graves (Q6): rechazan el estudio** con `ValueError` de mensaje fijo; el runner lo marca `failed` y
  el lote sigue:
  - geometría ausente o incoherente (`validate_geometry`: affine no 4×4, no finita, última fila distinta
    de `[0, 0, 0, 1]` o no invertible; `shape` distinta de la del volumen);
  - volumen vacío (`"Volume is empty."`);
  - `voxel_size` ausente, nulo, negativo o no finito (`"Voxel size must be three positive finite numbers."`);
  - dimensionalidad distinta de 3D/4D (`"Unsupported volume dimensionality."`);
  - valores NaN/Inf (`"Volume contains non-finite values."`);
  - volumen perezoso ilegible o truncado (`"Unable to read volume data."`).
- **No graves: se anotan** con códigos constantes y el estudio pasa: `CONSTANT_VOLUME` (mínimo igual
  al máximo en toda la serie) y `SINGLE_VOLUME_4D` (4D con un solo volumen).
- Cada serie comprobada recibe `metadata["validation"] = {"status": "ok", "findings": [códigos]}`.
  `StepRecord.outputs` = `{"series": [{"index": i, "findings": [códigos], "volumes_checked": n}]}`:
  solo códigos y conteos, nunca valores del volumen, rutas ni PHI.
- El volumen se lee de a un volumen 3D en `float64` (`iter_volumes_3d`), también si es perezoso, y no
  se materializa en la serie de salida. Si el dtype en disco es entero, se omite la comprobación de
  NaN/Inf (no pueden existir). Un `.nii.gz` truncado cargado con `lazy=True` falla aquí.
- **Conserva** todo: volumen (el mismo objeto, sin copia), `shape`, `affine`, `orientation`,
  `voxel_size`, `dtype` y unidades; solo añade `metadata["validation"]`.
- No duplica la etapa 1: los archivos ilegibles al cargar los reporta el `on_error` de los lectores y la
  geometría DICOM la valida `build_series_volume`.

## Paso `normalize` (RF06, I3)

Algoritmos en `infrastructure/processing/normalize.py` (`normalize_volume`, `check_params`); paso
`normalize` (`application/pipeline/steps/normalize.py`, versión `1`).

| Parámetro | Defecto | Valores |
|---|---|---|
| `method` | `"zscore"` | `zscore` (resta la media y divide por la desviación), `minmax` (a `[0, 1]`), `percentile` (recorta a los valores de los percentiles `[p_low, p_high]` y reescala a `[0, 1]`) |
| `mask` | `"nonzero"` | `nonzero` (estadísticos sobre los vóxeles de entrada ≠ 0), `none` (todos) |
| `per_volume` | `true` | 4D: estadísticos por volumen 3D (`true`) o globales (`false`); sin efecto en 3D |
| `percentiles` | `null` | obligatorio con `method: percentile` (`0 ≤ p_low < p_high ≤ 100`); con otro método, error |
| `modalities` | `null` | filtro de series (Q12) |
| `allow_insufficient_memory` | `false` | `true`/`false` (solo `bool`; si no, `"Allow insufficient memory must be a boolean."`) |

- **Fuera de la máscara** los vóxeles quedan en `0` (el fondo sigue siendo fondo; decisión del humano,
  igual para los tres métodos). Por eso, con `mask: nonzero`, `normalize` **no es una transformación
  afín global** del volumen: solo se transforma la máscara. Con `mask: none` no hay fondo y sí lo es.
- **Conserva:** `shape`, `affine`, `orientation` y `voxel_size` (recalculados con `replace_volume`
  desde el mismo affine). **Cambia:** `dtype` → `float32`; unidades → adimensionales (z-score) o `[0, 1]`.
  La desviación es poblacional (`ddof=0`).
- **Errores (mensaje fijo):** `"Normalization mask is empty."`, `"Volume is constant within the
  normalization mask."` (desviación o rango nulo), `"Volume contains non-finite values."` (NaN/Inf en
  la máscara; nunca se propagan en silencio), `"Insufficient available memory for the normalized
  volume."` (ver abajo), parámetros inválidos.
- **4D y memoria:** se lee un volumen 3D a la vez en `float64` (`iter_volumes_3d`) y la salida se
  escribe en un único `float32`. En modo global hay dos pasadas: la primera combina media y varianza por
  volumen (Chan et al.) o mín/máx, sin materializar el 4D en `float64`. Límite: `percentile` global
  guarda todos los valores de la máscara en `float32` (≈ el 4D en `float32`) para calcular los
  percentiles exactos.
- **Comprobación de RAM (QA1-09).** Antes de leer el volumen o reservar nada, `normalize_volume` compara
  su estimación del pico con `psutil.virtual_memory().available` mediante el helper
  `check_available_memory` de `processing/memory.py`, el mismo que usa `resample`. La estimación es
  `required_bytes(shape, method, per_volume)` = `4 × N` (salida `float32`) `+ 32 × V` (copias de trabajo
  `float64` de un frame 3D: entrada, máscara y transformación), donde `N` son todos los vóxeles y `V` los
  de un frame. Con `percentile` global en 4D se suman `16 × N` (valores de la máscara en `float32`, su
  concatenación y la copia de `np.percentile`). Medido con `tracemalloc` en entradas `int16` sintéticas:
  ≈ 25 B por vóxel del frame más la salida, y ≈ 10 B por vóxel más en percentile global. Una prueba fija
  `pico ≤ estimación < 3 × pico`.
  - Si no cabe, lanza `ValueError("Insufficient available memory for the normalized volume.")` sin
    cifras: el runner marca solo ese estudio como `failed` y el lote sigue.
  - Con `allow_insufficient_memory: true` (consentimiento explícito) sigue adelante y registra un
    WARNING sin cifras.
  - Si `psutil` falla, la comprobación no bloquea y la red de seguridad queda en `MemoryError`.
  - El parámetro entra en `params` y en el manifiesto. Los manifiestos anteriores, sin él, se
    reconstruyen con `false` (la versión sigue en `"1"`).
  - **Qué no comprueba:** es una foto de un instante, así que no garantiza que la memoria siga libre
    al reservarla. No cuenta lo que ya está en memoria: la entrada si ya está materializada (p. ej. la
    salida `float32` de `resample`, que sigue viva mientras se normaliza) ni el pico de otros pasos.
    `available` es una estimación del sistema operativo (incluye caché reclamable y no cuenta el swap).
    En Linux con *overcommit*, con `true` el proceso puede morir por OOM en vez de fallar.
  - **Reproducibilidad:** el status `ok` o `failed` depende de la RAM libre de la máquina en ese instante,
    y ese dato no se guarda en el manifiesto, así que reproducirlo en otra máquina puede dar otro status.
    `allow_insufficient_memory: true` queda en `params`, así que al reproducir el manifiesto se
    reutiliza el consentimiento. Ver la viñeta «Reproducibilidad de la comprobación de RAM» de
    `docs/processing/geometry.md`.
- **Invariancia:** escala positiva previa → misma salida; desplazamiento previo → misma salida con
  `mask: none` (con `nonzero` un desplazamiento cambia la máscara).
- `StepRecord.outputs`: `{"series": [{"index": i, "method": m, ...}]}` con `mean`/`std` (zscore),
  `min`/`max` (minmax) o `low`/`high` (percentile: los valores de intensidad en esos percentiles); en 4D
  con `per_volume` esos valores van en `"volumes": [{...}, ...]`, uno por volumen. Floats nativos;
  sin valores de vóxeles ni PHI.

## Resumen de metadatos: `summarize_study` (RF04, I2)

`application/services/summary.py`: `summarize_study(study) -> dict`, determinista y con solo tipos
básicos JSON (sin NaN). Es la parte «extraer» de RF04; «mostrar» es de la etapa 5.

```
{"series_count": n,
 "series": [{"modality": ..., <claves permitidas de metadata>, "sidecar": {...}, "validation": {...},
             "dtype": "int16" | null,
             "intensity": {"min", "max", "mean", "std", "non_finite_voxels"} | null}]}
```

- **Lista blanca única**: importa `METADATA_WHITELIST`, `FILTERED_METADATA_KEYS`, `SIDECAR_WHITELIST`
  y `filter_validation` de `infrastructure/anonymization/policy.py` (dueño @anonimizacion); no copia
  valores. De `metadata` salen directamente las claves de `METADATA_WHITELIST` que no están en
  `FILTERED_METADATA_KEYS` (geometría y descripción del array). Las filtradas se tratan así:
  `sidecar` → solo las claves de `SIDECAR_WHITELIST` con un escalar o una lista de escalares;
  `validation` → `filter_validation` (estado conocido y códigos de hallazgo), omitida si queda `{}`;
  `bids` y `provenance` **no** se incluyen (la modalidad ya es el sufijo BIDS).
- **Nunca** salen UIDs, `files`/rutas, `subject_id`/`session_id` ni claves fuera de la lista. Un valor
  permitido que no es de tipo básico (p. ej. un `Path`) se descarta, no se convierte a texto. Un
  float NaN/Inf en `metadata` o en el sidecar también se descarta (con la lista que lo contiene): el
  resumen pasa `json.dumps(..., allow_nan=False)`.
- `dtype`: el del volumen (con carga perezosa, el dtype **en disco**; con eager, `float64`). Sin volumen,
  `dtype` e `intensity` son `null` y el resto son solo metadatos.
- `intensity` se calcula sobre los vóxeles finitos, un volumen 3D a la vez en `float64`
  (`iter_volumes_3d`), sin materializar el 4D ni la serie perezosa; los NaN/Inf se cuentan en
  `non_finite_voxels`. Desviación poblacional.
- **Q10:** con los metadatos actuales (NIfTI: geometría y cabecera; DICOM: `rows`, `columns`,
  `pixel_spacing`, `slice_thickness`, `spacing_between_slices`, `image_orientation`, `Modality`; BIDS:
  sidecar técnico) RF04 queda cubierto; no se amplió el lector DICOM.
