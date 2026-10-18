# Conversión DICOM ↔ NIfTI

Servicio en `application/services/conversion.py`. Sigue *lector → modelo de dominio → escritor*; nunca convierte archivo a archivo.

## Geometría canónica

Toda `MRISeries` con `volume` lleva en `metadata`: `shape`, `voxel_size`, `affine` (4×4, RAS+, convención NIfTI) y `orientation`
(`nib.aff2axcodes`). `NIfTIReader` y `build_series_volume` la rellenan; `NIfTIWriter` y `DICOMWriter` la consumen.
Los helpers `lps_to_ras` / `ras_to_lps` (en `volume_builder.py`) convierten entre DICOM (LPS) y NIfTI (RAS+).

## `convert_dicom_to_nifti(input_dir, output_dir, on_error=None) -> list[MRIStudy]`

- Carga cabeceras con `DICOMBatchReader`, construye cada volumen con `build_series_volume` y escribe un
  `study-NNN_series-NNN.nii.gz` por serie (nombres sin datos del paciente).
- `output_dir` dentro de `input_dir` → `ValueError`. No sobrescribe salidas (`FileExistsError` por serie, reportado vía `on_error`).
- Una serie que falla se reporta con `on_error(primer_archivo, error)` y el resto continúa.
- Un volumen a la vez: el resultado devuelve series con `volume=None`, `files=[ruta escrita]`, geometría y `metadata["provenance"]`.
- Límite: `convert_dicom_to_nifti` no pasa `on_error` a `DICOMBatchReader`, así que los archivos DICOM ilegibles se omiten sin reportarse.

## `convert_nifti_to_dicom(input_path, output_dir, on_error=None) -> list[MRIStudy]`

- Acepta un `.nii`/`.nii.gz` o un directorio (vía `NIfTIBatchReader`); escribe cada entrada con `DICOMWriter` en `output_dir/study-NNN/`.
- Entradas que fallan (ilegibles, 4D, affine no ortogonal, salida existente…) se reportan con `on_error` y el lote sigue.
- Sin ninguna entrada cargable → `ValueError("No valid NIfTI studies were found.")`.
- Volúmenes 4D no se convierten a DICOM en v1 (ver `writer.md`).

## Límites generales

- Solo MR de un frame; multi-frame, mosaico Siemens, RGB, gantry tilt y espaciado no uniforme se rechazan (ver `volume_builder.md`).
- Los volúmenes DICOM se construyen en `float64`; el pico de memoria al construir una serie es ≈ 2× el volumen final.
- El DICOM escrito no es conforme al IOD MR estricto (ver `writer.md`).
