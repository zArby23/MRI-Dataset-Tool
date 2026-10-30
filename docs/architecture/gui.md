# Arquitectura de la GUI (`presentation/gui/`)

La GUI es un asistente Tkinter (stdlib, sin dependencias nuevas) sobre los mismos servicios de `application/` que
la CLI. Es una capa de presentación: dibuja, valida con las funciones de los servicios y traduce resultados y
errores a textos. Manual de uso: `docs/user_manual/gui.md`.

## Estructura

```text
src/mri_dataset_tool/presentation/gui/
├── __init__.py
├── __main__.py        # python -m mri_dataset_tool.presentation.gui
├── app.py             # App(tk.Tk): marco, navegación, bienvenida, sondeo de la cola, cierre, DPI (main)
├── controller.py      # Controller, WizardState y Activity: SIN Tk; estado, validación, tareas, textos
├── worker.py          # Worker (un hilo daemon, una tarea a la vez), Reporter y eventos
├── messages.py        # catálogo es/en por código, gravedad de cada mensaje y tablas mensaje fijo → código
├── theme.py           # el único módulo con literales visuales: paletas, fuentes, tamaños, apply_theme
├── widgets.py         # widgets dibujados con el tema (botones, cabecera, tarjetas, iconos, ayudas…)
├── dialogs.py         # diálogos modales con el tema (ask_ok_cancel, ask_choice, show_sections)
└── views/
    ├── __init__.py    # StepView (base): invalidate_on_edit, status_line, focus_first
    ├── input_step.py  # paso 1
    ├── config_step.py # paso 2
    ├── mapping_step.py# paso 3 (solo DICOM/NIfTI)
    ├── run_step.py    # paso 4
    ├── labels_step.py # paso 5
    └── export_step.py # paso 6 «Resultados» (y open_folder)
```

Puntos de entrada: `mri-dataset-gui` (`[project.gui-scripts]` → `presentation.gui.app:main`),
`python -m mri_dataset_tool.presentation.gui` y, en Windows, `MRI-Dataset-Tool.exe` (ver «Ejecutable portable»). `main()` declara el proceso consciente del DPI en Windows y abre
la App con la pantalla de bienvenida (ver «Arranque»).

## Capas

- **Vistas**: solo widgets. Leen el estado del controlador para dibujar y llaman a sus métodos; no importan
  servicios. `refresh_texts()` redibuja en el idioma actual; `on_event(event)` recibe los eventos del trabajador
  cuando la vista está activa.
- **Controlador** (`controller.py`): sin Tk, se prueba sin pantalla. Guarda `WizardState` (solo lo que el usuario
  eligió y lo que devolvieron los servicios), valida cada paso con las mismas funciones que la CLI
  (`check_input_paths`/`check_build_args`, `load_build_pipeline`, `check_split_params`, `load_mapping`,
  `plan_ingest`…), construye las tareas largas y convierte excepciones en `Check(code, values)`. Navegación:
  `complete(step)` desbloquea el siguiente paso, `reopen(step)` invalida ese y los siguientes (y, antes de la
  ejecución, el dataset construido). También decide, sin Tk, el estado visual: `step_states()` (hecho, actual o
  pendiente), `activity` (indicador de actividad), `pending_label_edits()`, `leave_question()` y
  `close_question()`.
