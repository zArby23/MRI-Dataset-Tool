# QA5 — Auditoría adversarial de la etapa 5A (CLI)

Rama `etapa-5-cli`. La auditoría empezó sobre `9cbb591` y se cerró sobre `a819037` (2026-10-25), que incluye C7
(aviso de espacio en disco) y C8 (correcciones de QA5). Pruebas en `tests/qa/test_qa5_{cli,memory,disk_space}.py`:
55 pasan y 1 se omite en Windows (la de QA5-07: crear symlinks exige privilegios), sin `xfail`: todos los hallazgos
con prueba están corregidos (C8, C9).
Ninguna prueba ni informe contiene datos reales; los valores plantados son sintéticos y contienen `Planted`.

## 1. Hallazgos

| Id | Severidad | Qué pasa | Reproducción mínima (sin PHI) | Esperado | Archivo / dueño | Estado |
|---|---|---|---|---|---|---|
| QA5-01 | **importante** | Los comandos que reciben `DATASET` (un dataset exportado) aceptan cualquier directorio. Sobre un BIDS de **entrada** sin anonimizar, `labels template` y `dataset export-ml --allow-unfinalized` escriben dentro de la entrada `labels.tsv`, `labels.json`, `dataset_index.csv`, `datalist.json`, `splits.tsv` y `splits.json`, con los ids `sub-`/`ses-` de origen (todos menos `labels.json` y `splits.json`), y terminan con código 0. Modifica la entrada, cosa que el resto de la CLI impide. Además, produce un índice para ML con identificadores reales, y es justo el archivo que se comparte. No hay pérdida de datos: no sobrescribe nada | BIDS `sub-PlantedSubjA/ses-PlantedSesA/anat/..._T1w.nii.gz`; `mri-dataset labels template <bids> --classes A B` o `mri-dataset dataset export-ml <bids> --allow-unfinalized` | Rechazar con código 2 un directorio que no sea un dataset exportado (p. ej., sin `code/run_manifest.json` o sin `GeneratedBy` de la herramienta en `dataset_description.json`), sin crear nada | `presentation/cli/commands/{labels,dataset}.py` (@cli); quizá una comprobación compartida en `application/services` | **Corregido** (C8, `dataset_build.is_exported_dataset`: `GeneratedBy[].Name == "MRI-Dataset-Tool"`); los comandos `labels *`, `dataset export-ml` y `dataset report` salen con código 2 (`Not a dataset exported by this tool.`) antes de escribir. Se volvió a probar: `test_dataset_commands_refuse_a_raw_input` y `test_raw_or_malformed_description_is_not_a_dataset` (14 descripciones × 7 comandos: BIDS crudo con su propia descripción, `GeneratedBy` vacío, objeto, cadena, lista de cadenas, otro `Name`, otras mayúsculas, espacio final, clave `name`, `Name` lista, raíz lista, JSON inválido, no UTF-8, directorio) → 2 y árbol intacto |
| QA5-02 | menor | Los errores de `argparse` repiten en stderr el valor tecleado: `invalid choice: 'sub-…'`, `unrecognized arguments: E:/pacientes/sub-…` (p. ej., una ruta pasada sin su opción) e `invalid float/int value: '…'`. Riesgo: solo lo que el propio usuario escribió y solo en su terminal. Pero si la CLI corre dentro de un script, de CI o de un registro de sesión, la ruta con `sub-<id>` queda en ese registro. Viola la letra de RNF07 («consola sin rutas ni ids») | `mri-dataset inspect <dir> --format bids E:/x/sub-PlantedSubjA` | Mensaje fijo con el uso, sin el valor (p. ej., `error()` propio en el parser que no imprima el argumento) | `presentation/cli/main.py`, `_common.py` (@cli) | **Corregido** (C8); `test_argparse_errors_do_not_echo_typed_values` pasa sin `xfail` |
| QA5-03 | menor (RNF03) | Los mensajes de error van a **stdout**, no a stderr. Con `--json`, un fallo (`Input path not found.`, `Run failed: …`) deja en stdout texto que no es JSON. El código de salida sí es correcto | `mri-dataset inspect <vacío> --format bids --json` → stdout `Run failed: ValueError`, código 1 | Errores en stderr, o un JSON `{"error": "<tipo>"}` con `--json` | `presentation/cli/commands/*.py` (@cli) | **Corregido** (C8) para `--json`: los errores van a stderr y stdout queda vacío (`inspect --json` sobre un directorio vacío o inexistente; `labels review --json` sobre un directorio que no es un dataset). Sin `--json`, los errores siguen en stdout, junto con los estados; se acepta |
| QA5-04 | menor | `process` sobre un directorio sin estudios válidos crea `--output-dir` vacío y sale con código 1 (`Run failed at process: ValueError`). El contrato solo exige no crear nada con el código 2, así que no lo incumple, pero deja una carpeta vacía | `mri-dataset process <vacío> --format nifti --config … --output-dir O --manifest-path M` | Crear el directorio de salida al escribir el primer archivo, o borrarlo si queda vacío | `application/services/pipeline_run.py` (@cli) | **Corregido** (C8): tras el fallo no queda el directorio de salida (comprobado como subproceso) |
| QA5-05 | observación (conocida) | El `mri-dataset` instalado solo funciona desde la raíz del repositorio: en otro directorio, `process` y `dataset build` salen con código 2 y `Invalid config: FileNotFoundError` porque `config/default.yaml` se lee desde el directorio actual. Está documentado en el manual (§ Configuración, tabla de errores), pero limita el punto de entrada instalado | `cd E:/; mri-dataset process …` | Resolver `config/` desde el paquete o el repositorio, o aceptar `--config-dir` | `infrastructure/config/loader.py` (congelado) / @cli | Documentado; decisión del humano |
| QA5-06 | observación (conocida) | Un `--manifest-path` que apunta a un directorio existente se informa como «salida de una corrida previa» (código 1) | `--manifest-path E:/existente` | Mensaje propio, código 2 | `commands/process.py` | Documentado en el manual |
| QA5-07 | menor (solo Linux/macOS, C7) | `estimate_input_bytes` usa `lstat` y solo suma archivos regulares, así que no cuenta los symlinks. En un dataset de git-annex o DataLad en Linux, cada imagen es un symlink a `.git/annex/objects` (que además se omite por oculto): la estimación da ≈ 0 y el aviso no sale nunca, justo con los lotes grandes. Los lectores sí siguen los symlinks | Un `sub-01_T1w.nii.gz` que es symlink a un archivo de 4 KiB: `estimate_input_bytes(dir) == 0` | Sumar el tamaño del destino (`os.stat`) de los symlinks a archivos que se leerán, sin entrar en bucles | `application/services/disk_space.py` (@cli) | **Corregido** (C9): sigue los symlinks a archivo (`os.stat`); un enlace roto cuenta 0 y los symlinks a directorio no se siguen. Se revisó el código y se quitó el `xfail`. La prueba `test_symlinked_input_files_count_toward_the_estimate` se omite en Windows; en Linux debe pasar (pendiente del humano) |

