# Política de anonimización (RF09, RNF07)

> **Versión de la política: `1`** (`POLICY_VERSION` en `infrastructure/anonymization/policy.py`).
> Estado: **política v1 vigente desde el 2026-10-20** (etapa 3).
> Guía de uso en la sección 7.

La política es **datos**: listas blancas y una tabla etiqueta → acción. Lo que no aparece en una
lista se **descarta**.

**Versionado:** la versión `1` es la vigente desde el 2026-10-20. Desde entonces,
cualquier cambio que altere un resultado anonimizado sube `POLICY_VERSION`.

| Módulo | Contenido |
|---|---|
| `infrastructure/anonymization/policy.py` | `POLICY_VERSION`, `Action`, listas blancas (`METADATA_WHITELIST`, `SIDECAR_WHITELIST`, `PROVENANCE_WHITELIST`, entidades BIDS), `VALIDATION_STATUSES`, `filter_validation`, `DICOM_ACTIONS`, `DICOM_DEFAULT_ACTION`, `DICOM_FIXED_VALUES` |
| `infrastructure/anonymization/pseudonym.py` | `load_key` (`MRI_ANON_KEY`), `pseudonymize_uid`, `pseudonymize_label` |
| `application/pipeline/steps/anonymize.py` | Paso `anonymize` sobre `MRIStudy` (A1, sección 2) |
| `infrastructure/anonymization/dicom.py` | `anonymize_dataset` (aplica la tabla de la sección 4) y `generalize_date`/`generalize_datetime`/`generalize_age` |
| `infrastructure/anonymization/report.py` | `AnonymizationReport` |
| `application/services/anonymize.py` | `anonymize_dicom_tree` sobre archivos DICOM (A2, sección 5) |

## 1. Seudónimos y clave

- **HMAC-SHA256** con una clave secreta leída de la variable de entorno `MRI_ANON_KEY`. La clave se
  lee **al construir el paso** (`build_step`, `pipeline_from_config`, `pipeline_from_manifest`): sin
  ella, vacía o con menos de **32 caracteres** → `ValueError("Anonymization key is not set or too short.")`
  antes de procesar nada. `anonymize_dicom_tree` la lee al llamarse, antes de crear nada. El mínimo
  evita adivinar una clave corta por fuerza bruta sobre IDs cortos.
- **Deterministas**: mismo valor + misma clave → mismo seudónimo, en la corrida y entre corridas.
  Otra clave → otros seudónimos. **No hay tabla de correspondencia.**
- Dominios separados: el mismo texto como UID, sujeto o sesión da seudónimos sin relación.
- **Formatos:** UID → `2.25.<entero de 128 bits>` (máx. 44 caracteres, UID DICOM válido);
  `subject_id`/`session_id` → 16 caracteres hex en minúsculas (etiqueta BIDS válida).
- **Autoverificables (idempotencia):** seudónimo = `h ‖ MAC(clave, h)`, con `h = HMAC(clave, valor)`
  truncado (UID: 96 + 32 bits; etiqueta: 40 + 24 bits). Un valor que ya verifica con la clave se
  conserva, así que anonimizar dos veces da lo mismo que una.
  **Supuesto:** quien no tiene la clave no puede fabricar un valor que verifique. Un valor original
  verifica por azar con probabilidad 2⁻³² (UID) o 2⁻²⁴ (etiqueta de 16 hex); en ese caso se conservaría
  sin seudonimizar. Es un riesgo aceptado, pero distinto de cero.
- **Colisiones (aceptado):** la parte `h` de la etiqueta tiene 40 bits. Con 10 000 sujetos, la
  probabilidad de que dos tengan el mismo seudónimo es ≈ 5·10⁻⁵ (n²/2⁴¹); si ocurre, los dos sujetos se
  fundirían en uno. Para UIDs (`h` de 96 bits) es despreciable.
- La clave nunca aparece en `params`, `repr`, logs, errores, manifiesto ni informes. Si se filtra,
  permite recalcular seudónimos de IDs conocidos: debe guardarse fuera del repositorio.

