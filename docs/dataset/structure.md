# Estructura del dataset BIDS (RF10, RF13, RF15)

Módulos: `infrastructure/dataset/bids_layout.py` (D0, reglas de nombres),
`infrastructure/dataset/bids_writer.py` (D1, `BIDSDatasetWriter`) y `application/services/dataset.py`
(D1, `export_dataset`).

## Árbol escrito

```
<raíz>/
├── dataset_description.json
├── participants.tsv
├── participants.json
├── README
├── code/run_manifest.json          (solo si se exporta con pipeline o se pasa un manifiesto)
└── sub-<id>/[ses-<id>/]<carpeta>/sub-<id>[_ses-<id>][_run-<n>]_<sufijo>.nii.gz  (+ .json)
```

- **Ids**: `subject_id`/`session_id` del estudio (seudonimizados por el paso `anonymize`), sin prefijo.
  Solo letras y dígitos ASCII (`validate_label`). Nunca se deducen de rutas ni de `series.files`.
  Un estudio sin `session_id` se escribe sin el nivel `ses-`.
- **Sufijos soportados** (`SUFFIX_DATATYPES`): `T1w`, `T2w`, `PDw`, `T2starw`, `FLAIR` → `anat`;
  `dwi` → `dwi`; `magnitude1`, `magnitude2`, `phasediff` → `fmap`. El sufijo es `series.modality`.
  Otro valor (`MR` de DICOM, `bold`, `None`) no se escribe y se reporta (Q2): nunca se adivina.
  `bold` queda fuera porque BIDS le exige la entidad `task-`. Para ampliar la lista se añade el sufijo
  con su carpeta en `SUFFIX_DATATYPES` (solo sufijos que no exijan más entidades que `sub`/`ses`/`run`).
- **`run-<n>`** (decisión del humano): si un sufijo aparece más de una vez en un mismo estudio
  (sujeto/sesión), **todas** sus series llevan `run-1..n` en el orden de `study.series`; un sufijo que
  aparece una sola vez no lleva `run`. Si una de esas series falla, sus números no se reasignan (puede
  quedar `run-2` sin `run-1`). Las demás entidades de origen (`acq`, `dir`, `echo`, ...) no se conservan.
- **Imagen**: NIfTI `float32` con el affine canónico (`metadata["affine"]`), escrito con `NIfTIWriter`
  (`qform`/`sform` código 1). Se conservan `shape` y `affine` (y con ello `voxel_size` y orientación);
  el dtype de origen no se conserva.
- **Sidecar** `.json` (siempre, aunque quede `{}`): solo claves de `SIDECAR_WHITELIST`
  (`infrastructure/anonymization/policy.py`) con valores escalares o listas de escalares finitos.
  Sin `AcquisitionTime`, fechas, rutas ni UIDs.
- **`participants.tsv`**: solo la columna `participant_id` (Q7), ordenada; un sujeto aparece si se
  escribió al menos una serie suya. `participants.json` describe esa columna.
- **`dataset_description.json`**: `Name`, `BIDSVersion` (`1.9.0`), `DatasetType: raw` (Q8) y
  `GeneratedBy` (`MRI-Dataset-Tool` y su versión). La política de anonimización (`POLICY_VERSION`) se
  declara en `GeneratedBy.Description` y en el `README` **solo** si el manifiesto registra el paso
  `anonymize`; sin él, el `README` dice que no se registró anonimización.
- **`code/run_manifest.json`**: el `RunManifest` de la corrida. `export_dataset` lo escribe siempre con
  `source_path = None` en todos los reports (aunque el pipeline no tenga `anonymize`) y sin la clave
  `report` de la configuración (`report.path` es una ruta local), para que el dataset no contenga rutas.
  `finalize` rechaza por su cuenta un manifiesto con algún `source_path` distinto de `None`, también
  cuando se llama directamente. Sin manifiesto no se crea `code/`.

## Uso

