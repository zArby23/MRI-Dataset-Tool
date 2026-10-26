# QA6: auditoría adversarial de la ingesta DICOM/NIfTI (etapa 5B)

Esta auditoría se hizo sobre la rama `etapa-5b-gui` (base `44ffa77`, igual a `main`) el 2026-10-26. Cubre
`dataset build --format dicom|nifti`, `--mapping`, `suffix_rules`, `identity`, `dataset_ingest` y
`dataset_build`. Las pruebas están en `tests/qa/test_qa6_ingest.py`. Tras los arreglos de @gui (QA6-01 a 04 y 06,
verificados de nuevo) pasan las 67, sin `xfail`. Las pruebas y este informe no contienen datos reales: los valores plantados son
sintéticos y contienen `Planted`.

## 1. Hallazgos

| Id | Severidad | Qué pasa | Reproducción mínima (sin PHI) | Esperado | Archivo / dueño | Estado |
|---|---|---|---|---|---|---|
| QA6-01 | **bloqueante** | Los UIDs DICOM no conformes salen en la consola y en los logs. pydicom 3.0.2 valida cada valor al leerlo (`reading_validation_mode = WARN`). Ante un UI con caracteres fuera de `[0-9.]`, llama a `warn_and_log("Invalid value for VR UI: '<valor>' …")`, y el valor llega dos veces a stderr: como `UserWarning` y por el logger `pydicom` (`WARNING:pydicom:…`). Pasa también con `--quiet`. El árbol de salida queda limpio. PatientID, SeriesDescription y ProtocolName (VR LO) solo provocan avisos de longitud, sin el valor. Modality (CS) también se repite, pero no es PHI | `write_synthetic_series(d, StudyInstanceUID="1.2.PlantedStudyUid.9", SeriesInstanceUID="1.2.PlantedSeriesUid.1")`; luego `mri-dataset --quiet dataset build d --format dicom …` (14 líneas en stderr con los UIDs) o `mri-dataset --quiet inspect --format dicom d` (8 líneas) | Consola y logs sin UIDs (MEMORY §3) | Todo punto de lectura DICOM (ver la lista siguiente): `infrastructure/dicom/` (congelado; excepción para @gui) | **Corregido** (@gui): el gestor de contexto `quiet_value_validation()` de `_study_assembler.py` fija `reading_validation_mode = IGNORE` durante la lectura. Pasan las 9 pruebas. Además se comprobó por subproceso que `convert dicom-to-nifti`, `anonymize` y `dataset build` dejan stderr vacío, y que los avisos de decodificación de juego de caracteres (`Failed to decode … UTF8`) no citan el valor. La prueba de lectura tenía un defecto, que señaló @gui: `caplog` también recogía los avisos de pydicom al **escribir** el árbol sintético. Se corrigió con `caplog.clear()`. El ajuste es de todo el proceso. Luego se protegió con un contador y un `threading.Lock` (el primer hilo que entra lo fija y el último que sale lo restaura), con una prueba de dos hilos en `test_dicom_reader.py`; el código se revisó. Queda verificarlo en QA7 con la GUI real |
| QA6-02 | **importante** | El FLAIR 3D de Siemens abreviado `da-fl` (`t2_spc_da-fl_sag_p2_iso`, `t2_spc_da-fl_irprep_sag_p2_iso`) se mapea a **T2w**. La exclusión `dark` solo ve la palabra completa `dark-fluid`. Un FLAIR entra en el dataset como T2w sin aviso y contamina la clase T2w | `suffix_from_text("t2_spc_da-fl_sag_p2_iso", exclude_sub=True) == ("T2w", "MATCHED")`; con DICOM, un estudio con esa serie queda con `T2w` | `FLAIR` o `EXCLUDED`, nunca `T2w` (las reglas «nunca adivinan») | `infrastructure/dataset/suffix_rules.py` (congelado; excepción) | **Corregido** (`da-fl` excluido; pasan las 2 pruebas) |
| QA6-03 | **importante** | `T2 STAR` escrito en dos palabras (`T2_STAR_HEMO`, `Ax T2 Star`) se mapea a **T2w**: solo se reconocen `t2star` y `t2*`. Un T2* (eco de gradiente) entra como T2w, justo lo que la exclusión de `gre`/`ffe` quiere evitar | `suffix_from_text("T2_STAR_HEMO", exclude_sub=True) == ("T2w", "MATCHED")` | `T2starw` o `EXCLUDED` | `suffix_rules.py` | **Corregido** (`t2[ _-]*star` → `T2starw`; pasan las 3 pruebas) |
| QA6-04 | menor | Otros nombres reales que las reglas aceptan y que **no** son la imagen del sufijo (sin salvaguarda): `Sag T1 Reformatted` (reformateo derivado: `reformat` solo como palabra exacta) → T1w; `t1_mprage_sag_ND` (copia sin corrección de distorsión de Siemens) → T1w; `T2 relaxometry` (multieco para mapas) → T2w; `Cor T2 STIR` → T2w; `sub-01_space-MNI_desc-preproc_T1w` (un derivado de un BIDS) → T1w con `--format nifti`. Los dos primeros añaden un `run-2` a la sesión. El límite está documentado («no se leen otros campos DICOM, p. ej. `ImageType`») | `suffix_from_text("Sag T1 Reformatted", exclude_sub=True)` | Decisión de producto: ampliar las exclusiones (`reformatted`, `nd`, `relaxometry`, `desc-preproc`/`space-`) o leer `ImageType` (`DERIVED`) | `suffix_rules.py` / `identity.py` | **Corregido** por decisión del humano: exclusiones nuevas `reformatted`, `nd`, `desc`, `preproc`, `stir` y `relaxometry`; los 5 nombres quedan como regresión en `test_vendor_names` |
| QA6-05 | menor (RNF03) | Una tabla que da **el mismo** participante a cada carpeta de serie, sin una fila que contenga el estudio entero, se rechaza con `Mapping gives one study more than one participant or session.` El mensaje confunde: los valores son iguales. La regla («el participante sale de las filas que contienen el estudio entero») sí está en `docs/dataset/ingest.md` | Árbol `s/a` y `s/b` (mismo estudio); tabla `s/a P01` y `s/b P01` | Aceptarlo cuando todos los valores coinciden, o un mensaje que diga «use una fila con la carpeta del estudio» | `application/services/dataset_ingest.py` | Prueba que fija el comportamiento actual: `test_consistent_per_series_participant_is_rejected` |
| QA6-06 | observación | Un estudio con un solo archivo sin PatientID pasa a ser su propio participante, aunque los otros estudios del mismo paciente lo tengan. El paciente queda partido en dos participantes y las particiones de ML podrían ponerlo en `train` y `test` (fuga entre particiones). Está documentado («con valores distintos dentro del estudio: un participante por estudio») | `test_one_file_without_patient_id_splits_the_patient` | Ningún cambio de código obligatorio; quizá un aviso con conteo (`INCONSISTENT_PATIENT_ID: n`) para que el usuario use la tabla | `identity.py` | **Corregido** con un aviso nuevo, `WARNING MISSING_PATIENT_ID: n` (también con `--quiet`; comprobado por subproceso). La agrupación no cambia; `plan.missing_patient_id` se comprueba en la prueba |
| QA6-07 | observación | Una ruta de la tabla en otra normalización Unicode que la carpeta (NFC frente a NFD: macOS o texto copiado) no se encuentra (`Mapping paths not found in the input: 1.`, código 2). Es el comportamiento correcto («comparación exacta»), pero el mensaje no da ninguna pista | `test_mapping_in_another_unicode_normalization_is_not_found` | Nada, o mencionarlo en el manual | `docs/dataset/ingest.md` | Documentado aquí |
| QA6-08 | observación | `PatientID` que difieren solo en mayúsculas (`pat1` y `PAT1`) dan participantes distintos. Los espacios en los bordes sí se ignoran | `test_unusual_patient_ids` | Probablemente correcto (el PatientID es un identificador exacto); documentarlo | `docs/dataset/ingest.md` | Documentado aquí |

