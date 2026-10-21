# QA1 — Auditoría adversarial de las etapas 1–3

> Fecha: 2026-10-21 · Rama `etapa-3-procesamiento`, HEAD `ff0769b` · Autor: agente @qa.
> Alcance: `tasks/etapa-3/todo.md` (QA1) y `.claude/roles/qa.md`. No se editó código de producción.

## Resumen

| | |
|---|---|
| Suite completa | `python -m pytest -q`: **832 passed** en HEAD `bd372db` (180 de ellas en `tests/qa/`) |
| Bloqueantes | 0. QA1-01 se avisó como bloqueante; el humano lo fijó en **importante** |
| Importantes | 2: QA1-01 y QA1-06 (rendimiento, hallado con datos reales) **corregidos** |
| Menores | 4: QA1-02, QA1-03 y QA1-05 **corregidos**; QA1-04 **límite documentado** |
| Fugas de PHI nuevas | **Ninguna**. Solo aparecen los riesgos residuales ya documentados en `docs/anonymization/policy.md` §6 |
| Cobertura de líneas | ≈ 93.8 % de `src/` (medición propia con `sys.monitoring`; ver §5) |

Cada prueba de un hallazgo en `tests/qa/` cita su id (QA1-NN). Las correcciones de QA1-01/02/03/05 se
verificaron primero con sus pruebas `xfail(strict=True)`, que pasaron a XPASS; después se cambiaron por
aserciones del comportamiento corregido.

| Id | Severidad | Estado | Prueba |
|---|---|---|---|
| QA1-01 | importante (decisión del humano) | **Corregido** (commit `6a0602f`) | `test_complex_nifti_is_rejected_by_the_reader`, `test_complex_ndarray_volume_fails_its_study`, `test_complex_nifti_to_dicom_writes_nothing` |
| QA1-02 | menor | **Corregido**: se aceptan `.NII`/`.nii.GZ` | `test_uppercase_extensions_are_read_and_written_compressed` |
| QA1-03 | menor | **Corregido** | `test_negative_dim_error_has_a_fixed_message` |
| QA1-04 | menor | **Límite documentado** en `docs/architecture/config.md` | `test_duplicate_yaml_key_keeps_the_last_one` |
| QA1-05 | menor | **Corregido** | `test_step_output_does_not_alias_input_metadata` |
| QA1-06 | importante | **Corregido** (`keep_file_open=True`; aprobado por el humano, commit `9139d25`) | `test_lazy_4d_gz_is_read_with_one_open_per_pass` (una apertura por pasada y archivo liberado al soltar el estudio) |

## 1. Hallazgos

### QA1-01 — Importante — Corregido — Un NIfTI complejo pierde la parte imaginaria sin error

- **Qué pasa:** un NIfTI `complex64`/`complex128` se procesa como si fuera real, sin error.
  - Carga eager: `NIfTIReader.load_study` usa `get_fdata()` y devuelve `float64` con solo la parte real.
    Solo emite una `ComplexWarning`, que no es un error.
  - Carga lazy: `validate` y `reorient` conservan `complex64`; `resample` y `normalize` lo convierten a `float32` real.
  - El pipeline completo termina en `ok`, y `convert_nifti_to_dicom` escribe un DICOM solo con la parte real.
  - Se rompe además el invariante eager = lazy: tras `validate`/`reorient`, el dtype es `float64` en eager y `complex64` en lazy.
- **Reproducción (sin PHI):**
  ```python
  data = (np.arange(24).reshape(2, 3, 4) + 100j).astype(np.complex64)
  nib.save(nib.Nifti1Image(data, np.eye(4)), "c.nii")
  NIfTIReader().load_study(Path("c.nii")).series[0].volume.dtype   # float64, imag perdida
  convert_nifti_to_dicom(Path("c.nii"), Path("out"))                 # 1 estudio escrito, sin error
  ```
