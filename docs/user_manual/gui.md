# Manual de usuario: interfaz gráfica (`mri-dataset-gui`)

La interfaz gráfica es un asistente de seis pasos que convierte una carpeta de estudios (BIDS, DICOM o NIfTI
sueltos) en un dataset BIDS anonimizado, con etiquetas, exportes para ML y un reporte. Hace lo mismo que
`mri-dataset dataset build` y los comandos `labels` y `dataset` de la CLI (`docs/user_manual/cli.md`), con las
mismas validaciones y los mismos archivos de salida. La ventana muestra solo conteos, códigos y tipos de error:
**nunca** identificadores de pacientes, UIDs ni valores de cabecera. Las únicas rutas que aparecen son las que
usted elige y, en la tabla de mapeo (paso 3), las rutas relativas a la carpeta de entrada.

> Estado: en desarrollo. Las pruebas automáticas usan datos sintéticos. **Pendiente de verificación manual:**
> el recorrido completo con datos reales, el aspecto en Windows y en Linux y la ejecución en Linux.

## 1. Instalación y lanzamiento

Requisitos: Python 3.14 o superior con Tkinter (incluido en el instalador de Python para Windows; en Linux,
según la distribución, el paquete `python3-tk`).

```powershell
# desde la raíz del repositorio
python -m pip install -e .
mri-dataset-gui
```

Si `mri-dataset-gui` no está en el `PATH`, use el módulo:

```powershell
python -m mri_dataset_tool.presentation.gui
```

El menú **Idioma** cambia entre español (por defecto) e inglés en cualquier momento, también durante una tarea.
El idioma no se recuerda: al reabrir el programa vuelve a español.

## 2. Antes de empezar

### Clave de anonimización de la sesión

La GUI no pide la clave. Al abrirse:

- si la variable de entorno `MRI_ANON_KEY` existe y tiene al menos 32 caracteres, la usa y el paso 1 muestra
  «definida en el entorno»;
- si no existe, o tiene menos de 32 caracteres, **genera una clave nueva para esta sesión** (64 caracteres
  hexadecimales, al azar) y la guarda solo en la memoria del proceso. Nunca se muestra, se guarda ni se registra.
  (La CLI, con una clave corta, termina con error; la GUI la reemplaza.)

Con una clave nueva en cada sesión **los seudónimos cambian cada vez que abre el programa**. Consecuencias:

1. Construir dos veces el mismo origen en sesiones distintas da identificadores distintos.
2. Las etiquetas o correcciones (TSV) de una construcción no sirven para otra construcción posterior del mismo
   origen.
3. Dos datasets construidos en sesiones distintas no se pueden combinar: el mismo paciente tendría dos
   identificadores y podría quedar en particiones distintas (fuga entre entrenamiento y prueba).
4. El manifiesto de la corrida (`code/run_manifest.json`) solo se puede reproducir con la misma clave, es decir,
   dentro de la misma sesión.
5. La CLI con su propia `MRI_ANON_KEY` produce otros identificadores.

Etiquetar, cerrar, escribir los exportes para ML y generar el reporte **no** necesitan la clave: se pueden hacer
sobre un dataset ya construido en cualquier sesión. Si necesita seudónimos estables entre sesiones, defina
`MRI_ANON_KEY` (32 caracteres o más) antes de abrir la GUI, como con la CLI.

### Configuración

La GUI lee `config/default.yaml` y el preajuste `config/stage3_bids.yaml` de la **raíz del proyecto** (la carpeta
que contiene `src/`), desde donde sea que se abra. Solo si allí no existen los busca en la carpeta actual. La CLI,
en cambio, los busca en la carpeta actual. Un archivo de configuración propio (paso 2) puede estar en cualquier
lugar.

## 3. Los seis pasos

En la parte superior se ve «Paso N de M». «Siguiente» se habilita cuando el paso actual se validó; cambiar algo
en un paso invalida ese paso y los siguientes. Con una entrada BIDS no hay paso de mapeo (cinco pasos).

### Paso 1: Entrada

