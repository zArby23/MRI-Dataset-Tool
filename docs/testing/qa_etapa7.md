# QA7: auditoría adversarial de la GUI y su controlador (etapa 5B)

Esta auditoría se hizo sobre la rama `etapa-5b-gui` (commit `52f73ec`, GUI completa de seis pasos) el 2026-10-26.
Cubre `presentation/gui/` (controlador, trabajador, cola de eventos, vistas Tk) y las fachadas que usa. Las
pruebas están en `tests/qa/test_qa7_gui.py`. Tras los arreglos de @gui (QA7-01 a 04) pasan las 74, sin `xfail`. QA no
tocó código de producción. Las pruebas y este informe no contienen datos reales: los valores plantados son sintéticos y
contienen `Planted`.

## 1. Hallazgos

No hay bloqueantes.

| Id | Severidad | Qué pasa | Reproducción mínima (sin PHI) | Esperado | Archivo / dueño | Estado |
|---|---|---|---|---|---|---|
| QA7-01 | menor (RNF06) | Si una vista lanza en `on_event`, `App._poll` no vuelve a programarse: `self.after(POLL_MS, self._poll)` está después del bucle. `report_callback_exception` muestra el tipo, pero la ventana deja de sondear la cola **para siempre**: la tarea siguiente nunca se drena, `busy` queda en `True`, todo queda deshabilitado y cerrar pide confirmar siempre. No encontré ningún disparador real (los textos de todos los códigos alcanzables reciben sus campos), así que es un endurecimiento | `test_the_window_keeps_polling_after_a_view_fails_on_an_event`: una vista cuyo `on_event` lanza `KeyError`; después, una tarea vacía queda «en curso» | Reprogramar el sondeo en un `finally` (o al principio de `_poll`) | `presentation/gui/app.py` (@gui) | **Corregido** (@gui): el sondeo se reprograma aunque una vista falle; la prueba pasa |
| QA7-02 | menor (RNF03) | Dos salidas pasaban los pasos 1 y 2 y solo fallaban al ejecutar (`STAGE_FAILED` en `export`, sin crear nada). La primera era un nombre de carpeta nueva de más de 255 caracteres, porque `is_valid_folder_name` no miraba la longitud. La segunda, una salida con `:` en Windows. **Corrección del informe** (señalada por @gui): la prueba original construía `base / "o" / "a:b"`, que pathlib convierte en la ruta relativa a la unidad `a:b` (unidad A:), no en un flujo NTFS. El caso real del flujo es el texto `.../o/a:b`, y una unidad inexistente se comporta igual. La CLI tiene el mismo comportamiento con `--output-dir` | `test_a_new_folder_name_is_limited_to_255_utf8_bytes`, `test_an_output_with_a_colon_or_a_missing_drive_is_refused_at_step_1` | Rechazarlas en el paso 1 (`INVALID_FOLDER_NAME`), o aceptarlo como está | `application/services/inputs.py` (@gui) | **Corregido** (@gui): límite de 255 bytes UTF-8 (`INVALID_FOLDER_NAME`); flujo NTFS, ruta relativa a una unidad y unidad inexistente → `INVALID_OUTPUT_PATH` en el paso 1 (`inputs.new_folders_valid`). Las pruebas pasan |
| QA7-03 | menor (RNF03) | «Guardar tabla…» con una ruta que es una carpeta o cuyo padre no existe lanza un `OSError` crudo desde `save_mapping_file` (solo captura `FileExistsError` e `InvalidBuildInput`). La ventana lo muestra como `UNEXPECTED(<tipo>)` en la barra inferior, sin ruta. El diálogo de archivos casi nunca da esas rutas, pero un disco de solo lectura sí (`PermissionError`) | `test_saving_the_mapping_table` | Un código propio (p. ej. `MAPPING_FILE_IO`) | `presentation/gui/controller.py` (@gui) | **Corregido** (@gui): `Check("MAPPING_FILE_UNWRITABLE")`; la prueba pasa |
| QA7-04 | menor (RNF03) | En el paso 3, cambiar de idioma redibuja la tabla desde la última vista previa y **oculta las ediciones pendientes** (la celda vuelve al valor anterior). El estado (`state.mapping`) las conserva y «Siguiente» sigue deshabilitado hasta la próxima vista previa, que las muestra. Así que no hay pérdida de datos, pero la tabla engaña | `test_a_language_change_keeps_the_pending_mapping_edits_on_screen` | Volver a aplicar las ediciones pendientes al redibujar, o redibujar solo los encabezados | `presentation/gui/views/mapping_step.py` (@gui) | **Corregido** (@gui); la prueba pasa |
| QA7-05 | observación | La descripción de una clase puede empezar por `= + - @` (`AD==x`, `AD=@cmd`): `labels._check_classes` solo aplica los prefijos de fórmula al nombre. La descripción solo va a `labels.json`, nunca a una celda TSV o XLSX, así que no hay riesgo de inyección. Pero `MEMORY.md` §3 dice «clases (y descripciones) … sin inicio `= + - @`». Igual en la CLI (código congelado) | `test_hostile_classes` | Corregir la frase de `MEMORY.md`, o validar también la descripción | `MEMORY.md` (@orquestador) | Documentado aquí |
| QA7-06 | observación | Las rutas relativas escritas a mano (entrada, salida, carpeta del reporte) se resuelven contra la carpeta actual del proceso, que en un acceso directo o en el ejecutable portable (G9) puede ser cualquiera. El diálogo siempre da rutas absolutas | Revisión del código (`Path(texto)` sin `resolve` en `set_input` y `report_task`); sin prueba | Avisarlo en el manual, o exigir rutas absolutas en la GUI | `docs/user_manual/gui.md` (@gui) | Documentado aquí |
| QA7-07 | observación | Intermitencia de Tk en la suite completa: un `TclError` aislado en `test_gui_labels_batch.py::test_labels_view_batch_tools` (1 de 3 corridas) y una omisión de más en otra corrida, sin identificar | Ver la §2, «Intermitencias» | Aislar la causa: un `tk.Tk()` por prueba con `destroy` garantizado, o un fixture de sesión | `tests/unit/test_gui_*.py` (@gui) | Abierto |
| QA7-08 | menor (RNF01/RNF03) | Con árboles DICOM muy grandes, la vista previa del paso 3 tarda más de 10 minutos (ver la §3), y el paso 4 vuelve a leer todas las cabeceras. El manual solo dice «tarda minutos». La barra de progreso es indeterminada y no hay cancelación | Corrida real, §3 | Decir en el manual que puede tardar **más de 15 minutos** (recomendación del humano), y quizá mostrar un contador de archivos leídos | `docs/user_manual/gui.md` (@gui) | Abierto |

