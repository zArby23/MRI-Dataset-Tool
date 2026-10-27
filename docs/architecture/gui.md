# Arquitectura de la GUI (`presentation/gui/`)

La GUI es un asistente Tkinter (stdlib, sin dependencias nuevas) sobre los mismos servicios de `application/` que
la CLI. Es una capa de presentación: dibuja, valida con las funciones de los servicios y traduce resultados y
errores a textos. Manual de uso: `docs/user_manual/gui.md`.

## Estructura

```text
src/mri_dataset_tool/presentation/gui/
├── __init__.py
├── __main__.py        # python -m mri_dataset_tool.presentation.gui
├── app.py             # App(tk.Tk): navegación, menú Idioma, sondeo de la cola, cierre, errores de callbacks
├── controller.py      # Controller y WizardState: SIN Tk; estado, validación, tareas, textos
├── worker.py          # Worker (un hilo daemon, una tarea a la vez), Reporter y eventos
├── messages.py        # catálogo es/en por código y tablas mensaje fijo → código
└── views/
    ├── __init__.py    # StepView (base) e invalidate_on_edit
    ├── input_step.py  # paso 1
    ├── config_step.py # paso 2
    ├── mapping_step.py# paso 3 (solo DICOM/NIfTI)
    ├── run_step.py    # paso 4
    ├── labels_step.py # paso 5
    └── export_step.py # paso 6 (y open_folder)
```

Puntos de entrada: `mri-dataset-gui` (`[project.gui-scripts]` → `presentation.gui.app:main`) y
`python -m mri_dataset_tool.presentation.gui`. `main()` llama a `session_key.ensure_session_key()` y abre la App.

## Capas

- **Vistas**: solo widgets. Leen el estado del controlador para dibujar y llaman a sus métodos; no importan
  servicios. `refresh_texts()` redibuja en el idioma actual; `on_event(event)` recibe los eventos del trabajador
  cuando la vista está activa.
- **Controlador** (`controller.py`): sin Tk, se prueba sin pantalla. Guarda `WizardState` (solo lo que el usuario
  eligió y lo que devolvieron los servicios), valida cada paso con las mismas funciones que la CLI
  (`check_input_paths`/`check_build_args`, `load_build_pipeline`, `check_split_params`, `load_mapping`,
  `plan_ingest`…), construye las tareas largas y convierte excepciones en `Check(code, values)`. Navegación:
  `complete(step)` desbloquea el siguiente paso, `reopen(step)` invalida ese y los siguientes (y, antes de la
  ejecución, el dataset construido).
- **Servicios** (`application/services/`): toda la lógica de negocio. Fachadas nuevas de la etapa 5B:
  - `session_key.py`: `ensure_session_key()` (clave `sha256(secrets.token_bytes(32))` solo en `os.environ` si
    falta o es corta), `key_is_set()`.
  - `inputs.py`: lo que la presentación necesita de la infraestructura (Q8; la CLI también lo importa de aquí,
    salvo `inspect.py`, deuda conocida). `project_config_dir()` es el único punto que ubica `config/` (raíz del
    proyecto; respaldo, el cwd), `check_input_paths()`, `with_memory_consent()`, `is_valid_folder_name()`.
  - `ingest_preview.py`: `preview_ingest` (las `decisions` de `plan_ingest`), `apply_edit` (edición de la tabla →
    filas de `--mapping`), `write_mapping` (TSV nuevo, releído con `load_mapping`).
  - `labels_table.py`: `read_label_sheet`/`read_label_rows` (filas con defecto, una sola revisión),
    `apply_label_edits` (TSV temporal de seudónimos + `apply_label_corrections`), `read_label_corrections`,
    `label_classes`, `labels_finalized`.
  - `dataset_outputs.py`: `ml_exports_exist`, `write_report` (carpeta nueva o vacía) y `report_warnings`.
  - `write_ml_exports(..., output_dir=None)` / `write_ml_files(..., output_dir=None)` (G7b, aprobado en código
    congelado): un juego regenerado en otra carpeta con rutas `../dataset/…`; sin `output_dir`, idéntico a antes.
  - En código de 5A (excepciones aprobadas): `dataset_build.is_new_or_empty_dir` (la salida puede ser una carpeta
    vacía, también en la CLI) e `IngestPlan.decisions` (`SeriesDecision` por serie).

## Trabajador, cola y eventos

Solo el hilo principal toca widgets. Las tareas largas (espacio en disco, vista previa, ejecución, etiquetas,
exportes, reporte) corren en `Worker`: un hilo **daemon**, una tarea a la vez, sin cancelación (al cerrar la
ventana con una tarea se pide confirmación y la tarea se corta). La tarea recibe un `Reporter` cuyos callbacks
encajan con los servicios (`on_status`, `on_skipped`, `on_error`, `on_report_error`) y publican en una
`queue.Queue` solo eventos inmutables: `Status(stage, counts)` (solo enteros), `Skipped(tipo)`,
`StudyFailed(tipo)`, `ReportReadError(tipo)`, `Failed(code, tipo, stage, values)` y `Done(summary)` (solo
enteros). Rutas y mensajes de excepción se descartan en el `Reporter`.