- **Servicios** (`application/services/`): toda la lógica de negocio. Fachadas de la GUI:
  - `session_key.py`: `ensure_session_key()` (clave `sha256(secrets.token_bytes(32))` solo en `os.environ` si
    falta o es corta), `key_is_set()`.
  - `inputs.py`: lo que la presentación necesita de la infraestructura (la CLI también lo importa de aquí,
    salvo `inspect.py`, deuda conocida). `project_config_dir()` es el único punto que ubica `config/` (`sys._MEIPASS/config` en el
    ejecutable portable; si no, la raíz del proyecto; respaldo, el cwd), `check_input_paths()`, `with_memory_consent()`, `is_valid_folder_name()`.
  - `ingest_preview.py`: `preview_ingest` (las `decisions` de `plan_ingest`), `apply_edit` (edición de la tabla →
    filas de `--mapping`), `write_mapping` (TSV nuevo, releído con `load_mapping`).
  - `labels_table.py`: `read_label_sheet`/`read_label_rows` (filas con defecto, una sola revisión),
    `apply_label_edits` (TSV temporal de seudónimos + `apply_label_corrections`), `read_label_corrections`,
    `label_classes`, `labels_finalized`.
  - `dataset_outputs.py`: `ml_exports_exist`, `write_report` (carpeta nueva o vacía) y `report_warnings`.
  - `write_ml_exports(..., output_dir=None)` / `write_ml_files(..., output_dir=None)`:
    un juego regenerado en otra carpeta con rutas `../dataset/…`; sin `output_dir`, idéntico a antes.
  - En los servicios de la CLI: `dataset_build.is_new_or_empty_dir` (la salida puede ser una carpeta
    vacía, también en la CLI) e `IngestPlan.decisions` (`SeriesDecision` por serie).

## Tema (`theme.py`)

Es el único módulo con colores, fuentes y tamaños. Una prueba estática recorre el resto de `presentation/gui/`
y falla si encuentra un color `#rrggbb`, `font=(…)`, un relleno numérico, `wraplength`/`length` numéricos,
`px(<número>)` o `start(<número>)`. Los anchos en **caracteres** (campos, combos, el cuadro de clases) sí se
permiten: crecen con la fuente.

- **Paletas como datos**: `PALETTES["light"|"dark"]` con los mismos tokens (fondo, superficie, filas alternas,
  selección, hover, borde, texto, apagado, deshabilitado, acento y sus variantes, foco, borde de campo, error, aviso,
  ok, y los de la cabecera `header_top`, `header_text`, `header_muted`, `header_done`, `header_hover`). Morado de
  base; error, aviso y ok conservan su matiz (rojo, ámbar, verde). Claro por defecto; el tema se cambia en caliente
  desde el pie y no se guarda.
- **Contraste probado sin pantalla**: `contrast_ratio` (WCAG 2.x) sobre todos los pares de texto que se dibujan
  (`TEXT_PAIRS`, ≥ 4,5:1, incluido el texto de la cabecera contra los **dos** extremos de su degradado) y sobre los
  bordes y el anillo de foco (`BORDER_PAIRS`, ≥ 3:1). El degradado de la cabecera debe verse (≥ 1,5:1 entre
  extremos) y el hover debe distinguirse de las filas alternas.
- **Tamaños**: `px()` convierte píxeles lógicos (96 dpi) en píxeles de pantalla con la escala de Tk; `space()`
  (escala 4/8/12/16/24), `size()` sobre `SIZES` (barras, ajustes de texto, ayudas, anillo de foco…), `wrap()`,
  `WINDOW` (960×680), `TASKBAR`, `BAR_STEP_MS`, `DIALOG_TEXT` y `MAPPING_COLUMNS`. Marcas de texto: `DONE_MARK`
  (✓ en un paso hecho) y `EDIT_MARK` (▾ en el encabezado de una columna editable).
- **Fuente**: la primera instalada de `FONT_FAMILIES` (Verdana, luego DejaVu Sans; si no hay ninguna, la del
  sistema), elegida con `font.families()` al aplicar el tema y puesta en las fuentes con nombre de Tk
  (`TkDefaultFont`, `TkTextFont`, `TkHeadingFont`…). No se incluye ningún archivo de fuente: Verdana no es
  redistribuible. Tres niveles, todos de la misma familia: nombre de la herramienta 13 pt negrita
  (`MRIAppName`), título del paso 12 pt (`MRIStepTitle`), texto 9 pt (negrita solo en la píldora del paso actual,
  `MRIStepCurrent`); `MRILink` subraya los enlaces. Los objetos `Font` se guardan en la ventana: Tk borra una
  fuente con nombre cuando su objeto Python desaparece.
