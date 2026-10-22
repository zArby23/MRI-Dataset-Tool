# Exportación para ML/DL (RF13)

Módulos: `infrastructure/dataset/splits.py` (particiones, funciones puras),
`infrastructure/dataset/index.py` (archivos de exportación) y `write_ml_exports` en
`application/services/dataset.py` (tarea D2). Sin tensores (`.pt`/`.npy`): decisión Q6.

## Uso

```python
from mri_dataset_tool.application.services.dataset import write_ml_exports

write_ml_exports(Path("E:/salida/dataset"), ratios=(0.7, 0.15, 0.15), seed=0)
```

Se corre sobre un dataset ya escrito por `export_dataset` (ver `structure.md`), después de rellenar
las etiquetas si las hay (`labels.md`). Solo lee nombres de archivo y la tabla de etiquetas, nunca
volúmenes. Escribe en la raíz del dataset:

| Archivo | Contenido |
|---|---|
| `dataset_index.csv` | Una fila por imagen: `participant_id`, `session_id`, `suffix`, `run`, `image`, `label`, `split` |
| `datalist.json` | Estilo MONAI: `{"training": [{"image", "label"}], "validation": [...], "testing": [...]}`; con etiquetas, además `classes` y `unlabeled` |
| `splits.tsv` | `participant_id`, `split` (solo participantes asignados) |
| `splits.json` | `seed`, `ratios`, `stratified`, participantes por partición, `unlabeled_participants` y `warnings` |

- `image` es la ruta **relativa a la raíz del dataset**, con `/`; nunca rutas absolutas.
- Los ids llevan el prefijo BIDS en los archivos (`sub-…`, `ses-…`). Las filas siguen el orden de la
  ruta como texto (igual en Windows y Linux).
- `datalist.json` tiene una entrada por imagen (no agrupa las imágenes de una sesión). `label` es el
  nombre de la clase; `classes` es la lista ordenada de clases de `labels.json`, de modo que el índice
  entero de una clase es su posición en esa lista. Sin `labels.tsv` las entradas no tienen `label`.

## Particiones (Q5)

- **Por participante**: todas las sesiones y series de un participante caen en la misma partición
  (sin fuga). Por defecto 70/15/15 con semilla 0; ambos quedan en `splits.json`.
- **Deterministas**: mismos participantes, etiquetas, proporciones y semilla → mismas particiones
  (independiente del orden de entrada).
- **Estratificadas** si existe `labels.tsv`. El estrato de un participante es la tupla ordenada de las
  clases distintas de sus sesiones etiquetadas (normalmente una sola clase; un participante con
  sesiones de clases distintas forma su propio estrato, p. ej. `["AD", "CN"]`). Cada estrato se reparte
  por separado: si tiene al menos un participante por partición con proporción positiva, cada una
  recibe uno; el resto va, de a uno, a la partición más lejos de su cuota.
- Un estrato con menos participantes que particiones activas da el aviso `FEW_PARTICIPANTS` en
  `splits.json` (no es error); no puede estar en todas las particiones.
- **Sin etiqueta**: un participante sin ninguna sesión etiquetada no se asigna (`split` vacío en
  `dataset_index.csv`) y se lista en `unlabeled_participants`. Una sesión sin etiqueta de un
  participante asignado conserva la partición del participante en el índice, pero en `datalist.json`
  va a `unlabeled`, nunca a una partición con una etiqueta inventada.
- Una proporción 0 deja esa partición vacía (p. ej. `(0.8, 0, 0.2)`).

## Errores (mensajes fijos)

| Caso | Resultado |
|---|---|
| Proporciones que no son tres números ≥ 0 que suman 1 | `ValueError` |
| Semilla que no es `int` | `ValueError("Split seed must be an integer.")` |
| Raíz inexistente | `NotADirectoryError("Dataset directory not found.")` |
| Dataset sin imágenes | `ValueError("No dataset images were found.")` |
| Un NIfTI cuya ruta no es exactamente la de `bids_path` (otra entidad, `.nii`, otra carpeta, `run-01`) | `ValueError("Dataset contains a file outside the BIDS layout.")` |
| Tabla de etiquetas inválida | errores de `read_labels` (`labels.md`) |
| Algún archivo de exportación ya existe | `FileExistsError("Dataset file already exists.")`, sin escribir ninguno |

Los cuatro archivos se escriben todos o ninguno (temporal + `os.replace` por archivo; si uno falla se
borran los ya escritos y se puede reintentar). Los parámetros se validan antes de leer el dataset.

## Límites conocidos

- Los archivos de exportación y las etiquetas están en la raíz del dataset; el `bids-validator` puede
  reportarlos como archivos desconocidos (no hay `.bidsignore`). Verificación manual del humano.
- Las particiones dependen del algoritmo de `random.Random(seed).shuffle` de Python; una versión de
  Python que lo cambiara daría otras particiones con la misma semilla (por eso se guarda `splits.tsv`).
