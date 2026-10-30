# Estudios NIfTI en el programa

Cómo el programa lee, procesa, escribe y organiza archivos NIfTI (`.nii` y `.nii.gz`). Cubre RF02, RF05, RF17 y RF18.
Los contratos exactos están en `MEMORY.md` §5; aquí se explica el comportamiento observable.

## Dónde aparece NIfTI

| Uso | Dónde | Capa |
|---|---|---|
| Leer un archivo | `NIfTIReader.load_study(path, lazy=False)` | `infrastructure/nifti/reader.py` |
| Leer un árbol de archivos | `NIfTIBatchReader.iter_studies / load_studies` | `infrastructure/nifti/batch_reader.py` |
| Escribir un archivo | `NIfTIWriter.write(series, path, overwrite=False)` | `infrastructure/nifti/writer.py` |
| DICOM → NIfTI y NIfTI → DICOM | `convert_dicom_to_nifti`, `convert_nifti_to_dicom` | `application/services/conversion.py` (ver `docs/dicom/conversion.md`) |
| NIfTI dentro de un dataset BIDS | `BIDSReader`, `BIDSBatchReader` | ver `docs/bids/sidecar_inheritance.md` |
| Procesar (reorientar, remuestrear, normalizar) | pasos del pipeline | ver `docs/processing/` |
| Organizar NIfTI sueltos en un dataset | `dataset build --format nifti` y el paso de mapeo de la GUI | ver `docs/dataset/ingest.md` |

## Qué es un «estudio» NIfTI

Cada archivo es un `MRIStudy` con una sola `MRISeries`:

- `study_uid = None`, `series_uid = None`, `modality = None`, `files = [ruta]`.
- `volume`: el arreglo cargado (`float64`) o, con `lazy=True`, el proxy de nibabel (no se lee ningún vóxel al cargar).
- `metadata`: `shape`, `voxel_size` (tres primeros zooms), `datatype`, `bitpix`, `affine`, `qform_code`, `sform_code`
  y `orientation` (códigos de ejes del affine, p. ej. `RAS`).

`shape`, `voxel_size`, `affine` y `orientation` son la **geometría canónica**: todo el programa (pasos, escritores,
exportes) trabaja con ese contrato, sea cual sea el origen del volumen.

## Lectura de un archivo

- Ruta inexistente → `FileNotFoundError`; una carpeta → `ValueError`.
- Solo `.nii` y `.nii.gz`, sin distinguir mayúsculas (BIDS exige minúsculas, pero el lector tolera `.NII` y `.nii.GZ`).
- Un archivo ilegible, truncado o con cabecera inválida da `ValueError("Unable to load NIfTI image.")` (con la causa
  original encadenada). Un dtype complejo se rechaza con `ValueError("Unsupported NIfTI data type.")`.
- **Carga perezosa (`lazy=True`):** la `metadata` es idéntica a la carga normal y el archivo se abre en la primera
  lectura, no al cargar. Así un 4D `.nii.gz` se recorre volumen a volumen con memoria acotada (RNF02). El archivo queda
  abierto mientras viva el estudio y se cierra al soltarlo; en Windows un archivo abierto no se puede borrar ni mover.
- Un `.nii.gz` truncado **no se detecta al cargar** en modo perezoso: falla al leer los vóxeles con
  `ValueError("Unable to read volume data.")` y el lote lo informa y continúa.

## Lectura por lote

`NIfTIBatchReader.iter_studies(directory, on_error=None)` recorre el árbol en orden determinista (por ruta):

- Solo considera archivos regulares `.nii` y `.nii.gz`; el resto se ignora sin contarse como error.
- Ignora en silencio lo que cuelga de carpetas o archivos ocultos (`.git`, `.datalad`, objetos de git-annex).
- Cada archivo ilegible se informa con `on_error(ruta, error)` y el lote sigue (RF16). Un callback que falla se captura
  y solo se registra su tipo.
- `iter_studies` entrega un estudio a la vez; `load_studies` los junta en una lista (todo en memoria).
- Sin ningún estudio válido → `ValueError("No valid NIfTI studies were found.")`.
- Los registros y la consola contienen solo conteos y nombres de tipo de excepción, nunca rutas ni valores de cabecera.

## Escritura

`NIfTIWriter.write(series, path, overwrite=False)`:

- Exige `.nii` o `.nii.gz`, `series.volume` y un `metadata["affine"]` de 4×4. El tamaño de vóxel sale del affine, no de
  `voxel_size`.
- Fija `qform_code` y `sform_code` en 1 y conserva el dtype del volumen.
- Escritura atómica (temporal en la misma carpeta + `os.replace`): un fallo no deja un archivo truncado.
- Si el archivo existe y `overwrite=False` → `FileExistsError` sin modificarlo. No crea carpetas.
- Un proxy con `scl_slope`/`scl_inter` se recuantiza al dtype del disco: materialícelo antes con `load_array`.

## Uso desde la CLI y la GUI

```
mri-dataset inspect IN --format nifti
mri-dataset convert nifti-to-dicom IN OUT          # solo 3D; los 4D se rechazan
mri-dataset convert dicom-to-nifti IN OUT
mri-dataset process IN --format nifti --config CFG --output-dir OUT
mri-dataset dataset build IN --format nifti --config CFG --output-dir OUT [--mapping TSV]
```

- `process` con NIfTI sueltos escribe `study-NNN.nii.gz` (`float32`, sin sobrescribir) y el manifiesto de la corrida.
  Use `config/stage3_example.yaml`: remuestrea todas las series. `config/stage3_bids.yaml` solo remuestrea las
  modalidades que lista y no sirve para NIfTI sueltos (su `modality` es `None`).
- `dataset build --format nifti` organiza los archivos en un dataset BIDS anonimizado. Sin tabla `--mapping`, cada
  archivo es un participante (seudónimo de la ruta) y el sufijo BIDS (T1w, T2w, FLAIR, T2starw, PDw, dwi) se deduce del
  nombre con reglas conservadoras; lo ambiguo se omite con un aviso. Detalle en `docs/dataset/ingest.md`.
- En la GUI, el tipo de entrada «NIfTI» sigue los mismos pasos que DICOM, incluido el paso de mapeo.

## Muestra de prueba

`data/samples/nifti_test_studies/` contiene NIfTI públicos para probar la entrada `nifti`, y
`data/samples/bids_test_studies/` un dataset BIDS pequeño con NIfTI T1w y T2w.

## Límites

- Solo archivos únicos `.nii`/`.nii.gz`; no se leen pares `.hdr/.img`.
- Dtype complejo no soportado.
- El acceso aleatorio dentro de un `.nii.gz` vuelve a descomprimir desde el inicio (sin `indexed_gzip`).
- NIfTI → DICOM no admite 4D (decisión de la versión 1).
- Un NIfTI suelto no trae identidad de paciente: el participante sale de la ruta o de la tabla `--mapping`.
