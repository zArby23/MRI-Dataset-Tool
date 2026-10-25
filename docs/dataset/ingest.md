# Ingesta de DICOM y NIfTI sueltos (`dataset build --format dicom|nifti`)

`dataset build` acepta tres entradas y todas terminan en el **mismo dataset BIDS anonimizado** (`OUT/dataset`),
con las mismas etiquetas, particiones y reporte:

| `--format` | Entrada | Participante / sesión | Sufijo BIDS |
|---|---|---|---|
| `bids` (defecto) | dataset BIDS | entidades `sub-`/`ses-` de los nombres | sufijo del nombre |
| `dicom` | árbol de archivos DICOM | `PatientID` seudonimizado; una sesión por estudio | reglas sobre `SeriesDescription`/`ProtocolName` |
| `nifti` | carpeta de `.nii`/`.nii.gz` sin nombres BIDS | un participante por archivo (id derivado de la ruta) | reglas sobre el nombre del archivo |

En `dicom` y `nifti` una tabla opcional `--mapping` corrige o fuerza participante, sesión, sufijo y etiqueta. El
camino `bids` no cambia y no admite `--mapping`.

Código: `infrastructure/dataset/suffix_rules.py` (reglas), `infrastructure/dicom/identity.py` (identidad DICOM),
`application/services/dataset_ingest.py` (tabla, planificación y lectura en streaming).

## 1. Planificación antes de crear nada

Antes de crear la carpeta de salida, la herramienta lee solo cabeceras (DICOM) o nombres (NIfTI), aplica las reglas
y la tabla, y decide el participante, la sesión, el sufijo y la etiqueta de cada serie. Termina con código 2, sin
escribir nada, si:

- la tabla `--mapping` es inválida (sección 4);
- dos series de un mismo participante/sesión reciben etiquetas distintas;
- la tabla le daría a un estudio DICOM más de un participante o sesión;
- dos estudios distintos quedarían con el mismo participante y sesión (p. ej. una fila `.` con participante y
  sesión sobre un árbol con varios estudios);
- un participante quedaría con sesión en unas series y sin sesión en otras;
- no hay estudios válidos en la entrada, o ninguna serie tiene sufijo.

Después lee un estudio a la vez (un volumen vivo): DICOM se construye con `build_series_volume` y se guarda en
`float32`; NIfTI se lee de forma perezosa. Una serie que no se puede construir (multi-frame, mosaico, geometría
inconsistente...) se cuenta como archivo omitido y el lote sigue. Si al final no se exportó ningún estudio, la etapa
de exportación falla (código 1).

## 2. Identidad

### DICOM

- **Participante:** `PatientID` seudonimizado con HMAC-SHA256 y `MRI_ANON_KEY` (`pseudonymize_label`, el mismo de la
  política de anonimización). Dos estudios del mismo `PatientID` son el mismo participante.
- **Sin `PatientID`**, o con valores distintos dentro del estudio: un participante por estudio, seudónimo del
  `StudyInstanceUID`.
- **Sesión:** cada `StudyInstanceUID` es una sesión (seudónimo del UID).
- `PatientID`, `SeriesDescription` y `ProtocolName` se leen en una segunda pasada de cabeceras
  (`stop_before_pixels`) y **solo viven en memoria**: no se devuelven, no se registran en logs y no se escriben.

### NIfTI suelto

- Sin tabla: **un participante por archivo**, sin sesión, con id = seudónimo de su ruta relativa (nunca el nombre en
  claro). Dos archivos del mismo paciente quedan como dos participantes: use la tabla para agruparlos.
- Con tabla: los archivos con el mismo participante y sesión forman un solo estudio (una sesión con varias series).

### Relación con el paso `anonymize`

Los ids automáticos ya son seudónimos de 16 hex (`[A-Za-z0-9]+`, válidos en BIDS). Como el seudónimo se
autoverifica con la clave, el paso `anonymize` los deja iguales. Los ids que el usuario da en la tabla
(`participant`, `session`) deben ser `[A-Za-z0-9]+` y `anonymize` los seudonimiza, como en la entrada BIDS: nunca
llegan al dataset en claro. `dataset build` exige que la configuración incluya `anonymize`.

## 3. Reglas de sufijo