- **Se esperaba:** `ValueError` con mensaje fijo y la entrada reportada por `on_error`.
- **Causa:** `get_fdata()` y `np.asarray(..., float)` descartan la parte imaginaria con solo un aviso.
- **Arreglo mínimo propuesto:** rechazar los datos complejos en **un solo punto**, en `NIfTIReader.load_study`:
  `if image.header.get_data_dtype().kind == "c": raise ValueError("Unsupported NIfTI data type.")`.
  - Cubre las cargas eager y lazy, `NIfTIBatchReader`, `BIDSReader`/`BIDSBatchReader` y `convert_nifti_to_dicom`.
  - Requiere una prueba en `tests/unit/test_nifti_reader.py`.
  - Archivos: `infrastructure/nifti/reader.py` (código congelado de la etapa 1; la excepción M0 era de @intensidad) y su prueba.
  - Defensa opcional: que `processing/arrays.load_array` rechace un origen de tipo `c`, para un `ndarray` complejo llegado por otra vía.
- **Corrección aplicada:** `NIfTIReader` rechaza los datos complejos con `ValueError("Unsupported NIfTI data type.")`
  y `arrays.load_array` rechaza un origen complejo (defensa para un `ndarray`).
- **Pruebas:** ver la tabla del resumen.
- **Riesgo real:** bajo. Los NIfTI de magnitud o fase que producen los escáneres son reales.

### QA1-02 — Menor — Corregido — `.NII` / `.nii.GZ` en mayúsculas se ignoran en silencio

- **Qué pasa:** `is_nifti_file` distingue mayúsculas y minúsculas. En un lote, `x.nii.GZ` o `X.NII`
  no se cargan ni llegan a `on_error`. En Windows, el sistema de archivos no distingue mayúsculas.
- **Reproducción:** guardar un NIfTI válido como `ok.nii.GZ` en un directorio y llamar a
  `NIfTIBatchReader().load_studies(dir)` → `ValueError("No valid NIfTI studies were found.")`.
- **Se esperaba:** cargarlo o, al menos, reportarlo (decisión de diseño pendiente).
- **Archivos:** `infrastructure/nifti/reader.py::is_nifti_file` (congelado) y sus usos en los lectores por lote y BIDS.
- **Corrección aplicada:** `is_nifti_file` y la elección de compresión de `NIfTIWriter` no distinguen mayúsculas.

### QA1-03 — Menor — Corregido — Una cabecera NIfTI con `dim` negativo da un mensaje no fijo (`"negative count"`)

- **Qué pasa:**
  - Carga eager: `NIfTIReader` solo convierte `ImageFileError`/`OSError`/`EOFError`, así que el `ValueError` de numpy sale con su texto.
  - Carga lazy: `arrays.load_array` tampoco lo convierte. El mensaje no tiene PHI ni rutas, pero no es el contrato
    (`"Unable to load NIfTI image."` / `"Unable to read volume data."`).
  - El lote sigue, y el estudio se reporta y se omite.
- **Reproducción:** escribir un NIfTI válido y poner `int16` = -3 en el byte 42 (`dim[1]`). Luego cargarlo
  con `NIfTIBatchReader().iter_studies(..., lazy=False/True)` y correr el pipeline.
- **Archivos:** `infrastructure/nifti/reader.py` (congelado) y `infrastructure/processing/arrays.py` (@intensidad).
- **Corrección aplicada:** `NIfTIReader` convierte un `dim` negativo en `"Unable to load NIfTI image."`.

### QA1-04 — Menor — Límite documentado — Claves YAML duplicadas: gana la última, sin aviso

- **Qué pasa:** `pipeline: {steps: [], steps: [{name: validate}]}` se acepta y se queda con la segunda
  lista. Es el comportamiento de PyYAML. Un archivo de corrida editado a mano puede ejecutar un pipeline
  distinto del que el autor cree ver, aunque el manifiesto registra el efectivo.
- **Archivos:** `infrastructure/config/loader.py` (congelado). Se arregla con un `SafeLoader` que rechace claves duplicadas.
- **Decisión del humano:** se conserva y se documenta como límite en `docs/architecture/config.md`.

