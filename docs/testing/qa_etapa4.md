# QA4 — Auditoría adversarial de la etapa 4 (dataset)

Rama `etapa-4-dataset`, HEAD `25bdc86` (2026-10-22). Pruebas en `tests/qa/test_qa4_{phi_sweep,hostile_inputs,invariants}.py`:
`tests/qa/` da 235 pruebas que pasan y 9 `xfail(strict=True)`, una por cada defecto abierto. Cuando se corrija un
defecto, su prueba pasará y fallará por el `strict`: hay que quitar el marcador. Ningún informe, prueba ni log
contiene datos reales; los valores plantados son sintéticos y todos contienen `Planted`.

## 1. Hallazgos

| Id | Severidad | Qué pasa | Reproducción mínima (sin PHI) | Esperado | Archivo / dueño | Estado |
|---|---|---|---|---|---|---|
| QA4-01 | **bloqueante** | El lanzador aceptaba un `--config` sin `anonymize` y escribía el dataset con los ids de origen (nombres de carpeta y archivo, `participants.tsv`, `labels.tsv`, índice), con código 0 | Config con solo `validate`; BIDS `sub-JohnDoe` | Rechazo antes de crear nada (el plan dice "el lanzador lo exige") | `scripts/run_stage4_dataset.py` (E2) | **Corregido** en `23b7490`; se volvió a probar: código 2 y nada creado (`test_launcher_refuses_a_pipeline_without_anonymize`) |
| QA4-09 | mayor | Con `labels.json` y `labels_final.json` presentes pero sin `labels.tsv` (renombrado, o "guardar como" en Excel), `write_ml_exports` escribe las exportaciones sin etiquetas y sin estratificar (`stratified: false`, `labels_finalized: null`), sin aviso | Dataset con etiquetas cerradas; renombrar `labels.tsv` → `labels.txt`; llamar a `write_ml_exports` | Error fijo: hay etiquetas declaradas o cerradas sin su tabla | `application/services/dataset.py` (@dataset) | Abierto |
| QA4-03 | menor (deuda conocida) | `find_nifti_files` ordena objetos `Path`, y en Windows esa comparación ignora mayúsculas. Con `acq-B` y `acq-a` en un mismo estudio, `run-1` es `acq-a` en Windows y `acq-B` en Linux: el mismo input da datasets distintos según el SO | Dos T1w de un sujeto con `acq-B` y `acq-a` | El mismo orden en todo SO (p. ej. por `as_posix()`) | `infrastructure/bids/reader.py` (congelado) | Abierto, requiere `PROPUESTA DE CONTRATO` |
| QA4-04 | menor | Una clase con un carácter de control (p. ej. `\x01`) pasa `LabelTable` (y la validación de `--classes`); después `report_dataset` falla siempre con `"Report content is invalid."` | `write_label_template(ds, {"A\x01": "x", "B": "y"})`; `report_dataset` | Rechazar la clase en `LabelTable` | `infrastructure/dataset/labels.py` (@etiquetas) | Abierto |
| QA4-05 | menor | `BIDSDatasetWriter` escribe volúmenes 2D y 5D en `anat/` (el pipeline los rechazaría en `validate`; solo con `export_dataset(pipeline=None)`) | `add_study` con un volumen `(4, 4)` | `on_error` con mensaje fijo | `bids_writer.py` (@dataset) | Abierto |
| QA4-06 | menor | float64 fuera del rango de float32 se escribe como `inf`, con solo un `RuntimeWarning` | Volumen lleno de `1e300` | Error por serie, o documentarlo | `bids_writer.py` (@dataset) | Abierto |
| QA4-07 | menor | Una carpeta `sub-x` sin imágenes cuenta como par del dataset: entra en la plantilla y `finalize_labels` exige etiquetarla | `mkdir sub-ghost` en el dataset | Pares a partir de las imágenes | `application/services/labels.py` (@etiquetas) | Abierto |
| QA4-08 | menor (solo Windows, solo sin `anonymize`) | Dos ids que solo difieren en mayúsculas (`AB`/`ab`) comparten carpeta: `dataset_pairs` pierde uno y `write_ml_exports` falla con "outside the BIDS layout". Con QA4-01 corregido, los seudónimos son hex en minúsculas y no pueden chocar así | `export_dataset([sub AB ses 01, sub ab])` | Detectar el choque al escribir | `bids_writer.py` (@dataset) | Abierto, bajo riesgo |
| QA4-10 | menor | `--classes A=uno A=dos` se queda en silencio con la última descripción | `parse_classes(["A=first", "A=second"])` | `Invalid --classes.` | `scripts/run_stage4_dataset.py` | Abierto |
| QA4-11 | observación (RNF03) | La consola imprime `errors: 0` al exportar y después `Errors by type: {'ValueError': 86}`: `DatasetReport.errors` no cuenta los errores del lector, que llegan directo al `on_error` | Corrida real (§3) | Una sola cifra, o etiquetarlas | `dataset.py` / lanzador | Abierto, sin prueba |

