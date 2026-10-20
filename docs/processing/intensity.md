# Procesamiento de intensidad

## Carga perezosa de volúmenes (M0)

Por defecto los lectores NIfTI cargan el volumen completo en `float64` (`image.get_fdata()`). Con
`lazy=True` dejan en `MRISeries.volume` el proxy de nibabel (`image.dataobj`, un `ArrayProxy`) y **no
leen ningún vóxel** hasta que algo lo materializa.

```python
from mri_dataset_tool.infrastructure.nifti.batch_reader import NIfTIBatchReader
from mri_dataset_tool.infrastructure.processing.arrays import iter_volumes_3d, load_array

for study in NIfTIBatchReader().iter_studies(root, lazy=True):
    volume = study.series[0].volume           # proxy: shape y dtype sin leer datos
    data = load_array(volume, "float32")      # lee todo el volumen
    for frame in iter_volumes_3d(volume, "float32"):  # 4D: un volumen 3D a la vez
        ...
```

`lazy` existe en `NIfTIReader.load_study`, `NIfTIBatchReader.iter_studies/load_studies`,
`BIDSReader.load_study/load_files` y `BIDSBatchReader.iter_studies/load_studies`; por defecto es
`False` y el comportamiento no cambia.

### Contrato

- `MRISeries.volume: np.ndarray | VolumeLike | None`. `VolumeLike` (`domain/models/serie.py`) es un
  `Protocol` con `shape`, `dtype`, `__array__` y `__getitem__`; lo cumplen `ndarray` y `ArrayProxy`. El
  dominio no importa nibabel.
- La `metadata` (`shape`, `voxel_size`, `datatype`, `bitpix`, `affine`, `qform_code`, `sform_code`,
  `orientation`) sale de la cabecera y es idéntica a la de la carga eager.
- `infrastructure/processing/arrays.py` es el **único acceso al volumen** para los pasos:
  - `load_array(volume, dtype=None) -> np.ndarray`. Un `ndarray` que ya tiene ese `dtype` (o con
    `dtype=None`) se devuelve sin copiar. `load_array(proxy, "float64")` es igual a `get_fdata()`.
  - `iter_volumes_3d(volume, dtype=None)`: 3D cede un volumen; 4D cede `volume[..., t]` uno a uno (con
    un proxy solo se lee ese volumen). Es un generador: los errores salen en el primer `next()`.
  - Errores con mensaje fijo, sin rutas: `"Invalid volume dtype."` (solo enteros y flotantes reales),
    `"Unsupported volume dimensionality."` (no 3D/4D), `"Unable to read volume data."` (archivo
    truncado, corrupto o borrado al materializar).
- Con `lazy=True` el lector abre la imagen con `mmap=False` y nibabel no mantiene el archivo abierto
  (`keep_file_open=False`): el archivo se puede borrar o mover (también en Windows) mientras el proxy
  existe; materializarlo después falla con `"Unable to read volume data."`.

### Límites

- **Archivos truncados (decisión del humano).** Con `lazy=True` un `.nii.gz` truncado tiene la cabecera
  intacta: el lector lo carga y su `on_error` **no** lo reporta. Falla al materializar, con
  `ValueError("Unable to read volume data.")`, en el primer paso que lee el volumen; el runner lo
  reporta por su `on_error` y el lote sigue (RF16). Con `lazy=False` se sigue detectando al cargar.
- **dtype en disco.** El proxy conserva el dtype del archivo (p. ej. `int16`); nibabel aplica
  `scl_slope/scl_inter` al leer, así que `load_array(proxy)` sin `dtype` puede devolver el dtype en
  disco o un flotante si la cabecera escala. Los pasos deben pedir el `dtype` explícitamente. El dtype
  en disco se conoce sin leer datos (`volume.dtype`, `metadata["datatype"]`).
- **`.nii.gz` y 4D.** Leer `proxy[..., t]` descomprime el flujo desde el inicio hasta ese volumen. La
  memoria sigue acotada a un volumen, pero el tiempo crece: 4D sintético `96×96×60×30 int16`, lectura
  volumen a volumen `.nii` 0,07 s frente a `.nii.gz` 1,9 s (lectura completa del `.nii.gz`: 0,25 s). Sin
  dependencias nuevas (`indexed_gzip` queda fuera).
- **`NIfTIWriter`.** Acepta el proxy tal cual. Sin escalado en la cabecera el resultado es exacto; con
  `scl_slope/scl_inter` nibabel vuelve a cuantizar al dtype en disco (error ~1e-4 relativo). Si importan
  los valores exactos, materializar antes con `load_array(volume, dtype)`.
- Tras el primer paso que transforma el volumen, `series.volume` es un `ndarray`.

### Memoria medida

`scripts/memory_check_nifti_batch.py [--lazy]` sobre `data/raw/nifti_test_studies` (6 archivos
`.nii.gz` `192×256×256 int16`, Windows 10, nibabel 5.4.2), recorriendo el lote sin procesar:

| Modo | Pico sobre la línea base |
|---|---|
| eager (`float64`) | 97,3 MB |
| `lazy=True` | 1,3 MB |

Pendiente (verificación manual del humano): medir sobre la sesión con difusión de BIDS ds005299.