## 2. Paso `anonymize` (modelo de dominio)

`params = {"policy_version": "1"}` (llega al manifiesto); otra versión → `ValueError`.
Declara `redacts_sources: ClassVar[bool] = True` (no está en `params` ni en `repr`): en
un pipeline con `anonymize`, los `StudyReport` del manifiesto no guardan la ruta de origen.

- `study_uid`, `series_uid` → seudónimo UID; `subject_id`, `session_id` → seudónimo de etiqueta;
  `None` se queda en `None`.
- `files` → `[]`: las rutas de origen llevan nombres de sujeto, sesión o institución.
- `modality` se conserva (DICOM `MR` o sufijo BIDS).
- `metadata`: solo las claves de la sección 3; lo demás se descarta.
- `volume` no se toca ni se lee: un volumen perezoso sigue perezoso.
- No muta la entrada y es determinista dada la clave.

## 3. Listas blancas del modelo

`METADATA_WHITELIST` también la importa `summarize_study` (I2): hay una sola definición.

| Grupo | Claves | Por qué se conservan |
|---|---|---|
| Geometría y arreglo | `shape`, `voxel_size`, `affine`, `orientation`, `datatype`, `bitpix`, `qform_code`, `sform_code`, `rows`, `columns`, `pixel_spacing`, `slice_thickness`, `spacing_between_slices`, `image_orientation` | Describen la malla de voxels, no a la persona; el pipeline los necesita (contrato de geometría) |
| Filtradas | `sidecar`, `bids`, `provenance`, `validation` | Se filtran clave por clave (abajo) |

**`provenance` (`PROVENANCE_WHITELIST`)**: la escribe `application/services/conversion.py` con
valores fijos. Solo se conservan sus claves conocidas (`tool`, `source_format`, `target_format`,
`nibabel_version`, `compression`, `sop_class`, `image_type`) con valor `str`. Cualquier clave nueva,
p. ej. un directorio de origen, se descarta hasta que se añada aquí.

**`validation`**: la escribe el paso `validate`. Se conservan `status` si está en `VALIDATION_STATUSES`
(`ok`) y, de `findings`, solo los códigos en `UPPER_SNAKE_CASE` (p. ej. `CONSTANT_VOLUME`). Lo demás
se descarta. El filtro es `filter_validation(value) -> dict` en `policy.py` (devuelve `{}` si el valor
no es un diccionario); lo usan `anonymize` y `summarize_study`.

**`sidecar` (`SIDECAR_WHITELIST`)**: solo parámetros técnicos de adquisición. De cada clave
permitida solo se conserva un escalar (`str`, número, `bool`) o una lista de escalares; un diccionario
u otro valor anidado se descarta.

| Grupo | Claves | Por qué no identifican |
|---|---|---|
| Equipo (clase) | `Manufacturer`, `ManufacturersModelName`, `MagneticFieldStrength` | Identifican el modelo de escáner, que comparten miles de equipos; no la institución, la estación ni el número de serie |
| Secuencia | `MRAcquisitionType`, `ScanningSequence`, `SequenceVariant`, `ScanOptions`, `SequenceName`, `PulseSequenceType` | Códigos del protocolo |
| Tiempos | `RepetitionTime`, `EchoTime`, `InversionTime`, `SliceTiming`, `EffectiveEchoSpacing`, `TotalReadoutTime`, `EchoTrainLength` | Duraciones en segundos **relativas al inicio del volumen** (`SliceTiming` es el desfase de cada corte), nunca hora de reloj ni fecha |
| Codificación | `FlipAngle`, `SliceThickness`, `SliceEncodingDirection`, `PhaseEncodingDirection`, `ParallelReductionFactorInPlane`, `PartialFourier`, `MultibandAccelerationFactor`, `PixelBandwidth` | Parámetros del protocolo |

**Excluida a propósito**: `ImagingFrequency`. La frecuencia central exacta se ajusta por equipo y por
sesión, así que puede servir de huella del escáner o del día de la adquisición; `MagneticFieldStrength`
ya da la información técnica útil. También quedan fuera los descriptores de texto libre
(`SeriesDescription`, `ProtocolName`, `TaskName`, …), todo lo de institución, estación u operador,
y fechas y horas.