El texto (DICOM: `SeriesDescription` + `ProtocolName`; NIfTI: nombre sin `.nii`/`.nii.gz`) se pasa a minúsculas y
se parte en palabras alfanuméricas (`T1_MPRAGE_SAG` → `t1`, `mprage`, `sag`). Una serie DICOM con `Modality`
distinta de `MR` se excluye.

| Sufijo | Palabras | Ejemplos |
|---|---|---|
| `FLAIR` | `flair` (gana a `t2`) | `t2_flair_tra`, `FLAIR` |
| `T2starw` | `t2star`, o el texto `t2*` (también `t2 *`) | `T2*`, `t2star` |
| `T2w` | `t2`, `t2w` | `T2 TSE axial`, `sub-01_T2w` |
| `T1w` | `t1`, `t1w`, `mprage`, `bravo`, `spgr` | `T1_MPRAGE_SAG`, `Sag BRAVO`, `3D SPGR` |
| `PDw` | `pd`, `pdw`, o `proton` + `density` | `PD TSE`, `proton density` |
| `dwi` | `dwi`, `dti`, `diffusion`, `dmri`, `diff` | `ep2d_diff_mddw_30`, `DTI 64 dir` |

Resultado y código (cada serie omitida se cuenta en `WARNING UNMAPPED_SERIES`):

| Código | Cuándo | Ejemplos |
|---|---|---|
| `MATCHED` | exactamente un sufijo y ninguna exclusión | `T1 MPRAGE` → `T1w` |
| `EXCLUDED` | alguna palabra excluida, o `Modality` ≠ `MR` | ver la tabla siguiente |
| `AMBIGUOUS` | más de un sufijo | `PD T2 dual echo`, `PD_T2`, `t1 t2 combined`, `Sag T1 FLAIR` |
| `NO_MATCH` | ningún sufijo | `Brain tumour follow-up`, `t1map`, `magnitude`, `phasediff`, texto vacío |
| `NOT_4D_DWI` | sufijo `dwi` pero el volumen no es 4D (un mapa derivado o un solo volumen); aviso propio `WARNING NOT_4D_DWI: n` | `diffusion` 3D |

Exclusiones (cualquiera → `EXCLUDED`):

| Grupo | Palabras | Ejemplos excluidos |
|---|---|---|
| Localizadores | `localizer`, `localiser`, `scout`, `survey`, `loc` | `localizer`, `AAHead_Scout` |
| Mapas derivados | `adc`, `fa`, `trace`, `tracew`, `colfa`, `exp`, `tensor`, `dixon`, `mpr`, `mip`, `reformat` | `ep2d_diff_ADC`, `DWI TRACEW`, `dti FA`, `ep2d_diff_TENSOR`, `t1_vibe_dixon_W`, `t1 MPR cor` |
| Contraste | `c`, `km`, `mdc`, `ce`, y `post`, `gd`, `gad`, `contrast` también dentro de una palabra | `+C Ax T1`, `T1+C`, `T1_MPRAGE_postGd`, `T1 postcontrast`, `t1_se_tra_KM`, `sub-01_ce-gd_T1w` |
| Sustracción | `subtraction`; en DICOM también `sub` | `T1_SUB`, `t1_mprage_sag_SUB` |
| Dark-fluid llamado T2 | `dark`, `darkfluid`, `tirm` | `t2_tse_dark-fluid_tra`, `t2_tirm_tra_dark-fluid` |
| Eco de gradiente llamado T2 | `gre`, `ffe`, `fl2d`, `fl3d`, `medic`, `merge` | `Ax T2 GRE`, `T2W_FFE`, `t2_fl2d_tra`, `T2 * GRE` |
| Mapas cuantitativos y dinámicos | `map`, `mapping`, `molli`, `dyn`, `dynamic`, `perf`, `twist` | `T1 map`, `T2_mapping`, `T1_MOLLI`, `t1_vibe_dyn`, `T1 perf` |
| Perfusión, angiografía, SWI | `perfusion`, `dsc`, `dce`, `asl`, `swi`, `mra`, `tof` | `perfusion DSC`, `DCE`, `TOF MRA`, `SWI` |
| Funcionales | `bold`, `fmri`, `rest`, `resting` | `ep2d_bold_rest` |
| Varias imágenes por serie | `mp2rage`, `inv1`, `inv2`, `uni` | `MP2RAGE UNI` |

`sub` solo se excluye en DICOM: en los nombres NIfTI es la entidad BIDS de sujeto (`sub-01_T1w` → `T1w`). Un T2*
adquirido como eco de gradiente se omite (no se puede separar con seguridad de un T2w): fuércelo con la tabla.