### QA1-05 — Menor — Corregido — `validate` y `anonymize` comparten objetos anidados de `metadata` con la entrada

- **Qué pasa:** el paso no muta su entrada, pero la salida comparte con ella objetos anidados:
  - la de `validate` comparte `affine` (`ndarray`) y `sidecar`/`bids`/`provenance` (copia superficial `{**metadata}`);
  - la de `anonymize` comparte `affine` y las demás claves de geometría.
  
  Un consumidor que edite la salida en sitio (etapa 4: etiquetado u organización) modificaría
  también el estudio de entrada. `replace_volume` ya hace una copia profunda por esta razón.
- **Reproducción:**
  ```python
  out = build_step("validate").apply(study)
  out.series[0].metadata["affine"][0, 3] += 1   # cambia también study.series[0].metadata["affine"]
  ```
- **Archivos:** `application/pipeline/steps/validate.py` (@intensidad) y `application/pipeline/steps/anonymize.py` (@anonimizacion).
- **Corrección aplicada:** las salidas de `validate` y `anonymize` ya no comparten objetos anidados con la entrada.

### QA1-06 — Importante — Corregido — La lectura lazy de un 4D `.nii.gz` es cuadrática en el número de volúmenes

- **Qué pasa:** `iter_volumes_3d` lee `volume[..., t]` del `ArrayProxy` de nibabel. Con `.nii.gz`, cada acceso
  reabre el archivo y descomprime desde el principio hasta ese volumen. `validate`, `reorient`, `resample`,
  `normalize` y `summarize_study` recorren todos los volúmenes, así que cada paso paga O(T²). Con `.nii` sin
  comprimir y con carga eager el coste es lineal.
- **Medición** (64×64×40 `int16`, `validate`):

  | T | eager `.nii.gz` | lazy `.nii.gz` |
  |---|---|---|
  | 20 | 0,08 s | 0,34 s |
  | 40 | 0,13 s | 1,18 s |
  | 80 | 0,25 s | 4,25 s |

  En el BIDS real, la difusión de 144×144×78×140 tardó ≈ 220 s solo en `validate` + `reorient`.
- **Reproducción:** guardar `np.zeros((4, 4, 3, 10), np.int16)` como `x.nii.gz`, cargarlo con
  `NIfTIReader().load_study(p, lazy=True)` y contar las instancias de `nibabel.openers.ImageOpener`
  mientras se recorre `iter_volumes_3d`: se crean 10, una por volumen.
- **Se esperaba:** una sola lectura secuencial del archivo por pasada.
- **Arreglo mínimo medido:** en `NIfTIReader`, con `lazy=True`, usar `nib.load(path, mmap=False, keep_file_open=True)`.
  - Con eso la lectura es lineal: T=160 baja de 17,7 s a 0,26 s.
  - En Windows el archivo se libera al soltar la imagen: comprobado renombrándolo.
  - Coste: el archivo queda abierto mientras el estudio vive en memoria, lo que contradice la decisión de M0
    ("el archivo no queda abierto"). El runner suelta cada estudio antes de leer el siguiente, así que solo hay uno abierto a la vez.
  - No hace falta `indexed_gzip`, que no está instalado.
  - El humano aprobó el cambio.
- **Archivos:** `infrastructure/nifti/reader.py` (M0, @intensidad) y una prueba de liberación del archivo.
- **Corrección aplicada** (@intensidad): `NIfTIReader` con `lazy=True` usa `keep_file_open=True`. La docstring
  documenta que el archivo queda abierto hasta soltar el estudio. Se verificó con una apertura por pasada y con el
  archivo renombrable en Windows tras soltar el estudio. El humano aprobó el cambio a la decisión de M0 (commit `9139d25`).

### Observaciones (no son defectos)

