# Manual de usuario: línea de comandos (`mri-dataset`)

La CLI prepara datasets de resonancia magnética (DICOM, NIfTI, BIDS) para ML/DL: muestra metadatos, convierte,
anonimiza, procesa con un pipeline configurable, etiqueta, exporta y genera reportes. Todo lo que imprime son
conteos y tipos de error: **nunca** rutas, identificadores de pacientes, UIDs ni valores de cabecera.

> Estado: en desarrollo. Las pruebas automáticas usan datos sintéticos. **Pendiente de verificación
> manual:** instalación en un entorno limpio, un recorrido real con una carpeta de datos y la ejecución en Linux.

## 1. Instalación

Requisitos: Python 3.14 o superior, en Windows o Linux.

```powershell
# desde la raíz del repositorio
python -m pip install -e .
mri-dataset --help
```

Si el comando `mri-dataset` no está en el `PATH` (por ejemplo, en un entorno sin la carpeta `Scripts` del
intérprete), se puede usar el módulo directamente:

```powershell
python -m mri_dataset_tool.presentation.cli --help
```

Cada comando tiene su ayuda: `mri-dataset process --help`, `mri-dataset labels review --help`, etc.

En algunas consolas (p. ej. Git Bash en Windows) los acentos de la ayuda pueden verse mal; es un problema de la
codificación de la consola, no de la herramienta. PowerShell y las terminales de Linux los muestran bien.

## 2. Antes de empezar

### Clave de anonimización (`MRI_ANON_KEY`)

`anonymize`, `process` (si la configuración incluye el paso `anonymize`) y `dataset build` necesitan una clave
secreta de **al menos 32 caracteres** en la variable de entorno `MRI_ANON_KEY`. Con ella se calculan los
seudónimos (HMAC-SHA256): la misma clave produce siempre los mismos seudónimos y no existe tabla de
correspondencia. La herramienta nunca la imprime ni la guarda; guárdela usted en un lugar seguro y no la versione.

```powershell
$env:MRI_ANON_KEY = "<secreto de 32 caracteres o más>"     # PowerShell
```

```bash
export MRI_ANON_KEY="<secreto de 32 caracteres o más>"     # bash
```

Sin la clave (o si es corta) el comando termina con código 2 sin crear nada.

### Configuración y directorio de trabajo

`process` y `dataset build` leen un archivo YAML de corrida (`--config`) que se combina sobre
`config/default.yaml`. **Ese `config/default.yaml` y las rutas relativas de la configuración (`report.path`, el
manifiesto) se resuelven desde el directorio actual: ejecute la CLI desde la raíz del repositorio.** El esquema
(`logging.level`, `pipeline.steps`, `report.path`) está en `docs/architecture/config.md`; el nivel de log de la
CLI lo fijan `--quiet`/`--verbose`, no `logging.level`.

Configuraciones incluidas:

| Archivo | Uso |
|---|---|
| `config/stage3_example.yaml` | NIfTI sueltos: validate → anonymize → reorient → resample (1 mm) → normalize |
| `config/stage3_bids.yaml` | BIDS: igual, con `resample` a 1 mm para anatómicas/fmap y a 2 mm para `dwi`. Solo remuestrea las modalidades listadas; no usarlo con NIfTI sueltos |

### Dónde escribir las salidas

Las conversiones y los pipelines sobre datos reales generan archivos grandes; la salida puede ir en cualquier
disco. Antes de empezar, `convert`, `anonymize`, `process` y `dataset build` estiman el tamaño de la salida como
el tamaño de la entrada y lo comparan con el espacio libre del disco de la carpeta de salida. Si la estimación
alcanza el 90 % del espacio libre (margen del 10 %), imprimen, también con `--quiet`:

```text
WARNING INSUFFICIENT_DISK_SPACE: estimated output 12.3 GiB, 11.0 GiB free on the output drive; consider another drive.
```