Las reglas son deliberadamente conservadoras: un sufijo errado contaminaría el dataset, así que lo dudoso se omite
y se avisa. `magnitude1`, `magnitude2` y `phasediff` **nunca** se reconocen por texto: solo con la tabla.

## 4. Tabla `--mapping`

TSV en UTF-8 (se admite el BOM que añaden las hojas de cálculo), separado por tabuladores, con cabecera exacta:

```text
path	participant	session	suffix
```

o, con etiquetas:

```text
path	participant	session	suffix	label
```

- `path`: ruta **relativa a la entrada**, con `/`, de una carpeta o un archivo (`.` = toda la entrada). Es lo que
  usted conoce de su árbol: la carpeta de un paciente o de una serie DICOM, o un archivo NIfTI.
- Una fila aplica a todo archivo que esté bajo su `path`. Por columna gana el valor no vacío de la fila **más
  profunda**: una fila de carpeta puede fijar el participante y una de subcarpeta el sufijo. En DICOM una serie
  toma las filas que contienen todos sus archivos, y el participante/sesión de un estudio salen de las filas que
  contienen el estudio entero. Una fila que apunta a **un solo archivo** de una serie DICOM no aplica a la serie
  (queda como `MAPPING_UNUSED`): use la carpeta de la serie.
- Las rutas se comparan **exactamente**, mayúsculas incluidas, también en Windows: `Paciente1` no es `paciente1`.
- `participant`, `session`: vacío o `[A-Za-z0-9]+`. Se seudonimizan al anonimizar.
- `suffix`: vacío o uno de `T1w`, `T2w`, `PDw`, `T2starw`, `FLAIR`, `dwi`, `magnitude1`, `magnitude2`, `phasediff`.
  Fuerza el sufijo por encima de las reglas (así se corrige un sufijo errado o se mapea un mapa de campo).
- `label`: vacío o una de las clases de `--classes` (obligatorio si hay etiquetas). Se aplica al par
  (participante, sesión) de las series bajo ese `path`, con la misma regla de la fila más profunda.

Ejemplo (un paciente con dos visitas y una serie forzada):

```text
path	participant	session	suffix	label
paciente1	P01			
paciente1/visita1		V1		AD
paciente1/visita2		V2		AD
paciente1/visita2/serie7			FLAIR	
```

Cada fila lleva las cinco columnas (las vacías como tabuladores seguidos).

Validación (código 2, mensaje fijo sin valores): archivo inexistente o no UTF-8, cabecera distinta, número de
columnas distinto, `path` vacío, absoluto, con `..`, `\` o `:`, `path` repetido, `participant`/`session`/`suffix`
inválidos, `label` sin `--classes` o fuera de ellas, y **cualquier `path` que no exista en la entrada con ese
nombre exacto** (`Mapping paths not found in the input: N.`). Una fila válida que no aplica a ninguna serie se avisa con
`WARNING MAPPING_UNUSED: N`.

### Etiquetas de la tabla

Las etiquetas se aplican después de escribir la plantilla de `--classes`, como una corrección registrada en
`labels_changes.tsv`, y luego siguen `--corrections`, la revisión y el cierre de siempre (si quedan completas, se
cierran y se escriben los exportes para ML). Solo se aplican a los pares que llegaron al dataset. El archivo
temporal que se usa contiene solo seudónimos y se borra. Es la forma práctica de etiquetar una entrada DICOM:
usted conoce sus carpetas, no los seudónimos.

## 5. Límites

- `--mapping` (y por tanto `label`) con `--format bids` termina con código 2.
- `magnitude1/2` y `phasediff` solo por tabla; `bold` y las demás no listadas no se escriben (el dataset no tiene `task-`).
- No se leen otros campos DICOM (p. ej. `ImageType`); defacing y texto quemado en los píxeles quedan fuera.
- `dwi` sin `.bval`/`.bvec` y `phasediff` sin `EchoTime1/2`, como en el resto del dataset (`docs/dataset/structure.md`).
- Dos estudios DICOM con el mismo participante y sesión (p. ej. por la tabla) terminan con código 2 antes de crear
  nada (sección 1). La comparación se hace con los seudónimos finales: un id de la tabla igual al `PatientID` de otro
  estudio es el mismo participante.
- Sin tabla, los NIfTI de un mismo paciente quedan como participantes distintos.