- **`apply_theme(root, name)`**: base `clam` (existe en Windows y Linux y acepta todos los colores), estilos con
  nombre (`Accent.TButton`, `Error.TLabel`, `Card.TFrame`, `Link.TLabel`, `Footer.Horizontal.TProgressbar`…),
  borde de los campos apagado en reposo y vivo con el foco, encabezados de tabla neutros con línea inferior y
  altura de fila 1,4 × la línea. Los widgets que no son `ttk` se colorean uno a uno (`Listbox` sin línea activa
  subrayada; `Text` con el borde y la fuente de los campos, porque Tk le da `TkFixedFont`); las tablas reciben las
  etiquetas `hover` y `odd` (filas alternas); los widgets dibujados se redibujan con `retheme()`. `recolor(widget)`
  colorea lo que se crea después (diálogos).

## Marco de la ventana (`app.py`)

```text
┌───────────────────────────────────────────────────────────────────────┐
│ MRI Dataset Tool                                      (degradado)     │ HeaderCanvas
│ 1 Entrada ✓  2 Configuración ✓ (3 Mapeo de series) 4 Ejecución …      │ píldoras
│ Paso 3 de 6: Mapeo de series                                          │ título del paso
│                                                                       │
│   [vista del paso]                                                    │ cuerpo
│                                                                       │
├───────────────────────────────────────────────────────────────────────┤
│ ⊗ Error: … (error inesperado)                       [‹ Atrás] [Siguiente ›] │ navegación
├───────────────────────────────────────────────────────────────────────┤
│ ▓▓░░ Creando el dataset · Omitidos: 2 · Fallidos: 0 · Ilegibles: 0    │ actividad
│                          Idioma [Español▾]  Tema [Claro▾]  [Privacidad y memoria] │ pie
└───────────────────────────────────────────────────────────────────────┘
```

- **Ventana fija** de 960×680 píxeles lógicos (decisión de diseño), centrada, sin redimensionar ni maximizar.
  Con la escala de pantalla crece (1200×850 a 125 %, 1440×1020 a 150 %); si no cabe en la pantalla menos la barra
  de tareas, se limita a ella y ceden las tablas y el registro: la navegación, el pie, la línea de mensajes y la tarjeta de resumen siempre quedan
  visibles (en los pasos 3 y 5 la línea de mensajes se empaqueta antes que la tabla; en el 6 los grupos de exportes
  ocupan una fila cada uno y el registro cede) Con
  un tamaño fijo, los textos de ayuda se ajustan a un ancho fijo y no hay que recolocar nada al redimensionar.
- **Cabecera** (`HeaderCanvas`): nombre y píldoras de los pasos sobre un degradado de `header_top` a `bg`. El
  paso actual es una píldora rellena; los hechos llevan ✓, así que el estado no se indica solo con color. Si las
  píldoras no caben, pasan a una segunda fila. El título de la ventana es «MRI Dataset Tool - Paso n de N: Nombre».
- **Navegación**: Atrás y Siguiente (iconos ‹ ›, ayuda emergente con los atajos), y la línea de estado `_status`
  para un error inesperado en un callback (solo su tipo).
- **Atajos**: Alt+→ y Ctrl+Enter = Siguiente, Alt+← = Atrás, solo con el botón habilitado. En el cuadro de clases
  del paso 2, Ctrl+Enter no hace nada (ni salto de línea ni cambio de paso).
- **Foco inicial**: al mostrar un paso nuevo, el foco va a su primer control (`StepView.focus_first`, tras
  terminar de colocar el paso). El orden de Tab de cada paso se lee de arriba abajo y de izquierda a derecha.
- **Salir del paso 5 con cambios sin aplicar** (Atrás, Siguiente o atajos): `dialogs.ask_choice` con «Aplicar y
  continuar» (aplica con la tarea de siempre y navega solo si terminó bien), «Descartar» o «Cancelar». La pregunta
  está en la navegación de la ventana; `controller.go_next()`/`go_back()` no cambian.
- **Finalizar tras aplicar**: tras un «Aplicar» que deja las etiquetas completas y abiertas,
  `LabelsStep.ask_finalize` muestra `dialogs.ask_ok_cancel` con «Finalizar» (la misma tarea que el botón
  «Finalizar etiquetas») o «Más tarde». `controller.offer_finalize()` decide sin Tk: una vez cada vez que pasan a
  completas (`labels_complete`, `finalize_offered`, que vuelve a `False` al quedar incompletas o cerradas).