## 2. Qué se probó (pasa)

- **Rutas hostiles**: entrada con espacios, `ñ` y caracteres CJK; salida con una ruta de más de 260 caracteres
  (rutas largas habilitadas en este Windows); 250 caracteres en el nombre de la carpeta nueva. Se rechazan con su
  código: nombres de carpeta con salto de línea, `/`, `..`, `CON`, `con.txt`, `\x00`, punto o espacio final y `:`.
  Una ruta con `\x00` da `INPUT_NOT_FOUND` sin lanzar.
- **Clases** (`test_hostile_classes`): se rechazan `=x`, `+a`, `-a`, `@a`, repetidas, tabulador, `\x00` y
  sustitutos sueltos; se aceptan CRLF, espacios en los bordes y descripciones vacías.
- **Proporciones y semilla del paso 6**: `nan`, `inf`, `1e309`, coma decimal, suma 1 + 1e-8, vacías → `INVALID_RATIOS`;
  `1e3`, vacía y 5000 dígitos (límite de `int`) → `INVALID_SEED`; ` -3 ` se acepta. Los dígitos Unicode (`٣`, `０`)
  se aceptan como en la CLI (`int()`).
- **Celdas de la tabla de mapeo**: `../x`, `sub-01`, tabulador, salto de línea, `=1+1`, `ñ`, un espacio, `bold`,
  `t1w` y una clase desconocida se rechazan sin cambiar el estado. Guardar nunca sobrescribe un archivo existente.
  Cargar una carpeta como tabla da un código. Las tablas `--mapping` hostiles ya se cubrieron en QA6.
- **TSV de correcciones**: fórmula, par ajeno, par repetido, `sub-../../x`, vacío, bytes aleatorios, Latin-1 y una
  carpeta dan su código y ninguna edición pendiente; BOM con CRLF y columnas de más se aceptan.
- **Clave del entorno** vacía, corta o de 31 caracteres: se reemplaza por una de 64 hexadecimales que no aparece en
  el `repr` del estado, los textos (en los dos idiomas), stdout/stderr ni los logs DEBUG.