### Puntos de lectura DICOM afectados por QA6-01

| Punto | Estado |
|---|---|
| `DICOMReader.load_study` | **Verificado** |
| `DICOMBatchReader.load_studies` | **Verificado** |
| `identity.read_dicom_identities` | **Verificado** |
| `dataset_ingest.plan_ingest` (los dos anteriores) | **Verificado** |
| `volume_builder.build_series_volume` (vuelve a leer los archivos con píxeles) | **Verificado** (con la lectura previa silenciada, solo su propio aviso) |
| `anonymize_dicom_tree` | **Verificado** |
| `convert_dicom_to_nifti` | **Verificado** |
| CLI `dataset build --format dicom` y `inspect --format dicom`, con `--quiet` | **Verificado** (subproceso: stderr) |
| CLI `convert dicom-to-nifti`, `anonymize`, scripts `run_stage*` | Tras el arreglo, comprobado por subproceso para `convert` y `anonymize`; los scripts usan los mismos servicios |
| `DICOMWriter` (escritura, UIDs nuevos y conformes) | No afectado: no lee UIDs de origen |

El arreglo fue central (`quiet_value_validation`) y cubre todos los puntos verificados.

## 2. Qué se probó (pasa)

- **PatientID raros** (`test_unusual_patient_ids`): Unicode con espacio final, que se agrupa con el mismo id sin el
  espacio; 127 caracteres (más que el límite LO de 64), que se agrupan; vacío y en blanco, que dan un participante
  por estudio; y mayúsculas distintas, que dan participantes distintos. Ningún PatientID aparece en el plan ni en
  los logs DEBUG. Los avisos de pydicom por longitud citan la longitud, no el valor.