## Arranque y bienvenida

`app.py` no importa el controlador ni las vistas al cargarse (una prueba lo comprueba en un subproceso): así la
ventana aparece en seguida. `main()` crea `App(startup=load_services)`: la ventana muestra una tarjeta de
bienvenida sobre el degradado (nombre, subtítulo, versión, barra indeterminada, resumen de privacidad y enlace al
diálogo) mientras un hilo importa los servicios (scipy, nibabel, pydicom: de 2 a 7 s según la caché del sistema) y
llama a `ensure_session_key()`. El hilo no toca Tk ni guarda la ventana: escribe su resultado en una lista que el
hilo principal sondea con `after`; al terminar se crean el controlador y las vistas y la tarjeta desaparece. Sin
temporizadores ni esperas artificiales. Si el arranque falla, la tarjeta muestra solo el tipo del error y un botón
«Cerrar». `App(controller)` (lo que usan las pruebas) construye todo de inmediato, sin bienvenida.

La ventana tiene un único `after` de sondeo (`_schedule`, que reemplaza el anterior); `destroy()` lo cancela y
para las barras animadas: sus temporizadores de Tcl pertenecen al hilo y, si quedaran pendientes, se ejecutarían
sobre una ventana destruida en cuanto otra raíz de Tk procesara eventos.

## Trabajador, cola y eventos

Solo el hilo principal toca widgets. Las tareas largas (espacio en disco, vista previa, ejecución, etiquetas,
exportes, reporte) corren en `Worker`: un hilo **daemon**, una tarea a la vez, sin cancelación. La tarea recibe un
`Reporter` cuyos callbacks encajan con los servicios (`on_status`, `on_skipped`, `on_error`, `on_report_error`) y
publican en una `queue.Queue` solo eventos inmutables: `Status(stage, counts)` (solo enteros), `Skipped(tipo)`,
`StudyFailed(tipo)`, `ReportReadError(tipo)`, `Failed(code, tipo, stage, values)` y `Done(summary)` (solo
enteros). Rutas y mensajes de excepción se descartan en el `Reporter`.

La App sondea la cola cada 100 ms con `Controller.poll()` → `Worker.drain()`. `busy` lo limpia **solo el hilo
principal** al sacar el `Done`/`Failed`, para que el último evento de una tarea vieja nunca se tome por el de una
nueva. Los resultados grandes (filas de la vista previa, tabla de etiquetas, nombres de archivos) no viajan por la
cola: la tarea los deja en el controlador y el método `*_finished` los publica en el hilo principal al llegar el
`Done`. Cada tarea puede pasar su clasificador de excepciones (`start_task(task, classify, activity=…)`).

**Indicador de actividad**: `controller.activity` (`Activity`: tarea, última etapa y contadores de omitidos,
fallidos e ilegibles) se actualiza en `poll()` y se limpia con `Done`/`Failed`; el pie lo muestra en su propia
fila (barra de ~160 px y texto). La barra es siempre **indeterminada**: ningún evento trae un total («estudio i de
N»), así que un porcentaje sería inventado. En reposo la barra queda vacía y el alto no cambia.

`App.report_callback_exception` registra solo el tipo de una excepción en un callback de Tk y la muestra como
`UNEXPECTED(tipo)`: nunca su mensaje ni su traceback. Si `on_event` de una vista lanza, `_poll` lo reporta así y
sigue con los eventos siguientes; el próximo sondeo se programa en un `finally`.

Rutas: el controlador usa `Path(texto)` sin `resolve`, igual que la CLI; una ruta relativa escrita a mano se
resuelve contra la carpeta actual del proceso. En el paso 1, `new_folders_valid` exige que cada carpeta nueva de la
salida tenga un nombre válido y que la unidad exista (`INVALID_OUTPUT_PATH`).

## Widgets (`widgets.py`)