**Sospechas no confirmadas como defecto:**
- Un NIfTI ajeno dentro del dataset bloquea las exportaciones para ML (documentado), pero el reporte lo cuenta y usa
  su sufijo como nombre de modalidad (texto de un nombre de archivo).
- `labels_final.json` es una huella, no una firma: se puede falsificar recalculando el hash (`class_counts` queda
  desactualizado sin error). Está bien para detectar ediciones accidentales; no protege contra una edición deliberada.

## 2. Qué se probó (pasa)

- **Barrido de PHI de punta a punta**, con el lanzador en DEBUG, `--classes`, `--corrections` y luego una
  corrección, cierre, reapertura, nuevo cierre y un segundo reporte. Se plantaron valores en:
  - los ids `sub`/`ses`, las entidades `acq`/`dir`/`task` y la carpeta raíz de entrada (con `ñ` y espacios);
  - `participants.tsv`, `README` y `dataset_description.json` de la entrada;
  - un sidecar heredado en la raíz y valores no escalares bajo claves permitidas;
  - los campos `descrip`, `aux_file`, `intent_name` y `db_name` y una extensión NIfTI;
  - un `.git` oculto, un `bold` (no soportado), una columna extra con texto en el archivo de correcciones y una
    etiqueta escrita a mano que una corrección reemplaza (la bitácora registra `<invalid>`).

  Se buscaron en cada nombre y en cada contenido (partes del zip XLSX, cabecera y extensiones NIfTI), en la consola
  y en los logs DEBUG, junto con las rutas de entrada y salida y el nombre de usuario: **cero apariciones**. Los
  sidecars solo llevan escalares permitidos.
- **Entradas hostiles:**
  - correcciones con comillas, fórmulas (`=`, `+`), tabulador final, espacios, Unicode, NUL, UTF-16, duplicadas,
    pares ajenos o columnas faltantes: rechazo total con mensaje fijo, sin tocar `labels.tsv` ni la bitácora;
  - `labels_final.json` malformado (`[]`, `null`, hash no texto, bytes inválidos, vacío): cuenta como no cerrado;
  - bitácora sin salto de línea final;
  - `.bidsignore` y `.git` en el dataset;
  - `.nii.gz` perezoso truncado: se reporta y el resto se escribe, sin temporales ni carpetas vacías;
  - volumen complejo, corte único y 4D de un solo volumen;
  - rutas Unicode con espacios de más de 260 caracteres (en esta máquina `LongPathsEnabled = 1`);
  - manifiesto editado con `=HYPERLINK`/`@SUM`: el XLSX no tiene ninguna celda `<f>`;
  - configuraciones inválidas (paso desconocido, parámetros o YAML inválidos): código 2 sin crear nada.
