# QA8: auditoría adversarial del aspecto de la GUI (etapa 5C)

Esta auditoría se hizo el 2026-10-28 sobre la rama `etapa-5c-estilo` (commits `bb0ea8c` y `cd9821d`, con la
documentación de V6 sin commit). Cubre lo visual de `presentation/gui/`: tema, marco, diálogos propios, editores de
celda, teclado, escala de pantalla, textos hostiles y documentación. Lo que ya cubre E8
(`tests/integration/test_stage5c_gui_integration.py`) no se repite: la regresión de 5B, el barrido de PHI de los
textos visibles, la cola y la actividad, el cierre en subproceso y el humo de Tk en los dos temas e idiomas.

Las pruebas están en `tests/qa/test_qa8_gui.py`. Los defectos abiertos son `xfail(strict=True)` con su id: fallarán
en cuanto se corrijan, y entonces hay que quitar la marca. Las sondas exploratorias (no son pruebas de la suite)
están en `E:/qa8/p*.py`. QA no tocó código de producción. No se usaron datos reales: todos los valores son
sintéticos. G9 (ejecutable) queda fuera de este informe: por decisión del proyecto (2026-10-28) pasó a la etapa 5D, que tendrá su
propia auditoría.

Suite completa con `test_qa8_gui.py`: **2102 passed, 2 skipped (symlinks), 8 xfailed** (6 de QA8 y 2 anteriores).

## 1. Hallazgos

No hay bloqueantes. **Re-verificación del 2026-10-29** contra el código final de V7: QA8-01 a 10 corregidos o documentados; QA8-11 queda como límite conocido de las pruebas, documentado y no corregido. Las pruebas de `test_qa8_gui.py` ya no llevan `xfail`: 15 passed, y con `test_gui_v7.py`, 24 passed. La suite completa se corre aparte.