- **Carpeta de entrada** y su **formato**: BIDS, DICOM o NIfTI (archivos `.nii`/`.nii.gz` sin nombres BIDS).
- **Carpeta de salida**: debe estar fuera de la entrada y ser **nueva o estar vacía** (sin ningún archivo ni
  carpeta, ocultos incluidos). El selector de carpetas a veces la crea vacía: eso está bien.
  - Si la carpeta elegida **tiene contenido**, no se usa ni se sobrescribe: aparece el campo **«Nombre de la
    carpeta nueva»** y la salida pasa a ser `<carpeta elegida>/<nombre>`. El nombre debe ser simple (sin `/ \ :
    * ? " < > |`, sin `..`, sin punto ni espacio al final, y no un nombre reservado de Windows como `CON`) y no
    existir todavía.
- **Validar** comprueba todo (con las mismas reglas que la CLI) sin crear nada y luego estima el espacio en
  disco: si la salida estimada (el tamaño de la entrada) alcanza el 90 % del espacio libre del disco de salida,
  muestra un aviso. Es solo un aviso: la ejecución no se bloquea.

### Paso 2: Configuración

- **Archivo de configuración**: por defecto el preajuste `stage3_bids.yaml` (validate → anonymize → reorient →
  resample → normalize); puede elegir otro. Debe incluir el paso `anonymize`.
- **Uso de memoria** (texto obligatorio):

  > Antes de remuestrear (resample) o normalizar (normalize), la herramienta estima la memoria que necesita el
  > volumen de salida y la compara con la RAM disponible en ese momento. Si no alcanza, el estudio se marca como
  > fallido y el lote continúa con los demás. Puede forzar la ejecución con la casilla de abajo, que equivale al
  > parámetro `allow_insufficient_memory: true` de los pasos resample y normalize del archivo de configuración;
  > ese consentimiento queda registrado en el manifiesto de la corrida. Hágalo bajo su responsabilidad: si la
  > memoria no alcanza, el equipo puede volverse muy lento por el uso de disco como memoria, otros programas
  > pueden cerrarse, y el proceso puede terminar abruptamente sin guardar resultados (en Linux, el sistema puede
  > finalizarlo). La comprobación es una estimación en un instante y no cubre la memoria de otros pasos ni de
  > otros programas que se abran durante la ejecución. Volúmenes 4D grandes, como las difusiones, pueden
  > necesitar varios GB. Además, resample rechaza cualquier salida de más de `max_output_voxels` vóxeles (por
  > defecto 2**32, eje temporal incluido), aunque haya memoria; ese límite solo se cambia en el archivo de
  > configuración.

- **Clases de etiqueta**, una por línea: `NOMBRE` o `NOMBRE=descripción` (letras y números). Vacío = dataset sin
  etiquetas.
- Las proporciones y la semilla no se piden aquí: la ejecución usa los valores estándar (70/15/15, semilla 0).
  Escribe los exportes para ML en el dataset **solo si las etiquetas quedan cerradas en la ejecución** (completas
  por la tabla de mapeo) **o si no hay clases**; si quedan incompletas, los exportes se escriben en el paso 6,
  después de cerrarlas en el paso 5. Otros valores se usan en el paso 6.
- **Validar** muestra los pasos del pipeline con sus parámetros.

### Paso 3: Mapeo de series (solo DICOM y NIfTI)

**Vista previa** lee solo las cabeceras (DICOM) o los nombres (NIfTI) y muestra una fila por serie: carpeta o
archivo (relativo a la entrada), sufijo BIDS, la decisión (*detectado*, *por tabla*, u *omitida* con su motivo:
sin coincidencia, ambigua, excluida), participante, sesión y etiqueta. Los participantes y sesiones automáticos
son seudónimos. Las reglas de sufijo son las de `docs/dataset/ingest.md`.

- **Doble clic** en sufijo, participante, sesión o etiqueta para editarla (vacía = automático). El sufijo se
  aplica a la serie; participante, sesión y etiqueta a **todo el estudio**.
- **Asignar etiqueta a la selección**: seleccione varias filas (Ctrl o Mayús), elija la clase y pulse el botón.
- **Cargar tabla… / Guardar tabla…**: el mismo TSV que `--mapping` de la CLI (`path participant session suffix
  label`). Guardar nunca sobrescribe un archivo existente.