- `RoundedButton` (alias `Button`): botón dibujado con esquinas redondeadas que se comporta como `ttk.Button` para
  el resto del código y las pruebas (`invoke()` pasa por Tk, así que un error llega a
  `report_callback_exception`; `configure`/`cget` de `text`, `state`, `command`; `state([...])`, `instate`).
  Estados normal, hover, pulsado y deshabilitado; `primary` (relleno de acento, cambiable en caliente: «Aplicar»
  con cambios pendientes); anillo de foco; Espacio y Enter lo activan; icono opcional (‹ › ×). Cambiar el alias a
  `ttk.Button` devuelve los botones rectos sin tocar las vistas.
- `HeaderCanvas` (cabecera con píldoras) y `GradientCanvas` (fondo de la bienvenida).
- `ChoiceCards`: tarjetas seleccionables sobre una `StringVar` (formato del paso 1, la misma variable que tenían
  los botones de opción): ✓ y negrita en la elegida, hover, foco, flechas, Espacio y Enter.
- `StatusLine`: un mensaje con icono, prefijo («Error:», «Aviso:», «Listo:») y color según su gravedad.
  `cget("text")` devuelve el mensaje sin prefijo, como la etiqueta que sustituye.
- Iconos vectoriales (`icon_lines`/`draw_icon`): error, aviso, ok, info, ‹, › y ×, dibujados con trazos en un
  Canvas; escalan con la pantalla, siguen el tema y no necesitan archivos. Solo en los estados y en Atrás,
  Siguiente y Cerrar (decisión de diseño).
- `Tooltip` (ayuda emergente: con retardo al pasar el puntero **y** al recibir el foco por teclado; Esc, salir o
  perder el foco la cierran; nunca toma el foco) e `InfoIcon` (ⓘ con su ayuda).
- `Link`: texto subrayado que actúa con clic, Enter o Espacio.
- Tablas: `bind_row_hover`, `stripe` (filas alternas), `elide` (recorta con «…» al ancho), y
  `bind_cell_editing`: un clic en una celda editable abre su editor (tras seleccionar la fila), Enter/F2 abren la
  primera celda editable de la fila enfocada, cursor de mano encima. `column_at` calcula la columna con las cajas
  de las celdas: en este Tk, `Treeview.identify_column` cuenta la columna oculta de una tabla `show="headings"` y
  devuelve la de la izquierda. `open_list` despliega la lista de un combo al abrirlo.
  El editor de celda sigue a su celda al desplazar la tabla o mover columnas (`_follow_editor`); el texto libre del
  paso 3 se guarda cuando el foco pasa a otro control de la ventana, con Tab o al cambiar de paso o cerrar
  (`StepView.finish_edit`, llamado por `App._leave` y `request_close`); si el foco se va a otro programa (Alt+Tab,
  una notificación) el editor sigue abierto (`MappingStep._focus_left`); Esc cancela. Una segunda X con la pregunta de cierre abierta se ignora
  (`_asking_close`). «Asignar etiqueta a la selección» aplica una edición por estudio DICOM, no por serie
  (`_label_edits`: `apply_edit` recorre todas las filas en cada llamada).

## Diálogos (`dialogs.py`)

Modales con el tema, centrados sobre la ventana, con `grab` (tras `wait_visibility`, que Linux exige), foco inicial
en el botón principal, Esc = cancelar y Enter = principal: `ask_ok_cancel(title, text, parent, ok_text,
cancel_text) -> bool` (todas las confirmaciones), `ask_choice(title, text, choices, parent) -> str | None` (tres
botones) y `show_sections` («Privacidad y uso de memoria»: dos secciones con títulos en negrita, desplazable a una
sección). Se llaman **siempre por el atributo del módulo** (`dialogs.ask_ok_cancel(...)`) para que una prueba
pueda reemplazarlos. Los selectores de archivos y carpetas siguen siendo los del sistema.

## Cierre de la ventana

`request_close(confirm=False)` usa `controller.close_question(confirm)`:

| Situación | Qué pasa |
|---|---|
| Una tarea en curso | `ask_ok_cancel`: la tarea se corta y la salida queda incompleta. |
| Paso 5 con cambios de etiquetas sin aplicar | `ask_choice`: «Aplicar y cerrar» (cierra solo si se aplicó bien), «Descartar» o «Cancelar». |
| Botón «Cerrar» del paso 6 | `ask_ok_cancel`: «¿Cerrar la herramienta?». |
| La X sin nada de lo anterior | Se cierra sin preguntar. |

## Mensajes

`messages.CATALOG` tiene los textos en español e inglés por código; una prueba exige las mismas claves y los
mismos campos en los dos idiomas. Los servicios lanzan mensajes fijos en inglés; la GUI nunca los muestra: los
busca en tablas (`FIXED_MESSAGES`, `LABEL_MESSAGES`, `EXPORT_MESSAGES`) y muestra el texto de su código. Lo que no
está en una tabla se muestra con un código genérico y el tipo de la excepción. `severity(code)` da la gravedad
(`OK_CODES`, `INFO_CODES`, `WARNING_CODES`; el resto, error). Pruebas: ningún texto empieza por un prefijo de
gravedad (la línea de estado ya lo pone) y ningún texto visible nombra `MRI_ANON_KEY`, `allow_insufficient_memory`
ni `max_output_voxels` (el manual sí los explica).

## Privacidad (RNF07)

- Estado (`repr`), cola, textos y logs: solo códigos, tipos y conteos. Las filas con rutas relativas (vista
  previa y mapeo) y la tabla de etiquetas (seudónimos) están fuera del `repr` del estado y se muestran solo en sus
  tablas, sus ayudas emergentes y el TSV que el usuario guarda.
- Las rutas mostradas son las que el usuario eligió. La clave de la sesión nunca se muestra, guarda ni registra.
- Barridos de PHI con valores plantados (PatientID, descripciones, ids, rutas) sobre el estado, los textos, la
  cola y los logs DEBUG en las pruebas de cada paso.
- pydicom citaba UIDs no conformes en sus avisos: `quiet_value_validation()` los silencia durante las lecturas
  DICOM (contador con `threading.Lock`, porque el ajuste es de todo el proceso).

## Escala de pantalla (DPI)

`enable_dpi_awareness()` llama a `SetProcessDpiAwareness(1)` (por `ctypes`, stdlib) **solo en `main()` y solo en
Windows**, en un `try`: si falla, todo sigue como antes. Así Tk lee el DPI real, `tk scaling` y `px()` escalan juntos
y el texto se ve nítido a 125 y 150 % (sin la declaración, Windows estira la ventana como un mapa de bits).

## Rendimiento

- Un estudio en memoria a la vez: la ejecución usa `build_dataset` como la CLI.
- La vista previa (`preview_ingest`) y la ejecución (`plan_ingest`) leen cada una todas las cabeceras: con árboles
  DICOM muy grandes cada una puede pasar de 15 minutos, con barra indeterminada y sin cancelación.
- Tabla de etiquetas: se reconstruye solo cuando cambian sus filas, ediciones, filtro o idioma (`label_version`) y
  conserva la selección; cada acción recorre el árbol del dataset (~2 s con 3000 pares) y corre en el trabajador.
- Tabla de mapeo con 5000 series (Windows): llenarla tarda ~2,4 s; el recorte de rutas con «…» se recalcula solo
  con filas nuevas o un ancho de columna nuevo (un `<Configure>` de la ventana: ~0,1 ms); cambiar a mano el ancho de
  la columna de rutas tarda ~1,9 s (se recortan todas).

## Ejecutable portable (Windows)

La GUI se distribuye para Windows como una carpeta `onedir` de PyInstaller comprimida en `MRI-Dataset-Tool.zip`
(~58 MB; ~134 MB y ~1170 archivos descomprimida): `MRI-Dataset-Tool.exe` (sin consola) y `_internal/` con el
intérprete, las bibliotecas, `config/*.yaml` y los `dist-info` de los paquetes. No es `onefile`: ese formato se
descomprime en la carpeta temporal en cada arranque, tarda más y lo bloquean más antivirus. En Linux se ejecuta
desde el código fuente.

