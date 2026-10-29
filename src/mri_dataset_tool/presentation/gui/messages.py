"""GUI texts in Spanish (default) and English, by code (``docs/architecture/gui.md``).

The window shows only these texts, filled with counts, stage names or exception type names; never the
message of an exception, a path read from the data, an id, a UID or a header value.
"""

import re

LANGUAGES = ("es", "en")
DEFAULT_LANGUAGE = "es"

CATALOG: dict[str, dict[str, str]] = {
    "es": {
        "APP_TITLE_STEP": "MRI Dataset Tool - {header}",
        "MENU_LANGUAGE": "Idioma",
        "LANGUAGE_es": "Español",
        "LANGUAGE_en": "Inglés",
        "APP_NAME": "MRI Dataset Tool",
        "WELCOME_SUBTITLE": "Preparación de datasets de resonancia magnética para ML/DL",
        "VERSION": "Versión {version}",
        "VERSION_UNKNOWN": "desconocida",
        "LOADING": "Cargando",
        "STARTUP_FAILED": "No se pudo iniciar ({error_type}).",
        "CLOSE": "Cerrar",
        "CLOSE_CONFIRM_TITLE": "Cerrar la herramienta",
        "CLOSE_CONFIRM": "¿Cerrar la herramienta?",
        "PREFIX_error": "Error:",
        "PREFIX_warning": "Aviso:",
        "PREFIX_ok": "Listo:",
        "ACTIVITY_disk_space": "Comprobando el espacio en disco",
        "ACTIVITY_preview": "Leyendo las series",
        "ACTIVITY_run": "Creando el dataset",
        "ACTIVITY_labels": "Guardando las etiquetas",
        "ACTIVITY_corrections": "Leyendo las correcciones",
        "ACTIVITY_ml": "Creando los archivos para entrenamiento",
        "ACTIVITY_report": "Creando el reporte",
        "ACTIVITY_COUNTS": "Omitidos: {skipped} · Fallidos: {failed} · Ilegibles: {unreadable}",
        "THEME_LABEL": "Tema",
        "THEME_light": "Claro",
        "THEME_dark": "Oscuro",
        "PRIVACY_BUTTON": "Privacidad y memoria",
        "PRIVACY_TITLE": "Privacidad y uso de memoria",
        "DIALOG_OK": "Aceptar",
        "DIALOG_CANCEL": "Cancelar",
        "MORE_INFO": "Más información",
        "FORMAT_HELP_bids": "Carpetas sub-/ses- con NIfTI",
        "FORMAT_HELP_dicom": "Carpetas con series DICOM",
        "FORMAT_HELP_nifti": "NIfTI sueltos (.nii, .nii.gz)",
        "SUMMARY_DONE": (
            "Dataset terminado con {studies} estudios, {series} series y {participants} participantes. "
            "Archivos no leídos: {skipped}."
        ),
        "OPEN_FAILED": "No se pudo abrir la carpeta ({error_type}).",
        "PRIVACY_SUMMARY": "Sus datos se quedan en este equipo y los resultados se anonimizan.",
        "PRIVACY_HEADING": "Aviso de privacidad",
        "PRIVACY_LEAD": "Sus datos se quedan en este equipo.",
        "PRIVACY_1": (
            "• Los estudios se procesan localmente; la herramienta no envía información por la red."
        ),
        "PRIVACY_2": (
            "• Los resultados se anonimizan: los identificadores se reemplazan por seudónimos y solo se conservan"
            " los metadatos técnicos necesarios (política v1)."
        ),
        "PRIVACY_3": (
            "• La clave que genera los seudónimos no se muestra ni se guarda. Si usted no define una, se crea una"
            " nueva en cada sesión: los seudónimos cambian y los datasets de sesiones distintas no deben combinar"
            "se."
        ),
        "PRIVACY_4": (
            "• La anonimización no borra texto incrustado en las imágenes ni elimina los rasgos de la cara (defac"
            "ing). Revise el resultado antes de compartirlo."
        ),
        "MEMORY_1": (
            "Antes de remuestrear o normalizar, la herramienta estima la memoria que necesitará y la compara con "
            "la disponible. Si no alcanza, ese estudio se marca como fallido y el lote continúa con los demás."
        ),
        "MEMORY_2": (
            "Puede forzar la ejecución con la casilla «Permitir continuar…», bajo su responsabilidad: el equipo p"
            "uede volverse muy lento, otros programas pueden cerrarse y el proceso puede terminar sin guardar res"
            "ultados."
        ),
        "MEMORY_3": (
            "La estimación es de un instante y no incluye otros programas. Los volúmenes 4D grandes, como las dif"
            "usiones, pueden necesitar varios GB. El tamaño máximo de salida solo se cambia en el archivo de conf"
            "iguración."
        ),
        "BACK": "< Atrás",
        "NEXT": "Siguiente >",
        "STEP_HEADER": "Paso {number} de {total}: {title}",
        "STEP_input": "Entrada",
        "STEP_config": "Configuración",
        "STEP_mapping": "Mapeo de series",
        "STEP_run": "Ejecución",
        "STEP_labels": "Etiquetas",
        "STEP_export": "Resultados",
        "STEP_PENDING": "Este paso aún no está disponible.",
        "TASK_RUNNING": "Hay una tarea en curso; espere a que termine.",
        "CLOSE_TITLE": "Tarea en curso",
        "CLOSE_WHILE_RUNNING": (
            "Hay una tarea en curso. Si cierra ahora se interrumpe y la salida queda incompleta; antes de "
            "repetir tendrá que vaciar la carpeta de salida. ¿Cerrar de todos modos?"
        ),
        "INVALID_INPUT": "Entrada no válida ({error_type}).",
        "OUTPUT_EXISTS": "La salida ya existe; elija una carpeta nueva.",
        "STAGE_FAILED": "Falló la etapa «{stage}» ({error_type}).",
        "UNEXPECTED": "Error inesperado ({error_type}).",
        # step 1: input
        "INPUT_DIR": "Carpeta de entrada",
        "INPUT_FORMAT": "Formato de la entrada",
        "OUTPUT_DIR": "Carpeta de salida (nueva)",
        "BROWSE": "Examinar…",
        "VALIDATE": "Validar",
        "KEY_DEFINED": "Clave de anonimización: definida por usted (se mantiene entre sesiones).",
        "KEY_GENERATED": (
            "Clave de anonimización: generada para esta sesión; los seudónimos cambian en cada sesión."
        ),
        "INPUT_OK": "Entrada y salida válidas.",
        "CHECKING_DISK_SPACE": "Comprobando el espacio en disco.",
        "DISK_SPACE_OK": "Espacio en disco suficiente para la salida estimada.",
        "LOW_DISK_SPACE": (
            "La salida puede ocupar unos {required} GiB y el disco solo tiene {free} GiB libres. Puede "
            "seguir, pero conviene usar otro disco."
        ),
        "INPUT_REQUIRED": "Elija la carpeta de entrada.",
        "OUTPUT_REQUIRED": "Elija la carpeta de salida.",
        "NEW_FOLDER": "Nombre de la carpeta nueva",
        "OUTPUT_NOT_EMPTY": (
            "La carpeta de salida ya tiene archivos. Escriba el nombre de una carpeta nueva y se creará "
            "dentro."
        ),
        "INVALID_FOLDER_NAME": (
            "Nombre de carpeta no válido. Use un nombre simple, sin / \\ : * ? \" < > | ni «..», que no "
            "termine en punto ni en espacio."
        ),
        "FOLDER_NAME_EXISTS": "Ya existe una carpeta o un archivo con ese nombre; elija otro.",
        "INVALID_OUTPUT_PATH": (
            "No se puede crear la carpeta de salida. Revise que la unidad exista y que los nombres nuevos no "
            "tengan / \\ : * ? \" < > |, no terminen en punto o espacio y no sean demasiado largos."
        ),
        # step 2: configuration
        "CONFIG_FILE": "Archivo de configuración (preajuste o propio)",
        "MEMORY_TITLE": "Uso de memoria",
        "ALLOW_MEMORY": "Permitir continuar aunque la memoria disponible no alcance (bajo mi responsabilidad)",
        "CLASSES": (
            "Clases para etiquetar, una por línea. Por ejemplo «AD» o «AD=Alzheimer». Déjelo vacío si no va a "
            "etiquetar."
        ),
        "RATIOS": "Proporciones entrenamiento / validación / prueba",
        "SEED": "Semilla de las particiones",
        "CONFIG_OK": "Configuración válida. Pasos del pipeline:",
        "INVALID_SEED": "La semilla debe ser un número entero.",
        # step 3: mapping
        "PREVIEW": "Vista previa",
        "LOAD_MAPPING": "Cargar tabla…",
        "SAVE_MAPPING": "Guardar tabla…",
        "MAPPING_HELP": (
            "Haga clic en una celda de sufijo, participante, sesión o etiqueta para cambiarla. Si la deja "
            "vacía, se decide sola. El sufijo cambia solo esa serie y lo demás, todo el estudio. Después "
            "pulse «Vista previa». Sin una vista previa correcta no se puede seguir. Si los nombres de los "
            "archivos no dicen qué imagen son, cargue antes un archivo de tabla con «Cargar tabla»."
        ),
        "COL_location": "Carpeta o archivo",
        "COL_suffix": "Sufijo",
        "COL_code": "Decisión",
        "COL_participant": "Participante",
        "COL_session": "Sesión",
        "COL_label": "Etiqueta",
        "CODE_MATCHED": "detectado",
        "CODE_MAPPED": "por tabla",
        "CODE_NO_MATCH": "omitida: sin coincidencia",
        "CODE_AMBIGUOUS": "omitida: ambigua",
        "CODE_EXCLUDED": "omitida: excluida",
        "PREVIEW_RUNNING": "Leyendo las series.",
        "PREVIEW_OK": (
            "{series} series encontradas: {skipped} sin sufijo (se omitirán) y {files} archivos que no se "
            "pudieron leer."
        ),
        "EDIT_PENDING": "Cambios sin comprobar: pulse «Vista previa».",
        "MAPPING_SAVED": "Tabla guardada.",
        "MAPPING_LOADED": "Tabla cargada: pulse «Vista previa».",
        "MAPPING_FILE_EXISTS": "El archivo ya existe; elija otro nombre.",
        "MAPPING_FILE_UNWRITABLE": (
            "No se pudo escribir el archivo (¿una carpeta, una carpeta que no existe o un disco de solo lectura?); "
            "elija otro."
        ),
        "SHARED_SERIES_FOLDER": (
            "Varias series comparten esta carpeta: el sufijo no se puede fijar desde aquí (use un archivo de tabla)."
        ),
        "SHARED_STUDY_FOLDER": (
            "La carpeta del estudio contiene también otros estudios: edítelo con un archivo de tabla."
        ),
        # step 4: run
        "RUN": "Ejecutar",
        "RUN_HELP": (
            "Crea en la carpeta de salida el dataset anonimizado, con sus etiquetas, los archivos para "
            "entrenar modelos y el reporte. Puede tardar y no se puede cancelar."
        ),
        "RUN_RUNNING": "Creando el dataset.",
        "RUN_DONE": "Terminado.",
        "RUN_CLEAN": "Sin errores.",
        "LABELS_UNAPPLIED": "Cambios sin aplicar: {count}.",
        "LEAVE_PENDING_TITLE": "Cambios sin aplicar",
        "LEAVE_PENDING": "Hay {count} cambios de etiquetas sin aplicar. ¿Qué quiere hacer?",
        "APPLY_AND_CONTINUE": "Aplicar y continuar",
        "DISCARD": "Descartar",
        "CLOSE_PENDING": "Hay {count} cambios de etiquetas sin aplicar. ¿Qué quiere hacer antes de cerrar?",
        "APPLY_AND_CLOSE": "Aplicar y cerrar",
        "HINT_EDIT_LABEL": "Clic para elegir la clase",
        "HINT_EDIT_CELL": "Clic para editar",
        "HINT_NEXT": "Siguiente paso (Alt+→ o Ctrl+Enter)",
        "HINT_BACK": "Paso anterior (Alt+←)",
        "RUN_FAILED_HINT": "Antes de repetir, vacíe o borre la carpeta de salida.",
        "RUN_ERRORS": "Estudios con error, por tipo: {counts}.",
        "RUN_SKIPPED": "Archivos que no se pudieron leer: {counts}.",
        "RUN_REPORT_ERRORS": "Archivos que el reporte no pudo leer: {counts}.",
        "NONE": "ninguno",
        "EV_export": "Procesando y anonimizando los estudios.",
        "EV_exported": (
            "Estudios guardados: {studies}. Series: {series}. Participantes: {participants}. Con error: "
            "{errors}."
        ),
        "EV_labels_skipped": "Sin etiquetas, porque no se indicaron clases.",
        "EV_label_template": "Lista de etiquetas preparada con {classes} clases.",
        "EV_mapping_labels_applied": "Etiquetas tomadas de la tabla: {rows}.",
        "EV_corrections_applied": "Correcciones aplicadas: {rows}.",
        "EV_labels_finalized": "Etiquetas cerradas: {labels}.",
        "EV_ml_exports_skipped": (
            "Faltan etiquetas, así que aún no se crearon los archivos para entrenamiento. Complételas en el "
            "paso siguiente."
        ),
        "EV_ml_exports": "Archivos para entrenamiento creados: {files}.",
        "EV_report": "Reporte creado: {files} archivos.",
        "WARN_UNMAPPED_SERIES": "Aviso UNMAPPED_SERIES: series omitidas por código: {codes}.",
        "WARN_NOT_4D_DWI": "Aviso NOT_4D_DWI: {count} series dwi no son 4D y se omitieron.",
        "WARN_MAPPING_UNUSED": "Aviso MAPPING_UNUSED: {count} filas de la tabla no aplican a ninguna serie.",
        "WARN_MISSING_PATIENT_ID": (
            "Aviso MISSING_PATIENT_ID: {count} estudios con archivos sin PatientID; el paciente puede quedar partido "
            "en varios participantes (corríjalo en la tabla)."
        ),
        "WARN_LABELS_INCOMPLETE": "Aviso LABELS_INCOMPLETE: etiquetas incompletas ({codes}).",
        # step 5: labels
        "LABELS_HELP": (
            "Haga clic en una celda de «Etiqueta» para elegir la clase. Los cambios quedan pendientes hasta "
            "que pulse «Aplicar», y cada cambio queda registrado. Para «Finalizar etiquetas», todas las filas "
            "deben tener clase; después podrá crear los archivos para entrenamiento. «Reabrir» permite volver "
            "a editarlas."
        ),
        "APPLY": "Aplicar",
        "FINALIZE": "Finalizar etiquetas",
        "FINALIZE_NOW_TITLE": "Etiquetas completas",
        "FINALIZE_NOW": "Todas las filas tienen etiqueta. ¿Finalizar las etiquetas ahora?",
        "LATER": "Más tarde",
        "REOPEN": "Reabrir",
        "RELOAD": "Recargar",
        "COL_defect": "Defecto",
        "DEFECT_UNLABELED": "sin etiqueta",
        "DEFECT_UNKNOWN_CLASS": "clase desconocida",
        "DEFECT_DUPLICATED": "repetida en la tabla",
        "DEFECT_MISSING": "falta en la tabla",
        "LABELS_OPEN": "Etiquetas abiertas: {labeled} de {pairs} filas con clase.",
        "LABELS_CLOSED": "Etiquetas cerradas: {labeled} de {pairs} filas con clase.",
        "LABELS_FOREIGN": (
            "El archivo de etiquetas tiene {foreign} filas de otro dataset y {invalid} con identificadores no "
            "válidos. No se usan."
        ),
        "LABELS_APPLIED": "Cambios aplicados: {count}.",
        "NO_LABELS": "Este dataset no tiene etiquetas (no se indicaron clases en el paso 2). Puede seguir.",
        "LABEL_TABLE_NOT_FOUND": "No se encuentra el archivo de etiquetas del dataset.",
        "LABELS_FINALIZED": "Las etiquetas están cerradas: reábralas para editarlas.",
        "LABELS_NOT_FINALIZED": "Las etiquetas no están cerradas.",
        "LABELS_INCOMPLETE": "No se pueden cerrar: hay filas sin clase o con defectos.",
        "LABELS_FIX_BY_HAND": (
            "El archivo de etiquetas se editó fuera de la herramienta y tiene filas repetidas o no válidas. "
            "Corríjalo antes de seguir."
        ),
        "LABEL_UNKNOWN_CLASS": "Esa clase no está en la lista de clases.",
        "LABEL_PAIR_UNKNOWN": "Un participante o sesión no está en el dataset.",
        "LABEL_EDIT_INVALID": "Cambio de etiqueta no válido.",
        "LABEL_FILES_INVALID": "Los archivos de etiquetas del dataset no son válidos.",
        "LABEL_FILES_IO": "No se pudieron leer o escribir los archivos de etiquetas del dataset.",
        "LABELS_NO_DATASET": "No se encuentra el dataset o no tiene participantes.",
        "LABELS_DISCARDED": "Se descartaron {count} cambios sin aplicar.",
        "LABEL_CORRECTIONS_INVALID": (
            "El archivo de correcciones no es válido: debe tener las columnas participant_id, session_id y "
            "label, sin filas repetidas."
        ),
        "CORRECTIONS_UNREADABLE": "No se pudo leer el archivo de correcciones (permisos o no es un archivo).",
        "BATCH_CLASS": "Clase:",
        "ASSIGN_SELECTION": "Asignar a la selección",
        "ASSIGN_UNLABELED": "Asignar a todas las sin etiquetar",
        "LOAD_CORRECTIONS": "Cargar correcciones (archivo TSV)…",
        "FILTER": "Mostrar:",
        "FILTER_all": "todas",
        "FILTER_unlabeled": "sin etiquetar",
        "FILTER_defect": "con defecto",
        "NOTHING_SELECTED": "Seleccione una o más filas (Ctrl o Mayús para varias).",
        "NOTHING_UNLABELED": "No hay filas sin clase.",
        "CONFIRM_TITLE": "Confirmar",
        "CONFIRM_ASSIGN_UNLABELED": "¿Asignar la clase «{label}» a las {count} filas sin clase?",
        "ASSIGNED": "Clase asignada a {count} filas. Pulse «Aplicar» para guardarla.",
        "CORRECTIONS_LOADED": "Correcciones cargadas como cambios pendientes: {count}. Pulse «Aplicar».",
        "ASSIGN_LABEL_SELECTION": "Asignar etiqueta a la selección",
        "MAPPING_ASSIGNED": (
            "Etiqueta asignada a los estudios de {count} series. Pulse «Vista previa» para comprobarlo."
        ),
        "LABELS_EDITS_PENDING": "Aplique o descarte los cambios antes de cerrar.",
        "LABELS_ERROR": "Error en las etiquetas ({error_type}).",
        # step 6: exports and report
        "ML_EXPORTS": "Archivos para entrenar modelos (índice y particiones por participante)",
        "WRITE_ML": "Crear los archivos para entrenamiento",
        "REGENERATE_ML": "Crear otro juego en una carpeta nueva",
        "ML_WRITTEN_IN": "Archivos para entrenamiento creados en «{folder}»: {files}.",
        "ML_REGENERATE_HELP": (
            "Al ejecutar se crean los archivos para entrenamiento con los valores estándar (70/15/15, semilla "
            "0). Aquí puede crear otro juego con otras proporciones o semilla. Se guarda en una carpeta nueva "
            "junto al dataset."
        ),
        "ML_DIR_NOT_EMPTY": "La carpeta para los archivos de entrenamiento ya tiene contenido. Elija otra.",
        "ML_DIR_INSIDE_DATASET": "La carpeta para los archivos de entrenamiento debe estar fuera del dataset.",
        "ML_DIR_OTHER_DRIVE": (
            "La carpeta para los archivos de entrenamiento debe estar en el mismo disco que el dataset."
        ),
        "REPORT": "Reporte del dataset (JSON, Markdown, XML y Excel)",
        "REPORT_DIR": "Carpeta del reporte (nueva o vacía)",
        "WRITE_REPORT": "Generar reporte",
        "OPEN_FOLDER": "Abrir la carpeta de salida",
        "TASK_STARTED": "En curso.",
        "ML_PRESENT": "Los archivos para entrenamiento ya están creados.",
        "ML_ABSENT": "Los archivos para entrenamiento aún no están creados.",
        "REPORT_WRITTEN": "Reporte creado: {files} archivos.",
        "FILE_NAME": "  {name}",
        "REPORT_WARNING": "Aviso del reporte {warning}: {count}.",
        "REPORT_WARNING_UNREADABLE_FILES": "Aviso UNREADABLE_FILES: {count} archivos del dataset no se pudieron leer.",
        "REPORT_WARNING_LABELS_UNREADABLE": "Aviso LABELS_UNREADABLE: las etiquetas no se pudieron leer.",
        "REPORT_WARNING_MANIFEST_UNREADABLE": "Aviso MANIFEST_UNREADABLE: no se pudo leer el registro de la ejecución.",
        "REPORT_DIR_REQUIRED": "Elija la carpeta del reporte.",
        "REPORT_DIR_NOT_EMPTY": "La carpeta del reporte tiene contenido; elija una nueva o vacía.",
        "REPORT_INSIDE_DATASET": "La carpeta del reporte debe estar fuera del dataset.",
        "REPORT_IO": "No se pudo escribir el reporte.",
        "REPORT_NO_STUDIES": "El dataset no tiene estudios legibles: no hay reporte.",
        "ML_EXPORTS_EXIST": "Los archivos para entrenamiento ya existen. No se sobrescriben.",
        "ML_LABELS_NOT_FINALIZED": (
            "Las etiquetas no están cerradas: ciérrelas en el paso anterior antes de crear los archivos para "
            "entrenamiento."
        ),
        "DATASET_NOT_FOUND": "No se encuentra el dataset.",
        "DATASET_LAYOUT_INVALID": "El dataset tiene archivos fuera de su estructura (¿se añadieron a mano?).",
        "DATASET_NO_IMAGES": "El dataset no tiene imágenes o participantes que repartir.",
        "EXPORT_ERROR": "No se pudieron crear los archivos o el reporte ({error_type}).",
        # fixed service messages (``FIXED_MESSAGES``)
        "INPUT_NOT_FOUND": "No se encuentra la carpeta de entrada.",
        "CONFIG_NOT_FOUND": "No se encuentra el archivo de configuración.",
        "CORRECTIONS_NEED_CLASSES": "Las correcciones de etiquetas necesitan clases.",
        "CORRECTIONS_NOT_FOUND": "No se encuentra el archivo de correcciones.",
        "INVALID_CLASSES": (
            "Clases no válidas. Use solo letras y números, sin repetir. La descripción va después de «=»."
        ),
        "INVALID_FORMAT": "Formato de entrada no válido.",
        "INVALID_MAPPING": "Tabla de mapeo no válida.",
        "INVALID_RATIOS": "Proporciones no válidas: tres números no negativos que sumen 1.",
        "INVALID_CONFIG": "Configuración no válida ({error_type}).",
        "MAPPING_NOT_FOUND": "No se encuentra la tabla de mapeo.",
        "MAPPING_PATHS_NOT_FOUND": "Rutas de la tabla que no existen en la entrada: {count}.",
        "MAPPING_LABEL_CONFLICT": "La tabla asigna etiquetas distintas al mismo participante y sesión.",
        "MAPPING_SESSION_MIX": "La tabla deja a un participante con sesión y sin sesión.",
        "MAPPING_STUDY_SPLIT": (
            "La tabla da a un estudio más de un participante o sesión; use una fila con la carpeta del estudio."
        ),
        "MAPPING_PAIR_REPEATED": "La tabla da el mismo participante y sesión a más de un estudio.",
        "MAPPING_LABEL_UNKNOWN": "Una etiqueta de la tabla no es una de las clases.",
        "MAPPING_LABELS_NEED_CLASSES": "Las etiquetas de la tabla necesitan clases.",
        "NO_MAPPED_SERIES": (
            "Ninguna serie tiene un sufijo reconocido. Cargue un archivo de tabla con el sufijo de cada serie "
            "y pulse otra vez «Vista previa»."
        ),
        "NO_INPUT_STUDIES": "No hay estudios válidos en la entrada.",
        "OUTPUT_INSIDE_INPUT": "La carpeta de salida debe estar fuera de la entrada.",
        "PIPELINE_WITHOUT_ANONYMIZE": "El pipeline debe incluir el paso anonymize.",
    },
    "en": {
        "APP_TITLE_STEP": "MRI Dataset Tool - {header}",
        "MENU_LANGUAGE": "Language",
        "LANGUAGE_es": "Spanish",
        "LANGUAGE_en": "English",
        "APP_NAME": "MRI Dataset Tool",
        "WELCOME_SUBTITLE": "Preparing MRI datasets for ML/DL",
        "VERSION": "Version {version}",
        "VERSION_UNKNOWN": "unknown",
        "LOADING": "Loading",
        "STARTUP_FAILED": "Could not start ({error_type}).",
        "CLOSE": "Close",
        "CLOSE_CONFIRM_TITLE": "Close the tool",
        "CLOSE_CONFIRM": "Close the tool?",
        "PREFIX_error": "Error:",
        "PREFIX_warning": "Warning:",
        "PREFIX_ok": "Done:",
        "ACTIVITY_disk_space": "Checking the disk space",
        "ACTIVITY_preview": "Reading the series",
        "ACTIVITY_run": "Creating the dataset",
        "ACTIVITY_labels": "Saving the labels",
        "ACTIVITY_corrections": "Reading the corrections",
        "ACTIVITY_ml": "Creating the training files",
        "ACTIVITY_report": "Creating the report",
        "ACTIVITY_COUNTS": "Skipped: {skipped} · Failed: {failed} · Unreadable: {unreadable}",
        "THEME_LABEL": "Theme",
        "THEME_light": "Light",
        "THEME_dark": "Dark",
        "PRIVACY_BUTTON": "Privacy and memory",
        "PRIVACY_TITLE": "Privacy and memory use",
        "DIALOG_OK": "OK",
        "DIALOG_CANCEL": "Cancel",
        "MORE_INFO": "More information",
        "FORMAT_HELP_bids": "sub-/ses- folders with NIfTI",
        "FORMAT_HELP_dicom": "Folders with DICOM series",
        "FORMAT_HELP_nifti": "Loose NIfTI (.nii, .nii.gz)",
        "SUMMARY_DONE": (
            "Dataset finished with {studies} studies, {series} series and {participants} participants. Files "
            "not read: {skipped}."
        ),
        "OPEN_FAILED": "The folder could not be opened ({error_type}).",
        "PRIVACY_SUMMARY": "Your data stays on this computer and the results are anonymized.",
        "PRIVACY_HEADING": "Privacy notice",
        "PRIVACY_LEAD": "Your data stays on this computer.",
        "PRIVACY_1": (
            "• Studies are processed locally; the tool sends no information over the network."
        ),
        "PRIVACY_2": (
            "• The results are anonymized: identifiers are replaced by pseudonyms and only the technical metadata"
            " needed is kept (policy v1)."
        ),
        "PRIVACY_3": (
            "• The key that generates the pseudonyms is never shown or saved. If you do not set one, a new one is"
            " created every session: pseudonyms change and datasets from different sessions must not be combined."
        ),
        "PRIVACY_4": (
            "• Anonymization does not remove text burned into the images or the facial features (defacing). Revie"
            "w the result before sharing it."
        ),
        "MEMORY_1": (
            "Before resampling or normalizing, the tool estimates the memory it will need and compares it with th"
            "e memory available. If it is not enough, that study is marked as failed and the batch goes on with t"
            "he others."
        ),
        "MEMORY_2": (
            "You can force the run with the «Allow the run to continue…» checkbox, at your own risk: the computer"
            " may become very slow, other programs may close and the process may end without saving results."
        ),
        "MEMORY_3": (
            "The estimate is a snapshot and does not include other programs. Large 4D volumes, such as diffusion "
            "scans, may need several GB. The maximum output size can only be changed in the configuration file."
        ),
        "BACK": "< Back",
        "NEXT": "Next >",
        "STEP_HEADER": "Step {number} of {total}: {title}",
        "STEP_input": "Input",
        "STEP_config": "Configuration",
        "STEP_mapping": "Series mapping",
        "STEP_run": "Run",
        "STEP_labels": "Labels",
        "STEP_export": "Results",
        "STEP_PENDING": "This step is not available yet.",
        "TASK_RUNNING": "A task is running; wait for it to finish.",
        "CLOSE_TITLE": "Task running",
        "CLOSE_WHILE_RUNNING": (
            "A task is running. Closing now interrupts it and leaves the output incomplete; before trying "
            "again you will have to empty the output folder. Close anyway?"
        ),
        "INVALID_INPUT": "Invalid input ({error_type}).",
        "OUTPUT_EXISTS": "The output already exists; choose a new folder.",
        "STAGE_FAILED": "Stage \"{stage}\" failed ({error_type}).",
        "UNEXPECTED": "Unexpected error ({error_type}).",
        # step 1: input
        "INPUT_DIR": "Input folder",
        "INPUT_FORMAT": "Input format",
        "OUTPUT_DIR": "Output folder (new)",
        "BROWSE": "Browse…",
        "VALIDATE": "Validate",
        "KEY_DEFINED": "Anonymization key: set by you (kept across sessions).",
        "KEY_GENERATED": "Anonymization key: generated for this session; pseudonyms change every session.",
        "INPUT_OK": "Valid input and output.",
        "CHECKING_DISK_SPACE": "Checking the disk space.",
        "DISK_SPACE_OK": "Enough disk space for the estimated output.",
        "LOW_DISK_SPACE": (
            "The output may take about {required} GiB and the drive has only {free} GiB free. You can go on, "
            "but another drive is advisable."
        ),
        "INPUT_REQUIRED": "Choose the input folder.",
        "OUTPUT_REQUIRED": "Choose the output folder.",
        "NEW_FOLDER": "Name of the new folder",
        "OUTPUT_NOT_EMPTY": (
            "The output folder already has files. Type a name for a new folder and it will be created inside."
        ),
        "INVALID_FOLDER_NAME": (
            "Invalid folder name. Use a simple name, without / \\ : * ? \" < > | or \"..\", not ending in a "
            "dot or a space."
        ),
        "FOLDER_NAME_EXISTS": "A folder or file with that name already exists; choose another.",
        "INVALID_OUTPUT_PATH": (
            "The output folder cannot be created. Check that the drive exists and that the new names have no "
            "/ \\ : * ? \" < > |, do not end in a dot or a space and are not too long."
        ),
        # step 2: configuration
        "CONFIG_FILE": "Configuration file (preset or your own)",
        "MEMORY_TITLE": "Memory use",
        "ALLOW_MEMORY": "Allow the run to continue even if the available memory is not enough (at my own risk)",
        "CLASSES": (
            "Classes to label with, one per line. For example \"AD\" or \"AD=Alzheimer\". Leave it empty if "
            "you will not label."
        ),
        "RATIOS": "Training / validation / test ratios",
        "SEED": "Split seed",
        "CONFIG_OK": "Valid configuration. Pipeline steps:",
        "INVALID_SEED": "The seed must be an integer.",
        # step 3: mapping
        "PREVIEW": "Preview",
        "LOAD_MAPPING": "Load table…",
        "SAVE_MAPPING": "Save table…",
        "MAPPING_HELP": (
            "Click a suffix, participant, session or label cell to change it. If you leave it empty, it is "
            "decided automatically. The suffix changes only that series and the rest, the whole study. Then "
            "press \"Preview\". Without a correct preview you cannot go on. If the file names do not say "
            "which image they are, first load a table file with \"Load table\"."
        ),
        "COL_location": "Folder or file",
        "COL_suffix": "Suffix",
        "COL_code": "Decision",
        "COL_participant": "Participant",
        "COL_session": "Session",
        "COL_label": "Label",
        "CODE_MATCHED": "detected",
        "CODE_MAPPED": "by table",
        "CODE_NO_MATCH": "skipped: no match",
        "CODE_AMBIGUOUS": "skipped: ambiguous",
        "CODE_EXCLUDED": "skipped: excluded",
        "PREVIEW_RUNNING": "Reading the series.",
        "PREVIEW_OK": (
            "{series} series found: {skipped} without a suffix (they will be left out) and {files} files that "
            "could not be read."
        ),
        "EDIT_PENDING": "Unchecked changes: press \"Preview\".",
        "MAPPING_SAVED": "Table saved.",
        "MAPPING_LOADED": "Table loaded: press \"Preview\".",
        "MAPPING_FILE_EXISTS": "The file already exists; choose another name.",
        "MAPPING_FILE_UNWRITABLE": (
            "The file could not be written (a folder, a missing folder or a read-only drive?); choose another."
        ),
        "SHARED_SERIES_FOLDER": (
            "Several series share this folder: the suffix cannot be set from here (use a table file)."
        ),
        "SHARED_STUDY_FOLDER": "The study folder also holds other studies: edit it with a table file.",
        # step 4: run
        "RUN": "Run",
        "RUN_HELP": (
            "Creates the anonymized dataset in the output folder, with its labels, the files to train models "
            "and the report. It may take a while and cannot be cancelled."
        ),
        "RUN_RUNNING": "Creating the dataset.",
        "RUN_DONE": "Done.",
        "RUN_CLEAN": "No errors.",
        "LABELS_UNAPPLIED": "Changes not applied: {count}.",
        "LEAVE_PENDING_TITLE": "Changes not applied",
        "LEAVE_PENDING": "There are {count} label changes not applied. What do you want to do?",
        "APPLY_AND_CONTINUE": "Apply and continue",
        "DISCARD": "Discard",
        "CLOSE_PENDING": "There are {count} label changes not applied. What do you want to do before closing?",
        "APPLY_AND_CLOSE": "Apply and close",
        "HINT_EDIT_LABEL": "Click to choose the class",
        "HINT_EDIT_CELL": "Click to edit",
        "HINT_NEXT": "Next step (Alt+→ or Ctrl+Enter)",
        "HINT_BACK": "Previous step (Alt+←)",
        "RUN_FAILED_HINT": "Before trying again, empty or delete the output folder.",
        "RUN_ERRORS": "Studies with errors, by type: {counts}.",
        "RUN_SKIPPED": "Files that could not be read: {counts}.",
        "RUN_REPORT_ERRORS": "Files the report could not read: {counts}.",
        "NONE": "none",
        "EV_export": "Processing and anonymizing the studies.",
        "EV_exported": (
            "Studies saved: {studies}. Series: {series}. Participants: {participants}. With errors: {errors}."
        ),
        "EV_labels_skipped": "No labels, because no classes were given.",
        "EV_label_template": "Label list ready with {classes} classes.",
        "EV_mapping_labels_applied": "Labels taken from the table: {rows}.",
        "EV_corrections_applied": "Corrections applied: {rows}.",
        "EV_labels_finalized": "Labels closed: {labels}.",
        "EV_ml_exports_skipped": (
            "Some labels are missing, so the training files were not created yet. Complete them in the next "
            "step."
        ),
        "EV_ml_exports": "Training files created: {files}.",
        "EV_report": "Report created: {files} files.",
        "WARN_UNMAPPED_SERIES": "Warning UNMAPPED_SERIES: series skipped by code: {codes}.",
        "WARN_NOT_4D_DWI": "Warning NOT_4D_DWI: {count} dwi series are not 4D and were skipped.",
        "WARN_MAPPING_UNUSED": "Warning MAPPING_UNUSED: {count} table rows apply to no series.",
        "WARN_MISSING_PATIENT_ID": (
            "Warning MISSING_PATIENT_ID: {count} studies with files without PatientID; the patient may be split "
            "into several participants (fix it in the table)."
        ),
        "WARN_LABELS_INCOMPLETE": "Warning LABELS_INCOMPLETE: incomplete labels ({codes}).",
        # step 5: labels
        "LABELS_HELP": (
            "Click a \"Label\" cell to choose the class. Changes stay pending until you press \"Apply\", and "
            "every change is logged. To \"Finalize labels\", every row must have a class; then you can create "
            "the training files. \"Reopen\" lets you edit them again."
        ),
        "APPLY": "Apply",
        "FINALIZE": "Finalize labels",
        "FINALIZE_NOW_TITLE": "Labels complete",
        "FINALIZE_NOW": "Every row has a label. Finalize the labels now?",
        "LATER": "Later",
        "REOPEN": "Reopen",
        "RELOAD": "Reload",
        "COL_defect": "Defect",
        "DEFECT_UNLABELED": "unlabeled",
        "DEFECT_UNKNOWN_CLASS": "unknown class",
        "DEFECT_DUPLICATED": "repeated in the table",
        "DEFECT_MISSING": "missing from the table",
        "LABELS_OPEN": "Labels open: {labeled} of {pairs} rows with a class.",
        "LABELS_CLOSED": "Labels closed: {labeled} of {pairs} rows with a class.",
        "LABELS_FOREIGN": (
            "The label file has {foreign} rows from another dataset and {invalid} with invalid identifiers. "
            "They are not used."
        ),
        "LABELS_APPLIED": "Changes applied: {count}.",
        "NO_LABELS": "This dataset has no labels (no classes were given in step 2). You can go on.",
        "LABEL_TABLE_NOT_FOUND": "The label file of the dataset is missing.",
        "LABELS_FINALIZED": "The labels are finalized: reopen them to edit.",
        "LABELS_NOT_FINALIZED": "The labels are not finalized.",
        "LABELS_INCOMPLETE": "They cannot be closed: some rows have no class or have defects.",
        "LABELS_FIX_BY_HAND": (
            "The label file was edited outside the tool and has repeated or invalid rows. Fix it before going "
            "on."
        ),
        "LABEL_UNKNOWN_CLASS": "That class is not in the list of classes.",
        "LABEL_PAIR_UNKNOWN": "A participant or session is not in the dataset.",
        "LABEL_EDIT_INVALID": "Invalid label change.",
        "LABEL_FILES_INVALID": "The label files of the dataset are not valid.",
        "LABEL_FILES_IO": "The label files of the dataset could not be read or written.",
        "LABELS_NO_DATASET": "The dataset was not found or has no participants.",
        "LABELS_DISCARDED": "{count} changes not applied were discarded.",
        "LABEL_CORRECTIONS_INVALID": (
            "The corrections file is not valid: it needs the columns participant_id, session_id and label, "
            "without repeated rows."
        ),
        "CORRECTIONS_UNREADABLE": "The corrections file could not be read (permissions or not a file).",
        "BATCH_CLASS": "Class:",
        "ASSIGN_SELECTION": "Assign to the selection",
        "ASSIGN_UNLABELED": "Assign to all unlabeled",
        "LOAD_CORRECTIONS": "Load corrections (TSV file)…",
        "FILTER": "Show:",
        "FILTER_all": "all",
        "FILTER_unlabeled": "unlabeled",
        "FILTER_defect": "with a defect",
        "NOTHING_SELECTED": "Select one or more rows (Ctrl or Shift for several).",
        "NOTHING_UNLABELED": "No rows without a class.",
        "CONFIRM_TITLE": "Confirm",
        "CONFIRM_ASSIGN_UNLABELED": "Give the class \"{label}\" to the {count} rows without a class?",
        "ASSIGNED": "Class given to {count} rows. Press \"Apply\" to save it.",
        "CORRECTIONS_LOADED": "Corrections loaded as pending changes: {count}. Press \"Apply\".",
        "ASSIGN_LABEL_SELECTION": "Assign label to the selection",
        "MAPPING_ASSIGNED": "Label set for the studies of {count} series. Press \"Preview\" to check it.",
        "LABELS_EDITS_PENDING": "Apply or discard the changes before finalizing.",
        "LABELS_ERROR": "Label error ({error_type}).",
        # step 6: exports and report
        "ML_EXPORTS": "Files to train models (index and splits by participant)",
        "WRITE_ML": "Create the training files",
        "REGENERATE_ML": "Create another set in a new folder",
        "ML_WRITTEN_IN": "Training files created in \"{folder}\": {files}.",
        "ML_REGENERATE_HELP": (
            "Running creates the training files with the standard values (70/15/15, seed 0). Here you can "
            "create another set with other ratios or seed. It is saved in a new folder next to the dataset."
        ),
        "ML_DIR_NOT_EMPTY": "The folder for the training files already has content. Choose another one.",
        "ML_DIR_INSIDE_DATASET": "The folder for the training files must be outside the dataset.",
        "ML_DIR_OTHER_DRIVE": "The folder for the training files must be on the same drive as the dataset.",
        "REPORT": "Dataset report (JSON, Markdown, XML and Excel)",
        "REPORT_DIR": "Report folder (new or empty)",
        "WRITE_REPORT": "Write report",
        "OPEN_FOLDER": "Open the output folder",
        "TASK_STARTED": "In progress.",
        "ML_PRESENT": "The training files are already created.",
        "ML_ABSENT": "The training files are not created yet.",
        "REPORT_WRITTEN": "Report created: {files} files.",
        "FILE_NAME": "  {name}",
        "REPORT_WARNING": "Report warning {warning}: {count}.",
        "REPORT_WARNING_UNREADABLE_FILES": "Warning UNREADABLE_FILES: {count} dataset files could not be read.",
        "REPORT_WARNING_LABELS_UNREADABLE": "Warning LABELS_UNREADABLE: the labels could not be read.",
        "REPORT_WARNING_MANIFEST_UNREADABLE": "Warning MANIFEST_UNREADABLE: the run record could not be read.",
        "REPORT_DIR_REQUIRED": "Choose the report folder.",
        "REPORT_DIR_NOT_EMPTY": "The report folder has content; choose a new or empty one.",
        "REPORT_INSIDE_DATASET": "The report folder must be outside the dataset.",
        "REPORT_IO": "The report could not be written.",
        "REPORT_NO_STUDIES": "The dataset has no readable studies: no report.",
        "ML_EXPORTS_EXIST": "The training files already exist. They are not overwritten.",
        "ML_LABELS_NOT_FINALIZED": (
            "The labels are not closed: close them in the previous step before creating the training files."
        ),
        "DATASET_NOT_FOUND": "The dataset was not found.",
        "DATASET_LAYOUT_INVALID": "The dataset has files outside its structure (were they added by hand?).",
        "DATASET_NO_IMAGES": "The dataset has no images or participants to split.",
        "EXPORT_ERROR": "The files or the report could not be created ({error_type}).",
        # fixed service messages (``FIXED_MESSAGES``)
        "INPUT_NOT_FOUND": "The input folder was not found.",
        "CONFIG_NOT_FOUND": "The configuration file was not found.",
        "CORRECTIONS_NEED_CLASSES": "Label corrections need classes.",
        "CORRECTIONS_NOT_FOUND": "The corrections file was not found.",
        "INVALID_CLASSES": (
            "Invalid classes. Use only letters and digits, without repeats. The description goes after \"=\"."
        ),
        "INVALID_FORMAT": "Invalid input format.",
        "INVALID_MAPPING": "Invalid mapping table.",
        "INVALID_RATIOS": "Invalid ratios: three non-negative numbers that sum to 1.",
        "INVALID_CONFIG": "Invalid configuration ({error_type}).",
        "MAPPING_NOT_FOUND": "The mapping table was not found.",
        "MAPPING_PATHS_NOT_FOUND": "Table paths that do not exist in the input: {count}.",
        "MAPPING_LABEL_CONFLICT": "The table gives different labels to the same participant and session.",
        "MAPPING_SESSION_MIX": "The table leaves a participant both with and without a session.",
        "MAPPING_STUDY_SPLIT": (
            "The table gives a study more than one participant or session; use a row with the study folder."
        ),
        "MAPPING_PAIR_REPEATED": "The table gives the same participant and session to more than one study.",
        "MAPPING_LABEL_UNKNOWN": "A label of the table is not one of the classes.",
        "MAPPING_LABELS_NEED_CLASSES": "The table labels need classes.",
        "NO_MAPPED_SERIES": (
            "No series has a known suffix. Load a table file with the suffix of each series and press "
            "\"Preview\" again."
        ),
        "NO_INPUT_STUDIES": "There are no valid studies in the input.",
        "OUTPUT_INSIDE_INPUT": "The output folder must be outside the input.",
        "PIPELINE_WITHOUT_ANONYMIZE": "The pipeline must include the anonymize step.",
    },
}


