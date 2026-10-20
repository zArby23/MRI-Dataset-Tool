# Política de anonimización (RF09, RNF07)

> **Versión de la política: `1`** (`POLICY_VERSION` en `infrastructure/anonymization/policy.py`).
> Estado: **propuesta pendiente de aprobación del humano (Checkpoint 1)**. Las listas de las
> secciones 3 y 4 son propuesta; las reglas de fechas, edad, seudónimos y clave ya las decidió el humano.

La política es **datos**: listas blancas y una tabla etiqueta → acción. Lo que no aparece en una
lista se **descarta**. Cualquier cambio que altere un resultado anonimizado sube `POLICY_VERSION`.

| Módulo | Contenido |
|---|---|
| `infrastructure/anonymization/policy.py` | `POLICY_VERSION`, `Action`, listas blancas del modelo y del sidecar, `DICOM_ACTIONS` |
| `infrastructure/anonymization/pseudonym.py` | Clave (`MRI_ANON_KEY`) y seudónimos HMAC |
| `application/pipeline/steps/anonymize.py` | Paso `anonymize` sobre `MRIStudy` (A1) |

El servicio sobre archivos DICOM (`anonymize_dicom_tree`, A2) aplicará la tabla de la sección 4; aún
no está implementado.

## 1. Seudónimos y clave

- **HMAC-SHA256** con una clave secreta leída de la variable de entorno `MRI_ANON_KEY`. La clave se
  lee **al construir el paso** (`build_step`, `pipeline_from_config`, `pipeline_from_manifest`): sin
  ella, vacía o con menos de **32 caracteres** → `ValueError("Anonymization key is not set or too short.")`
  antes de procesar nada. El mínimo evita adivinar una clave corta por fuerza bruta sobre IDs cortos.
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
- La clave nunca aparece en `params`, `repr`, logs, errores, manifiesto ni informes. Si se filtra,
  permite recalcular seudónimos de IDs conocidos: debe guardarse fuera del repositorio.

## 2. Paso `anonymize` (modelo de dominio)

`params = {"policy_version": "1"}` (llega al manifiesto); otra versión → `ValueError`.

- `study_uid`, `series_uid` → seudónimo UID; `subject_id`, `session_id` → seudónimo de etiqueta;
  `None` se queda en `None`.
- `files` → `[]`: las rutas de origen llevan nombres de sujeto, sesión o institución.
- `modality` se conserva (DICOM `MR` o sufijo BIDS).
- `metadata`: solo las claves de la sección 3; lo demás se descarta.
- `volume` no se toca ni se lee: un volumen perezoso sigue perezoso.
- No muta la entrada y es determinista dada la clave.

## 3. Listas blancas del modelo (propuesta)

`METADATA_WHITELIST` también la importa `summarize_study` (I2): hay una sola definición.

| Grupo | Claves | Por qué se conservan |
|---|---|---|
| Geometría y arreglo | `shape`, `voxel_size`, `affine`, `orientation`, `datatype`, `bitpix`, `qform_code`, `sform_code`, `rows`, `columns`, `pixel_spacing`, `slice_thickness`, `spacing_between_slices`, `image_orientation` | Describen la malla de voxels, no a la persona; el pipeline los necesita (contrato de geometría) |
| Escritas por la herramienta | `provenance`, `validation` | Las genera este código con valores fijos o códigos constantes, nunca valores de cabecera |
| Filtradas | `sidecar`, `bids` | Se filtran clave por clave (abajo) |

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
no estándar se descarta. Estas entidades describen la adquisición (contraste, dirección de fase,
repetición) y no a la persona. Riesgo residual: sus etiquetas las elige quien organiza el dataset, y
un `acq-<nombre>` mal elegido podría llevar texto identificable.

## 4. Tabla DICOM (para A2; propuesta)

Lista blanca: **todo elemento no listado se elimina** (`removed`), incluidos los elementos privados y
las secuencias no listadas (con todo su contenido anidado). `DICOM_ACTIONS` usa keywords de pydicom.