- **Memoria:** el pico no crece con el lote. Ejemplo: volumen `int16` de 128×128×96 a 1,2×1,2×1,5 mm, pipeline completo
  remuestreando a 1 mm. Con 5 y con 40 estudios, el pico medido con `tracemalloc` es de 95 MiB en lazy y 107 MiB en eager,
  y queda en ≈ 0 MiB al terminar. Ese pico equivale a ≈ 8 veces el volumen de entrada en `float64`, porque el remuestreo
  a 1 mm agranda la salida y suma el suavizado y el relleno. Sirve como dato para RNF01/RNF02 con volúmenes grandes.
- **Difusión con `config/stage3_example.yaml`:** con datos reales, `resample` a 1 mm rechaza la difusión
  de 144×144×78×140 con `"Resampled volume would be too large."`, porque saldrían ≈ 1.300 millones de vóxeles,
  por encima del límite de entonces, `MAX_OUTPUT_VOXELS` = 2²⁸. El estudio se cortaba entero y se perdían también
  sus otras 8 series.
  **Resuelto después de esta auditoría** (commits sin revisar por @qa):
  - **QA1-07** (`8563e53`): el límite por defecto sube a 2³² y pasa a ser el parámetro `max_output_voxels` de `resample`.
  - **QA1-08** (`717c85f`) y **QA1-09** (`9e155eb`): `resample` y `normalize` comprueban la RAM disponible antes de reservar
    la salida; el parámetro `allow_insufficient_memory` permite seguir de forma explícita.
  
  La prueba de humo **no se repitió** con el límite nuevo. Queda como verificación manual: correr la difusión real
  con ≥ 8–10 GB de RAM libres.
- **YAML:** `spacing: [1e-9, 1, 1]` se acepta al construir el paso y falla por estudio con
  `"Resampled volume would be too large."`. Es el comportamiento documentado.

## 2. Qué se probó (y pasó)

**Barrido de PHI** (`tests/qa/test_qa_phi_sweep.py`). Se plantaron valores sintéticos reconocibles en lugares
que las pruebas de A2/E1 no cubren:

- **NIfTI y BIDS:**
  - cabecera NIfTI: `descrip`, `aux_file`, `db_name`, `intent_name` y una extensión (ecode 6);
  - nombre `sub-<ID>_ses-<fecha>`;
  - sidecar con `PatientName`, `InstitutionName` y `AcquisitionDateTime`.
- **DICOM:**
  - en el *file meta*: `SourceApplicationEntityTitle` y `PrivateInformation`;
  - un preámbulo con texto;
  - transfer syntax implícita y *deflated*;
  - identificadores con VR `UN`.

Después se corrió el pipeline completo, eager y lazy, más `NIfTIWriter`, `convert_nifti_to_dicom`,
`convert_dicom_to_nifti` y `anonymize_dicom_tree`. Los valores se buscaron en:

- las salidas: NIfTI descomprimido, cada DICOM (bytes y `repr`), nombres de archivo y carpeta;
- el manifiesto, `summarize_study` y los campos del estudio en memoria;
- los logs en DEBUG.

Resultado: **ninguna aparición**. Además, `NIfTIWriter` crea una cabecera nueva (no copia `descrip` ni
extensiones), y el gzip de salida no lleva nombre de archivo y tiene `mtime = 0`.

**Riesgos residuales confirmados** (ya documentados en la política §6; no son hallazgos):

- los valores de entidades BIDS permitidas (`acq-JohnDoe` sobrevive en `metadata["bids"]["other"]`);
- los valores de claves técnicas permitidas (`SequenceName` en el sidecar; `ImageType`, `SequenceName` y `PatientSex` en DICOM).

**Entradas hostiles** (`test_qa_hostile_inputs.py`, eager y lazy), por el pipeline completo:

- **Fallan con el mensaje fijo esperado, en el paso esperado:** 2D, 5D, NaN, Inf, `float64` fuera del rango de `float32`
  (falla en `normalize` como no finito), volumen constante, todo ceros y un solo vóxel.