| Id | Severidad | Qué pasa | Reproducción mínima (sin PHI) | Esperado | Archivo / dueño | Estado |
|---|---|---|---|---|---|---|
| QA8-01 | importante (RNF03) | En pantallas pequeñas con escala, la ventana se limita a la pantalla y la **línea de estado** de los pasos 3 y 5 se queda sin sitio: 1 px de alto de los 38–76 que pide. Los errores y avisos de esos pasos (p. ej. una edición rechazada o «Aplicar» fallido) no se ven. La tabla está empaquetada antes que la línea de estado, y con `pack` cede primero lo último. En el paso 6, con 150 %, queda cortada la tarjeta de resumen (con «Abrir la carpeta de salida» y «Cerrar»). Medido: 1366×768 al 125 % (pasos 3 y 5), 1280×720 al 125 y 150 % (pasos 1, 3, 5 y 6), 1366×768 al 200 % (todos los pasos). En 1920×1080 a 100–150 % no pasa (lo que prueban E8 y V5) | `test_the_status_line_of_steps_3_and_5_stays_visible_on_small_screens`; sonda `E:/qa8/p1_small_screens.py` | Que cedan la tabla y el registro, no los mensajes: empaquetar la línea de estado (y la tarjeta de resumen) con `side="bottom"` antes de la tabla, o dar una altura mínima a la tabla | `views/mapping_step.py`, `views/labels_step.py`, `views/export_step.py` | **Corregido** (V7): la línea de estado de los pasos 3 y 5 se empaqueta con `side="bottom"` antes de la tabla; la tarjeta del paso 6 la cubre `test_gui_v7.py::test_the_summary_card_of_step_6_stays_inside_the_window_on_small_screens`. Re-verificado 2026-10-29. Aspecto del paso 6 compacto: verificación del usuario |
| QA8-02 | importante (RNF03, RNF06) | «Generar reporte» (paso 6): si el reporte trae un aviso sin texto propio (`UNLABELED_SESSIONS` con etiquetas incompletas, `NON_FINITE_VOXELS`, `UNKNOWN_CLASS`, `MISSING_SUBJECT_ID`...), `controller.export_finished` añade `("REPORT_WARNING", {"code": ..., "count": ...})`. `ExportStep.refresh_texts` lo dibuja con `text(code, **values)` y `code` llega dos veces: `TypeError`. Desde ahí cada redibujo del paso 6 lanza: se ve «Error inesperado: TypeError» y el registro de exportes queda incompleto durante toda la sesión. Los cuatro archivos del reporte sí se escriben. Viene de 5B (G7), no de 5C | `Controller().text("REPORT_WARNING", code="X", count=1)` → `TypeError`; `test_a_report_warning_without_its_own_text_is_shown` | Un nombre de marcador que no choque (p. ej. `{warning}`) en los dos idiomas y en `controller.py:681` | `controller.py`, `messages.py` | **Corregido** (V7): el marcador es `{warning}` en es/en; `test_a_report_warning_without_its_own_text_is_shown` y `test_gui_v7.py::test_every_report_warning_code_is_shown` pasan. Re-verificado 2026-10-29 |
| QA8-03 | importante (RNF01, RNF03) | «Asignar etiqueta a la selección» del paso 3 con DICOM es cuadrático y corre en el hilo principal, con la ventana congelada («No responde»): 250 series 1,3 s, 500 5,1 s, 1000 20 s, 2000 83 s; con 5000 serían ~9 min. Con NIfTI es mucho menor (2000 → 1,4 s). `assign_mapping_label` llama a `apply_edit` una vez por fila seleccionada, y cada llamada recorre todas las filas (`_study_path`, con `parents`) y reordena la tabla. Viene de 5B | `test_batch_label_of_the_mapping_table_scales_with_the_selection` (300 series en menos de 0,5 s); sonda `E:/qa8/p6_big_tables.py` | Lineal: calcular la carpeta de cada estudio una vez (las filas de un mismo estudio comparten la etiqueta), o correrlo en el trabajador | `controller.py`; `ingest_preview.py` está congelado | **Corregido** (V7): una edición por estudio (`_label_edits`), no por fila; `test_batch_label_of_the_mapping_table_scales_with_the_selection` pasa. Re-verificado 2026-10-29 |
| QA8-04 | menor (RNF03) | El editor de una celda (pasos 3 y 5) se coloca una vez con `place` sobre la celda. Si la tabla se desplaza (rueda del ratón o barra), el editor se queda donde estaba, encima de **otra fila**, con el valor de la primera. Lo que se elija o escriba va a la fila original, no a la que se ve debajo. En el paso 3 el valor solo se confirma con Enter, así que es fácil desplazarse con el editor abierto | `test_a_cell_editor_does_not_float_over_another_row_after_scrolling`; sonda `p5_interaction.py` (B) | Cerrar el editor al desplazar la tabla (`yscrollcommand`, `<MouseWheel>`) o recolocarlo | `views/mapping_step.py`, `views/labels_step.py` | **Corregido** (V7): el editor sigue a su celda o se confirma al salir de la vista (`_follow_editor` en `yscrollcommand`, `xscrollcommand` y `<Configure>`, pasos 3 y 5). Re-verificado 2026-10-29 |
| QA8-05 | menor (RNF03) | Paso 3, celdas de texto libre (participante, sesión): lo escrito solo se guarda con Enter. Un clic en otra celda, «Siguiente», «Atrás» o los atajos lo descartan **sin aviso**, y el editor sigue colocado sobre la tabla al volver al paso. El manual dice «Un clic … abre su editor» y «Esc cancela», pero no que hace falta Enter para confirmar | Sonda `p5_interaction.py` (A): editor con «nuevo», sin Enter, «Siguiente» → no queda en `state.mapping`, el editor sigue existiendo | Decisión de diseño: confirmar al perder el foco, o cerrar el editor al salir y decir en el manual y en la ayuda de la celda que Enter confirma | `views/mapping_step.py`, `docs/user_manual/gui.md` | **Corregido** (V7): el texto libre se guarda al perder el foco dentro de la ventana (`FocusOut` → `after_idle`), con Tab o al cambiar de paso («Siguiente», «Atrás» y los atajos pasan por `_leave` → `finish_edit`); Esc cancela; con Alt+Tab el editor queda abierto y el manual lo dice. Pruebas: las tres de QA8 y `test_gui_v7.py::test_free_text_…`. Alt+Tab real: verificación del usuario |
| QA8-06 | menor | Pulsar la X de la ventana (o enviar `WM_CLOSE`) con una pregunta de cierre ya abierta apila **una segunda pregunta igual**: el `grab` es local y no frena el protocolo de cierre. Contestar cualquiera de las dos funciona bien: probé «Aplicar y cerrar», «Descartar», «Cancelar» y «Aceptar» con una tarea en curso, sin errores de Tcl. Es solo una pregunta duplicada | Sondas `p2_dialogs.py wm_close_twice` y `p3_pending_twice.py`; guarda `test_a_second_close_question_while_the_first_is_open_closes_cleanly` | Ignorar `request_close` mientras haya un diálogo abierto | `app.py` | **Corregido** (V7): `request_close` ignora la X mientras la pregunta está abierta (`_asking_close`); `test_the_x_while_a_close_question_is_open_asks_only_once` pasa (y falla con `[2]` si se quita la guarda). Su intermitencia era de la prueba, ver §3 |
| QA8-07 | menor (pruebas) | `theme._scale` y `theme._current` son globales del módulo y quedan con el último `apply_theme` (nota de la revisión). **Confirmado**: en orden inverso falla una prueba de E8, que compara con `theme.px(theme.WINDOW)` después de una prueba de escala al 125 % (§3). En orden normal pasa | Suite de GUI en orden inverso (§3) | Restaurarlos en un fixture de las pruebas de escala, o comparar con el tamaño medido en el recorrido | `tests/integration/test_stage5c_gui_integration.py:335`; `tests/unit/test_gui_scaling.py` | **Corregido** (pruebas): `tests/conftest.py::restore_theme_scale` restaura `theme._scale` y `_current` tras cada prueba. Re-verificado 2026-10-29 (código; el orden inverso no se volvió a correr) |
| QA8-11 | importante (pruebas) | **La escala simulada solo funciona en la primera ventana de cada proceso.** `tk scaling` pertenece a la pantalla y la comparten todas las raíces Tk del proceso. Una raíz nueva hereda la escala de la anterior y calcula su `TkDefaultFont` en puntos a partir de ella: 9 pt pasan a 6 pt (con 2,0) o 7 pt (con 1,25), y al simular otra vez la escala el texto **ya no crece** (sigue con 15 px de interlínea). Así que, dentro de la suite, las pruebas de escala de V5 (`test_every_step_fits_a_full_hd_screen_at_each_scaling`) y de E8 (`test_the_finished_wizard_fits_at_each_display_scaling`) simulan solo el tamaño de la ventana y de los espaciados, no el del texto. Solas, en un proceso limpio, las dos pasan (comprobado). Con QA8-01 la diferencia sí importa: en la suite completa la prueba daba XPASS, y aislada falla siempre. La GUI real no se ve afectada: abre una sola raíz | Raíz A: `tk scaling 2.0` y `destroy`; raíz B: `TkDefaultFont` = 6 pt y la interlínea no cambia al poner otra vez `tk scaling 2.0`. En un proceso nuevo: 9 pt y 25 px | Correr cada caso de escala en un subproceso (como hace ahora QA8-01) o restaurar `tk scaling` y las fuentes con nombre en un fixture | `tests/unit/test_gui_scaling.py`, `tests/integration/test_stage5c_gui_integration.py` | **Límite conocido, documentado, no corregido** (solo afecta a las pruebas, no a la GUI; ver §3): `tests/conftest.py` restaura `tk scaling` después de crear cada raíz, pero sus fuentes con nombre ya se construyeron con la escala heredada. Sonda del 2026-10-29: tras una raíz con `tk scaling` 2,0, una raíz nueva tiene `TkDefaultFont` de 5 pt (8 px de interlínea, frente a 9 pt y 15 px en un proceso limpio). Una revisión observa que el texto de `test_every_step_fits_a_full_hd_screen_at_each_scaling` no crece dentro de la suite. Siguiente paso: correr cada caso de escala en un subproceso, o reconstruir las fuentes con nombre (`font.nametofont(...).configure`) tras restaurar la escala. Escala 125/150 % real: verificación del usuario |
| QA8-10 | menor (pruebas) | Las sondas `_display()` convierten cualquier `TclError` de `tk.Tk()` en «No display available», también en Windows: un fallo de Tk se cuenta como omisión y la prueba no corre (§3) | Omisiones intermitentes en Windows: `test_gui_smoke.py:22`, `test_gui_labels.py:78`, `test_qa7_gui.py:330` | Omitir solo sin pantalla; si no, fallar o dar el motivo en la omisión | `tests/unit`, `tests/integration`, `tests/qa`  | **Corregido**: los `_display()` de `tests/unit`, `tests/integration` y `tests/qa` omiten solo con «no display name». Re-verificado 2026-10-29 |
| QA8-08 | observación (docs) | El manual dice que las clases son «letras y números». La regla real (la de la CLI) acepta espacios internos, guiones, acentos, emojis, árabe y nombres de 300 caracteres (`AD CN`, `a-b`, `Tumor🧠`). Además, en §5 y en la arquitectura se dice que «ceden las tablas»: en pantallas pequeñas ceden los mensajes (QA8-01) | `check_classes(parse_classes(["AD CN"]))` acepta | Describir la regla real (sin tabulador, sin saltos de línea, sin `= + - @` al inicio, sin espacios en los bordes) | `docs/user_manual/gui.md` | **Corregido** (V7): el manual describe la regla real (sin espacios en los bordes, sin `= + - @` al inicio, sin tabuladores, saltos de línea ni control) y la arquitectura dice que ceden las tablas y el registro. Re-verificado 2026-10-29 |
| QA8-09 | observación | Tk 8.6 no aplica el algoritmo bidireccional: un texto árabe o hebreo (clase o ruta) se dibuja de izquierda a derecha y sin ligaduras, y un `U+202E` de una ruta no se interpreta. No hay error ni desborde, solo un orden de lectura incorrecto. Es un límite de Tk, no de la GUI | Sonda `p4_hostile_text.py` | Mencionarlo en los límites del manual | `docs/user_manual/gui.md` | **Documentado** (V7): límite de Tk en el manual («Límite conocido: texto de derecha a izquierda»). Aspecto real: verificación del usuario |

