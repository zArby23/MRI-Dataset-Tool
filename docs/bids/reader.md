# Lectores BIDS

Cubren RF17. Leen datasets organizados según BIDS y los convierten en `MRIStudy`. La herencia de los sidecars `.json`
está en `sidecar_inheritance.md`.

## Nombres de archivo

`parse_bids_filename(name) -> BIDSEntities` (`infrastructure/bids/entities.py`, función pura) separa un nombre BIDS en
`sub`, `ses`, el resto de entidades (`other`, ordenadas), `suffix` y `extension`. La entidad `sub-` debe ser la primera.

## `BIDSReader.load_study(path, on_error=None, lazy=False) -> MRIStudy`

- `path` puede ser un directorio de sujeto o sesión, o un archivo suelto con nombre BIDS. **Modo flexible:** no exige el
  árbol completo ni `dataset_description.json`.
- Cada imagen se lee con `NIfTIReader` (ver `docs/nifti/nifti.md`). El estudio lleva `study_uid=None`, `subject_id` y
  `session_id` tomados del nombre (sin los prefijos `sub-`/`ses-`), y por serie `modality` = sufijo BIDS,
  `metadata["bids"]` con las entidades y `metadata["sidecar"]` con el JSON fusionado por herencia.
- La identidad del estudio es la del primer archivo válido; un archivo de otro sujeto o sesión se informa por `on_error` y
  se omite.
- Un JSON inválido produce un error sin contenido ni causa.
- `metadata["sidecar"]` **puede contener datos sensibles** y no se registra: los pasos y las exportaciones lo filtran con
  listas blancas (`docs/anonymization/policy.md`).

## `BIDSBatchReader.iter_studies / load_studies(dataset_root, on_error=None, lazy=False)`

- Agrupa las imágenes por (sujeto, sesión) y entrega **un estudio por grupo**, en orden determinista y en streaming.
- `dataset_description.json` ausente se tolera; presente pero inválido lanza `ValueError`.
- Sin ningún estudio válido lanza `ValueError("No valid BIDS studies were found.")`.
- Los archivos ilegibles se informan con `on_error` y el lote sigue (RF16).

## Búsqueda de archivos

`find_nifti_files(directory)` recorre el árbol en orden y devuelve los `.nii` y `.nii.gz`. Ignora en silencio las rutas con
componentes que empiezan por `.` relativos a la raíz (`.git`, `.datalad`, objetos de git-annex). Un archivo pasado
explícitamente a `load_study` se carga siempre.

## Carga perezosa

Con `lazy=True` el volumen es el proxy de nibabel: no se lee ningún vóxel al cargar y los 4D se recorren volumen a
volumen. Es la forma que usan el pipeline y la GUI para acotar la memoria.

## Límites

- No valida el dataset contra el esquema BIDS completo; para eso use el `bids-validator` oficial.
- Los archivos de la exportación (`dataset_index.csv`, `splits.*`, etc.) viven en la raíz del dataset exportado; ver
  `docs/dataset/structure.md` y `docs/dataset/export.md`.
- Los archivos que son punteros de git-annex sin contenido descargado se omiten como ilegibles.