- **Pasan con geometría coherente:** 4D de un volumen, `uint64`, `int8`, un solo corte, affine oblicuo, LPS y con cizalla.
- **Archivos corruptos:** `.nii` truncado, solo cabecera, `dim` mayor que los datos y `dim` negativo. Se reportan y el lote sigue.
- **Rutas:** con espacios, Unicode (ñ, ü, CJK) y de más de 260 caracteres en Windows, en lectura (proxy perezoso incluido),
  `NIfTIWriter`, ambas conversiones y `anonymize_dicom_tree`. Los directorios y archivos ocultos se ignoran.
- **Parámetros YAML inválidos** (sondeo manual): `spacing` como texto, con NaN o con bool; parámetro desconocido;
  `params` como lista o null; paso desconocido; `name` entero; `target` en minúsculas; percentiles invertidos;
  `per_volume` como texto; `modalities` como texto; `policy_version` entero; interpolación en mayúsculas; clave extra.
  Todos se rechazan con mensaje fijo.
- **DICOM de un solo corte sin `SliceThickness`:** se rechaza con mensaje fijo y se reporta (documentado).

**Invariantes** (`test_qa_invariants.py`):

- Las **120 permutaciones** de `validate, anonymize, reorient, resample, normalize`, sobre un 4D oblicuo,
  invertido y anisótropo con `scl_slope/inter`:
  - geometría canónica coherente (`shape`, `voxel_size` desde el affine, `orientation`);
  - volumen y reports idénticos en eager y lazy;
  - entrada sin mutar.
- Dos corridas son idénticas.
- Reproducción desde el manifiesto JSON con `outputs`.
- `anonymize` es idempotente con BIDS, UIDs y sidecar.
- Memoria: el pico con 24 estudios no supera en más del 10 % el pico con 3 (eager y lazy).

## 3. Datos reales (`data/raw/`, solo lectura)

Se corrió el sistema sin copiar ni citar contenido. Las salidas fueron a un directorio temporal fuera del repositorio
y solo se registraron conteos, tipos, tiempos, CPU y RAM (CPU = tiempo de usuario + sistema; RAM pico = *working set*
máximo del proceso). Al terminar, `git status data/` estaba limpio: no se modificó ninguna entrada.

| Corrida | Resultado | Tiempo | CPU | RAM pico |
|---|---|---|---|---|
| `nifti_test_studies`, pipeline stage3 (lazy) | 6/6 estudios ok, 0 errores; el manifiesto no contiene rutas de entrada | 19 s | 18 s | 355 MB |
| `bids_test_studies` (1 dataset, 4,1 GB), corrida completa (lazy) | **Detenida por tiempo** a los 18 min, sin errores. Antes se había detenido una primera corrida con `tracemalloc` (41,9 min; CPU 1771 s; RAM pico 881 MB) | 18 min | 1051 s | 880 MB (85 MB entre estudios) |
| BIDS, prueba de humo (1 sujeto/sesión, 9 series) | `validate`, `anonymize` y `reorient` ok; `resample` falla con `"Resampled volume would be too large."` (difusión 144×144×78×140 a 1 mm; ver Observaciones). Hubo 2 archivos del dataset con nombre BIDS inválido, reportados con mensaje fijo | 227 s | 224 s | 879 MB |
| `dicom_test_studies` (43.719 archivos), `convert_dicom_to_nifti` | 31 estudios y 343 series convertidas. Hubo 1 `InvalidDicomError`: un archivo del árbol que no es DICOM, reportado según el contrato | 21 min | 381 s | 446 MB |
| Pipeline stage3 sobre los 343 NIfTI convertidos (lazy) | **343/343 ok**, 0 errores; el manifiesto no contiene rutas de entrada | 77 min | 4529 s | 446 MB (193 MB al terminar) |
| `anonymize_dicom_tree` sobre `dicom_test_studies` | **Incompleta**: se entregó el informe con la corrida en curso. Hasta entonces no hubo errores; ritmo de ~450 a ~2.900 archivos/min, limitado por el disco. Por falta de espacio se borraron a mano parte de las salidas durante la corrida, así que no hay conteo final válido | > 16 min | — | 446 MB |
| Reconversión del DICOM anonimizado a NIfTI | **No llegó a correr** | — | — | — |

