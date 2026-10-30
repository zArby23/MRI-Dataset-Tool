# Manual de usuario: interfaz gráfica (`mri-dataset-gui`)

La interfaz gráfica es un asistente de seis pasos que convierte una carpeta de estudios (BIDS, DICOM o NIfTI
sueltos) en un dataset BIDS anonimizado, con etiquetas, archivos para entrenar modelos (exportes para ML) y un
reporte. Hace lo mismo que `mri-dataset dataset build` y los comandos `labels` y `dataset` de la CLI
(`docs/user_manual/cli.md`), con las mismas validaciones y los mismos archivos de salida. La ventana muestra solo
conteos, códigos y tipos de error: **nunca** identificadores de pacientes, UIDs ni valores de cabecera. Las únicas
rutas que aparecen son las que usted elige y, en la tabla de mapeo (paso 3), las rutas relativas a la carpeta de
entrada.

> Estado: en desarrollo. Las pruebas automáticas usan datos sintéticos. **Pendiente de verificación manual:**
> el recorrido completo con datos reales, la escala de pantalla real de Windows (125 y 150 %) y la ventana en Linux.

## 1. Instalación y lanzamiento

### Ejecutable portable (solo Windows)

En Windows la GUI también se distribuye como un archivo `MRI-Dataset-Tool.zip` (unos 58 MB; unos 135 MB una vez
descomprimido) que no necesita Python ni instalación.

1. **Descomprima** el `.zip` completo (clic derecho → «Extraer todo…») en una **ruta corta**, por ejemplo
   `C:\MRI-Dataset-Tool` o el Escritorio. Windows no abre un programa cuya ruta pasa de 260 caracteres, y la
   carpeta `_internal` contiene archivos con nombres largos: en una carpeta muy profunda el programa no arranca o
   muestra «Failed to load Python DLL». No lo ejecute desde dentro del `.zip` sin descomprimir.
2. **Ejecute** `MRI-Dataset-Tool\MRI-Dataset-Tool.exe` (doble clic). Puede crear un acceso directo al `.exe`; no lo
   mueva fuera de su carpeta: necesita `_internal` a su lado.
3. **Aviso de SmartScreen o del antivirus.** El ejecutable no está firmado, así que la primera vez Windows puede
   mostrar «Windows protegió su PC». Si obtuvo el `.zip` de una fuente de confianza, pulse «Más información» →
   «Ejecutar de todas formas». Un antivirus puede analizarlo o ponerlo en cuarentena la primera vez; en ese caso,
   restáurelo o añada una excepción para la carpeta.

Requisitos: Windows 10 u 11 de 64 bits. La memoria y el disco que hacen falta dependen de los datos (sección 2).

- No modifique ni borre `_internal\config`: ahí están `default.yaml` y el preajuste del paso 2. Sin ellos, el paso 1
  dice «No se encuentra el archivo de configuración» y, en ese caso, el programa usaría en silencio una carpeta
  `config` de la carpeta actual (por ejemplo, una junto al `.exe`).
- El ejecutable solo escribe en las carpetas que usted elige (salida, tabla de mapeo, reporte): nada en la carpeta
  del programa, en la carpeta temporal de Windows ni en la carpeta actual. No guarda preferencias.
- Para actualizarlo, borre la carpeta anterior y descomprima la nueva; sus datasets no están ahí.

En Linux no hay ejecutable: use la instalación desde el código fuente (abajo).

### Desde el código fuente (Windows y Linux)

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

### La ventana

- **Bienvenida**: al abrir aparece una tarjeta con el nombre, la versión, una barra de carga y un resumen de
  privacidad, mientras se cargan los componentes (unos segundos; la primera vez tras encender el equipo, algo
  más). Desaparece sola en cuanto todo está listo.
- **Cabecera**: el nombre y los pasos como «píldoras». El paso actual está relleno; los pasos ya hechos llevan ✓.
  Debajo, el título «Paso n de N: nombre».