**Rutas congeladas.** `inputs.project_config_dir()` es el único punto que localiza `config/`: con
`sys.frozen` y `sys._MEIPASS` (el `_internal/` del bundle) usa `<_MEIPASS>/config`; desde el código fuente, la raíz
del proyecto. Si esa carpeta no tiene `default.yaml`, recurre en silencio a `config/` del directorio de trabajo (el
mismo respaldo que desde el código fuente). Con el bundle intacto, la de `_internal` siempre gana; sin ella, el paso 1
se detiene con `CONFIG_NOT_FOUND` sin crear nada, salvo que haya una `config/` en el directorio de trabajo, que se
usaría. `check_input_paths` comprueba la entrada y la salida pasando `project_config_dir()/"default.yaml"` como
archivo de configuración a `check_build_args` (antes usaba el propio `.py` del módulo, que en el bundle no existe:
los módulos van compilados dentro del archivo PYZ). Ningún otro módulo usa `__file__` ni escribe junto al
ejecutable; la clave de sesión vive solo en memoria.

**Versiones y licencias.** `--copy-metadata` incluye los `dist-info` de `mri-dataset-tool`, `numpy`, `nibabel` y
`pydicom` (las versiones que muestra la bienvenida y que registra `code/run_manifest.json` vía
`importlib.metadata`; sin ellos saldría «unknown») y de `scipy`, `PyYAML`, `psutil` y `openpyxl`, cuyos `dist-info`
llevan el texto de su licencia. El script borra `direct_url.json` de los `dist-info`: una instalación editable anota
ahí la carpeta del repositorio. Los nombres de archivo de los módulos compilados son relativos al paquete
(`mri_dataset_tool\application\services\inputs.py`).

**Compilación** (`packaging/build_exe.py`, solo Windows). PyInstaller es una herramienta de build, no una
dependencia del paquete: se instala a mano en el entorno virtual, sin tocar `pyproject.toml`.

```powershell
python -m pip install pyinstaller==6.22.3   # trae pyinstaller-hooks-contrib, altgraph, pefile, pywin32-ctypes
python packaging/build_exe.py --out D:/build/mri-dataset-tool   # cualquier carpeta fuera del repositorio
```

`--out` es obligatorio y debe estar fuera del repositorio (el script lo rechaza dentro); conviene un disco con
espacio (~1 GB entre todo; en el equipo de desarrollo, `E:`, no `C:`). Allí quedan `build/` (temporales), `spec/` (el `.spec` que genera PyInstaller),
`dist/MRI-Dataset-Tool/` y `MRI-Dataset-Tool.zip`. Tarda 1–2 minutos. El script pasa a PyInstaller la entrada
`presentation/gui/__main__.py`, `--windowed --onedir --name MRI-Dataset-Tool`, `--paths src`, los YAML de `config/`
como datos y las exclusiones de paquetes opcionales que la GUI no usa (matplotlib, PIL, IPython/Jupyter, pytest,
pandas, h5py…). Los argumentos que no reconoce van a PyInstaller tal cual (por ejemplo `--debug=imports` para
diagnosticar un import que falta). **Solo se distribuye el `.zip`**: `build/` y `spec/` llevan rutas absolutas del
equipo donde se compiló y nunca se comparten. `build/`, `dist/` y `*.spec` están en `.gitignore`.

Medidas en el equipo de desarrollo: la ventana aparece en ~0,6–1 s, los servicios están listos a los ~3,5 s y
la memoria ronda los 100 MB al arrancar.

**Límites.** Solo Windows de 64 bits; sin firma de código (SmartScreen y algunos antivirus avisan la primera vez);
sin instalador ni actualización automática; sin ejecutable de la CLI. La ruta del `.exe` y la de los archivos de
`_internal` deben caber en 260 caracteres si Windows no tiene habilitadas las rutas largas: el manual pide
descomprimir en una ruta corta. El bundle incluye algunos módulos que la GUI no usa y que entran por imports
opcionales de las dependencias (p. ej. `requests` por `pydicom.data`); excluirlos ahorraría unos MB a cambio del
riesgo de romper un import perezoso.

## Pruebas

Lo que se puede probar sin pantalla se prueba sin pantalla; las pruebas de Tk se omiten si no hay pantalla.