**`bids`**: `sub`/`ses` → los mismos seudónimos que `subject_id`/`session_id`. Se conservan `suffix`
y `extension`. De `other` solo quedan las entidades de adquisición de la especificación BIDS MRI
(`task`, `acq`, `ce`, `rec`, `dir`, `run`, `echo`, `flip`, `inv`, `mt`, `part`, `chunk`); una entidad
no estándar se descarta. Las **claves** de estas entidades describen la adquisición (contraste,
dirección de fase, repetición), pero sus **valores** (`acq-<etiqueta>`, `task-<etiqueta>`, …) son
**texto libre** que elige quien organiza el dataset y no se filtran. Un `acq-<nombre>` mal elegido
llevaría texto identificable a la salida (riesgo residual, sección 6).

## 4. Tabla DICOM

Lista blanca: **todo elemento no listado se elimina** (`removed`), incluidos los elementos privados y
las secuencias no listadas (con todo su contenido anidado). `DICOM_ACTIONS` usa keywords de pydicom.

| Acción | Elementos | Regla |
|---|---|---|
| `replaced` | `StudyInstanceUID`, `SeriesInstanceUID`, `SOPInstanceUID`, `MediaStorageSOPInstanceUID`, `FrameOfReferenceUID`, `PatientID` | Seudónimo HMAC (sección 1), consistente en toda la serie |
| `replaced` | `PatientIdentityRemoved` = `YES`, `DeidentificationMethod` = `MRI-Dataset-Tool anonymization policy <POLICY_VERSION>` | Marcas de desidentificación de PS3.15 E.1.1 (`DICOM_FIXED_VALUES`); se añaden si faltan |
| `emptied` | `PatientName`, `PatientBirthDate`, `ReferringPhysicianName`, `StudyID`, `AccessionNumber`, `StudyTime` | Tipo 2: deben existir, pero llevan identidad, fecha de nacimiento u hora |
| `generalized` | `StudyDate`, `SeriesDate`, `AcquisitionDate`, `ContentDate`, `AcquisitionDateTime`, `PatientAge` | Ver reglas abajo |
| `kept` | `PatientSex` | Decisión de diseño |
| `kept` | `SpecificCharacterSet`, `SOPClassUID`, `MediaStorageSOPClassUID`, `TransferSyntaxUID`, `Modality`, `ImageType` | Codificación y tipo de objeto |
| `kept` | Módulo de píxel y geometría: `Rows`, `Columns`, `SamplesPerPixel`, `PhotometricInterpretation`, `BitsAllocated`, `BitsStored`, `HighBit`, `PixelRepresentation`, `PixelData`, `RescaleSlope`, `RescaleIntercept`, `RescaleType`, `WindowCenter`, `WindowWidth`, `PixelSpacing`, `SliceThickness`, `SpacingBetweenSlices`, `ImageOrientationPatient`, `ImagePositionPatient`, `SliceLocation`, `PatientPosition`, `SeriesNumber`, `InstanceNumber`, `AcquisitionNumber`, `TemporalPositionIdentifier`, `NumberOfTemporalPositions` | Los necesita `build_series_volume` para reconstruir el volumen; no describen a la persona |
| `kept` | Técnicos: `Manufacturer`, `ManufacturerModelName`, `MagneticFieldStrength`, `MRAcquisitionType`, `ScanningSequence`, `SequenceVariant`, `ScanOptions`, `SequenceName`, `RepetitionTime`, `EchoTime`, `InversionTime`, `EchoTrainLength`, `FlipAngle`, `PixelBandwidth` | Mismos grupos que el sidecar |
| `removed` | Todo lo demás: dirección, otros IDs, peso y talla, institución, estación, número de serie, médicos y operadores, descripciones y comentarios, horas, secuencias de referencia, privados | Perfil básico de PS3.15 más la lista blanca |