# The severity of a message, for its color, icon and prefix («Error:», «Aviso:», «Listo:»). Codes not listed
# are errors: the failures and validation codes.
OK_CODES = frozenset({
    "INPUT_OK", "CONFIG_OK", "DISK_SPACE_OK", "PREVIEW_OK", "MAPPING_LOADED", "MAPPING_SAVED", "MAPPING_ASSIGNED",
    "LABELS_APPLIED", "ASSIGNED", "CORRECTIONS_LOADED", "ML_WRITTEN_IN", "REPORT_WRITTEN", "RUN_DONE", "SUMMARY_DONE", "RUN_CLEAN",
})
INFO_CODES = frozenset({
    "CHECKING_DISK_SPACE", "PREVIEW_RUNNING", "EDIT_PENDING", "TASK_STARTED", "NO_LABELS", "NOTHING_UNLABELED",
    "RUN_RUNNING", "LABELS_OPEN", "LABELS_CLOSED", "ML_PRESENT", "ML_ABSENT", "FILE_NAME",
})
WARNING_CODES = frozenset({
    "LOW_DISK_SPACE", "LABELS_DISCARDED", "LABELS_FOREIGN", "OUTPUT_NOT_EMPTY", "REPORT_WARNING", "LABELS_UNAPPLIED",
    "LABELS_FINALIZED", "LABELS_EDITS_PENDING", "TASK_RUNNING", "NOTHING_SELECTED",  # the action was not done
})