- **Pie**: el indicador de actividad (una barra que se mueve y el texto de lo que se está haciendo, con los
  archivos omitidos y los estudios fallidos), el **idioma** (español por defecto, o inglés), el **tema** (claro u
  oscuro) y el botón **Privacidad y memoria**. El idioma y el tema se pueden cambiar en cualquier momento, también
  durante una tarea, y no se recuerdan al reabrir.
- **Tamaño**: la ventana tiene un tamaño fijo, centrada en la pantalla; no se puede redimensionar ni maximizar.
  Con la escala de Windows al 125 o 150 % crece en proporción y, si no cabe en la pantalla, se ajusta al espacio
  libre: las tablas y el registro se acortan, y los mensajes, el resumen final y los botones de navegación siempre se
  ven.
- **Mensajes**: los resultados llevan un icono, un prefijo y un color: «Error:» (rojo), «Aviso:» (ámbar) y «Listo:»
  (verde). El prefijo permite leerlos sin distinguir colores.

### Teclado

| Tecla | Qué hace |
|---|---|
| Alt+→ o Ctrl+Enter | Siguiente paso (si está habilitado) |
| Alt+← | Paso anterior |
| Tab / Mayús+Tab | Recorre los controles del paso de arriba abajo y de izquierda a derecha |
| Espacio o Enter | Pulsa el botón con el foco, elige la tarjeta de formato con el foco |
| ← → ↑ ↓ | Cambian la tarjeta de formato elegida (paso 1) |
| Enter o F2 | En las tablas de los pasos 3 y 5: edita la fila seleccionada |
| Esc | Cancela la edición de una celda, cierra un diálogo o una ayuda emergente |

Al entrar en un paso, el teclado empieza en su primer control. Las ayudas emergentes (por ejemplo, la de ⓘ en el
paso 6) aparecen al pasar el puntero **o** al llegar con Tab. En el cuadro de clases del paso 2, Ctrl+Enter no hace
nada: Enter escribe una línea nueva.

## 2. Antes de empezar

### Clave de anonimización de la sesión

La GUI no pide la clave. Al abrirse:

- si la variable de entorno `MRI_ANON_KEY` existe y tiene al menos 32 caracteres, la usa y el paso 1 muestra
  «definida por usted (se mantiene entre sesiones)»;
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

Etiquetar, cerrar, crear los archivos para entrenamiento y generar el reporte **no** necesitan la clave: se pueden
hacer sobre un dataset ya construido en cualquier sesión. Si necesita seudónimos estables entre sesiones, defina
`MRI_ANON_KEY` (32 caracteres o más) antes de abrir la GUI, como con la CLI.

### Privacidad y uso de memoria

El botón **Privacidad y memoria** del pie (y «Más información» en la bienvenida y en el paso 2) abre un diálogo con
dos secciones: el aviso de privacidad (los datos se procesan solo en este equipo; los resultados se anonimizan con
seudónimos y una lista blanca de metadatos; la anonimización no borra texto incrustado en las imágenes ni hace
*defacing*) y el uso de memoria, en versión corta. El texto completo es este:

> **Uso de memoria.** Antes de remuestrear (resample) o normalizar (normalize), la herramienta estima la memoria
> que necesita el volumen de salida y la compara con la RAM disponible en ese momento. Si no alcanza, el estudio se
> marca como fallido y el lote continúa con los demás. Puede forzar la ejecución con la casilla «Permitir continuar
> aunque la memoria disponible no alcance» del paso 2, que equivale al parámetro
> `allow_insufficient_memory: true` de los pasos resample y normalize del archivo de configuración; ese
> consentimiento queda registrado en el manifiesto de la corrida. Hágalo bajo su responsabilidad: si la memoria no
> alcanza, el equipo puede volverse muy lento por el uso de disco como memoria, otros programas pueden cerrarse, y
> el proceso puede terminar abruptamente sin guardar resultados (en Linux, el sistema puede finalizarlo). La
> comprobación es una estimación en un instante y no cubre la memoria de otros pasos ni de otros programas que se
> abran durante la ejecución. Volúmenes 4D grandes, como las difusiones, pueden necesitar varios GB. Además,
> resample rechaza cualquier salida de más de `max_output_voxels` vóxeles (por defecto 2**32, eje temporal
> incluido), aunque haya memoria; ese límite solo se cambia en el archivo de configuración.