Conclusiones:
- **RNF02 confirmado con datos reales:** la RAM pico se mantuvo en 446 MB a lo largo de 343 estudios y de toda la
  conversión, y vuelve a ~190 MB entre estudios.
- **Errores de lectura del BIDS (cifras conciliadas en QA2).** El dataset tiene **86 punteros de git-annex** sin
  contenido descargado: archivos de texto de 105–108 bytes con extensión `.nii.gz`. Los otros 76 NIfTI cargan bien.
  - **84** de esos punteros tienen nombre BIDS válido: fallan al cargar con `"Unable to load NIfTI image."`. Son los
    84 errores de la primera corrida y los 84 de la corrida completa de QA2.
  - **2** tienen nombre BIDS inválido: fallan antes, al interpretar el nombre, con
    `"Invalid BIDS file name: missing entities or suffix."`. Son los 2 `ValueError` de la prueba de humo.
  
  (Antes este informe decía que la primera corrida "se detuvo antes de leer los 2 restantes", y en un aviso anterior
  atribuí los 2 `ValueError` a archivos sin relación con los punteros. Ambas cosas eran inexactas.)
  Todos se reportan con mensaje fijo y el lote sigue (RF16). No es un defecto: para correr el dataset entero hace falta `datalad get`.
- **QA1-06 se descubrió aquí:** en BIDS, la difusión tardó ≈ 220 s solo en `validate` + `reorient`. Las corridas
  anteriores usaron el código previo a la corrección, así que sus tiempos no la reflejan.

### 3.1 QA2 — verificaciones manuales sobre datos reales (2026-10-21)

Se ejecutaron con HEAD `5ab5537`, con las salidas en `E:/qa_runs/` (fuera del repositorio, regla de `MEMORY.md` §2)
y con 6,4–6,5 GiB de RAM disponibles de 13,9. Al terminar, `git status data/` estaba limpio.

| Corrida | Resultado | Tiempo | CPU | RAM pico |
|---|---|---|---|---|
| **Pico eager vs lazy**, difusión `sub-01/ses-01` (144×144×78×140), leída volumen a volumen | eager `float64`: 2.169 MB; lazy `uint16`: **85 MB** | 2,9 s / 1,8 s | — | ver resultado |
| `scripts/memory_check_nifti_batch.py` sin y con `--lazy` (ruta fija `nifti_test_studies`, 6 archivos) | Aumento del pico sobre la base: 97,3 MB en eager y 1,3 MB en lazy | — | — | 151 / 55 MB |
| **Difusión** por el pipeline stage3 (límite nuevo 2³²), estudio completo de 9 series | `validate`, `anonymize`, `reorient` y **`resample` ok**. `normalize` falla con `"Insufficient available memory for the normalized volume."`; no se usó `allow_insufficient_memory`. El manifiesto no contiene rutas | 138 s | 137 s | 6.003 MB |
| La misma sesión, serie por serie | Las 8 series que no son dwi (T2w, T1w, 2× magnitude1, 2× magnitude2, 2× phasediff) están ok, cada una en < 3 s y < 410 MB. dwi falla en `normalize` por RAM | 128 s (dwi) | 127 s | 5.648 MB (dwi) |
| **BIDS completo** (27 sesiones, lazy), **dwi excluida** con `modalities` en validate/reorient/resample/normalize | **27/27 ok**, 0 fallos de paso. Errores de lectura: 84 punteros más 2 nombres inválidos. El manifiesto no contiene rutas | 97 s | 95 s | 544 MB |
| **`anonymize_dicom_tree` completo** (43.719 archivos) | **43.718 escritos y 1 fallido** (`InvalidDicomError`: el archivo no DICOM del árbol). Hay 43.718 `.dcm` en disco y el informe guardado coincide | 11,2 min | 332 s | 77 MB |
| **Reconversión** del DICOM anonimizado a NIfTI | **31 estudios y 343 series**, lo mismo que la conversión original. 1 `InvalidDicomError`: el `anonymization_report.json` de la carpeta de salida, que el lector reporta como no DICOM, según su contrato | 13,7 min | 274 s | 403 MB |