La App sondea la cola cada 100 ms (`after`) con `Controller.poll()` → `Worker.drain()`. `busy` lo limpia
**solo el hilo principal** al sacar el `Done`/`Failed`, para que el último evento de una tarea vieja nunca se tome
por el de una nueva. Los resultados grandes (filas de la vista previa, tabla de etiquetas, nombres de archivos)
no viajan por la cola: la tarea los deja en el controlador y el método `*_finished` los publica en el hilo
principal al llegar el `Done`. Cada tarea puede pasar su clasificador de excepciones (`start_task(task,
classify)`): en el paso 6, `FileExistsError` es «exporte o reporte existente», no «salida existente».

`App.report_callback_exception` registra solo el tipo de una excepción en un callback de Tk y la muestra como
`UNEXPECTED(tipo)` en la barra inferior: nunca su mensaje ni su traceback. Si `on_event` de una vista lanza, `_poll`
lo reporta así y sigue con los eventos siguientes, y el próximo sondeo se programa en un `finally` (QA7-01): la
cola nunca deja de drenarse, así que `busy` no queda en `True` para siempre.

Rutas: el controlador usa `Path(texto)` sin `resolve`, igual que la CLI; una ruta relativa escrita a mano se
resuelve contra la carpeta actual del proceso (QA7-06, documentado en el manual). En el paso 1,
`new_folders_valid` (fachada `inputs`) exige que cada carpeta de la salida que aún no existe tenga un nombre válido
(`is_valid_folder_name`, ≤ 255 bytes) y que la unidad exista (`INVALID_OUTPUT_PATH`, QA7-02).

## Mensajes

`messages.CATALOG` tiene los textos en español e inglés por código; una prueba exige las mismas claves y los
mismos campos en los dos idiomas. Los servicios lanzan mensajes fijos en inglés; la GUI nunca los muestra: los
busca en tablas (`FIXED_MESSAGES` para `InvalidBuildInput`, `LABEL_MESSAGES`, `EXPORT_MESSAGES`) y muestra el
texto de su código. Lo que no está en una tabla se muestra con un código genérico y el tipo de la excepción.
Pruebas de cobertura recorren con expresiones regulares los `raise X("…")` de los servicios y de los archivos de
infraestructura que llaman: todo mensaje fijo debe tener código o estar en una lista explícita de no alcanzables.

## Privacidad (RNF07)

- Estado (`repr`), cola, textos y logs: solo códigos, tipos y conteos. Las filas con rutas relativas (vista
  previa y mapeo, decisión D2 del humano) y la tabla de etiquetas (seudónimos) están fuera del `repr` del estado
  y se muestran solo en sus tablas y en el TSV que el usuario guarda.
- Las rutas mostradas son las que el usuario eligió. La clave de la sesión nunca se muestra, guarda ni registra.
- Barridos de PHI con valores plantados (PatientID, descripciones, ids, rutas) sobre el estado, los textos, la
  cola y los logs DEBUG en las pruebas de cada paso.
- QA6-01: pydicom citaba UIDs no conformes en sus avisos. `infrastructure/dicom/_study_assembler.quiet_value_validation()`
  pone `reading_validation_mode = IGNORE` durante las lecturas DICOM; el ajuste es de todo el proceso, así que un
  contador protegido con `threading.Lock` hace que el primer hilo que entra lo fije y el último que sale lo
  restaure (la GUI puede leer en el trabajador mientras otro hilo lee).

## Rendimiento

- Un estudio en memoria a la vez: la ejecución usa `build_dataset` como la CLI.
- La vista previa (`preview_ingest`) y la ejecución (`plan_ingest` dentro de la tarea) leen cada una todas las
  cabeceras: con árboles DICOM muy grandes cada una puede pasar de 15 minutos (QA7-08), con progreso indeterminado
  y sin cancelación.
- La tabla de etiquetas se reconstruye solo cuando cambian sus filas, ediciones, filtro o idioma
  (`label_version`); con miles de pares cada acción recorre el árbol del dataset (`dataset_pairs`, ~2 s con 3000
  pares en Windows) y corre en el trabajador.

## Pruebas

`tests/unit/test_gui_*.py`: controlador sin Tk con los servicios reales sobre datos sintéticos (BIDS con NaN y PHI
plantada, DICOM, NIfTI sueltos), equivalencia con la CLI (mismas cifras, mismos nombres de archivos, exportes ML y
reporte iguales byte a byte salvo el XLSX), un fallo por etapa, catálogo y coberturas de mensajes, trabajador
(eventos, una tarea a la vez, daemon) y humo de Tk con `skip` si no hay pantalla (un `tk.Tk()` vacío decide).
Pruebas de las fachadas: `test_service_{session_key,inputs,ingest_preview,labels_table,dataset_outputs}.py`.
Auditoría adversarial QA7: `tests/qa/test_qa7_gui.py` e informe `docs/testing/qa_etapa7.md`.

## Decisiones de diseño

- Tkinter: stdlib, Windows y Linux (RNF04, RNF12).
- Controlador sin Tk: todo lo que se puede probar sin pantalla se prueba sin pantalla.
- Clave por sesión (decisión del humano): sin pedir la clave; consecuencias en el manual.
- La configuración se resuelve desde la raíz del proyecto (decisión del humano), en un solo punto
  (`project_config_dir`), para que un ejecutable portable lo apunte a sus YAML incluidos.
- La GUI exige etiquetas cerradas para los exportes ML (decisión del humano; la CLI tiene `--allow-unfinalized`).
- Sin cancelación: los servicios no son cancelables.