### Configuración

La GUI lee `config/default.yaml` y el preajuste `config/stage3_bids.yaml` de la **raíz del proyecto** (la carpeta
que contiene `src/`), desde donde sea que se abra; el ejecutable portable, de su carpeta `_internal\config`. Solo si
allí no existen los busca en la carpeta actual. La CLI,
en cambio, los busca en la carpeta actual. Un archivo de configuración propio (paso 2) puede estar en cualquier
lugar.

## 3. Los seis pasos

«Siguiente» se habilita cuando el paso actual se validó; cambiar algo en un paso invalida ese paso y los
siguientes. Con una entrada BIDS no hay paso de mapeo (cinco pasos).

### Paso 1: Entrada

- **Carpeta de entrada** y su **formato**, con tres tarjetas: BIDS (carpetas `sub-`/`ses-` con NIfTI), DICOM
  (carpetas con series DICOM) o NIfTI (archivos `.nii`/`.nii.gz` sin nombres BIDS). La elegida tiene borde morado y
  ✓.
- **Carpeta de salida**: debe estar fuera de la entrada y ser **nueva o estar vacía** (sin ningún archivo ni
  carpeta, ocultos incluidos). El selector de carpetas a veces la crea vacía: eso está bien.
  - Si la carpeta elegida **tiene contenido**, no se usa ni se sobrescribe: aparece el campo **«Nombre de la
    carpeta nueva»** y la salida pasa a ser `<carpeta elegida>/<nombre>`. El nombre debe ser simple (sin `/ \ :
    * ? " < > |`, sin `..`, sin punto ni espacio al final, de 255 bytes como máximo, y no un nombre reservado de
    Windows como `CON`) y no existir todavía.
  - Las carpetas de la ruta de salida que todavía no existen siguen las mismas reglas, y la unidad debe existir.
- **Rutas escritas a mano**: el selector siempre da rutas absolutas. Una ruta relativa escrita a mano (entrada,
  salida o carpeta del reporte del paso 6) se resuelve contra la **carpeta actual del proceso**, que en un acceso
  directo o en un ejecutable puede ser cualquiera: use rutas absolutas o el botón del selector.
- Límites aceptados: una ruta `\\?\…` escrita a mano se rechaza; una ruta total de más de 260 caracteres en un
  Windows sin rutas largas habilitadas pasa este paso y falla al ejecutar, igual que en la CLI.
- **Validar** comprueba todo (con las mismas reglas que la CLI) sin crear nada y luego estima el espacio en disco:
  si la salida estimada (el tamaño de la entrada) se acerca al espacio libre del disco de salida, muestra un aviso
  con las cifras. Es solo un aviso: la ejecución no se bloquea.

### Paso 2: Configuración

- **Archivo de configuración**: por defecto el preajuste `stage3_bids.yaml` (validate → anonymize → reorient →
  resample → normalize); puede elegir otro. Debe incluir el paso `anonymize`.
- **Permitir continuar aunque la memoria disponible no alcance (bajo mi responsabilidad)**: el consentimiento
  descrito en «Privacidad y uso de memoria» (sección 2). **Más información** abre ese diálogo en la sección de
  memoria.
- **Clases para etiquetar**, una por línea: `NOMBRE` o `NOMBRE=descripción`. El nombre puede llevar letras, números, espacios y signos, pero no puede
  empezar ni terminar con espacio, ni empezar con `=`, `+`, `-` o `@` (para que una hoja de cálculo no lo tome por una
  fórmula), ni llevar tabuladores, saltos de línea o caracteres de control. Vacío = dataset sin
  etiquetas.
- Las proporciones y la semilla no se piden aquí: la ejecución usa los valores estándar (70/15/15, semilla 0).
  Crea los archivos para entrenamiento en el dataset **solo si las etiquetas quedan cerradas en la ejecución**
  (completas por la tabla de mapeo) **o si no hay clases**; si quedan incompletas, se crean en el paso 6, después
  de cerrarlas en el paso 5.