| Acción | Elementos | Regla |
|---|---|---|
| `replaced` | `StudyInstanceUID`, `SeriesInstanceUID`, `SOPInstanceUID`, `MediaStorageSOPInstanceUID`, `FrameOfReferenceUID`, `PatientID` | Seudónimo HMAC (sección 1), consistente en toda la serie |
| `emptied` | `PatientName`, `ReferringPhysicianName`, `StudyID`, `AccessionNumber`, `StudyTime` | Tipo 2: deben existir, pero llevan identidad u hora |
| `generalized` | `PatientBirthDate`, `StudyDate`, `SeriesDate`, `AcquisitionDate`, `ContentDate`, `AcquisitionDateTime`, `PatientAge` | Ver reglas abajo |
| `kept` | `PatientSex` | Decisión del humano |
| `kept` | `SpecificCharacterSet`, `SOPClassUID`, `MediaStorageSOPClassUID`, `TransferSyntaxUID`, `Modality`, `ImageType` | Codificación y tipo de objeto |
| `kept` | Módulo de píxel y geometría: `Rows`, `Columns`, `SamplesPerPixel`, `PhotometricInterpretation`, `BitsAllocated`, `BitsStored`, `HighBit`, `PixelRepresentation`, `PixelData`, `RescaleSlope`, `RescaleIntercept`, `RescaleType`, `WindowCenter`, `WindowWidth`, `PixelSpacing`, `SliceThickness`, `SpacingBetweenSlices`, `ImageOrientationPatient`, `ImagePositionPatient`, `SliceLocation`, `PatientPosition`, `SeriesNumber`, `InstanceNumber`, `AcquisitionNumber`, `TemporalPositionIdentifier`, `NumberOfTemporalPositions` | Los necesita `build_series_volume` para reconstruir el volumen; no describen a la persona |
| `kept` | Técnicos: `Manufacturer`, `ManufacturerModelName`, `MagneticFieldStrength`, `MRAcquisitionType`, `ScanningSequence`, `SequenceVariant`, `ScanOptions`, `SequenceName`, `RepetitionTime`, `EchoTime`, `InversionTime`, `EchoTrainLength`, `FlipAngle`, `PixelBandwidth` | Mismos grupos que el sidecar |
| `removed` | Todo lo demás: dirección, otros IDs, peso y talla, institución, estación, número de serie, médicos y operadores, descripciones y comentarios, horas, secuencias de referencia, privados | Perfil básico de PS3.15 más la lista blanca |

**Fechas** (decisión del humano): DA → `AAAA0101`; DT → `AAAA` (DT admite solo el año); TM eliminado
(o vacío si es tipo 2, como `StudyTime`).

**Edad** (decisión del humano): `PatientAge` (AS, `nnnD/W/M/Y`) → límite inferior de su rango de 10
años, p. ej. `047Y` → `040Y`. 90 años o más → `090Y`. D/W/M se pasan a años antes; menos de 1 año → `000Y`.
El VR AS no admite `90+` ni rangos, por eso se escribe el límite inferior.

## 5. Riesgo residual

- **La imagen** puede reidentificar: reconstrucción de la cara en volúmenes 3D (*defacing* fuera de
  alcance) y texto quemado en los píxeles (fuera de alcance, Q11).
- **Cuasi-identificadores conservados**: año de las fechas, rango de edad, sexo y modelo de escáner.
  En conjunto, y en cohortes pequeñas, pueden reducir mucho el número de candidatos.
- **Valores de claves permitidas**: una clave técnica permitida (p. ej. `Manufacturer`) que un equipo
  rellene con texto identificable se conservaría; la lista blanca filtra claves, no el contenido.
- **Seudónimos**: quien tenga la clave puede comprobar si un ID conocido corresponde a un seudónimo.
  También existe la verificación por azar de la sección 1.
- **Manifiesto**: `StudyReport.source_path` guarda la ruta del archivo de **entrada** tal cual (la del
  estudio antes de anonimizar). En BIDS esa ruta contiene `sub-<ID>`. Es la deuda de rutas absolutas
  del manifiesto (etapa 4) y el paso `anonymize` no la resuelve.
