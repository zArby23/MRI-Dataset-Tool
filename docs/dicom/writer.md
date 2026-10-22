# Escritor DICOM

`infrastructure/dicom/writer.py` → `DICOMWriter.write(series, output_dir, overwrite=False) -> list[Path]`.

Escribe un archivo `slice-NNNN.dcm` por corte de un volumen **3D** (`MRISeries.volume` + `metadata["affine"]` RAS+).

- SOP Class MR Image Storage, `Modality=MR`, `ImageType=DERIVED\SECONDARY`.
- UIDs nuevos (`generate_uid`) de estudio, serie, marco de referencia y cada instancia.
- Sin identificadores: `PatientName`, `PatientID`, fechas, etc. se escriben como atributos tipo 2 vacíos.
- Geometría derivada del affine (RAS → LPS con `ras_to_lps`). Se rechazan affines con ejes no ortogonales (cosenos, tol. 1e-4) o con el eje de corte inclinado respecto a la normal del plano: el desplazamiento del origen del último corte fuera de la normal debe ser ≤ `IN_PLANE_TOLERANCE_MM` (1e-3 mm), constante compartida con `volume_builder.py` para que lo escrito siempre se pueda releer.
- Píxeles `int16` con un único `RescaleSlope/Intercept` por serie; error máximo ≤ slope/2. Enteros que caben en int16 se guardan sin pérdida (slope 1, intercept 0).
- Atomicidad: se escribe en un directorio de staging hermano (`.dicomwriter-*`) y se mueve con `os.replace` al final; un fallo a mitad no deja archivos nuevos ni temporales.
- Directorio de salida no vacío → `FileExistsError` salvo `overwrite=True`. Con `overwrite=True` nunca se borran archivos previos (solo se reemplazan los `slice-NNNN.dcm` con el mismo nombre); si hay `slice-*.dcm` de más (serie anterior más larga) → `ValueError` sin escribir. Si la validación falla no se escribe nada.
- Affine con eje de corte opuesto a `cross(fila, columna)` (determinante < 0): al releer con `build_series_volume` el volumen es el mismo con el eje de corte invertido (affine equivalente, no idéntico).
- 4D → DICOM queda fuera de v1 por decisión explícita: un volumen 4D lanza `ValueError("Only 3D volumes are supported.")`. Si se necesita, será un cambio posterior.
- Conformidad: no se escriben `ScanningSequence` ni `SequenceVariant` (tipo 1 del IOD MR) por decisión de diseño. El archivo **no pasa un validador estricto del IOD MR** (p. ej. `dciodvfy`) por esos dos atributos, aunque pydicom lo abre. Apertura en 3D Slicer / ITK-SNAP: verificación manual pendiente.

## Límites

- No hay transacción única en el `os.replace` final; un crash entre movimientos puede dejar una mezcla de archivos nuevos y viejos con `overwrite=True`.
- Si el proceso es matado (SIGKILL) puede quedar un directorio `.dicomwriter-*` sin limpiar.