- Después de cualquier cambio pulse **Vista previa** otra vez: sin una vista previa válida no se puede seguir.
- Si los nombres no indican el sufijo (p. ej. NIfTI con nombres neutros como `scan_01.nii.gz`), la primera vista
  previa sin tabla termina con «Ninguna serie de la entrada tiene un sufijo BIDS» (`NO_MAPPED_SERIES`): **cargue
  primero una tabla** con los sufijos y luego pulse **Vista previa**.

### Paso 4: Ejecución

**Ejecutar** construye `<salida>/dataset` (BIDS anonimizado) y `<salida>/report` en segundo plano: la ventana
sigue respondiendo, pero **la tarea no se puede cancelar**. Se ven las etapas con sus cifras, los avisos fijos
(`UNMAPPED_SERIES`, `NOT_4D_DWI`, `MAPPING_UNUSED`, `MISSING_PATIENT_ID`, `LABELS_INCOMPLETE`) y, al terminar, los
errores por tipo, los archivos omitidos por el lector y los errores de lectura del reporte. Un estudio que falla
(p. ej. un volumen con NaN) se cuenta y el lote sigue. Si las etiquetas quedan completas (o no hay clases) se
cierran y se escriben los exportes para ML en este mismo paso.

Si una etapa completa falla se muestra cuál y el tipo de error: **vacíe o borre la carpeta de salida antes de
reintentar**. Tras una ejecución correcta, «Ejecutar» queda deshabilitado (la salida ya tiene contenido).

### Paso 5: Etiquetas

Una fila por par participante/sesión del dataset (seudónimos), con su clase y su defecto (*sin etiqueta*, *clase
desconocida*, *repetida en la tabla*, *falta en la tabla*). Todos los cambios quedan **pendientes** hasta
**Aplicar**, que los guarda todos o ninguno y los registra en `labels_changes.tsv`.

- **Doble clic** en la clase para cambiarla (vacía = sin etiqueta).
- **En lote**: seleccione filas (Ctrl o Mayús), elija la clase y pulse **Asignar a la selección**; o **Asignar a
  todas las sin etiquetar** (pide confirmación con el número de pares). El filtro **Mostrar** (todas, sin
  etiquetar, con defecto) ayuda a seleccionar.
- **Cargar correcciones desde TSV…**: un archivo con las columnas de `labels.tsv` (`participant_id`, `session_id`
  con los prefijos `sub-`/`ses-`, `label`), el mismo formato que `--corrections` de la CLI. Se valida entero y sus
  filas pasan a cambios pendientes.
- **Recargar** vuelve a leer la tabla y descarta los cambios pendientes (avisa cuántos).
- **Cerrar** exige todos los pares etiquetados y ningún cambio pendiente; habilita el paso 6. **Reabrir** permite
  volver a editar.

Con miles de pares cada acción tarda unos segundos (se recorre el árbol del dataset); corre en segundo plano.

### Paso 6: Exportes y reporte

- **Exportes para ML** (`dataset_index.csv`, `datalist.json`, `splits.tsv`, `splits.json`) con las proporciones y
  la semilla de este paso (por defecto 70/15/15 y 0):
  - si el dataset aún no los tiene (las etiquetas se cerraron en el paso 5), **Escribir exportes para ML** los
    escribe en el dataset, como `mri-dataset dataset export-ml`;
  - si ya los tiene, **Regenerar exportes en una carpeta nueva** escribe otro juego en `<salida>/ml_exports_2`,
    `ml_exports_3`…, con las rutas de las imágenes relativas a esa carpeta (`../dataset/sub-…`). Los exportes del
    dataset y los juegos anteriores nunca se sobrescriben ni se borran. Detalle en `docs/dataset/export.md`.
  - **La GUI exige etiquetas cerradas** (o un dataset sin etiquetas); la CLI permite exportar con etiquetas
    abiertas (`--allow-unfinalized`), la GUI no.
- **Generar reporte** (JSON, Markdown, XML y XLSX) en una carpeta **nueva o vacía** fuera del dataset. Como el paso
  4 ya escribió `<salida>/report`, se propone `report_2`, luego `report_3`… Se muestran los archivos escritos y
  los avisos del reporte (`UNREADABLE_FILES`, `LABELS_UNREADABLE`, `MANIFEST_UNREADABLE`).