- **Validar** muestra los pasos del pipeline en orden, por ejemplo «validate -> anonymize -> reorient -> resample ->
  normalize».

### Paso 3: Mapeo de series (solo DICOM y NIfTI)

**Vista previa** lee solo las cabeceras (DICOM) o los nombres (NIfTI) y muestra una fila por serie: carpeta o
archivo (relativo a la entrada), sufijo BIDS, la decisión (*detectado*, *por tabla*, u *omitida* con su motivo),
participante, sesión y etiqueta. Los participantes y sesiones automáticos son seudónimos. Las reglas de sufijo son
las de `docs/dataset/ingest.md`.

- **Un clic** en una celda de sufijo, participante, sesión o etiqueta abre su editor (una lista ya desplegada para
  sufijo y etiqueta). Esas columnas llevan ▾ en el encabezado y el puntero se vuelve una mano encima. Vacía =
  automático. El sufijo se aplica a la serie; participante, sesión y etiqueta a **todo el estudio**. Con el
  teclado: seleccione la fila y pulse Enter o F2. Un texto escrito (participante o sesión) se guarda al pulsar
  Enter, al hacer clic fuera, con Tab o al cambiar de paso; Esc lo cancela. Si cambia a otro programa (Alt+Tab)
  la celda sigue abierta con lo escrito, sin guardarse, y al volver puede seguir escribiendo.
- Las rutas que no caben en su columna terminan en «…»: al pasar el puntero se ve la ruta completa. La tabla tiene
  barra horizontal y las columnas se pueden ensanchar.
- **Asignar etiqueta a la selección**: seleccione varias filas (Ctrl o Mayús), elija la clase y pulse el botón.
- **Cargar tabla… / Guardar tabla…**: el mismo TSV que `--mapping` de la CLI (`path participant session suffix
  label`). Guardar nunca sobrescribe un archivo existente.
- **Duración**: con árboles DICOM muy grandes (decenas de miles de archivos), la vista previa puede tardar **más
  de 15 minutos**; la barra no indica cuánto falta y la tarea no se puede cancelar. Déjela terminar.
- Después de cualquier cambio pulse **Vista previa** otra vez: sin una vista previa correcta no se puede seguir.
- Si los nombres no indican el sufijo (p. ej. NIfTI con nombres neutros como `scan_01.nii.gz`), la primera vista
  previa termina con «Ninguna serie tiene un sufijo reconocido»: **cargue primero una tabla** con los sufijos y
  luego pulse **Vista previa**.

### Paso 4: Ejecución

**Ejecutar** crea `<salida>/dataset` (BIDS anonimizado) y `<salida>/report` en segundo plano: la ventana sigue
respondiendo, pero **la tarea no se puede cancelar**. Con DICOM y NIfTI vuelve a leer todas las cabeceras antes
de convertir: con árboles DICOM muy grandes puede tardar **más de 15 minutos** (más la conversión).

El registro muestra las etapas con sus cifras (por ejemplo «Estudios guardados: 6. Series: 12. Participantes: 6.
Con error: 0.»), los avisos fijos en ámbar (`UNMAPPED_SERIES`, `NOT_4D_DWI`, `MAPPING_UNUSED`,
`MISSING_PATIENT_ID`, `LABELS_INCOMPLETE`) y, al terminar, «Terminado.» y «Sin errores.»; si hubo problemas, en su
lugar aparecen solo las líneas con algo que contar (estudios con error por tipo, archivos que no se pudieron leer,
archivos que el reporte no pudo leer). Un estudio que falla (p. ej. un volumen con NaN) se cuenta y el lote sigue.
Si las etiquetas quedan completas (o no hay clases) se cierran y se crean los archivos para entrenamiento en este
mismo paso.

Si una etapa completa falla se muestra cuál y el tipo de error en rojo: **vacíe o borre la carpeta de salida antes
de repetir**. Tras una ejecución correcta, «Ejecutar» queda deshabilitado (la salida ya tiene contenido).

