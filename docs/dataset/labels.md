# Etiquetas del dataset (RF11, RF12, RF15)

Módulos: `src/mri_dataset_tool/infrastructure/dataset/labels.py` (L1: tabla, formatos de archivo) y
`src/mri_dataset_tool/application/services/labels.py` (L2: plantilla, revisión, correcciones, cierre).

## Modelo

Una etiqueta categórica por (participante, sesión), tomada de una lista cerrada de clases (Q3). Una
etiqueta vacía significa **sin etiquetar**; una clase fuera de la lista es **inválida** (error).

`LabelTable(classes, labels, description="")`:

- `classes`: `dict[str, str]` clase → descripción.
- `labels`: `dict[(participante, sesión | None), str | None]`; ids **sin** prefijo `sub-`/`ses-`
  (como `MRIStudy.subject_id`/`session_id`); `None` = sin etiquetar.
- Valida al construirse; copia los dicts de entrada (no los comparte).

## Archivos (formato aprobado por el humano, 2026-10-22)

Ambos en la raíz del dataset.

`labels.tsv`: TSV UTF-8 con fin de línea `\n`, sin comillas. Columnas `participant_id`, `session_id`,
`label`. Los ids llevan el prefijo BIDS en el archivo (`sub-01`, `ses-01`). La columna `session_id`
siempre existe; una celda vacía significa dataset sin sesiones (clave `(sub, None)`).

```
participant_id	session_id	label
sub-01	ses-01	AD
sub-01	ses-02
sub-02	ses-01	CN
```

`labels.json`: sidecar de columna al estilo BIDS; las clases válidas son las claves de `Levels`.

```json
{"label": {"Description": "Diagnosis", "Levels": {"AD": "Alzheimer", "CN": "Control"}}}
```

Ids: `sub-`/`ses-` seguido de una etiqueta válida para `bids_layout.validate_label` (alfanumérica ASCII). Nombres de clase:
no vacíos, sin espacios al inicio o al final, sin tabuladores ni saltos de línea, codificables en UTF-8
y sin empezar por `=`, `+`, `-` o `@` (inyección de fórmulas; decisión del humano, 2026-10-22).
Las descripciones (de clase y de la tabla) deben ser codificables en UTF-8 y sin tabuladores ni saltos
de línea.

## API

| Función | Qué hace |
|---|---|
| `serialize_labels(table)` | Texto canónico `(labels.tsv, labels.json)`: filas ordenadas por participante y sesión, JSON con `sort_keys`. Base de la escritura y de la huella. |
| `write_labels(table, root, overwrite=False)` | Escribe ambos archivos. Sin `overwrite`, si alguno existe → `FileExistsError("Label table already exists.")` sin escribir nada. Primero escribe los dos temporales y después hace los dos `os.replace`. Si algo falla, no quedan temporales; sin `overwrite` tampoco queda media tabla, y con `overwrite` una tabla previa se conserva si el fallo ocurre antes de los reemplazos. `root` debe existir. |
| `read_labels(root)` | Lectura **estricta**: cualquier defecto → `ValueError` de mensaje fijo. |
| `read_classes(root)` | Lee `labels.json` → `(clases, descripción)`. |
| `parse_label_rows(path)` | Lectura **tolerante** (para `review_labels`, L2): solo valida la estructura y devuelve `(participant_id, session_id, label)` tal como están escritos, en el orden del archivo. |
| `parse_label_key(participant_cell, session_cell)` | Celdas de id → clave de la tabla; inválidas → `ValueError`. |

Límites conocidos de `write_labels`: hay una ventana mínima entre la comprobación de existencia y el
`os.replace` (proceso de un solo usuario), igual que en `NIfTIWriter`. Con `overwrite`, un fallo entre
los dos `os.replace` dejaría el `labels.json` nuevo junto al `labels.tsv` anterior. En las correcciones
el JSON no cambia de contenido, así que no tiene efecto.

La lectura tolera lo que suele dejar Excel: BOM, `\r\n`, líneas en blanco y columnas extra (se ignoran,
en cualquier orden).

## Errores (mensajes fijos, sin ids, etiquetas ni rutas)

| Caso | Excepción |
|---|---|
| Sin filas de datos (vacío o solo cabecera) | `ValueError("Label table is empty.")` |
| Falta una columna o hay columnas repetidas | `ValueError("Label table is missing required columns.")` |
| Fila con distinto número de celdas que la cabecera | `ValueError("Label table has a malformed row.")` |
| Id sin prefijo o con caracteres no alfanuméricos | `ValueError("Label table has an invalid participant or session id.")` |
| (participante, sesión) repetido | `ValueError("Label table has a duplicate participant/session.")` |
| Clase fuera de `Levels` | `ValueError("Label table has an unknown class.")` |
| TSV no UTF-8 | `ValueError("Label table is not valid UTF-8.")` (sin causa) |
| `labels.json` inválido / clases inválidas | `ValueError("Label classes file is invalid.")` / `ValueError("Label classes are invalid.")` |
| Archivo ausente | `FileNotFoundError("Label table not found.")` / `FileNotFoundError("Label classes file not found.")` |
| Fallo de E/S | `OSError` de mensaje fijo, sin causa encadenada (citaría la ruta) |
| Texto no codificable que llega a la escritura saltándose la validación | `ValueError("Label table could not be written.")` (sin causa) |