- **Invariantes:**
  - escribir y releer conserva la geometría oblicua, de un corte y 4D, y los vóxeles float32 bit a bit;
  - el dataset y sus exportaciones son idénticos con el orden de entrada invertido;
  - la salida del lanzador es igual en dos procesos con `PYTHONHASHSEED` distinto (sin contar marcas de tiempo
    ni los bytes del XLSX; las celdas sí son iguales);
  - en 16 combinaciones de semilla × proporciones, con participantes de varias sesiones y clases mezcladas,
    ningún participante cruza particiones, `datalist` cubre todas las imágenes una sola vez y una proporción 0
    deja su partición vacía;
  - `assign_splits` no depende del orden del mapeo;
  - la huella de etiquetas ignora el orden de filas, el BOM y CRLF, y una edición de etiqueta la rompe.
- **Memoria (RNF02):** `tracemalloc` con 3 frente a 30 estudios de 48×48×40, con el pipeline de la etapa 3 completo:
  exportación 6,0 frente a 6,2 MiB y reporte 5,1 frente a 5,1 MiB. El pico no crece con el lote.
- **Cobertura:** no hay `coverage` ni `pytest-cov` instalados y no instalé nada. Medí con `trace` de la biblioteca
  estándar sobre las pruebas unitarias y de integración de la etapa 4: 86–100 % por módulo. Los huecos reales son
  las ramas de I/O fallido (`OSError` al crear la raíz, al leer etiquetas o al escribir la bitácora con su
  reversión, y la escritura atómica de `_write_bytes`) y el callback que lanza en `export_dataset`.

## 3. Corrida real (solo lectura de `data/raw`, salida en `E:/mri_qa4/`)

`run_stage4_dataset.py data/raw/bids_test_studies/ds005299 --output-dir E:/mri_qa4/real1 --classes A B --seed 5`,
con la clave desechable que el humano dejó en la variable de usuario (no se imprimió). Después, con los servicios:
correcciones para los 27 pares, cierre, exportaciones para ML y un segundo reporte. `git status data/` quedó limpio.

| Medida | Resultado |
|---|---|
| Lanzador | 548 s, RAM pico 1.808 MB (árbol de procesos). `Studies written: 27 series: 76 participants: 1`; `Errors by type: {'ValueError': 86}`, los 86 punteros de git-annex ya conocidos (QA3) |
| Etiquetas | Plantilla escrita; `LABELS_INCOMPLETE: UNLABELED 27` y exportaciones para ML omitidas, como está documentado; después, 27 correcciones, cierre y 4 archivos de exportación |
| Particiones | 1 participante → todo a `training`, aviso `FEW_PARTICIPANTS` (esperado) |
| Relectura con `BIDSBatchReader` | T1w 27, T2w 27, magnitude1 6, magnitude2 6 y phasediff 5, todas 3D a 1 mm; dwi 5, 4D a 2 mm. Todo RAS y float32 (coincide con QA3) |
| Barrido | Valores de entidad de la entrada (de 3 o más caracteres), rutas, usuario: 173 archivos revisados. Las únicas coincidencias son falsos positivos: el valor `acq-dwi` coincide con la carpeta `dwi/` y con la clave `PixelBandwidth` |
| Consola y logs | Cero `sub-`/`ses-` y cero rutas |

## 4. Verificaciones manuales pendientes (humano)

1. Correr el `bids-validator` oficial sobre `E:/mri_qa4/real1/dataset`. Se esperan errores ya documentados:
   dwi sin `.bval`/`.bvec`, phasediff sin `EchoTime1/2` y archivos de etiquetas y exportación sin `.bidsignore`.
2. Abrir en un visor dos imágenes de `E:/mri_qa4/real1/dataset` (una anatómica y una dwi) y confirmar orientación
   y espaciado.
3. Revisar `E:/mri_qa4/real1/report_final/` (los cuatro formatos; el XLSX en Excel) y la tabla de etiquetas.
4. Buscar identificadores conocidos del dataset real en `E:/mri_qa4/real1` (yo solo busqué los valores de los
   nombres de archivo).
5. `pytest` en Linux (además confirma QA4-03 del otro lado).
6. Borrar la variable de usuario `MRI_ANON_KEY` y, cuando ya no sirvan, `E:/mri_qa4/`.