Conclusiones de QA2:
- **QA1-06 confirmado con datos reales:** lazy lee los 140 volúmenes de la difusión en 1,8 s (antes ≈ 220 s solo
  `validate` + `reorient`) y con 25 veces menos RAM que eager.
- **QA1-07/08/09 se comportan como se documentó:** `resample` de la difusión ya cabe (≈ 5,3 GiB de salida). La
  comprobación de RAM rechaza `normalize` con su mensaje fijo, porque necesitaría otros ≈ 5,3 GiB con 6,5 disponibles.
- **Observación:** el runner corta el estudio en el primer fallo, así que una sesión con difusión pierde también sus
  8 series válidas cuando la difusión no cabe en RAM. Excluir dwi con `modalities` resuelve el caso. El árbol ya tiene
  una configuración BIDS con `resample` por modalidad (commit `d3dc3fc`, posterior a esta corrida y no auditado por @qa).
- **La anonimización a escala real conserva la reconstrucción:** el mismo número de estudios y series antes y después.

### 3.2 QA3 — lanzador BIDS con `config/stage3_bids.yaml` (2026-10-21)

Se usó `scripts/run_stage3_bids_pipeline.py` con HEAD `9ad5f95`: anatomía y mapas de campo a 1 mm, dwi a 2 mm. Las
salidas fueron a `E:/qa_runs/qa3_*`, con 5,8–6,4 GiB de RAM disponibles. No se usó `allow_insufficient_memory`.
`git status data/` quedó limpio. La RAM pico se midió sobre el árbol de procesos, porque el `python.exe` del venv es
un lanzador y el intérprete real es su hijo.

| Corrida | Resultado del lanzador | Salidas | Tiempo | RAM pico |
|---|---|---|---|---|
| `sub-01/ses-01` (la sesión con difusión), con la carpeta de la sesión como raíz | `Studies: 1 ok: 1 failed in a step: 0 files written: 9`, `Errors by type: none`, `Manifest without source paths: True reproduced from manifest: True` | dwi 130×130×71×140 a **2,0 mm**. 8 series a **1,0 mm** (p. ej. T1w 167×256×255). Todas `float32` y RAS | 95 s (con la reproducción) | 1.874 MB (primera pasada) |
| Dataset completo (27 sesiones, lazy) | `Studies: 27 ok: 27 failed in a step: 0 files written: 76`, `Errors by type: {'ValueError': 86}`, `Manifest without source paths: True reproduced from manifest: True` | 71 series 3D a 1,0 mm y **5 dwi 4D a 2,0 mm**, todas `float32`. Son los 76 NIfTI reales del dataset | 610 s (con la reproducción) | 1.864 MB |

Conclusiones de QA3:
- **Éxito:** la sesión con difusión pasa entera, con la dwi normalizada con ~6 GiB disponibles. La RAM pico baja
  de 6.003 MB (dwi a 1 mm, QA2) a ~1,9 GB.
- Ni la consola ni el manifiesto contienen rutas ni `sub-`.
- Los 86 `ValueError` son los 86 punteros de git-annex: 84 que fallan al cargar y 2 con nombre inválido (§3).
- La consola muestra además el log `ERROR:...nifti.reader:Unable to load NIfTI image` una vez por puntero y por pasada
  (172 líneas). No contiene PHI, pero repite lo que ya cuenta `error N: ValueError`. Es una observación menor de legibilidad.
- Con la carpeta de la sesión como raíz, los sidecars solo se heredan desde la sesión. No afecta al procesamiento.
- **Incidencias del script de medición de @qa, no del sistema:** un primer intento se bloqueó en la reproducción
  porque la consola iba a una tubería que nadie vaciaba. Además medía solo el `python.exe` lanzador. Se corrigieron
  las dos cosas: la consola va a un archivo y se mide el árbol de procesos. Durante ese intento el humano tenía
  3D Slicer abierto, así que la caída de la RAM disponible del sistema en esa corrida no se usa como consumo del pipeline.