**Cambio posterior a la auditoría.** Tras la re-verificación, la GUI ofrece finalizar las etiquetas después de «Aplicar» y el
botón pasó a llamarse «Finalizar etiquetas» (commits `6f6edb7` y `cde031a`). QA no lo auditó: lo cubren sus propias
pruebas y las de integración adaptadas.

## 2. Qué se probó (pasa)

- **Textos hostiles** (`test_hostile_texts_in_the_tables_and_dialogs_stay_inside_the_window`, `p4_hostile_text.py`):
  una palabra de 300 caracteres, 120 palabras, emojis con ZWJ, árabe, texto mixto, marcas combinantes, CJK y
  `U+202E`, como rutas de la tabla de mapeo, clases, etiquetas, línea de estado y diálogo de confirmación. Nada pasa
  el borde derecho, no hay errores de Tcl, las rutas se cortan con «…» dentro de su columna y la palabra sin espacios
  se parte dentro del ancho del diálogo (456 px).
- **Letra grande del sistema** (`test_a_bigger_system_font_keeps_every_step_inside_the_fixed_window`, `p8_big_fonts.py`):
  `TkDefaultFont` a 11 y 13 pt, con Verdana y sin Verdana ni DejaVu (cae a Segoe UI). En los seis pasos y en los
  dos idiomas, nada pasa el borde derecho de la ventana de 960 px.