### Paso 5: Etiquetas

Una fila por participante y sesión del dataset (seudónimos), con su clase y su defecto (*sin etiqueta*, *clase
desconocida*, *repetida en la tabla*, *falta en la tabla*).

- **Un clic** en una celda de «Etiqueta ▾» abre la lista de clases ya desplegada; con el teclado, seleccione la
  fila y pulse Enter o F2; Esc cancela. Elegir el valor vacío quita la etiqueta.
- **En lote**: seleccione filas (Ctrl o Mayús), elija la clase y pulse **Asignar a la selección**; o **Asignar a
  todas las sin etiquetar** (pide confirmación con el número de filas). El filtro **Mostrar** (todas, sin
  etiquetar, con defecto) ayuda a seleccionar. La selección se conserva al editar.
- **Aplicar**: todos los cambios quedan **pendientes** hasta pulsarlo; los guarda todos o ninguno y registra cada
  cambio. Mientras haya cambios pendientes, «Aplicar» se ve en morado y aparece «Cambios sin aplicar: n.».
- **Cargar correcciones (archivo TSV)…**: un archivo con las columnas `participant_id`, `session_id` (con los
  prefijos `sub-`/`ses-`) y `label`, el mismo formato que `--corrections` de la CLI. Se valida entero y sus filas
  pasan a cambios pendientes.
- **Recargar** vuelve a leer la tabla y descarta los cambios pendientes (avisa cuántos).
- **Finalizar etiquetas** exige todas las filas con clase y ningún cambio pendiente; habilita el paso 6.
  **Reabrir** permite volver a editar. Cuando un «Aplicar» deja todas las filas con clase, un diálogo pregunta
  «¿Finalizar las etiquetas ahora?»: **Finalizar** hace lo mismo que el botón y **Más tarde** no hace nada (no se
  vuelve a preguntar hasta que falte alguna clase y se complete otra vez).
- **Si sale del paso con cambios sin aplicar** (Atrás, Siguiente o los atajos), un diálogo pregunta: **Aplicar y
  continuar** (aplica y cambia de paso solo si se aplicaron bien), **Descartar** o **Cancelar** (Esc).

Con miles de filas cada acción tarda unos segundos (se recorre el dataset); corre en segundo plano.

### Paso 6: Resultados

- **Archivos para entrenar modelos** (`dataset_index.csv`, `datalist.json`, `splits.tsv`, `splits.json`) con las
  proporciones y la semilla de este paso (por defecto 70/15/15 y 0). El icono ⓘ explica la diferencia:
  - si el dataset aún no los tiene (las etiquetas se cerraron en el paso 5), **Crear los archivos para
    entrenamiento** los crea en el dataset, como `mri-dataset dataset export-ml`;
  - si ya los tiene, **Crear otro juego en una carpeta nueva** crea otro juego en `<salida>/ml_exports_2`,
    `ml_exports_3`…, con las rutas de las imágenes relativas a esa carpeta (`../dataset/sub-…`). Nada se
    sobrescribe ni se borra. Detalle en `docs/dataset/export.md`.
  - **La GUI exige etiquetas cerradas** (o un dataset sin etiquetas); la CLI permite crearlos con etiquetas
    abiertas (`--allow-unfinalized`), la GUI no.
- **Generar reporte** (JSON, Markdown, XML y Excel) en una carpeta **nueva o vacía** fuera del dataset. Como el paso
  4 ya escribió `<salida>/report`, se propone `report_2`, luego `report_3`…
- **Resumen final**: una tarjeta con «Listo:» y las cifras del dataset (estudios, series, participantes y archivos
  no leídos), con los botones **Abrir la carpeta de salida** (abre en el explorador la carpeta de salida, que
  contiene el dataset y los reportes; si no se puede abrir, se muestra solo el tipo de error) y **Cerrar**, que
  cierra la herramienta tras pedir confirmación.

## 4. Cerrar la ventana