Es solo un aviso: la ejecución sigue y el código de salida no cambia. En datasets git-annex/DataLad, donde cada
imagen es un enlace simbólico, se cuenta el tamaño del archivo enlazado (un enlace roto cuenta 0; no se siguen
enlaces a carpetas ni carpetas ocultas como `.git`). La estimación es aproximada; el
remuestreo a un espaciado menor o la salida en `float32` de entradas `int16` pueden ocupar bastante más que la
entrada. Si el espacio libre no se puede leer, no hay aviso. `dataset report` y `dataset export-ml` escriben
archivos pequeños y no avisan.

La CLI **nunca sobrescribe**: si una salida ya existe termina con código 1; bórrela o elija otra carpeta. La
única excepción es la carpeta `--output-dir` de `dataset build`: una carpeta existente y vacía se usa (sección 5).

## 3. Opciones globales y códigos de salida

```text
mri-dataset [-h] [--version] [-q | -v] COMANDO ...
```

- `-q`, `--quiet`: oculta las líneas de estado; quedan los avisos, los errores y el resumen final.
- `-v`, `--verbose`: muestra los logs de depuración (que tampoco contienen rutas ni datos de pacientes).
- `--version`: versión instalada.

Las opciones globales van **antes** del comando: `mri-dataset --quiet process ...`.

| Código | Significado |
|---|---|
| **0** | Terminó. También si algunos estudios fallaron y se reportaron (el lote continúa). |
| **1** | Una salida ya existe, o una etapa completa falló (`Run failed...`). |
| **2** | Argumentos, clave, configuración o entrada inválidos. Se comprueba antes de crear nada. |

Los errores de cada archivo o estudio se cuentan por tipo de excepción (`Errors by type: {'ValueError': 1}`); el
mensaje y la ruta no se muestran porque pueden contener datos del paciente. Por la misma razón, un argumento mal
escrito no se repite: la CLI muestra el uso del comando y `error: Invalid arguments (see --help).` (código 2);
revise la línea con `--help`.

Con `--json` (`inspect`, `labels review`) la salida estándar contiene solo el JSON; los mensajes de error van a la
salida de errores (stderr), de modo que un fallo deja la salida estándar vacía.

## 4. Flujo recomendado

```text
inspect → dataset build (--format bids|dicom|nifti) → labels → dataset export-ml / report
```

- **Cualquier entrada llega al dataset:** `dataset build` acepta un BIDS (por defecto), un árbol DICOM
  (`--format dicom`) o una carpeta de NIfTI sueltos (`--format nifti`), y todas terminan en el mismo dataset BIDS
  anonimizado con etiquetas, particiones y reporte. Con DICOM **no hace falta convertir antes**.
- **Solo procesar (sin dataset):** `process` trabaja sobre NIfTI o BIDS; para DICOM, `convert dicom-to-nifti`
  primero. `convert` y `anonymize` siguen disponibles como pasos sueltos.
- **Camino corto con un BIDS:** `dataset build` hace en un solo paso pipeline + dataset + etiquetas + exportes +
  reporte. Los subcomandos `labels`, `dataset export-ml` y `dataset report` permiten rehacer cada parte por separado.
- **Etiquetar después del build:** pase `--classes` a `dataset build` (sin `--corrections`). Así se escribe la
  plantilla y, como las etiquetas quedan incompletas, se omiten los exportes para ML. Luego haga `labels apply`,
  `labels finalize` y por último `dataset export-ml`. **Sin `--classes`, `build` escribe los exportes para ML sin
  etiquetas** y un `export-ml` posterior falla con código 1 porque los archivos ya existen.

```text
mri-dataset dataset build E:/mri/bids --output-dir E:/mri/out --config config/stage3_bids.yaml --classes AD CN
mri-dataset labels apply E:/mri/out/dataset --corrections E:/mri/fix.tsv
mri-dataset labels finalize E:/mri/out/dataset
mri-dataset dataset export-ml E:/mri/out/dataset
```

## 5. Comandos