| Sin pantalla | Con pantalla |
|---|---|
| Controlador con los servicios reales sobre datos sintéticos, equivalencia con la CLI, catálogo y coberturas de mensajes, trabajador | Humo de la ventana, cada paso con sus vistas |
| Paletas y contraste, escala de tamaños, elección de fuente, degradado, prueba estática de literales, `app.py` sin servicios al importarse | Tema en caliente, familia de fuente **real** (`font.actual()`) en todos los textos, bienvenida y fallo del arranque, cierre sin errores de Tcl (en subproceso) |
| `Activity`, `step_states`, `close_question`, `leave_question`, gravedades, textos sin prefijo ni nombres internos, iconos dentro de su caja | Teclado: tarjetas, diálogos (Esc, Enter, Tab), ayudas por foco, atajos, foco inicial y orden de Tab |
| DPI solo en Windows y sin fallar | Un clic para editar, selección conservada, «Aplicar» destacado, diálogo de salida y de cierre, barras sin cortes en es/en, escala simulada 100/125/150 % en 1920×1080 |

Archivos: `tests/unit/test_gui_*.py` (entre ellos `test_gui_theme.py`, `test_gui_activity.py`,
`test_gui_keyboard.py`, `test_gui_editing.py` y `test_gui_scaling.py`), las pruebas de las fachadas
`test_service_{session_key,inputs,ingest_preview,labels_table,dataset_outputs}.py`, la integración
`tests/integration/test_stage5b_gui_integration.py` y la auditoría `tests/qa/test_qa7_gui.py`. El modo congelado
se prueba sin PyInstaller simulando `sys.frozen`/`sys._MEIPASS` (`test_service_inputs.py`,
`tests/integration/test_stage5d_frozen_integration.py`, también el script de compilación con PyInstaller simulado)
y el bundle compilado se audita en `tests/qa/test_qa9_bundle.py`.

**Intermitencia de Tk en la suite completa**: en Windows, con la máquina cargada, un intérprete de Tk nuevo a veces
no logra leer sus propios archivos de biblioteca, que existen («couldn't read file …/tk8.6/panedwindow.tcl», «invalid
command name tcl_findLibrary»). `tests/conftest.py` reintenta `tk.Tk()` hasta 3 veces (0,2 s de pausa) **solo** ante
esos errores de carga y avisa con `TkLoadRetryWarning`; cualquier otro error (por ejemplo, sin pantalla) se propaga
igual y, tras el último intento, el error original. En las corridas completas aparece 0 o 1 reintento.

## Límites conocidos

- La barra de título y los selectores de archivos y carpetas son los del sistema: con el tema oscuro siguen claros.
- La escala real de Windows (125 y 150 %) está pendiente de verificación manual; las
  pruebas simulan la escala.
- Tabla de mapeo con miles de series: cambiar a mano el ancho de la columna de rutas tarda unos segundos.
- Sin cancelación de tareas: los servicios no son cancelables.
- Texto bidireccional (árabe, hebreo): Tk 8.6 no aplica el algoritmo bidi; el texto se dibuja de izquierda a derecha.
  Los datos no se alteran.

## Decisiones de diseño

- Tkinter con `ttk` y un tema propio, sin dependencias nuevas (RNF04, RNF12); identidad con el nombre en texto,
  sin logotipo.
- Controlador sin Tk: todo lo que se puede probar sin pantalla se prueba sin pantalla.
- Clave por sesión: sin pedir la clave; consecuencias en el manual.
- La configuración se resuelve en un solo punto (`project_config_dir`): la raíz del proyecto o, en el ejecutable
  portable, sus YAML incluidos en `_internal/config`.
- Ejecutable portable `onedir` en `.zip`, solo Windows, con PyInstaller como herramienta de build fuera de las
  dependencias del paquete.
- La GUI exige etiquetas cerradas para los exportes ML (la CLI tiene `--allow-unfinalized`).
- Ventana fija, barra de actividad indeterminada, diálogos propios salvo los selectores de archivos, edición de un
  clic e iconos solo en estados y navegación.