| Situación | Qué pasa |
|---|---|
| Hay una tarea en curso | Se pide confirmación: **la tarea se corta y la salida queda incompleta; vacíe o borre la carpeta de salida antes de repetir.** |
| Paso 5 con cambios de etiquetas sin aplicar | Un diálogo pregunta: **Aplicar y cerrar** (cierra solo si se aplicaron bien), **Descartar** o **Cancelar**. |
| Botón «Cerrar» del paso 6 | Pregunta «¿Cerrar la herramienta?». |
| La X de la ventana en cualquier otro caso | Se cierra sin preguntar. |

## 5. Escala de pantalla

En Windows la GUI se declara compatible con la escala de pantalla: a 125 o 150 % el texto se ve nítido y todo
crece en proporción. Si la pantalla es pequeña (por ejemplo 1920×1080 al 150 %), la ventana se ajusta al espacio
libre sin cortar los botones de navegación ni el pie; las tablas y el registro son lo que se acorta, nunca la línea
de mensajes ni la tarjeta de resumen. Con pantallas muy pequeñas o una escala mayor del 150 % puede que no quepa todo.

**Límite conocido: texto de derecha a izquierda.** Tk 8.6 no aplica el algoritmo bidireccional: un texto en árabe o
hebreo que aparezca en una tabla (por ejemplo un nombre de clase) se dibuja en orden de lectura de izquierda a derecha.
Los datos no se alteran; solo cambia cómo se ve.

## 6. Resolución de problemas

| Síntoma | Qué hacer |
|---|---|
| El ejecutable no arranca, muestra «Failed to load Python DLL» o Windows dice que el nombre de archivo es demasiado largo | La carpeta está demasiado profunda: mueva la carpeta `MRI-Dataset-Tool` a una ruta corta (`C:\MRI-Dataset-Tool`) (sección 1). |
| «Windows protegió su PC» al abrir el ejecutable, o el antivirus lo bloquea | El ejecutable no está firmado: «Más información» → «Ejecutar de todas formas», o restáurelo desde el antivirus (sección 1). |
| El ejecutable dice «No se encuentra el archivo de configuración» en el paso 1 | Falta `_internal\config`: vuelva a descomprimir el `.zip` completo. |
| La bienvenida muestra «No se pudo iniciar (TclError)» o la ventana no abre | Reinstale Python con la opción Tcl/Tk (Windows) o instale `python3-tk` (Linux); en Linux necesita una sesión gráfica. |
| En Linux, la letra no es Verdana | Es lo esperado si Verdana no está instalada: la GUI usa DejaVu Sans y, si tampoco está, la del sistema. Instalar el paquete de DejaVu (p. ej. `fonts-dejavu`) da el aspecto previsto. |
| La ventana se ve borrosa en Windows | Abra la GUI con `MRI-Dataset-Tool.exe`, `mri-dataset-gui` o `python -m mri_dataset_tool.presentation.gui`: las tres declaran la escala de pantalla. Si aun así se ve borrosa, revise en las propiedades del programa (pestaña Compatibilidad) que no esté activada una opción que reemplace el escalado de DPI. |
| «Abrir la carpeta de salida» no hace nada en Linux | Necesita `xdg-open` (paquete `xdg-utils`). |
| Los diálogos de elegir carpetas y archivos salen claros con el tema oscuro | Son los del sistema: no siguen el tema. |

### Mensajes frecuentes