- **Catálogo** (`test_every_catalog_text_renders_with_its_own_placeholders`): todas las claves es/en se formatean con
  sus marcadores y sin llaves sueltas, salvo `REPORT_WARNING` (QA8-02). Las dos lenguas tienen las mismas claves y
  los mismos marcadores.
- **Contraste en píxeles reales** (`p7_pixels.py`: captura GDI de la pantalla de Windows, sin PIL): cabecera,
  título, botones (normal, hover, pulsado, foco, deshabilitado), pie, tarjetas de formato, líneas de estado
  (error, aviso, listo), filas pares e impares, filas seleccionadas, ayuda emergente, resumen y marcos. En los dos
  temas todo da **≥ 4,5:1** (mínimo 5,51 en claro y 5,79 en oscuro, ambos de un botón deshabilitado). La selección
  se ve encima de las filas rayadas y del hover. En el degradado de la cabecera, el peor punto de cada color de
  texto está en el extremo superior (≥ 5,33:1).
- **Teclado** (`p5_interaction.py` D): en los seis pasos, Tab y Mayús+Tab recorren el mismo anillo, sin trampas ni
  botones deshabilitados.
- **Diálogos reales** (sin reemplazarlos): con la ventana minimizada, la pregunta de cierre queda oculta y aparece
  al restaurar la ventana; responde a Esc. Dos preguntas apiladas se cierran bien (QA8-06).