def severity(code: str | None) -> str:
    """``ok``, ``info``, ``warning`` or ``error`` for message *code* (``None`` = no message: ``info``)."""
    if code is None or code in INFO_CODES:
        return "info"
    if code in OK_CODES:
        return "ok"
    if code in WARNING_CODES or code.startswith(("WARN_", "REPORT_WARNING_")):
        return "warning"
    return "error"


def text(code: str, language: str = DEFAULT_LANGUAGE, **values: object) -> str:
    """The text of *code* in *language*, filled with *values* (counts, stage or type names only)."""
    return CATALOG[language][code].format(**values)


# Fixed messages of ``InvalidBuildInput`` (English, in the services) -> code. The message is only looked
# up here, never shown.
FIXED_MESSAGES = {
    "Dataset directory not found.": "INPUT_NOT_FOUND",
    "Config file not found.": "CONFIG_NOT_FOUND",
    "--corrections needs --classes.": "CORRECTIONS_NEED_CLASSES",
    "Corrections file not found.": "CORRECTIONS_NOT_FOUND",
    "Invalid --classes.": "INVALID_CLASSES",
    "Invalid --format.": "INVALID_FORMAT",
    "Invalid --mapping.": "INVALID_MAPPING",
    "Invalid --ratios.": "INVALID_RATIOS",
    "Mapping file not found.": "MAPPING_NOT_FOUND",
    "Mapping assigns different labels to the same participant/session.": "MAPPING_LABEL_CONFLICT",
    "Mapping gives a participant both sessions and no session.": "MAPPING_SESSION_MIX",
    "Mapping gives one study more than one participant or session.": "MAPPING_STUDY_SPLIT",
    "Mapping gives the same participant/session to more than one study.": "MAPPING_PAIR_REPEATED",
    "Mapping label is not one of --classes.": "MAPPING_LABEL_UNKNOWN",
    "Mapping labels need --classes.": "MAPPING_LABELS_NEED_CLASSES",
    "No input series could be mapped to a BIDS suffix.": "NO_MAPPED_SERIES",
    "No valid input studies were found.": "NO_INPUT_STUDIES",
    "Output directory must be outside the dataset directory.": "OUTPUT_INSIDE_INPUT",
    "The pipeline must include the anonymize step.": "PIPELINE_WITHOUT_ANONYMIZE",
    "Several series share this folder.": "SHARED_SERIES_FOLDER",
    "The study folder also holds other studies.": "SHARED_STUDY_FOLDER",
}
_INVALID_CONFIG = re.compile(r"Invalid config: (\w+)")
_MAPPING_PATHS = re.compile(r"Mapping paths not found in the input: (\d+)\.")