**Cambio en las pruebas por C8:** en `test_empty_inputs_fail_without_traceback`, `labels review` y `dataset report`
sobre un directorio vacío esperaban 1 y ahora esperan 2: un directorio sin `dataset_description.json` de la
herramienta es una entrada inválida y se rechaza antes de leer.

**Riesgo residual de QA5-01:** el criterio es una marca, no una prueba de anonimización. Un BIDS crudo cuyo
`dataset_description.json` declare a mano `GeneratedBy: [{"Name": "MRI-Dataset-Tool"}]` pasa la comprobación. Es una
falsificación deliberada, no un error accidental; se acepta igual que la huella de `labels_final.json` (QA4).

**Sospechas no confirmadas como defecto:**
- Las abreviaturas de `argparse` (`allow_abbrev`, activado por defecto) aceptan `--out` por `--output-dir` y `--allow` por
  `--allow-unfinalized`. Hoy no hay ambigüedad entre opciones, pero si en el futuro se añade una opción con el mismo
  prefijo, cambiará en silencio el significado de lo que ya se tecleaba.
- Ctrl+C o una tubería cerrada (`| head`) imprimen un traceback de Python. Muestra líneas de código, no valores, así que
  el riesgo de PHI es bajo; no se probó.

## 2. Qué se probó (pasa)