En los ejemplos, `E:/mri/...` es una carpeta de trabajo cualquiera; sustitúyala por la suya. Los conteos de las
salidas son ilustrativos.

### 5.1 `inspect`: ver metadatos (RF04)

```text
mri-dataset inspect PATH --format dicom|nifti|bids [--json]
```

Muestra, por estudio y serie, los metadatos técnicos de la lista blanca (forma, tamaño de voxel, affine,
orientación, tipo de dato, rango de intensidad y claves técnicas del sidecar BIDS). Nunca muestra ids, UIDs,
nombres ni fechas. NIfTI y BIDS se leen de a un estudio por vez; en DICOM solo se leen las cabeceras, así que
`dtype` e `intensity` salen vacíos (`null`). Un archivo ilegible se cuenta y el resto continúa.

```text
> mri-dataset inspect E:/mri/bids --format bids
Reading studies...
Study 1: 1 series
  Series 1
    modality: "T1w"
    shape: [176, 256, 256]
    voxel_size: [1.0, 1.0, 1.0]
    ...
    dtype: "int16"
    intensity: {"min": 0.0, "max": 989.0, "mean": 71.1, "std": 126.5, "non_finite_voxels": 0}
Studies: 1
Errors by type: none
```

Con `--json` la salida es `{"studies": [...], "errors": {"<Tipo>": n}}`, apta para otros programas.

### 5.2 `convert`: DICOM ↔ NIfTI (RF05)

```text
mri-dataset convert dicom-to-nifti IN OUT
mri-dataset convert nifti-to-dicom IN OUT
```

- `dicom-to-nifti`: un `study-NNN_series-MMM.nii.gz` por serie DICOM de `IN` (carpeta). Los archivos que no son
  DICOM (README, DICOMDIR, ...) también se cuentan en `Errors by type`.
- `nifti-to-dicom`: una serie DICOM (`OUT/study-NNN/`) por NIfTI 3D (`IN` archivo o carpeta). Los 4D se rechazan.
- `OUT` debe estar fuera de `IN` y vacía (o no existir): si tiene archivos, código 1.

```text
> mri-dataset convert dicom-to-nifti E:/mri/dicom E:/mri/nifti
Converting DICOM to NIfTI...
  file skipped or failed 1: InvalidDicomError
Studies converted: 3  series written: 5
Errors by type: {'InvalidDicomError': 1}
```

### 5.3 `anonymize`: anonimizar un árbol DICOM (RF09)

```text
mri-dataset anonymize IN OUT
```

Aplica la política v1 (`docs/anonymization/policy.md`) a cada archivo DICOM y escribe
`OUT/study-<id>/series-<id>/<id>.dcm` más `OUT/anonymization_report.json` (acciones por etiqueta, sin valores).
Requiere `MRI_ANON_KEY`. Los píxeles no se modifican: no borra caras ni texto quemado en la imagen.

```text
> mri-dataset anonymize E:/mri/dicom E:/mri/dicom_anon
Anonymizing DICOM files...
Files written: 120  failed: 0  policy: v1
Actions (64 tags): {'emptied': 360, 'generalized': 480, 'kept': 2400, 'removed': 1800, 'replaced': 480}
Errors by type: none
```

Si `anonymization_report.json` ya existe en `OUT`, código 1.

### 5.4 `process`: pipeline configurable (RF06–RF09, RF15)

```text
mri-dataset process IN --format nifti|bids --config CFG --output-dir OUT [--manifest-path P] [--verify]
```

Aplica los pasos de `CFG` a cada estudio de `IN`, uno a la vez, y escribe cada serie como NIfTI `float32`
(`study-NNN.nii.gz` para NIfTI sueltos, `study-NNN_series-MMM.nii.gz` para BIDS) y el manifiesto de la corrida
(por defecto en `report.path` de la configuración). El manifiesto registra pasos, parámetros, versiones y
resultados para reproducir la corrida; con el paso `anonymize` no contiene rutas de origen.