def invalid_input(error: Exception) -> tuple[str, dict[str, object]]:
    """The code and values of an ``InvalidBuildInput`` (only type names and counts)."""
    message = str(error)
    if message in FIXED_MESSAGES:
        return FIXED_MESSAGES[message], {}
    if match := _INVALID_CONFIG.fullmatch(message):
        return "INVALID_CONFIG", {"error_type": match[1]}
    if match := _MAPPING_PATHS.fullmatch(message):
        return "MAPPING_PATHS_NOT_FOUND", {"count": int(match[1])}
    return "INVALID_INPUT", {"error_type": type(error).__name__}


# Fixed messages of the label services (``labels``, ``labels_table`` and the label files) -> code.
LABEL_MESSAGES = {
    "Label classes file not found.": "NO_LABELS",
    "Label table not found.": "LABEL_TABLE_NOT_FOUND",
    "Labels are finalized.": "LABELS_FINALIZED",
    "Labels are already finalized.": "LABELS_FINALIZED",
    "Labels are not finalized.": "LABELS_NOT_FINALIZED",
    "Labels are incomplete or invalid.": "LABELS_INCOMPLETE",
    "Label table must be fixed by hand before corrections.": "LABELS_FIX_BY_HAND",
    "Label table has an unknown class.": "LABEL_UNKNOWN_CLASS",
    "Correction targets a participant/session not in the dataset.": "LABEL_PAIR_UNKNOWN",
    "Label edits have an invalid participant or session id.": "LABEL_EDIT_INVALID",
    "Label edits have an invalid class.": "LABEL_EDIT_INVALID",
    "Label table is missing required columns.": "LABEL_FILES_INVALID",
    "Label table has a malformed row.": "LABEL_FILES_INVALID",
    "Label table is empty.": "LABEL_FILES_INVALID",
    "Label table is not valid UTF-8.": "LABEL_FILES_INVALID",
    "Label classes file is invalid.": "LABEL_FILES_INVALID",
    "Label classes are invalid.": "LABEL_FILES_INVALID",
    "Label table has a duplicate participant/session.": "LABEL_FILES_INVALID",
    "Label table has an invalid participant or session id.": "LABEL_FILES_INVALID",
    "Label table could not be read.": "LABEL_FILES_IO",
    "Label table could not be written.": "LABEL_FILES_IO",
    "Label classes file could not be read.": "LABEL_FILES_IO",
    "Final labels file could not be written.": "LABEL_FILES_IO",
    "Final labels file could not be removed.": "LABEL_FILES_IO",
    "Label changes could not be written.": "LABEL_FILES_IO",
    "Dataset has no participants.": "LABELS_NO_DATASET",
    "Dataset directory not found.": "LABELS_NO_DATASET",
    "Dataset path is not a directory.": "LABELS_NO_DATASET",
    "Corrections file not found.": "CORRECTIONS_NOT_FOUND",
    "Corrections file is invalid.": "LABEL_CORRECTIONS_INVALID",
    "Corrections file could not be read.": "CORRECTIONS_UNREADABLE",
    "Corrections have a duplicate participant/session.": "LABEL_CORRECTIONS_INVALID",
}
# Fixed messages of the label services that the GUI never triggers (corrections files, templates).
LABEL_MESSAGES_NOT_REACHABLE = ("Label table already exists.",)