- **Abrir la carpeta de salida** la abre en el explorador de archivos.

## 4. Cerrar la ventana durante una tarea

Si cierra la ventana mientras corre una tarea, se pide confirmación: **la tarea se corta y la salida queda
incompleta; vacíe o borre la carpeta de salida antes de reintentar.**

## 5. Errores frecuentes

| Mensaje (código) | Qué hacer |
|---|---|
| La carpeta de salida tiene contenido (`OUTPUT_NOT_EMPTY`) | Escriba el nombre de una carpeta nueva o elija otra carpeta. |
| La salida ya existe (`OUTPUT_EXISTS`) | La carpeta se llenó después del paso 1: elija otra. |
| La carpeta de salida debe estar fuera de la entrada (`OUTPUT_INSIDE_INPUT`) | Elija una salida fuera de la entrada. |
| No se encuentra el archivo de configuración / Configuración no válida (`CONFIG_NOT_FOUND`, `INVALID_CONFIG`) | Revise el archivo o use el preajuste. |
| El pipeline debe incluir el paso anonymize (`PIPELINE_WITHOUT_ANONYMIZE`) | Añada `anonymize` a la configuración. |
| Ninguna serie tiene un sufijo BIDS (`NO_MAPPED_SERIES`) | Fuerce los sufijos en el paso 3. |
| La tabla da a un estudio más de un participante o sesión (`MAPPING_STUDY_SPLIT`) | Use una fila con la carpeta del estudio. |
| Varias series comparten esta carpeta (`SHARED_SERIES_FOLDER`) | El sufijo no se puede fijar desde la tabla de la GUI; vea los límites. |
| Falló la etapa «…» (`STAGE_FAILED`) | Vacíe o borre la salida y reintente; el tipo de error orienta la causa. |
| No se puede cerrar: hay pares sin etiqueta o con defectos (`LABELS_INCOMPLETE`) | Use el filtro «con defecto» y etiquete. |
| labels.tsv tiene filas repetidas, ajenas o no válidas (`LABELS_FIX_BY_HAND`) | `labels.tsv` se editó a mano: corríjalo a mano. |
| Las etiquetas no están cerradas (`ML_LABELS_NOT_FINALIZED`) | Ciérrelas en el paso 5. |
| Los exportes para ML ya existen (`ML_EXPORTS_EXIST`) | Alguien los escribió a la vez: pulse otra vez para regenerarlos en una carpeta nueva. |
| La carpeta del reporte tiene contenido (`REPORT_DIR_NOT_EMPTY`) | Use la carpeta propuesta u otra nueva. |
| Archivos omitidos por el lector: `ValueError n` | En datasets git-annex/DataLad suelen ser imágenes sin descargar (punteros): ejecute `git annex get`/`datalad get` antes. |

## 6. Límites conocidos

- La configuración se lee de la raíz del proyecto; la CLI, de la carpeta actual (sección 2).
- La vista previa del paso 3 vuelve a leer todas las cabeceras: con árboles DICOM grandes (decenas de miles de
  archivos) tarda minutos.
- Si un DICOM guarda varias series en una sola carpeta, su sufijo no se puede fijar desde la tabla (tampoco con
  `--mapping`, que trabaja por carpetas).
- Una ruta de la tabla que empieza por `=` (una carpeta llamada así) se guarda tal cual en el TSV, igual que en la
  CLI; al abrir el TSV en una hoja de cálculo puede interpretarse como fórmula.
- Tras una ejecución correcta, si cambia un paso anterior debe elegir **otra** carpeta de salida (la anterior ya
  tiene contenido).
- Los exportes para ML del dataset no se reescriben: si reabre y cambia las etiquetas después de escribirlos, quedan desactualizados; regenere un juego nuevo en el paso 6 (`ml_exports_N`) o bórrelos a mano.
- Borrar `labels.json` a mano hace que el paso 5 diga que no hay etiquetas, y los exportes para ML fallarán.
- «Abrir la carpeta de salida» en Linux necesita `xdg-open`.
- Una `MRI_ANON_KEY` de menos de 32 caracteres se reemplaza por una clave de sesión (la CLI daría error).
- No hay cancelación de tareas ni visor de imágenes; el pipeline solo se elige como archivo (no paso a paso).