**Fechas** (decisión de diseño): DA → `AAAA0101`; DT → `AAAA` (DT admite solo el año); TM eliminado
(o vacío si es tipo 2, como `StudyTime`). **Excepción:** `PatientBirthDate` se vacía (no conserva
el año). La edad solo se conserva a través del rango de `PatientAge`.

**Edad** (decisión de diseño): `PatientAge` (AS, `nnnD/W/M/Y`) → límite inferior de su rango de 10
años, p. ej. `047Y` → `040Y`. 90 años o más → `090Y`. D/W/M se pasan a años antes; menos de 1 año → `000Y`.
El VR AS no admite `90+` ni rangos, por eso se escribe el límite inferior.

Un valor que no se puede generalizar (formato inválido o multivaluado) se vacía y el informe lo
cuenta como `emptied`. `PatientID` usa el mismo dominio de seudónimo que `subject_id` (`"subject"`):
el mismo ID con la misma clave da el mismo seudónimo en DICOM y en el modelo.

## 5. Servicio `anonymize_dicom_tree` (A2)

`anonymize_dicom_tree(input_dir, output_dir, on_error=None) -> AnonymizationReport`, con el mismo
patrón que `application/services/conversion.py`:

1. Antes de leer o crear nada: entrada inexistente → `FileNotFoundError`; no es directorio →
   `NotADirectoryError`; `output_dir` dentro de `input_dir` (o igual) → `ValueError`; sin clave →
   `ValueError`; `output_dir/anonymization_report.json` ya existe → `FileExistsError`.
2. Recorre `input_dir` como `DICOMBatchReader`: orden determinista, y se ignoran sin reportarlos los
   archivos y directorios ocultos (`.git`, …).
3. Cada archivo se lee completo con `pydicom.dcmread` y se le aplica la tabla de la sección 4 (file meta
   incluida). Al guardar, pydicom regenera con sus propios valores los elementos obligatorios de la file
   meta (`FileMetaInformationVersion`, `ImplementationClassUID`, `ImplementationVersionName`). Los
   datos de píxel y la sintaxis de transferencia no cambian. El **preámbulo** de 128 bytes (bytes
   libres fuera de todo elemento, donde algunos exportadores y los archivos «dual personality»
   escriben cabeceras con datos) se reescribe a ceros. Es una corrección de un defecto, no un cambio
   de política (sigue la versión `1`). Un elemento estándar con VR `UN` que deba generalizarse hace
   fallar el archivo entero: se reporta por `on_error` y no se escribe (seguro, pero ruidoso). pydicom
   ya convierte `UN` al VR conocido por defecto.
4. Salida: `output_dir/study-<id>/series-<id>/<id>.dcm`, donde cada `<id>` son 16 hex derivados por
   HMAC del UID **nuevo** (sin identificadores; estables entre corridas con la misma clave). Escritura
   atómica (temporal oculto + `os.replace`); una salida existente da `FileExistsError` y no se
   reemplaza. Hay una ventana mínima entre la comprobación y el reemplazo, como en `NIfTIWriter`.
   Colisión de nombres: los `<id>` usan la parte de 40 bits del seudónimo. Con ~10⁴ cortes en un mismo
   directorio, la probabilidad de que dos compartan nombre es ≈ 5·10⁻⁵. Si ocurre, el segundo da
   `FileExistsError` reportado: nunca hay pérdida silenciosa.
5. Un archivo ilegible, no DICOM, sin `Study/Series/SOPInstanceUID` o que falla al escribirse se
   reporta con `on_error(path, error)` y el lote sigue. Un callback que lanza se captura y solo se
   registra su tipo.
6. El informe (`AnonymizationReport`: `policy_version`, `files_written`, `files_failed` y, por
   etiqueta, acción → conteo) se guarda en `output_dir/anonymization_report.json` y se devuelve.
   Etiquetas: keyword DICOM o `GGGG,EEEE` para las privadas. Nunca guarda valores, rutas, UIDs ni la
   clave. Los elementos dentro de una secuencia eliminada no se cuentan por separado. Las acciones
   se acumulan por archivo y solo se suman al informe si el archivo se escribe: los conteos
   corresponden a `files_written`.