- `--verify`: reconstruye el pipeline desde el manifiesto guardado y lo vuelve a correr (sin escribir) para
  comprobar que se reproduce. Tarda el doble. Sin esta opción solo se comprueba que el manifiesto no tenga rutas.
- `--format dicom` no se admite: convierta primero con `convert dicom-to-nifti`.
- Si ya hay `study-*.nii.gz` en `OUT` o el manifiesto existe, código 1.

```text
> mri-dataset process E:/mri/bids --format bids --config config/stage3_bids.yaml --output-dir E:/mri/processed --manifest-path E:/mri/run.json --verify
Processing studies...
  error 1: ValueError
Writing the run manifest (3 studies, 2 files written)...
Verifying: running again from the saved manifest...
  replay error 1: ValueError
Studies: 3  ok: 2  failed in a step: 1  files written: 2
Errors by type: {'ValueError': 1}
Manifest without source paths: yes
Replay errors by type: {'ValueError': 1}
Reproduced from manifest: yes
```

Si una etapa falla (p. ej. la entrada no tiene estudios válidos) y la carpeta de salida la creó esta corrida y quedó
vacía, se borra (no así las carpetas padre intermedias que se crearon para ella ni la del manifiesto, ni la carpeta
si otro programa la bloquea). Termina con código 1 si `--verify` no reproduce la corrida, o si hay un paso `anonymize` y el manifiesto aún
contiene rutas. Sin `anonymize` el manifiesto guarda las rutas por diseño y se indica
`Manifest without source paths: no (no anonymize step; ...)`.

### 5.5 `labels`: etiquetas (RF11, RF12)

Una clase por (participante, sesión) de un dataset exportado, en `labels.tsv` y `labels.json` en su raíz
(`docs/dataset/labels.md`). Los ids del dataset son seudónimos; la consola no los muestra.

`labels`, `dataset export-ml` y `dataset report` solo aceptan un **dataset exportado por la herramienta** (su
`dataset_description.json` tiene `GeneratedBy` con `MRI-Dataset-Tool`, como el `OUT/dataset` de `dataset build`).
Con un BIDS de entrada terminan con código 2 sin escribir nada: así nunca se escriben etiquetas ni índices para ML
con los ids originales dentro de la entrada.

```text
mri-dataset labels template DATASET --classes NAME[=DESCRIPCIÓN] ...
mri-dataset labels review   DATASET [--json]
mri-dataset labels apply    DATASET --corrections TSV
mri-dataset labels finalize DATASET
mri-dataset labels reopen   DATASET
```

1. `template` escribe la plantilla con todos los pares sin etiquetar.
2. Prepare un TSV de correcciones con las mismas columnas que `labels.tsv`
   (`participant_id`, `session_id`, `label`) copiando los ids de `labels.tsv`; `apply` lo aplica todo o nada y lo
   registra en `labels_changes.tsv`.
3. `review` muestra pares, etiquetados, conteo por clase y defectos por código (`UNLABELED`, `UNKNOWN_CLASS`,
   `DUPLICATED`, `MISSING`, `NOT_IN_DATASET`, `INVALID_IDS`).
4. `finalize` cierra las etiquetas (exige la tabla completa) y guarda su huella en `labels_final.json`;
   `reopen` lo deshace.

```text
> mri-dataset labels review E:/mri/out/dataset
Pairs: 2  labeled: 0  classes: {'AD': 0, 'CN': 0}
Defects: {'UNLABELED': 2}
Complete: no
```

Editar `labels.tsv` a mano es posible pero no queda registrado; la huella lo detecta al exportar. Errores del
servicio (p. ej. aplicar correcciones a etiquetas cerradas) terminan con código 1 y solo el tipo:
`Labels apply failed: ValueError`.

### 5.6 `dataset`: construir, exportar y reportar (RF10, RF13, RF14)

