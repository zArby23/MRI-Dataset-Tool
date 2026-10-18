# Lectores DICOM y reporte de errores (`on_error`)

`DICOMReader.load_study(directory)` y `DICOMBatchReader.load_studies(directory, on_error=None)` leen **solo cabeceras**
(`stop_before_pixels=True`, `specific_tags=DICOM_HEADER_TAGS`). Los píxeles se cargan después, de forma explícita, con
`build_series_volume` (ver `volume_builder.md`).

## `on_error` en `DICOMBatchReader`

```python
DICOMBatchReader().load_studies(directory, on_error: Callable[[Path, Exception], None] | None = None) -> list[MRIStudy]
```

- Se llama **una vez por cada archivo omitido**, con la ruta y la excepción:
  - archivo que no es DICOM válido → `InvalidDicomError`;
  - archivo ilegible → `OSError` / `EOFError`;
  - sin `StudyInstanceUID` o sin `SeriesInstanceUID` → `ValueError` con mensaje fijo (`Missing StudyInstanceUID.` / `Missing SeriesInstanceUID.`), sin valores de cabecera.
- El lote continúa (RF16). Si el propio callback lanza, la excepción se captura y el log solo registra su nombre de tipo.
- Sin callback el comportamiento es el mismo que antes (los conteos siguen en el log).
- Los logs llevan contadores y nombres de tipo de excepción; nunca rutas ni valores de cabecera. La ruta solo llega al llamador por `on_error`.

## Entradas ocultas

Se ignoran en silencio (sin `on_error` ni conteo de error) los directorios y archivos cuyo nombre empieza por `.`, relativos a la raíz
recibida (p. ej. `.git`, `.datalad`, `.git/annex`); esos directorios ni se recorren. Si la propia raíz está bajo un directorio oculto,
se carga con normalidad.

## No filtra por extensión

`DICOMBatchReader` recorre recursivamente **todos** los archivos no ocultos y no filtra por extensión. Un `README`, un `DICOMDIR`, un `.json` o
cualquier archivo no DICOM genera una llamada a `on_error` (normalmente `InvalidDicomError`). Esas llamadas no son errores de conversión:
quien consuma el callback no debe presentarlas al usuario como estudios fallidos sin distinguirlas.

`DICOMReader.load_study` es distinto: lee solo los archivos directos de un directorio (sin recursión) y no tiene `on_error`.