## Flujo de revisión y cierre (L2; aprobado por el humano, 2026-10-22)

Todo ocurre en la raíz del dataset exportado. Los pares (participante, sesión) salen del árbol: carpetas
`sub-<id>` y, dentro, `ses-<id>` (sin carpetas `ses-` → `(sub, None)`), validadas con
`bids_layout.validate_label`. Se ignoran las entradas ocultas, los archivos y las carpetas con nombre inválido.

1. **Plantilla**: `write_label_template(root, classes, description="")` escribe `labels.json` y un
   `labels.tsv` con todos los pares del árbol **sin etiquetar**, y devuelve la ruta de `labels.tsv`. No
   hay archivo de plantilla aparte. No sobrescribe (`FileExistsError`); un dataset sin participantes
   → `ValueError("Dataset has no participants.")`.
2. **Asignación y correcciones**: `apply_label_corrections(root, corrections_path) -> int`. El archivo
   de correcciones tiene las mismas columnas que `labels.tsv`, solo con las filas que cambian (puede ser
   una copia rellenada de la plantilla). Una etiqueta vacía devuelve el par a «sin etiquetar».
   - **Todo o nada**: un par fuera del árbol, un par repetido, un id inválido o una tabla resultante
     con una clase desconocida rechazan el archivo entero; no se escribe nada.
   - La tabla actual se lee en modo tolerante: puede tener clases desconocidas o pares que faltan, y
     las correcciones pueden arreglarlos (la tabla resultante tiene que superar la validación estricta).
     Las filas duplicadas, con ids inválidos o de pares que no están en el árbol se quitan **a mano**
     (`ValueError("Label table must be fixed by hand before corrections.")`).
   - Devuelve el número de cambios; una fila igual al valor actual no se registra.
3. **Revisión**: `review_labels(root) -> LabelReview` no modifica nada. Campos: `dataset_pairs`,
   `class_counts` (todas las clases, incluidas las de cero), `unlabeled`, `unknown_class`, `duplicated`,
   `missing` (pares del árbol ausentes de la tabla; las listas tienen solo pares del árbol, ordenados),
   `not_in_dataset` e `invalid_ids` (solo conteos: no son ids del dataset); propiedades `labeled` e
   `is_complete`. Las filas de un par duplicado solo cuentan en `duplicated`.
4. **Cierre**: `finalize_labels(root)` exige `review.is_complete` (ningún par sin etiquetar, ninguna clase
   desconocida, sin duplicados, faltantes, ids inválidos ni pares ajenos); si no,
   `ValueError("Labels are incomplete or invalid.")`. Escribe `labels_final.json`, sin fecha:
   `{"label_count", "class_counts", "sha256"}`. Ya cerrado → `FileExistsError("Labels are already finalized.")`.
5. **Tras el cierre**, `apply_label_corrections` lanza `ValueError("Labels are finalized.")`.
6. **Reapertura explícita**: `reopen_labels(root)` borra `labels_final.json` y registra una fila
   `reopen`; sin cierre previo → `ValueError("Labels are not finalized.")`.

**Huella** (`label_fingerprint(table)`): SHA-256 de la serialización canónica de `labels.tsv` +
`labels.json`. Cambiar una etiqueta, una clase o una descripción la cambia; reordenar filas o claves no.

**Bitácora** `labels_changes.tsv` (solo crece): columnas `timestamp_utc` (`AAAA-MM-DDTHH:MM:SSZ`),
`action` (`correct`, `finalize`, `reopen`), `participant_id`, `session_id`, `old_label`, `new_label`.
Las filas `finalize`/`reopen` dejan vacías las demás columnas. Un valor anterior que no era una clase
(edición a mano) se registra como `<invalid>`, nunca con el texto original. Si falla la escritura de
la tabla, de `labels_final.json` o el borrado al reabrir, se quitan las filas recién anexadas: la
bitácora y los archivos no se contradicen.

**Editar `labels.tsv` a mano no queda registrado.** `review_labels` detecta los defectos que deja una
edición así, pero la bitácora solo registra lo que entra por `apply_label_corrections`.

Mensajes de error del archivo de correcciones: son los de la lectura de `labels.tsv` («Label table
…»), porque el formato es el mismo.

## Privacidad e inyección de fórmulas

- Los ids son los seudónimos del dataset exportado; el módulo no registra nada en logs.
- Ninguna clase puede empezar por `=`, `+`, `-`, `@`, tabulador o retorno de carro, así que ninguna
  etiqueta válida escrita parece una fórmula. Los ids son alfanuméricos.
- La lectura tolerante devuelve las celdas tal cual (datos, nunca se evalúan): una celda como
  `=HYPERLINK(...)` editada a mano llega a `review_labels` como clase desconocida, y `read_labels` la rechaza.