- **Tablas `--mapping` hostiles**: 14 casos rechazados con su texto fijo exacto. Son estos: columna de más, cabecera
  con espacio o en mayúsculas, ruta duplicada tras normalizar (`s` y `./s/`), `..` en medio, id no ASCII o con un
  dígito de ancho completo, id con `sub-`, sufijo en minúsculas o `bold`, ruta UNC o con unidad, otras mayúsculas y
  etiqueta fuera de `--classes`. Se aceptan BOM, CRLF y celdas con espacios.
- **Nombres de fabricantes** (`test_vendor_names`, 22 casos de Siemens, GE y Philips) que hoy se clasifican bien:
  quedan como regresión para cuando se arreglen QA6-02 y QA6-03. El ADC de GE (`Apparent Diffusion Coefficient
  (mm2/s)`) se reconoce como `dwi` por el texto, pero se descarta con `NOT_4D_DWI` por ser 3D (la salvaguarda
  funciona).
- **PHI en NIfTI sueltos**: nombres de carpeta y archivo con `Planted`, y `descrip`, `aux_file`, `intent_name` y
  una extensión de cabecera plantados. Se recorrieron con `--format nifti`, el pipeline completo y etiquetas: ni los
  nombres del árbol, ni el contenido (cabeceras NIfTI descomprimidas incluidas), ni los logs DEBUG contienen los
  valores plantados ni la ruta de entrada.
- **Equivalencia entre los tres formatos a nivel de vóxel**: E6 compara formas y tamaños de vóxel. Aquí se
  comparan, para el mismo volumen como DICOM, NIfTI suelto con tabla y BIDS, el sufijo, la forma, el **affine** y
  un hash de los **vóxeles** de cada imagen del dataset, y las cifras del reporte JSON (`studies`, `participants`,
  `sessions`, `series`, `modalities`). Coinciden.
- **Memoria (RNF02)**: `dataset build --format dicom` como subproceso, con lotes de 4 y 16 estudios de
  160×160×48 (≈ 9,4 MiB por volumen en float64). El pico no crece más de dos volúmenes entre un lote y el otro
  (`test_dicom_ingest_peak_memory_does_not_grow_with_the_batch`).
- **Rendimiento de la tabla** (sondeo, sin prueba): `plan_ingest` con 20 000 archivos y 220 filas tardó 3,2 s; el
  coste crece con filas × series, no con filas × archivos (el `all()` se corta en el primer archivo que no aplica).

## 3. Corrida real acotada

Se hizo en modo solo lectura sobre `data/raw`, con salidas en `E:/qa6_tmp/real` (borradas al terminar) y una clave
desechable generada en la corrida, porque no había una `MRI_ANON_KEY` del humano. La consola solo mostró conteos.

| Entrada | Formato | Resultado |
|---|---|---|
| `dicom_test_studies_old` (154 archivos) | `dicom` | Código 0 en 8 s; 2 estudios, 2 series, 2 participantes, 0 errores; stderr vacío |
| `nifti_test_studies` (6 archivos) | `nifti` | Código 0 en 22 s; 6 estudios, 6 series, 6 participantes, 0 errores; stderr vacío |
| `dicom_test_studies` (43 719 archivos) | `dicom`, solo `plan_ingest` | `No input series could be mapped to a BIDS suffix.` (código 2 en la CLI, sin crear nada) en 178 s; 1 archivo no DICOM omitido; stderr vacío. Es lo esperado: son series de perfusión DSC (excluidas). Observación de rendimiento (etapa 6): las dos pasadas de cabeceras (`DICOMBatchReader` + `identity`) hacen esperar unos 3 min antes del rechazo |

En las dos salidas escritas, todos los ids son `sub-<16 hex>`. Ningún nombre de archivo o carpeta de la entrada
(nombres de 5 o más caracteres) aparece en los nombres ni en el contenido del árbol de salida (cabeceras NIfTI
incluidas). Los datos reales no tienen UIDs no conformes, así que QA6-01 no se manifestó en ellos.

## 4. Pendiente y no verificado

- **Verificaciones manuales del humano:**
  1. Una corrida `dataset build --format dicom` con la clave real y un árbol de un escáner real (Siemens, GE o
     Philips) para revisar los sufijos asignados frente a las descripciones (QA6-02 a QA6-04).
  2. `pytest` en Linux (la prueba de memoria usa `ru_maxrss`).
- **Sospechas no probadas:**
  - Un `SeriesInstanceUID` repetido en dos estudios (datos mal anonimizados) mezclaría los textos de ambas series
    en `identity` (clave solo por UID de serie).
  - Un `SpecificCharacterSet` distinto entre archivos del mismo paciente daría PatientID decodificados de forma
    distinta y partiría al paciente (como QA6-06).
  - Las series DWI de GE y Philips que el escáner guarda como b0 + traza (2 volúmenes, 4D) pasan como `dwi`. Sin
    `ImageType` ni `.bval`/`.bvec` no se pueden distinguir de una DWI por direcciones (límite documentado).
- No se instaló ninguna herramienta de cobertura.