- **Trabajador y cola**: una tarea a la vez (un segundo `start_task` se rechaza sin arrancar nada); 500 `Status` y
  un `StudyFailed` antes de un `Failed` llegan todos y en orden; el `Failed` lleva solo el tipo; cambiar el idioma
  o el filtro de etiquetas durante una tarea no rompe nada, y `assign_labels` se rechaza con `TASK_RUNNING`.
- **`quiet_value_validation` con hilos reales** (seguimiento de QA6-01): cinco vistas previas DICOM en el
  trabajador, con UIDs no conformes, mientras el hilo principal lee otro árbol DICOM no conforme en bucle. Ningún
  aviso ni log cita un UID, y `reading_validation_mode` vuelve a su valor al terminar.
- **PHI plantada en los tres formatos, pasos 1 a 6**: DICOM (PatientID, PatientName, StudyDescription,
  ProtocolName, UIDs, nombres de carpeta), NIfTI sueltos (nombre del archivo, `descrip`, `aux_file`, `intent_name`
  y una extensión) y BIDS (ids de sujeto y sesión, las mismas cabeceras y un sidecar JSON con PatientName). Cada
  flujo cierra las etiquetas y escribe dos juegos de exportes ML (el del dataset y `ml_exports_2`, o `_2` y `_3`) y
  dos reportes (`report_2`, `report_3`). Ningún valor plantado aparece en los nombres ni en el contenido del árbol de
  salida (`.gz` descomprimidos), la cola, el estado (fuera de la ruta elegida), los textos, los logs DEBUG ni
  stdout/stderr. La ruta de trabajo tampoco aparece en la cola, los textos ni los logs.
- **Reabrir pasos**: tras escribir los exportes, reabrir las etiquetas impide exportar (`ML_LABELS_NOT_FINALIZED`)
  sin crear `ml_exports_2`. Al cerrarlas otra vez, un **archivo** llamado `ml_exports_2` se salta y se escribe
  `ml_exports_3`. Los exportes del dataset quedan intactos byte a byte. Cambiar el paso 1 después de la ejecución
  da `OUTPUT_NOT_EMPTY` y suelta el dataset.
- **Exportes regenerados, uniones (junctions) y otra unidad**: con la salida como una unión en `C:` que apunta a
  `E:`, las rutas `../dataset/...` de `ml_exports_2` resuelven a las imágenes. Un `ml_exports_2` vacío que es una
  unión a otra unidad da `ML_DIR_OTHER_DRIVE` sin escribir nada. Una carpeta de reporte que es una unión dentro del
  dataset da `REPORT_INSIDE_DATASET`.
- **Cerrar durante una tarea** (subproceso con Tk real): con la ejecución en curso, `request_close` pide
  confirmación una vez y, al aceptar, el proceso termina con código 0 en menos de 1 s, sin traceback ni
  `Fatal Python error` y sin PHI en stdout/stderr. La salida queda incompleta (`out/dataset`), como dice el manual.
  En los sondeos, el cálculo de espacio en disco y la carga de etiquetas acabaron antes del cierre (cierre sin
  pregunta). El resto de tareas usa el mismo hilo daemon.
- **Intermitencias**: `tests/unit/test_gui_*.py`, la integración E7 (incluido su recorrido Tk), `test_qa7_gui.py` y
  `test_qa5_disk_space.py`, cinco veces seguidas: 178 pasan en las cinco (61 a 69 s cada una), sin fallos ni
  omisiones aisladas. La única omisión es la de enlaces simbólicos (sin privilegios en este Windows). La prueba de
  la otra unidad de QA5 se omite ahora con un motivo cuando `tmp_path` está en `E:` (pedido de @orquestador).
  En la **suite completa**, tres corridas seguidas dieron:
  1. 1 fallo aislado: `test_gui_labels_batch.py::test_labels_view_batch_tools` con un `TclError` (6 min 36 s).
  2. Verde, con una omisión de más (3 en lugar de 2) que no se identificó porque la corrida no pedía `-rs`
     (9 min 8 s).
  3. Verde con las 2 omisiones habituales, las dos de enlaces simbólicos (4 min 38 s).

  La prueba del primer caso pasa sola, junto con `test_qa7_gui.py` y en las cinco repeticiones de las pruebas de
  la GUI. Coincide con la intermitencia que anotó @gui (Tk compartido entre pruebas en el mismo proceso). Queda
  como **QA7-07** (observación, dueño @gui): no se pudo reproducir ni aislar la causa.