- **Rutas con Unicode y espacios en todo el flujo**, como subproceso real (`python -m …`) en DEBUG: la raíz de entrada
  `Ñandú PlantedRoot datos`, la salida `salida con espacios ü`, el manifiesto `manifiesto é.json` y las correcciones
  `corrección ñ.tsv`. Se corrió `inspect --json`, `process --verify` y `dataset build` con clases y correcciones. Ni
  stdout, ni stderr, ni los nombres o contenidos de los archivos de texto de salida muestran la raíz, los ids plantados,
  el PHI del sidecar, `descrip` ni la clave. No aparece ningún traceback.
- **Rutas largas en Windows** (> 300 caracteres; `LongPathsEnabled=1` en esta máquina): `dataset build` termina con
  código 0. Los caracteres inválidos en Windows (`a<b>|c`) dan `Run failed at process: OSError` con código 1, sin
  traceback.
- **Clases hostiles** (`=x`, repetidas con distinta descripción, tabulador, `\n`, `\x00`, `@SUM(1)`, `+A`, `=A`,
  espacios en los bordes): código 2 con `Invalid --classes.` y nada creado. `-A` lo rechaza argparse (código 2).
  Aceptadas, correctamente: `A=B=C`, `A` y `a` a la vez, `Ñ`, y descripciones que empiezan por `+` o `@` (la
  descripción va solo a `labels.json`).
- **Ratios** NaN, Inf, negativos, `1e308` o que no suman 1: código 2 y nada creado, en `build` y en `export-ml`.
- **Semillas extremas:** `10**40` y `-7` funcionan (`random.Random`) y la misma semilla da las mismas particiones.
- **Clave ausente, vacía o de 31 caracteres:** `anonymize`, `process` y `build` salen con código 2, el mensaje fijo y
  nada creado. La clave nunca se imprime.
- **Código 2 deja el árbol intacto** (tamaño y `mtime` de cada archivo) en 11 casos: salida dentro de la entrada para
  `convert` (en los dos sentidos), `anonymize` y `dataset report`; manifiesto dentro de la entrada; config inválida
  (`spacing` 0) en `process` y `build`; `--format dicom` en `process`; correcciones sin `--classes`; correcciones
  inexistentes; un archivo como entrada DICOM.
- **«Salida dentro de la entrada» resistente a alias:** con otras mayúsculas, con `..` y a través de una junction de
  Windows, `convert`, `dataset report` y `process` salen con código 2 y no crean nada.
- **Entradas vacías:** `inspect` (bids, nifti), `convert`, `process` y `build` sobre un directorio vacío salen con
  código 1, sin traceback y sin rutas; `labels review` y `dataset report`, con código 2 desde C8.
- **Invariantes:**
  - `scripts/run_stage3_bids_pipeline.py` y `process --verify` escriben NIfTI idénticos byte a byte y el mismo
    manifiesto (sin `timestamps`).
  - `scripts/run_stage4_dataset.py` y `dataset build` producen el mismo árbol y los mismos bytes en todos los archivos,
    salvo los que llevan fecha: `run_manifest.json` (igual sin `timestamps`), `labels_changes.tsv` (igual sin la
    columna de hora) y `dataset_report.*`.
  - Dos corridas de `process` escriben los mismos bytes.
  - `--quiet` solo imprime los resultados.
  - La comparación CLI = servicios ya la hace E5 (`test_cli_equals_services`); no se repite.
- **Memoria (RNF02):** `process` (validate → reorient → normalize) con volúmenes de 128×128×96 en float32 (6 MiB por
  estudio), en procesos nuevos, sobre `E:/`. El pico de memoria residente es de 127 MiB con 5, con 20 y con 40
  estudios: no crece con el lote (`test_process_peak_memory_does_not_grow_with_the_batch`; tolera 3 estudios de
  diferencia).