**Pendiente de verificación manual del humano:**
- ~~la difusión **normalizada**~~: **hecho en QA3** a 2 mm con `config/stage3_bids.yaml`. A 1 mm (`stage3_example.yaml`)
  sigue necesitando ≥ 11–12 GiB libres;
- abrir en un visor las salidas de `E:/qa_runs/qa3_ses01/` (anatomía a 1 mm y dwi a 2 mm, RAS);
- los puntos del checkpoint que requieren ojos humanos: el visor, y revisar el `AnonymizationReport` y las salidas en `E:/qa_runs/`.

## 4. Qué no se verificó (sospechas y límites)

- **Linux (RNF04):** todo se corrió en Windows 10.
- **DICOM con píxeles comprimidos (JPEG/JPEG 2000):** sus segmentos de comentario pueden llevar texto.
  `anonymize_dicom_tree` conserva `PixelData` intacto. Es una sospecha, no probada, y está cerca del
  "texto quemado" fuera de alcance.
- **DICOM *enhanced* multi-frame** a través de `anonymize_dicom_tree`: las secuencias funcionales se
  eliminan (política) y el resultado probablemente queda inutilizable para `build_series_volume`, que ya
  rechaza multi-frame. No se probó.
- **Enlaces simbólicos y *junctions*** en los recorridos de los lectores: no se probaron.
- **Cobertura por ramas:** solo se midieron líneas.

## 5. Cobertura

No hay `coverage` ni `pytest-cov` instalados, y no se instaló nada. Se midió con un script propio fuera
del repositorio que usa `sys.monitoring` (biblioteca estándar, Python 3.14) mientras corre la suite
(antes de añadir `tests/qa/`): **≈ 93.8 % de líneas** (2067/2204). La cifra es aproximada: las firmas de
función de varias líneas cuentan como no cubiertas.

Huecos reales relevantes:

| Archivo | Sin cubrir |
|---|---|
| `infrastructure/dicom/reader.py` (≈ 78 %) | Errores: ruta inexistente o no directorio, sin DICOM válidos, varios estudios |
| `infrastructure/anonymization/dicom.py` | Rama de secuencia **conservada** (código muerto en la política v1: ninguna SQ es `kept`) y `_replacement` con valor vacío |
| `application/pipeline/steps/anonymize.py` | Ramas defensivas con `bids`/`sidecar`/`provenance` que no son `dict` |
| `bids/reader.py`, `conversion.py`, lectores por lote | Callback `on_error` que lanza (solo se registra su tipo) |
| `processing/{arrays,validation}.py`, `pipeline/{manifest,step}.py`, `anonymization/{policy,pseudonym,report}.py` | 100 % |

## 6. Verificaciones manuales pendientes para el humano

1. La difusión normalizada ya se verificó a 2 mm con `config/stage3_bids.yaml` (QA3, §3.2). A 1 mm necesita
   ≥ 11–12 GiB de RAM libres. El BIDS completo, la anonimización completa y su reconversión ya se verificaron en
   QA2 y QA3.
2. Las del checkpoint final de `tasks/etapa-3/todo.md`:
   1. abrir en un visor un volumen antes y después de reorientar, remuestrear y normalizar;
   2. revisar el `AnonymizationReport` y buscar identificadores en las salidas (las de QA2 están en
      `E:/qa_runs/qa2_anon/`);
   3. ~~medir el pico de memoria eager vs `lazy` en BIDS ds005299~~: **hecho en QA2** (§3.1);
   4. ~~opcional: anonimizar un DICOM real fuera del repositorio~~: **hecho en QA2** (§3.1), sobre `dicom_test_studies`.
3. Correr `python -m pytest -q` en Linux (RNF04).
4. Si hay a mano un DICOM real con compresión JPEG, comprobar fuera del repositorio que no conserva comentarios con identificadores (§4).