def label_error(error: Exception) -> tuple[str, dict[str, object]]:
    """The code and values of an error of the label services (only its type name besides the code)."""
    code = LABEL_MESSAGES.get(str(error)) if isinstance(error, (ValueError, OSError)) else None
    return (code, {}) if code else ("LABELS_ERROR", {"error_type": type(error).__name__})


# Fixed messages of the exports step (``write_ml_exports``, ``report_dataset``, ``dataset_outputs`` and the
# files they call) -> code. Label errors of ``write_ml_exports`` fall back to ``LABEL_MESSAGES``.
EXPORT_MESSAGES = {
    "Dataset directory not found.": "DATASET_NOT_FOUND",
    "Dataset directory does not exist.": "DATASET_NOT_FOUND",
    "Dataset path is not a directory.": "DATASET_NOT_FOUND",
    "Labels are not finalized.": "ML_LABELS_NOT_FINALIZED",
    "Report file already exists.": "REPORT_DIR_NOT_EMPTY",
    "Report directory is not empty.": "REPORT_DIR_NOT_EMPTY",
    "Report directory must be outside the dataset.": "REPORT_INSIDE_DATASET",
    "Report file could not be written.": "REPORT_IO",
    "No valid BIDS studies were found.": "REPORT_NO_STUDIES",
    "Dataset contains a file outside the BIDS layout.": "DATASET_LAYOUT_INVALID",
    "No dataset images were found.": "DATASET_NO_IMAGES",
    "No participants to split.": "DATASET_NO_IMAGES",
    "Split ratios must be three non-negative numbers that sum to 1.": "INVALID_RATIOS",
    "Split seed must be an integer.": "INVALID_SEED",
    "Dataset file already exists.": "ML_EXPORTS_EXIST",
    "ML export directory is not empty.": "ML_DIR_NOT_EMPTY",
    "ML export directory must be outside the dataset.": "ML_DIR_INSIDE_DATASET",
    "Output directory must be on the same drive as the dataset.": "ML_DIR_OTHER_DRIVE",
}
# Fixed messages of those files that the exports step never triggers.
EXPORT_MESSAGES_NOT_REACHABLE = ("Output directory must be outside the input directory.",)


def export_error(error: Exception) -> tuple[str, dict[str, object]]:
    """The code and values of an error of the exports step (only its type name besides the code)."""
    if isinstance(error, (ValueError, OSError)):
        if code := EXPORT_MESSAGES.get(str(error)) or LABEL_MESSAGES.get(str(error)):
            return code, {}
    return "EXPORT_ERROR", {"error_type": type(error).__name__}