- **Aviso de espacio en disco (C7)**, a través de `main` y con `shutil.disk_usage` falseado:
  - **Umbral:** sale cuando la estimación (el tamaño de la entrada) alcanza el 90 % del espacio libre (`required >=
    free * 0.9`) y no sale justo por debajo (`test_threshold_through_the_cli`). El borde exacto ya lo cubre la prueba
    unitaria.
  - **Texto fijo y siempre visible:** en `convert`, `anonymize`, `process` y `dataset build` el aviso aparece una sola
    vez, también con `--quiet`. Solo lleva cifras en GiB (`WARNING INSUFFICIENT_DISK_SPACE: estimated output X GiB, Y
    GiB free on the output drive; consider another drive.`), sin rutas ni valores plantados.
  - **No cambia nada más:** el código de salida y el conjunto de archivos escritos son los mismos que sin aviso.
  - **Otro disco:** con la entrada en `C:` y una salida aún inexistente en `E:/…/deep/missing`, se consulta el
    ancestro existente en `E:`, no el disco de la entrada.
  - **Letra de unidad inexistente:** no hay aviso ni traceback; `process` sale con código 1 y `Run failed at
    process: FileNotFoundError`.
  - **UNC:** un recurso compartido inalcanzable (`\\host-inexistente\share`) no da aviso (el espacio libre se
    registra como desconocido). Uno alcanzable (`\\localhost\C$`) lee el espacio libre real. Un host que rechaza el
    recurso tarda ~3,5 s en descartarse; la CLI no se cuelga.
- **Cobertura:** `coverage`/`pytest-cov` no están instalados; por decisión de @orquestador no se mide.

## 3. Corrida real (`data/raw`, solo lectura; salida en `E:/qa5_real`)

- **Primer intento (BIDS completo y todos los comandos):** Claude Code lo detuvo durante el primer comando por falta de
  memoria en el sistema. No hubo resultados y, por indicación de @orquestador, no se reintentó.
- **Corrida acotada (2026-10-25), con el OK del humano tras liberar memoria:** 7,4 GiB de RAM libre al empezar.
  - **Comandos:** `inspect --format nifti --json` y `process --format nifti --verify` sobre
    `data/raw/nifti_test_studies` (6 estudios 3D, lectura perezosa). Pipeline validate → anonymize → reorient →
    normalize, sin resample. La clave es aleatoria y solo vive en el entorno del subproceso; nunca se imprime ni se
    guarda, y no hay variable de usuario que borrar.
  - **Resultados:** `inspect` sale con código 0 (7 s) y `process --verify` con código 0 (15 s). El código 0 implica un
    manifiesto sin rutas de origen y reproducido. Se escribieron 6 NIfTI y el manifiesto. La RAM libre se mantuvo en
    7,4–7,5 GiB.
  - **Barrido:** las rutas de la entrada y del repositorio y los nombres de los archivos de origen aparecen 0 veces en
    la consola (en DEBUG), en los nombres de salida, en el manifiesto y en las cabeceras NIfTI. Sin tracebacks.
  - **Entrada:** intacta (`mtime` de cada archivo).
- **No corrido con datos reales:** DICOM (`convert`, `anonymize`, `inspect --format dicom`) y BIDS (`dataset build`).
  Ya los cubrían las corridas reales de QA4 y de las etapas anteriores; con la RAM actual queda para el humano (§5, 2).

## 4. No verificado

- **QA5-07 en Linux:** la prueba se omite en Windows; queda comprobar en Linux que pasa.
- **Linux:** no hay entorno. La prueba de memoria usa `ru_maxrss` allí; no se ejecutó.

## 5. Verificaciones manuales para el humano

1. `pip install -e .` en un entorno limpio y `mri-dataset --help` desde un directorio que no sea el repositorio
   (ver QA5-05).
2. Hacer el recorrido real del checkpoint (inspect → process → labels → dataset build) sobre DICOM y BIDS, con
   salida en `E:/` y la máquina libre de memoria (§3).
3. Comprobar en un terminal que, tras C8, un argumento inválido ya no repite lo tecleado (QA5-02).
4. `pytest` en Linux, incluido `tests/qa/test_qa5_memory.py`.
5. En Linux, un dataset de DataLad/git-annex: comprobar QA5-07 (el aviso de disco no sale).