7. Logs: solo contadores y nombres de tipo de excepción.

Para volver a ejecutar sobre la misma salida hay que retirar antes el informe; los archivos ya
escritos se reportan entonces como `FileExistsError`.

## 6. Riesgo residual

- **La imagen** puede reidentificar: reconstrucción de la cara en volúmenes 3D (*defacing* fuera de
  alcance) y texto quemado en los píxeles (fuera de alcance).
- **Cuasi-identificadores conservados**: año de las fechas del estudio, rango de edad, sexo y modelo de escáner.
  En conjunto, y en cohortes pequeñas, pueden reducir mucho el número de candidatos.
- **Valores de claves permitidas**: una clave técnica permitida (p. ej. `Manufacturer`) que un equipo
  rellene con texto identificable se conservaría; la lista blanca filtra claves, no el contenido.
- **Clave HMAC**: quien la tenga puede comprobar si un ID conocido corresponde a un seudónimo (no
  hay tabla, pero sí recálculo). Debe guardarse fuera del repositorio y no compartirse con el dataset.
- **Verificación por azar** (sección 1): un ID original verifica como seudónimo con probabilidad 2⁻²⁴
  (etiqueta) o 2⁻³² (UID) y se conservaría sin seudonimizar.
- **Colisiones** (aceptadas): dos sujetos con el mismo seudónimo de 40 bits se fundirían (≈ 5·10⁻⁵
  con 10⁴ sujetos); dos cortes con el mismo nombre de salida dan `FileExistsError` reportado (sección 5).
- **Valores de entidades BIDS** permitidas (`acq-`, `task-`, …): texto libre del autor del dataset, sin filtrar.
- **Manifiesto**: `StudyReport.source_path` guarda la ruta del archivo de **entrada** (en BIDS contiene
  `sub-<ID>`). El paso declara `redacts_sources = True` y el runner deja
  `source_path = None` en las corridas con `anonymize`. `on_error` sigue recibiendo
  la ruta: quien lo implemente no debe volcarla en salidas compartidas.
- **Validación con datos sintéticos**: las pruebas usan solo DICOM sintéticos. La revisión de un
  informe y de una salida reales es una verificación manual pendiente, fuera del repositorio (sección 7).

## 7. Guía de uso

1. **Definir la clave** (al menos 32 caracteres; guárdala fuera del repositorio; con otra clave, los
   seudónimos cambian):

   ```powershell
   $env:MRI_ANON_KEY = python -c "import secrets; print(secrets.token_urlsafe(32))"   # Windows
   ```

   ```bash
   export MRI_ANON_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"   # Linux
   ```

   Para reproducir una corrida (mismos UIDs y nombres), reutiliza la misma clave.

2. **Anonimizar un árbol DICOM** en un directorio de salida que no esté dentro de la entrada:

   ```python
   from pathlib import Path
   from mri_dataset_tool.application.services.anonymize import anonymize_dicom_tree

   failed = []
   report = anonymize_dicom_tree(Path("ruta/entrada"), Path("ruta/salida"),
                                 on_error=lambda path, error: failed.append((path, type(error).__name__)))
   print(report.files_written, report.files_failed)
   ```

   En un pipeline, añade el paso `anonymize` a `pipeline.steps` del YAML (sin `params`, o con
   `policy_version: "1"`).

3. **Leer el informe** `ruta/salida/anonymization_report.json`: `policy_version`, `files_written`,
   `files_failed` y, por etiqueta, cuántas veces se aplicó cada acción. Comprueba que los conteos
   cuadran con `files_written` y que no aparece ninguna etiqueta `kept` inesperada. Los errores de
   `on_error` llevan la ruta de entrada: no los compartas con la salida.

4. **Verificación manual (pendiente, fuera del repositorio):** correr el servicio sobre un DICOM real,
   revisar el informe y buscar en la salida (abriéndola con un visor DICOM o volcando las cabeceras)
   cualquier identificador: nombres, IDs, fechas completas, institución, texto libre. Nunca versionar
   datos reales ni sus salidas.
