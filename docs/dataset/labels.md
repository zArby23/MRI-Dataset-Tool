# Etiquetas del dataset (RF11)

Módulo: `src/mri_dataset_tool/infrastructure/dataset/labels.py` (tarea L1). El flujo de revisión,
correcciones y cierre (RF12, tarea L2) se documentará aquí cuando exista.

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
| `write_labels(table, root)` | Escribe ambos archivos (filas ordenadas por participante y sesión, JSON con `sort_keys`). Si alguno existe → `FileExistsError("Label table already exists.")` sin escribir nada. Escritura atómica por archivo; si falla el TSV se borra el JSON recién escrito. `root` debe existir. |
| `read_labels(root)` | Lectura **estricta**: cualquier defecto → `ValueError` de mensaje fijo. |
| `read_classes(root)` | Lee `labels.json` → `(clases, descripción)`. |
| `parse_label_rows(path)` | Lectura **tolerante** (para `review_labels`, L2): solo valida la estructura y devuelve `(participant_id, session_id, label)` tal como están escritos, en el orden del archivo. |
| `parse_label_key(participant_cell, session_cell)` | Celdas de id → clave de la tabla; inválidas → `ValueError`. |

Límite conocido de `write_labels`: hay una ventana mínima entre la comprobación de existencia y el
`os.replace` (proceso de un solo usuario), igual que en `NIfTIWriter`. Si la escritura falla por
cualquier causa, no quedan temporales ni media tabla.

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

## Privacidad e inyección de fórmulas

- Los ids son los seudónimos del dataset exportado; el módulo no registra nada en logs.
- Ninguna clase puede empezar por `=`, `+`, `-`, `@`, tabulador o retorno de carro, así que ninguna
  etiqueta válida escrita parece una fórmula. Los ids son alfanuméricos.
- La lectura tolerante devuelve las celdas tal cual (datos, nunca se evalúan): una celda como
  `=HYPERLINK(...)` editada a mano llega a `review_labels` como clase desconocida, y `read_labels` la rechaza.