| Mensaje (código) | Qué hacer |
|---|---|
| La carpeta de salida ya tiene archivos (`OUTPUT_NOT_EMPTY`) | Escriba el nombre de una carpeta nueva o elija otra carpeta. |
| No se puede crear la carpeta de salida (`INVALID_OUTPUT_PATH`) | Una carpeta nueva de la ruta tiene un nombre no válido (`:`, demasiado largo, `CON`…) o la unidad no existe. |
| No se pudo escribir el archivo (`MAPPING_FILE_UNWRITABLE`) | Al guardar la tabla del paso 3: elija un archivo en una carpeta que exista y se pueda escribir. |
| La salida ya existe (`OUTPUT_EXISTS`) | La carpeta se llenó después del paso 1: elija otra. |
| La carpeta de salida debe estar fuera de la entrada (`OUTPUT_INSIDE_INPUT`) | Elija una salida fuera de la entrada. |
| No se encuentra el archivo de configuración / Configuración no válida (`CONFIG_NOT_FOUND`, `INVALID_CONFIG`) | Revise el archivo o use el preajuste. |
| El pipeline debe incluir el paso anonymize (`PIPELINE_WITHOUT_ANONYMIZE`) | Añada `anonymize` a la configuración. |
| Ninguna serie tiene un sufijo reconocido (`NO_MAPPED_SERIES`) | Cargue una tabla con los sufijos en el paso 3. |
| La tabla da a un estudio más de un participante o sesión (`MAPPING_STUDY_SPLIT`) | Use una fila con la carpeta del estudio. |
| Varias series comparten esta carpeta (`SHARED_SERIES_FOLDER`) | El sufijo no se puede fijar desde la tabla de la GUI; vea los límites. |
| Falló la etapa «…» (`STAGE_FAILED`) | Vacíe o borre la salida y repita; el tipo de error orienta la causa. |
| No se pueden cerrar: hay filas sin clase o con defectos (`LABELS_INCOMPLETE`) | Use el filtro «con defecto» y etiquete. |
| El archivo de etiquetas se editó fuera de la herramienta (`LABELS_FIX_BY_HAND`) | `labels.tsv` tiene filas repetidas o no válidas: corríjalo a mano. |
| Las etiquetas no están cerradas (`ML_LABELS_NOT_FINALIZED`) | Ciérrelas en el paso 5. |
| Los archivos para entrenamiento ya existen (`ML_EXPORTS_EXIST`) | Pulse otra vez para crear otro juego en una carpeta nueva. |
| La carpeta del reporte tiene contenido (`REPORT_DIR_NOT_EMPTY`) | Use la carpeta propuesta u otra nueva. |
| Archivos que no se pudieron leer: `ValueError n` | En datasets git-annex/DataLad suelen ser imágenes sin descargar (punteros): ejecute `git annex get`/`datalad get` antes. |

## 7. Límites conocidos

- La configuración se lee de la raíz del proyecto (o de `_internal\config` en el ejecutable); la CLI, de la carpeta
  actual (sección 2).
- El ejecutable portable es solo para Windows, no está firmado (SmartScreen), es una carpeta (no un único `.exe`)
  y no se actualiza solo. No incluye la CLI (`mri-dataset`), que se usa desde el código fuente.
- La vista previa del paso 3 y la ejecución del paso 4 leen todas las cabeceras cada una: con árboles DICOM muy
  grandes (decenas de miles de archivos) cada una puede tardar **más de 15 minutos**, sin indicar cuánto falta y
  sin cancelación.
- Con miles de series, ensanchar a mano la columna de rutas del paso 3 tarda unos segundos.
- Las rutas relativas escritas a mano se resuelven contra la carpeta actual del proceso (paso 1).
- Si un DICOM guarda varias series en una sola carpeta, su sufijo no se puede fijar desde la tabla (tampoco con
  `--mapping`, que trabaja por carpetas).
- Una ruta de la tabla que empieza por `=` se guarda tal cual en el TSV; al abrirlo en una hoja de cálculo puede
  interpretarse como fórmula.
- Tras una ejecución correcta, si cambia un paso anterior debe elegir **otra** carpeta de salida.
- Los archivos para entrenamiento del dataset no se reescriben: si reabre y cambia las etiquetas después de
  crearlos, quedan desactualizados; cree otro juego en el paso 6 (`ml_exports_N`) o bórrelos a mano.
- Borrar `labels.json` a mano hace que el paso 5 diga que no hay etiquetas, y los archivos para entrenamiento
  fallarán.
- La barra de título y los selectores de archivos son los del sistema y no siguen el tema oscuro.
- Una `MRI_ANON_KEY` de menos de 32 caracteres se reemplaza por una clave de sesión (la CLI daría error).
- No hay cancelación de tareas ni visor de imágenes; el pipeline solo se elige como archivo (no paso a paso).