- **Bienvenida en pantallas pequeñas** (`p9_welcome_small.py`): con un arranque fallido, en 1366×768 al 100, 125 y
  200 % y en 1280×720 al 150 %, la tarjeta cabe entera y el botón «Cerrar» se ve.
- **Editor viejo** en el paso 5: un clic en otra celda con una tarea en curso destruye el editor y deja la
  referencia; cerrarlo después no lanza y se puede abrir otro (`p5_interaction.py` C).
- **Tablas grandes** (500 filas, `p6_big_tables.py`): llenar, cambiar idioma o tema, filtrar, editar una celda y
  asignar en lote en el paso 5 tardan ≤ 0,3 s; solo es lento el lote del paso 3 (QA8-03).
- **Portabilidad** (revisión del código): `os.startfile` y `SetProcessDpiAwareness` están protegidos por
  `sys.platform`. Sin `ctypes.windll` o sin `shcore`, `enable_dpi_awareness` devuelve `False` (lo prueba V5). Sin
  `xdg-open`, `Popen` lanza `FileNotFoundError`, que «Abrir la carpeta de salida» muestra como `OPEN_FAILED`. No
  hay imágenes ni archivos de recursos: los iconos son vectoriales, así que solo `config/` (por
  `project_config_dir`) importa para G9.

## 3. Intermitencia de Tk y orden de las pruebas

Las 270 pruebas de GUI (`tests/unit/test_gui_*.py`, E7, E8 y `tests/qa/test_qa7_gui.py`) se corrieron solas 3 veces
en orden normal y 1 en orden inverso (`E:/qa8/runs.sh`, ids en `E:/qa8/gui_ids*.txt`):

| Corrida | Resultado | Reintentos de `tests/conftest.py` |
|---|---|---|
| normal 1 | 270 passed (2 min 11 s) | 0 |
| normal 2 | 270 passed | 2 |
| normal 3 | 270 passed | 0 |
| inversa | **1 failed**, 269 passed | 2 |

- **El reintento no oculta fallos**: solo reintenta los errores de carga de la biblioteca de Tk y lo deja escrito
  como `TkLoadRetryWarning` en el resumen. En estas corridas se recuperó siempre al primer reintento.
- **Lo que sí oculta algo son las sondas `_display()`** de las pruebas: convierten **cualquier** `TclError` de
  `tk.Tk()` en una omisión «No display available for Tk.», también en Windows, que siempre tiene pantalla. En la suite
  completa del 2026-10-28 apareció una omisión así (`test_gui_smoke.py:22`), y se vieron otras dos
  (`test_gui_labels.py:78`, `test_qa7_gui.py:330`). Es decir, un fallo de Tk se cuenta como omisión y la prueba no
  corre. Sugerencia (QA8-10, menor): omitir solo si no hay pantalla (Linux sin `DISPLAY`), dejar que falle en otro
  caso, o al menos poner el tipo y la primera línea del error en el motivo de la omisión. Ubicación: `tests/unit`,
  `tests/integration`, `tests/qa`.
- **Orden inverso (QA8-07 confirmado)**: falla
  `test_stage5c_gui_integration.py::test_both_themes_and_languages_redraw_every_step_inside_the_fixed_window`
  (`(960, 680) == (1201, 851)`). La prueba compara con `theme.px(theme.WINDOW)` sin crear ventana, y en orden inverso
  se ejecuta después de `test_the_finished_wizard_fits_at_each_display_scaling[1.25]`, que dejó `theme._scale = 1.25`.
  En orden normal pasa. Es una dependencia de orden de la prueba, no un defecto de la GUI. Arreglo: comparar con el
  tamaño guardado en el recorrido, o restaurar `theme._scale`/`_current` tras las pruebas de escala (fixture).

### Intermitencias de foco (2026-10-29)

