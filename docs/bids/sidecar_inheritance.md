# Herencia de sidecars BIDS

`BIDSReader` y `BIDSBatchReader` llenan `MRISeries.metadata["sidecar"]` con el principio de herencia de BIDS.

## Regla

- Para cada imagen se consideran los `*.json` de cada directorio entre la raíz del dataset y el directorio de la imagen (raíz, sujeto, sesión, datatype).
- Un JSON aplica si su suffix es el de la imagen y sus entidades son una **subsecuencia ordenada** de las de la imagen (`sub`, `ses`, resto en su orden). `T1w.json` y `sub-01_T1w.json` aplican a `sub-01_ses-01_acq-x_T1w.nii.gz`; `task-rest_bold.json` y `run-1_acq-x_T1w.json` (orden invertido) no.
- Se fusiona de lo general a lo específico: primero por profundidad del directorio (el más profundo gana) y, dentro de un directorio, por número de entidades (el que tiene más gana). El más específico gana campo a campo.
- Solo se leen los JSON que aplican. Un JSON aplicable inválido (o que no sea un objeto) hace fallar esa imagen: se reporta por `on_error` con una excepción sin contenido ni causa encadenada, y no se registra nada del JSON en logs.

## Raíz del dataset

- `BIDSBatchReader`: `dataset_root`.
- `BIDSReader.load_study`: el primer directorio ascendente con `dataset_description.json`. Sin él (archivos sueltos, modo flexible) solo se usa el JSON del directorio de la imagen; no se sube por el árbol.

## Límites

- Modo flexible en el lote: sin `dataset_description.json` igualmente se usa `dataset_root` como raíz. Un `T1w.json` ajeno e inválido en la raíz hace fallar todas las T1w, cada una reportada por `on_error`.
- Rendimiento: cada imagen vuelve a leer y parsear los JSON heredados. Si resulta lento en datasets grandes, cachear por directorio.
- Los valores del sidecar se conservan tal cual en `metadata`, incluso si contienen campos que parecen PHI; decisión de anonimización pendiente (RF09/RF14).
