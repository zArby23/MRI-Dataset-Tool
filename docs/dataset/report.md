# Reporte estadístico del dataset (RF14, RF15, RF16)

Módulos: `infrastructure/dataset/report.py` (R1, `build_dataset_summary`),
`infrastructure/dataset/exporters.py` (R1/R2, formatos) y `application/services/dataset_report.py`
(R3, `report_dataset`).

## Uso

```python
from mri_dataset_tool.application.services.dataset_report import report_dataset

paths = report_dataset(Path("E:/salida/dataset"), Path("E:/salida/reporte"), on_error)
```

Escribe en `output_dir` (se crea si no existe) cuatro archivos con el mismo contenido:
`dataset_report.json`, `dataset_report.md`, `dataset_report.xml` y `dataset_report.xlsx`.

- Lee el dataset **ya escrito** (D1) con `BIDSBatchReader(lazy=True)`: el reporte describe lo que
  realmente se exportó. Un estudio vivo a la vez (RNF02); las intensidades se calculan volumen a volumen.
- Etiquetas: si existe `labels.tsv` o `labels.json` en la raíz, se leen con `read_labels` (L1).
- Pasos aplicados: si existe `code/run_manifest.json`, se resume por paso.
- `output_dir` **debe estar fuera del dataset** (también fuera de `derivatives/`): si quedara dentro,
  el reporte pasaría a formar parte del dataset. Se rechaza antes de crear nada.

## Contenido

| Sección | Qué contiene |
|---|---|
| Totales | `studies`, `participants`, `sessions` (pares sujeto/sesión), `series` |
| `modalities.<sufijo>` | `series`; distribución de `shape`, `voxel_size`, `orientation` y `dtype` como `[{value, count}]` (más frecuente primero; `voxel_size` agrupado a 6 decimales); `intensity` `{min, max, mean, std, finite_voxels, non_finite_voxels}` sobre los vóxeles finitos de todas las series de la modalidad. Modalidad ausente → `unknown` |
| `labels` | `null` sin etiquetas; si no, por clase `{participants, sessions, series}` (las clases de `labels.json` sin sesiones salen con 0), `unlabeled_sessions` y `unlabeled_participants` (participante con alguna sesión sin etiqueta) |
| `pipeline` | `null` sin manifiesto; si no, `studies` de la corrida y por paso `name`, `version`, `params`, `studies_ok`, `studies_failed`, `error_types` (tipo de excepción → conteo) y `series_transformed` (series en `outputs["series"]`). Los valores de `outputs` no se copian |
| `warnings` | `[{code, count}]` ordenados por código |

Códigos de aviso: los hallazgos de `validate` (`CONSTANT_VOLUME`, `SINGLE_VOLUME_4D`),
`NON_FINITE_VOXELS` (series con vóxeles no finitos), `NO_VOLUME`, `MISSING_SHAPE` (serie sin `shape`:
queda fuera de la intensidad), `MISSING_SUBJECT_ID`, `UNLABELED_SESSIONS`, `UNKNOWN_CLASS`,
`UNREADABLE_FILES` (archivos o estudios que no se pudieron leer), `LABELS_UNREADABLE` y
`MANIFEST_UNREADABLE`.

**Nunca** contiene ids de participante o sesión, UIDs, rutas, `provenance`, valores de cabeceras ni
claves de sidecar fuera de `SIDECAR_WHITELIST` (el resumen por estudio es `summarize_study`).

## Formatos

- **JSON**: `sort_keys`, indentado, UTF-8, `\n`. Es la referencia.
- **Markdown**: tablas por sección; los números se escriben con `json.dumps` (mismas cifras que el JSON);
  `|` y saltos de línea se escapan.
- **XML** (`xml.etree`): raíz `<dataset_report>`, un elemento por clave (orden alfabético), listas de
  registros como `<item>`, modalidades y clases como `<modality name="…">`/`<class name="…">`. Números,
  `null` y listas de escalares como texto JSON. `params` y `error_types` (claves que vienen del
  manifiesto, editable a mano) se escriben enteros como un texto JSON, igual que en las celdas del
  Markdown y del XLSX: ningún dato se usa como nombre de etiqueta. El texto no distingue el string `"1"`
  del número `1`; el JSON es la referencia para los tipos.
- **XLSX** (`openpyxl`): hojas `Totals`, `Modalities`, `Distributions`, `Intensity`, `Labels`,
  `Warnings`, `Pipeline`. Solo valores: sin fórmulas, macros ni enlaces; todo texto se guarda como cadena
  (un `=`, `+`, `-` o `@` inicial no se interpreta). Límites: los floats conservan 16 cifras
  significativas (openpyxl escribe `%.16g`; Excel muestra 15), y el archivo no es idéntico byte a byte
  entre corridas (openpyxl guarda la fecha), aunque sus celdas sí.

## Errores (mensajes fijos, sin rutas ni valores)

| Caso | Resultado |
|---|---|
| Dataset inexistente / no es directorio | `FileNotFoundError` / `NotADirectoryError` |
| `output_dir` dentro del dataset o igual | `ValueError("Report directory must be outside the dataset.")`, nada se crea |
| Algún archivo del reporte ya existe | `FileExistsError("Report file already exists.")` antes de leer nada; no se toca |
| Archivo ilegible, volumen truncado, etiquetas o manifiesto inválidos | `on_error(ruta, error)`, aviso con código y conteo; el reporte se genera con lo demás (RF16) |
| Dataset vacío o con todos los NIfTI ilegibles | `ValueError("No valid BIDS studies were found.")` del lector: **no se genera reporte** (los ilegibles ya pasaron por `on_error`) |
| Texto que XML/XLSX no admiten (caracteres de control, surrogates) | `ValueError("Report content is invalid.")` |
| Valores NaN/Inf en el resumen | `ValueError` de `json.dumps` en los cuatro formatos |
| Fallo al escribir un formato | se borran los ya escritos (los cuatro o ninguno); `OSError("Report file could not be written.")` |

Un callback `on_error` que lanza se captura y solo se registra su tipo. La ruta solo llega al llamador
por `on_error`, en memoria. Si `on_error` guarda la excepción, su `__traceback__` puede retener el estudio
(igual que en el runner).

## Determinismo

Mismo dataset → mismo JSON, Markdown y XML byte a byte, y mismas celdas en el XLSX.
