# Constructor de volúmenes DICOM

`infrastructure/dicom/volume_builder.py` → `build_series_volume(series: MRISeries) -> MRISeries`.

Los lectores (`DICOMReader`, `DICOMBatchReader`) son solo de cabeceras. El constructor es el paso
explícito que lee píxeles, ordena cortes, valida la geometría y devuelve una **nueva** `MRISeries`
con `volume` y la geometría canónica en `metadata` (`shape`, `voxel_size`, `affine` 4×4 RAS+,
`orientation`). Las claves DICOM existentes (`rows`, `pixel_spacing`, …) se conservan.

## Qué hace

- Ordena los cortes proyectando `ImagePositionPatient` sobre la normal del corte
  (`ImageOrientationPatient`); nunca por nombre de archivo ni solo por `InstanceNumber`.
- Verifica `Rows`/`Columns`/`ImageOrientationPatient`/`PixelSpacing` consistentes y espaciado uniforme.
- Aplica `RescaleSlope`/`RescaleIntercept`; el volumen es `float64` (igual que `NIfTIReader`).
- 3D: `shape = (columnas, filas, cortes)`. 4D: `(columnas, filas, cortes, tiempo)`, con los puntos
  temporales agrupados por `TemporalPositionIdentifier` y, si falta, por `AcquisitionNumber`.
- Un solo corte usa `SliceThickness` como espaciado.
- Helpers `lps_to_ras` / `ras_to_lps` (reutilizables por el writer).

## Qué rechaza (`ValueError` con mensaje fijo, sin valores de cabecera)

Archivo ilegible o no DICOM, pixel data no decodificable (sintaxis comprimida sin handler, datos
truncados), multi-frame, mosaico Siemens, `SamplesPerPixel > 1` (RGB), elementos requeridos
ausentes, Rows/Columns/orientación/PixelSpacing inconsistentes, espaciado no uniforme o cortes en
la misma posición sin clave temporal, y puntos temporales con distinto número o posición de cortes.

## Límites conocidos

- **Gantry tilt / cortes desplazados en el plano:** se rechazan (`IPP − proj·normal` debe ser
  constante entre cortes, tol. 1e-3 mm). Nunca se remuestrea en silencio; eso es RF08.
- **Falso rechazo conocido:** una serie 3D en la que el escáner asigna un `AcquisitionNumber`
  distinto a cada corte se interpreta como 4D con puntos temporales de un solo corte y se
  rechaza. Falla segura: no produce un volumen incorrecto.
- **Memoria:** el pico es ≈ 2× el volumen final (los cortes se apilan y luego se transponen/copian).
  Relevante para RNF02: construir un volumen a la vez, no en lista.
