# Exportación para ML/DL (RF13)

Módulos: `infrastructure/dataset/splits.py` (particiones, funciones puras),
`infrastructure/dataset/index.py` (archivos de exportación) y `write_ml_exports` en
`application/services/dataset.py`. Sin tensores (`.pt`/`.npy`): el formato de exportación es NIfTI más índices CSV/JSON.

## Uso

```python
from mri_dataset_tool.application.services.dataset import write_ml_exports

write_ml_exports(Path("E:/salida/dataset"), ratios=(0.7, 0.15, 0.15), seed=0, allow_unfinalized=False)
```

**Etiquetas cerradas** (decisión de diseño): si el dataset tiene algún archivo de etiquetas (`labels.tsv`, `labels.json` o `labels_final.json`), por defecto se exige
`labels_final.json` (escrito por `finalize_labels`) con una huella `sha256` igual a `label_fingerprint`
de la tabla actual. Si falta, es ilegible o la tabla cambió después del cierre →
`ValueError("Labels are not finalized.")` antes de escribir nada. `allow_unfinalized=True` exporta
igual (para pruebas o borradores) y lo deja registrado: `splits.json` lleva `"labels_finalized"`
(`true` con cierre válido, `false` sin él, `null` en un dataset sin `labels.tsv`, que no exige nada).

Se corre sobre un dataset ya escrito por `export_dataset` (ver `structure.md`), después de rellenar
las etiquetas si las hay (`labels.md`). Solo lee nombres de archivo y la tabla de etiquetas, nunca
volúmenes. Escribe en la raíz del dataset:

| Archivo | Contenido |
|---|---|
| `dataset_index.csv` | Una fila por imagen: `participant_id`, `session_id`, `suffix`, `run`, `image`, `label`, `split` |
| `datalist.json` | Estilo MONAI: `{"training": [{"image", "label"}], "validation": [...], "testing": [...]}`; con etiquetas, además `classes` y `unlabeled` |
| `splits.tsv` | `participant_id`, `split` (solo participantes asignados) |
| `splits.json` | `seed`, `ratios`, `stratified`, `labels_finalized`, participantes por partición, `unlabeled_participants` y `warnings` |

- `image` es la ruta **relativa a la carpeta de los archivos de exporte**, con `/`; nunca rutas absolutas. En
  el juego estándar (en la raíz del dataset) es relativa a la raíz: `sub-01/anat/sub-01_T1w.nii.gz`.
- **Juego regenerado** (`write_ml_exports(..., output_dir=DIR)`; en la GUI, el paso 6 escribe en
  `<salida>/ml_exports_2`, `_3`…): los cuatro archivos van a `DIR`, que debe ser nueva o estar vacía, fuera del
  dataset y en su mismo disco (en Windows no hay ruta relativa entre unidades), y `image` es relativa a `DIR`:
  `../dataset/sub-01/anat/sub-01_T1w.nii.gz`. MONAI (`load_decathlon_datalist`, cuya `base_dir` por defecto es la
  carpeta del `datalist.json`) y una unión `Path(DIR) / image` resuelven la imagen real. Los archivos de la raíz
  nunca se tocan; `splits.json` registra `seed`, `ratios` y `labels_finalized` del juego. La carpeta se vuelve a
  comprobar vacía tras crearla: si algo apareció en ella entre la validación y la escritura, `FileExistsError` sin
  escribir nada. La CLI aún no tiene `--output-dir` (mejora posible).
- **Límite (enlaces simbólicos y junctions):** la ruta relativa se calcula entre las ubicaciones **reales**
  (resueltas) de la carpeta del juego y del dataset. Si una de las dos se alcanza por un enlace simbólico o una
  junction de Windows, `../dataset/…` es correcto desde la ubicación real de la carpeta del juego, pero puede no
  serlo desde la ruta del enlace: abra el `datalist.json` por su ruta real o resuelva la ruta
  (`Path(...).resolve()`) antes de unirla.
- Los ids llevan el prefijo BIDS en los archivos (`sub-…`, `ses-…`). Las filas siguen el orden de la
  ruta como texto (igual en Windows y Linux).
- `datalist.json` tiene una entrada por imagen (no agrupa las imágenes de una sesión). `label` es el
  nombre de la clase; `classes` es la lista ordenada de clases de `labels.json`, de modo que el índice
  entero de una clase es su posición en esa lista. Sin `labels.tsv` las entradas no tienen `label`.
  Índice numérico para entrenar: `datalist["classes"].index(item["label"])`.

## Particiones

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
| Raíz inexistente | `FileNotFoundError("Dataset directory not found.")` |
| Raíz que no es un directorio | `NotADirectoryError("Dataset path is not a directory.")` |
| Dataset sin imágenes | `ValueError("No dataset images were found.")` |
| Un NIfTI cuya ruta no es exactamente la de `bids_path` (otra entidad, `.nii`, otra carpeta, `run-01`) | `ValueError("Dataset contains a file outside the BIDS layout.")` |
| Tabla de etiquetas inválida | errores de `read_labels` (`labels.md`) |
| Hay `labels.json` o `labels_final.json` pero falta `labels.tsv` (renombrado, "guardar como"), o al revés | `FileNotFoundError("Label table not found.")` / `FileNotFoundError("Label classes file not found.")`, también con `allow_unfinalized`, antes de leer las imágenes |
| Etiquetas sin cerrar o cierre desactualizado (sin `allow_unfinalized`) | `ValueError("Labels are not finalized.")` |
| Algún archivo de exportación ya existe | `FileExistsError("Dataset file already exists.")`, sin escribir ninguno |

Los cuatro archivos se escriben todos o ninguno (temporal + `os.replace` por archivo; si uno falla se
borran los ya escritos y se puede reintentar). Los parámetros se validan antes de leer el dataset.

## Límites conocidos

- Los archivos de exportación y las etiquetas están en la raíz del dataset; el `bids-validator` puede
  reportarlos como archivos desconocidos: el exportador no escribe `.bidsignore`. Si molesta, crear en la
  raíz un `.bidsignore` con `dataset_index.csv`, `datalist.json`, `splits.*` y `labels*` (una línea cada
  uno). Se comprobó con el `bids-validator`: solo marca estos archivos de la raíz.
- Las particiones dependen del algoritmo de `random.Random(seed).shuffle` de Python; una versión de
  Python que lo cambiara daría otras particiones con la misma semilla (por eso se guarda `splits.tsv`).