```python
from mri_dataset_tool.application.services.dataset import export_dataset

report = export_dataset(studies, Path("E:/salida/dataset"), on_error,
                        pipeline=pipeline, config=config, source_dir=input_dir)
```

- `studies` se consume en streaming: un estudio vivo a la vez (RNF02); cada serie se materializa con
  `load_array(..., float32)`, se escribe y se suelta.
- Con `pipeline`, cada estudio se procesa y se escribe en `on_result`; al final se escribe el manifiesto.
  Sin `pipeline`, los estudios se escriben tal como llegan y no hay `code/run_manifest.json`.
  Con `pipeline`, `on_error` recibe además los fallos del runner con la **ruta real de origen** (solo en
  memoria, nunca se escribe en el dataset).
- `DatasetReport(studies_written, series_written, participants, errors)`: solo conteos.
- `BIDSDatasetWriter(root)` puede usarse directamente: `add_study(study, on_error)` por estudio y
  `finalize(manifest_json)` una vez.

## Errores (mensajes fijos, sin rutas ni valores)

| Caso | Resultado |
|---|---|
| La raíz ya existe | `FileExistsError("Dataset directory already exists.")`, nada se toca |
| Raíz dentro de `source_dir` o igual | `ValueError` antes de crear nada |
| Estudio sin `subject_id` / id inválido / estudio repetido / mezcla con y sin sesión en un sujeto | `ValueError` del estudio, no escribe nada; `export_dataset` lo pasa a `on_error(Path(), error)` y sigue |
| Serie con sufijo no soportado, geometría inválida, volumen ilegible o destino existente | `on_error(<sub-…/ses-…>, error)`; el resto del estudio se escribe (RF16) |
| Volumen que no es 3D ni 4D (QA4-05) | `on_error` con `ValueError("Unsupported volume dimensionality.")`, sin escribir la serie |
| Valores finitos que desbordan `float32` al convertir, p. ej. `1e300` en float64 (QA4-06) | `on_error` con `ValueError("Volume values exceed the float32 range.")`, sin escribir la serie (un `inf`/`NaN` que ya venía en el origen se escribe tal cual) |
| `finalize` con archivos de nivel superior ya existentes | `FileExistsError("Dataset file already exists.")`, sin escribir ninguno |
| Manifiesto que no es JSON con `steps` y `reports` | `ValueError("Invalid run manifest.")` |
| Manifiesto con algún `source_path` | `ValueError("Run manifest must not contain source paths.")` |

Cada archivo se escribe de forma atómica (temporal + `os.replace`) y nunca se sobrescribe. Si falla el
sidecar se borra la imagen recién escrita, y las carpetas que queden vacías se eliminan. `finalize` es
todo o nada: si falla un archivo, borra los de nivel superior que ya había escrito y puede reintentarse. Un callback
`on_error` que lanza se captura y solo se registra su tipo. Los logs contienen solo tipos y conteos.

## Límites conocidos (decisiones del humano)

- **`dwi` sin `.bval`/`.bvec`**: el pipeline no los conserva; el `bids-validator` reportará error en
  esas series.
- **`phasediff` sin `EchoTime1`/`EchoTime2`**: `SIDECAR_WHITELIST` solo tiene `EchoTime` y no se amplía;
  el `bids-validator` reportará error en esas series.
- **Ids que solo difieren en mayúsculas** (`AB` y `ab`, QA4-08): en Windows (sistema de archivos sin
  distinción de mayúsculas) comparten carpeta y el dataset queda incoherente (`write_ml_exports` falla con
  "outside the BIDS layout"). Solo puede pasar sin el paso `anonymize`: los seudónimos son hex en minúsculas
  y el lanzador de la etapa 4 exige `anonymize`. No se detecta al escribir.
- La validación con el `bids-validator` oficial es una verificación manual del humano (requiere Node).
- Riesgo residual heredado de la etapa 3: cuasi-identificadores en la imagen (rostro, texto quemado).