- **`test_the_x_while_a_close_question_is_open_asks_only_once`** falló una vez en la suite completa (`seen == []`). Lo reproduje
  con la CPU saturada: 1 de 25. La pregunta real devolvía `True` a ~0,8 s sin que la prueba la aceptara, y la
  ventana se destruía antes del temporizador de 1000 ms. Causa: el diálogo real queda abierto unos 800 ms con
  `focus_force`, que se lleva el foco del sistema, y entonces un Enter o un clic dirigido a otra ventana mientras
  corre la suite lo responde. Además, la prueba dependía de temporizadores fijos (200/600/1000 ms). No es un
  defecto de la GUI. Corregido en la prueba, sin debilitarla: avanza por estado (la segunda X llega cuando la
  primera pregunta es visible, y el «OK» queda programado antes) y usa `focus_set` en lugar de `focus_force`.
  Resultado: 50 de 50 bajo carga, y con la guarda quitada da `[2]`.
- **`test_gui_scaling.py`** (pruebas de foco): se vio una vez `focus_get() is None` en dos pruebas de foco. Sospecha, sin
  reproducir: es la misma causa, porque en Windows `focus_get()` da `None` mientras otra aplicación tiene el foco
  del sistema. Sugerencia: comprobar el foco de Tk de la ventana (`tk.call("focus", "-lastfor", app)`) en vez del
  foco del sistema.

- **`test_free_text_of_a_mapping_cell_is_kept_when_the_editor_loses_the_focus`** falló una vez al correr `test_qa8_gui.py`
  junto con `test_qa7_gui.py`. No se reprodujo en otras dos corridas conjuntas ni en ~90 repeticiones sueltas.
  Sospecha, sin probar: es la misma familia. La GUI trata `focus_get() is None` como «otro programa tomó el foco» y
  deja el editor abierto sin guardar (comportamiento buscado); si en ese instante otra ventana tiene el foco del
  sistema, la prueba ve ese caso. Si se repite, preguntar el foco de Tk de la ventana (`focus -lastfor`) en lugar
  del foco del sistema.

## 4. Sospechas sin probar

- **Linux, `grab_set`**: en `_Dialog.show`, si otro programa tiene un `grab` global, `grab_set` lanza `TclError`
  después de mostrar el diálogo. El llamador recibe la excepción («Error inesperado: TclError»), la ventana no se
  cierra y el diálogo queda abierto sin efecto. No se puede reproducir en Windows.
- **Arranque sin pantalla**: en Linux, `mri-dataset-gui` sin `DISPLAY` termina con el traceback de
  `TclError: no display name…` (sin datos sensibles). El manual lo cubre en «Resolución de problemas». Las pruebas
  de Tk se omiten limpias sin pantalla (E8 y suites de 5B).
- **Mantener Enter pulsado** en un botón que abre una confirmación («Asignar a todas las sin etiquetar», «Cerrar»):
  la repetición del teclado puede pulsar también el botón principal del diálogo. Pasaba igual con el
  `messagebox` nativo de 5B. No lo reproduje con teclado real.

- **`after_idle(focus_first)` tras `destroy`**: `App.refresh` programa `focus_first` con `after_idle`, y
  `App.destroy` no lo cancela. Si la ventana se destruye antes de la siguiente pausa, Tcl escribe
  `invalid command name "…focus_first"` en stderr (lo vi en una prueba propia que destruye justo después de
  `refresh`). En la ventana real no encontré un camino que lo dispare: «Aplicar y cerrar» y «Descartar» destruyen sin
  un `refresh` en medio.

## 5. Verificaciones manuales pendientes

1. Escala real de Windows al 125 y 150 %, también en un portátil de 1366×768 (QA8-01, QA8-11), y la opción «Texto más
   grande». Aspecto del paso 6 compacto en pantallas pequeñas (QA8-01).
2. Ventana en Linux: fuentes (DejaVu), `grab` de los diálogos, `xdg-open`.
3. Aspecto del árabe y el hebreo en las tablas (QA8-09).
4. Doble clic sobre una celda editable con el ratón real (la lista se abre con un clic: el segundo puede cerrarla).
5. Recorrido completo con datos reales, juzgando el aspecto y la usabilidad (checkpoint 3).
6. Alt+Tab real con el editor de una celda abierto (paso 3): al volver se sigue escribiendo (QA8-05).