- **Humo de Tk con pantalla**: en este Windows hay pantalla, así que las pruebas Tk corrieron sin omitirse (la
  ventana con `withdraw()`). Verlas a mano sigue siendo del humano.

## 3. Corrida real acotada del controlador

Se hizo con el controlador (sin Tk), como lo usa la ventana. La entrada fue `data/raw`, en modo solo lectura, y las
salidas fueron a `E:/qa7_real`, borradas al terminar. Como no había una `MRI_ANON_KEY` del humano, se usó la clave
de sesión (`ensure_session_key`). La consola solo mostró conteos, códigos y tipos. Cada flujo recorrió los pasos
1 a 6: espacio en disco, configuración, vista previa (DICOM y NIfTI), ejecución, carga de etiquetas, asignación
en lote, aplicar, cerrar, dos juegos de exportes ML y un reporte. stderr quedó vacío en todas.

| Entrada | Formato y configuración | Resultado |
|---|---|---|
| `dicom_test_studies_old` (154 archivos) | `dicom`, preajuste `stage3_bids.yaml` | Vista previa: 2 series, 0 omitidas. Ejecución en 8 s: 2 estudios, 2 series, 2 participantes, 0 errores. Exportes ML (`dataset` y `ml_exports_2`) y `report_2` escritos |
| `nifti_test_studies` (6 archivos) | `nifti`, preajuste | 6 estudios, 0 errores, en 20 s; igual en los pasos 5 y 6 |
| `bids_test_studies` (1106 archivos, 4,1 GB) | `bids`, solo `validate` y `anonymize` (para acotar el tiempo) | 27 estudios, 76 series, 0 errores, en 185 s (341 s con otra carga en paralelo). 86 archivos omitidos por el lector (`ValueError`): los 86 son punteros de git-annex sin descargar, como avisa el manual |
| `dicom_test_studies` (43 719 archivos, 4,1 GB) | `dicom`, solo la vista previa | Termina con `NO_MAPPED_SERIES` (series de perfusión DSC, excluidas), sin PHI. La primera corrida, con otra carga en paralelo, tardó **741 s**. Una segunda corrida sola se detuvo a los **642 s** sin haber terminado. QA6 midió 178 s para el mismo `plan_ingest` desde la CLI; no se investigó la diferencia (caché de disco o antivirus, quizás) |

**Barrido de privacidad.** Se tomaron los nombres de archivos y carpetas de cada entrada (fragmentos de 5 o más
caracteres, sin el nombre de la carpeta raíz) y se buscaron como palabras completas en tres sitios: los nombres y el
contenido del árbol de salida (cabeceras NIfTI descomprimidas incluidas), la cola de eventos, el `repr` del estado y
los textos y logs DEBUG. Solo aparecieron palabras genéricas que la herramienta escribe por sí misma (en nombres de
archivo fijos, el manifiesto y los mensajes), ningún identificador. Una primera búsqueda por subcadenas dio falsos
positivos: ids cortos de la entrada contenidos dentro de seudónimos hexadecimales.

**Recomendación (pedida por el humano).** El manual debe decir que, con árboles DICOM muy grandes (decenas de miles
de archivos), una tarea puede tardar **más de 15 minutos** sin que la ventana se haya colgado. Afecta a la vista
previa del paso 3 y a la ejecución del paso 4, que vuelve a leer todas las cabeceras antes de convertir. Hoy
`docs/user_manual/gui.md` §6 solo dice «tarda minutos». Además, la barra de progreso es indeterminada y no hay
cancelación: el usuario no sabe cuánto falta. Dueño: @gui.

## 4. Pendiente y no verificado

- **Verificaciones manuales del humano** (las del plan): recorrer la ventana con un BIDS y un DICOM reales; revisar
  el aspecto y la usabilidad; `pytest` en Linux (las pruebas de uniones y de `:` se omiten allí); leer el manual.
- **No probado**:
  - El cierre durante una vista previa DICOM grande o durante el reporte (mismo hilo daemon que la ejecución;
    no se espera otro comportamiento).
  - Doble clic real del ratón en Tk: se probó el rechazo en el controlador y que los botones se deshabilitan en
    `refresh_texts`; los eventos de Tk se procesan en serie.
  - Linux: `xdg-open`, rutas con bytes no UTF-8 en el nombre y temas de Tk.
- No se instaló ninguna herramienta de cobertura.