```text
mri-dataset dataset build IN --output-dir OUT --config CFG [--format bids|dicom|nifti] [--mapping TSV]
                            [--classes ...] [--corrections TSV]
                            [--ratios TRAIN VAL TEST] [--seed N] [--allow-unfinalized]
mri-dataset dataset export-ml DATASET [--ratios TRAIN VAL TEST] [--seed N] [--allow-unfinalized]
mri-dataset dataset report DATASET OUT
```

- `build`: lee `IN` (BIDS por defecto; con `--format dicom` un árbol DICOM y con `--format nifti` NIfTI sueltos),
  aplica `CFG` (debe incluir `anonymize`; requiere `MRI_ANON_KEY`) y escribe
  `OUT/dataset` (BIDS con seudónimos) y `OUT/report`. `OUT` debe estar fuera de `IN` y ser nueva o una carpeta
  **vacía** (sin ningún archivo ni carpeta, ocultos incluidos); una `OUT` con contenido termina con código 1 sin
  tocar nada (`Output directory already exists; choose a new one.`), también si algo aparece en ella entre la
  validación y la escritura. Con `--classes`
  escribe la plantilla de etiquetas; `--corrections` (exige `--classes`) las asigna. Si quedan completas se cierran
  y se escriben los exportes para ML; si no, se avisa con `WARNING LABELS_INCOMPLETE` y se omiten salvo
  `--allow-unfinalized`.
- `build --format dicom|nifti`: la identidad y el sufijo BIDS de cada serie se deciden antes de crear nada
  (`docs/dataset/ingest.md`). DICOM: el participante es el `PatientID` seudonimizado y cada estudio es una sesión;
  NIfTI sin tabla: un participante por archivo. El sufijo (T1w, T2w, FLAIR, T2starw, PDw, dwi) sale de reglas
  conservadoras sobre la descripción de la serie o el nombre del archivo; lo dudoso se omite y se avisa con
  `WARNING UNMAPPED_SERIES: {código: n}` (`EXCLUDED`, `AMBIGUOUS`, `NO_MATCH`); un `dwi` que no es 4D se omite con
  `WARNING NOT_4D_DWI: n`. La tabla opcional `--mapping` (UTF-8, con o sin BOM; columnas `path`, `participant`,
  `session`, `suffix` y, opcional, `label`; `path` relativo a `IN`, con `/` y con las mayúsculas exactas)
  fuerza participante, sesión, sufijo o etiqueta; una fila que no aplica a ninguna serie se avisa con
  `WARNING MAPPING_UNUSED: n`. Con `label` (exige `--classes`) las etiquetas se aplican al dataset y, si quedan
  completas, se cierran: es la forma de etiquetar un DICOM, porque usted conoce sus carpetas, no los seudónimos.
  Los avisos salen también con `--quiet`.
- `export-ml`: escribe `dataset_index.csv`, `datalist.json`, `splits.tsv` y `splits.json` (particiones por
  participante, estratificadas, deterministas con `--seed`; por defecto 0.7/0.15/0.15 y semilla 0). Exige las
  etiquetas cerradas si existen, salvo `--allow-unfinalized`.
- `report`: escribe `dataset_report.{json,md,xml,xlsx}` (los cuatro o ninguno) en `OUT`, fuera del dataset.

```text
> mri-dataset dataset build E:/mri/bids --output-dir E:/mri/out --config config/stage3_bids.yaml --classes AD=Alzheimer CN
Exporting the dataset (pipeline)...
  error 1: ValueError
Studies written: 2  series: 2  participants: 2  errors: 1
Label template written (2 classes).
Label corrections: skipped (no --corrections).
WARNING LABELS_INCOMPLETE: {'UNLABELED': 2}
ML exports: skipped (labels incomplete; fix them or use --allow-unfinalized).
Report files written: 4
Errors by type: {'ValueError': 1}
Input files skipped by the reader: none
Report read errors: none
```

Con un árbol DICOM y una tabla de etiquetas:

```text
> mri-dataset dataset build E:/mri/dicom --format dicom --mapping E:/mri/map.tsv --output-dir E:/mri/out --config config/stage3_bids.yaml --classes AD CN
Exporting the dataset (pipeline)...
Studies written: 2  series: 2  participants: 1  errors: 0
WARNING UNMAPPED_SERIES: {'EXCLUDED': 1}
Label template written (2 classes).
Mapping labels applied: 2
Label corrections: skipped (no --corrections).
Labels finalized (2 labels).
ML export files written: 4
Report files written: 4
...
```

Después: `labels apply`, `labels finalize` y `dataset export-ml` sobre `E:/mri/out/dataset` (sección 4). Sin
`--classes`, `build` escribe los exportes para ML sin etiquetas y ese camino ya no está disponible en esa salida.

## 6. Uso de memoria

**Uso de memoria.** Antes de remuestrear (`resample`) o normalizar (`normalize`), la herramienta estima la memoria
que necesita el volumen de salida y la compara con la RAM disponible en ese momento. Si no alcanza, el estudio se
marca como fallido y el lote continúa con los demás. Puede forzar la ejecución con el parámetro
`allow_insufficient_memory: true` del paso `resample` o del paso `normalize` en el archivo de configuración; ese
consentimiento queda registrado en el manifiesto de la corrida. Hágalo bajo su responsabilidad: si la memoria no
alcanza, el equipo puede volverse muy lento por el uso de disco como memoria, otros programas pueden cerrarse, y
el proceso puede terminar abruptamente sin guardar resultados (en Linux, el sistema puede finalizarlo). La
comprobación es una estimación en un instante y no cubre la memoria de otros pasos ni de otros programas que se
abran durante la ejecución. Volúmenes 4D grandes, como las difusiones, pueden necesitar varios GB.

Además, `resample` rechaza cualquier salida de más de `max_output_voxels` vóxeles (por defecto 2**32 =
4 294 967 296, eje temporal incluido) con el error `Resampled volume would be too large.`, aunque haya memoria.
Ese límite se cambia solo en la configuración (`max_output_voxels` del paso `resample`) y también queda en el
manifiesto. La CLI no tiene ninguna opción para saltarse estas comprobaciones: el consentimiento solo se da en
el archivo de configuración.

Ejemplo (bajo su responsabilidad):

```yaml
pipeline:
  steps:
    - name: resample
      params: {spacing: [1.0, 1.0, 1.0], allow_insufficient_memory: true}
    - name: normalize
      params: {method: zscore, allow_insufficient_memory: true}
```

## 7. Errores frecuentes

| Mensaje | Causa y solución |
|---|---|
| `MRI_ANON_KEY is not set or is shorter than 32 characters; nothing was run.` | Defina la clave (sección 2). |
| `Invalid config: FileNotFoundError` | No se encontró `config/default.yaml`: ejecute desde la raíz del repositorio. |
| `Invalid config: ValueError` | YAML inválido, clave no admitida o paso/parámetro desconocido (`docs/architecture/config.md`). |
| `Output directory is not empty; use a new one.` / `Outputs of a previous run exist ...` / `... already exists` | La CLI no sobrescribe: borre la salida anterior o use otra carpeta. |
| `Outputs of a previous run exist ...` en `process` con una carpeta nueva | `--manifest-path` debe ser un archivo `.json`: si apunta a un directorio existente cuenta como salida previa (código 1). |
| `Output directory must not be inside the input.` (y variantes) | La salida no puede estar dentro de la entrada. |
| `DICOM input: convert it first with 'mri-dataset convert dicom-to-nifti'.` | `process` no lee DICOM. |
| `The pipeline must include the anonymize step.` | `dataset build` exige anonimizar para que el dataset tenga seudónimos. |
| `Run failed at <etapa>: <Tipo>` | Falló una etapa completa (p. ej. no hay estudios válidos, disco lleno). Borre la salida parcial antes de reintentar. Con `--verbose` verá logs de depuración (sin rutas). |
| `Errors by type: {'ValueError': n}` con código 0 | Algunos estudios fallaron (p. ej. valores NaN, memoria insuficiente); el resto se procesó. |
| `Labels finalize failed: ValueError` | Las etiquetas no están completas: revise con `labels review`. |
| `Not a dataset exported by this tool.` | `labels`, `export-ml` o `report` recibieron un BIDS de entrada u otra carpeta; use el `OUT/dataset` de `dataset build`. |
| `error: Invalid arguments (see --help).` | Falta un argumento, sobra uno o tiene un valor no admitido; el valor no se repite por privacidad. Revise con `--help`. |
| `WARNING UNMAPPED_SERIES: {...}` | Series sin sufijo seguro (localizadores, mapas derivados, nombres ambiguos...): se omiten. Fuerce el sufijo con `--mapping` si corresponde (`docs/dataset/ingest.md`). |
| `WARNING MAPPING_UNUSED: n` | Filas de `--mapping` que no aplican a ninguna serie (p. ej. una carpeta sin DICOM). |
| `WARNING MISSING_PATIENT_ID: n` | Estudios DICOM con algún archivo sin `PatientID` y sin participante en `--mapping`: cada uno queda como un participante propio y el paciente puede partirse. Use una fila con la carpeta del estudio. |
| `Mapping paths not found in the input: N.` | `path` de la tabla que no existe en la entrada (relativo a `IN`, con `/`). |
| `Invalid --mapping.` | Cabecera, columnas, `path`, ids o sufijo inválidos en la tabla. |
| `Mapping labels need --classes.` / `Mapping label is not one of --classes.` | La columna `label` exige `--classes` y una de esas clases. |
| `Mapping assigns different labels to the same participant/session.` / `Mapping gives one study more than one participant or session.` | Filas en conflicto: revise las filas más profundas. |
| `Mapping gives the same participant/session to more than one study.` | Dos estudios quedarían en el mismo par (p. ej. fila `.` con sesión): asigne la sesión por carpeta de estudio. |
| `Mapping gives a participant both sessions and no session.` | Un participante tiene series con sesión y sin sesión: dé sesión a todas o a ninguna. |
| `WARNING NOT_4D_DWI: n` | Series reconocidas como `dwi` cuyo volumen no es 4D (mapas derivados): se omiten. |
| `--mapping needs --format dicom or nifti.` | Con BIDS los ids y sufijos salen de los nombres; la tabla no se admite. |
| `No input series could be mapped to a BIDS suffix.` | Ninguna serie con sufijo seguro: use `--mapping`. |
| `ML exports failed: ValueError` | Etiquetas sin cerrar: `labels finalize` o `--allow-unfinalized`. |
| `ML export files already exist.` tras `dataset build` | `build` sin `--classes` ya escribió los exportes (sin etiquetas). Para etiquetar después, repita `build` en una carpeta nueva con `--classes` (sección 4). |

## 8. Límites conocidos

- No hay interfaz gráfica ni revisión interactiva de etiquetas: la revisión es por archivos.
- `inspect --format dicom` solo lee cabeceras (sin intensidades).
- `nifti-to-dicom` rechaza volúmenes 4D; el DICOM escrito no es conforme estricto al IOD MR (`docs/dicom/writer.md`).
- La anonimización no borra caras ni texto quemado en los píxeles y conserva cuasi-identificadores
  (`docs/anonymization/policy.md`).
- El dataset BIDS no incluye `.bval/.bvec` para `dwi` ni `EchoTime1/2` para `phasediff` (el `bids-validator` lo marcará).
- `dataset build --format dicom|nifti`: sufijos solo por reglas conservadoras o por tabla; `magnitude1/2` y
  `phasediff` solo por tabla; `--mapping` no se admite con `--format bids` (`docs/dataset/ingest.md`).
- La CLI no muestra rutas: el usuario conoce las que pasó como argumentos.
