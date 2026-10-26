"""GUI texts in Spanish (default) and English, by code (``docs/architecture/gui.md``).

The window shows only these texts, filled with counts, stage names or exception type names; never the
message of an exception, a path read from the data, an id, a UID or a header value.
"""

import re

LANGUAGES = ("es", "en")
DEFAULT_LANGUAGE = "es"

CATALOG: dict[str, dict[str, str]] = {
    "es": {
        "APP_TITLE": "MRI Dataset Tool: asistente",
        "MENU_LANGUAGE": "Idioma",
        "LANGUAGE_es": "Español",
        "LANGUAGE_en": "Inglés",
        "BACK": "< Atrás",
        "NEXT": "Siguiente >",
        "STEP_HEADER": "Paso {number} de {total}: {title}",
        "STEP_input": "Entrada",
        "STEP_config": "Configuración",
        "STEP_mapping": "Mapeo de series",
        "STEP_run": "Ejecución",
        "STEP_labels": "Etiquetas",
        "STEP_export": "Exportes y reporte",
        "STEP_PENDING": "Este paso aún no está disponible.",
        "TASK_RUNNING": "Hay una tarea en curso; espere a que termine.",
        "CLOSE_TITLE": "Tarea en curso",
        "CLOSE_WHILE_RUNNING": (
            "Hay una tarea en curso. Si cierra ahora, la tarea se corta y la salida queda incompleta: "
            "vacíe o borre la carpeta de salida antes de reintentar. ¿Cerrar de todos modos?"
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
        "KEY_DEFINED": "Clave de anonimización: definida en el entorno (MRI_ANON_KEY).",
        "KEY_GENERATED": (
            "Clave de anonimización: generada para esta sesión. Los seudónimos cambian cada vez que se abre el "
            "programa (vea el manual)."
        ),
        "INPUT_OK": "Entrada y salida válidas.",
        "CHECKING_DISK_SPACE": "Comprobando el espacio en disco…",
        "DISK_SPACE_OK": "Espacio en disco suficiente para la salida estimada.",
        "LOW_DISK_SPACE": (
            "Aviso: la salida estimada ({required} GiB) alcanza el 90 % del espacio libre del disco de salida "
            "({free} GiB). Considere otro disco; la ejecución no se bloquea."
        ),
        "INPUT_REQUIRED": "Elija la carpeta de entrada.",
        "OUTPUT_REQUIRED": "Elija la carpeta de salida.",
        "NEW_FOLDER": "Nombre de la carpeta nueva",
        "OUTPUT_NOT_EMPTY": (
            "La carpeta de salida tiene contenido y no se sobrescribe: escriba el nombre de una carpeta nueva que "
            "se creará dentro de ella."
        ),
        "INVALID_FOLDER_NAME": (
            "Nombre de carpeta no válido: un nombre simple, sin / \\ : * ? \" < > |, sin «..» y sin punto ni "
            "espacio al final."
        ),
        "FOLDER_NAME_EXISTS": "Ya existe una carpeta o un archivo con ese nombre; elija otro.",
        # step 2: configuration
        "CONFIG_FILE": "Archivo de configuración (preajuste o propio)",
        "MEMORY_TITLE": "Uso de memoria",
        "MEMORY_NOTICE": (
            "Antes de remuestrear (resample) o normalizar (normalize), la herramienta estima la memoria que "
            "necesita el volumen de salida y la compara con la RAM disponible en ese momento. Si no alcanza, el "
            "estudio se marca como fallido y el lote continúa con los demás. Puede forzar la ejecución con la "
            "casilla de abajo, que equivale al parámetro allow_insufficient_memory: true de los pasos resample y "
            "normalize del archivo de configuración; ese consentimiento queda registrado en el manifiesto de la "
            "corrida. Hágalo bajo su responsabilidad: si la memoria no alcanza, el equipo puede volverse muy lento "
            "por el uso de disco como memoria, otros programas pueden cerrarse, y el proceso puede terminar "
            "abruptamente sin guardar resultados (en Linux, el sistema puede finalizarlo). La comprobación es una "
            "estimación en un instante y no cubre la memoria de otros pasos ni de otros programas que se abran "
            "durante la ejecución. Volúmenes 4D grandes, como las difusiones, pueden necesitar varios GB. Además, "
            "resample rechaza cualquier salida de más de max_output_voxels vóxeles (por defecto 2**32, eje temporal "
            "incluido), aunque haya memoria; ese límite solo se cambia en el archivo de configuración."
        ),
        "ALLOW_MEMORY": "Permitir continuar aunque la memoria disponible no alcance (bajo mi responsabilidad)",
        "CLASSES": "Clases de etiqueta, una por línea: NOMBRE o NOMBRE=descripción (vacío = sin etiquetas)",
        "RATIOS": "Proporciones entrenamiento / validación / prueba",
        "SEED": "Semilla de las particiones",
        "CONFIG_OK": "Configuración válida. Pasos del pipeline:",
        "INVALID_SEED": "La semilla debe ser un número entero.",
        # step 3: mapping
        "PREVIEW": "Vista previa",
        "LOAD_MAPPING": "Cargar tabla…",
        "SAVE_MAPPING": "Guardar tabla…",
        "MAPPING_HELP": (
            "Doble clic en una celda de sufijo, participante, sesión o etiqueta para editarla (vacía = automático). "
            "El sufijo se aplica a la serie; participante, sesión y etiqueta a todo el estudio. Después pulse "
            "«Vista previa» para comprobar los cambios; sin vista previa válida no se puede seguir."
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
        "PREVIEW_RUNNING": "Leyendo cabeceras…",
        "PREVIEW_OK": "Series: {series}; omitidas: {skipped}; archivos omitidos por el lector: {files}.",
        "EDIT_PENDING": "Cambios sin comprobar: pulse «Vista previa».",
        "MAPPING_SAVED": "Tabla guardada.",
        "MAPPING_LOADED": "Tabla cargada: pulse «Vista previa».",
        "MAPPING_FILE_EXISTS": "El archivo ya existe; elija otro nombre.",
        "SHARED_SERIES_FOLDER": (
            "Varias series comparten esta carpeta: el sufijo no se puede fijar desde aquí (use un archivo de tabla)."
        ),
        "SHARED_STUDY_FOLDER": (
            "La carpeta del estudio contiene también otros estudios: edítelo con un archivo de tabla."
        ),
        # step 4: run
        "RUN": "Ejecutar",
        "RUN_HELP": (
            "Construye el dataset BIDS anonimizado, las etiquetas, los exportes para ML y el reporte en la carpeta de "
            "salida. La tarea no se puede cancelar; la ventana sigue respondiendo."
        ),
        "RUN_RUNNING": "Ejecutando…",
        "RUN_DONE": "Terminado.",
        "RUN_FAILED_HINT": "Vacíe o borre la carpeta de salida antes de reintentar.",
        "RUN_ERRORS": "Errores por tipo: {counts}.",
        "RUN_SKIPPED": "Archivos omitidos por el lector: {counts}.",
        "RUN_REPORT_ERRORS": "Errores de lectura del reporte: {counts}.",
        "NONE": "ninguno",
        "EV_export": "Exportando el dataset (pipeline)…",
        "EV_exported": "Estudios escritos: {studies}; series: {series}; participantes: {participants}; errores: {errors}.",
        "EV_labels_skipped": "Etiquetas: omitidas (sin clases).",
        "EV_label_template": "Plantilla de etiquetas escrita ({classes} clases).",
        "EV_mapping_labels_applied": "Etiquetas de la tabla aplicadas: {rows}.",
        "EV_corrections_skipped": "Correcciones de etiquetas: ninguna.",
        "EV_corrections_applied": "Correcciones de etiquetas aplicadas: {rows}.",
        "EV_labels_finalized": "Etiquetas cerradas ({labels} etiquetas).",
        "EV_ml_exports_skipped": "Exportes para ML: omitidos (etiquetas incompletas; complételas en el paso siguiente).",
        "EV_ml_exports": "Archivos de exportes para ML escritos: {files}.",
        "EV_report": "Archivos del reporte escritos: {files}.",
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
            "Doble clic en la clase de un par para cambiarla (vacía = sin etiqueta). «Aplicar» guarda los cambios "
            "(se registran en labels_changes.tsv); «Cerrar» exige todos los pares etiquetados y habilita los "
            "exportes; «Reabrir» permite volver a editar."
        ),
        "APPLY": "Aplicar",
        "FINALIZE": "Cerrar",
        "REOPEN": "Reabrir",
        "RELOAD": "Recargar",
        "COL_defect": "Defecto",
        "DEFECT_UNLABELED": "sin etiqueta",
        "DEFECT_UNKNOWN_CLASS": "clase desconocida",
        "DEFECT_DUPLICATED": "repetida en la tabla",
        "DEFECT_MISSING": "falta en la tabla",
        "LABELS_OPEN": "Etiquetas abiertas: {labeled} de {pairs} pares etiquetados.",
        "LABELS_CLOSED": "Etiquetas cerradas: {labeled} de {pairs} pares etiquetados.",
        "LABELS_FOREIGN": "Filas de labels.tsv ajenas al dataset: {foreign}; con ids no válidos: {invalid}.",
        "LABELS_PENDING": "Cambios sin aplicar: {count}.",
        "LABELS_APPLIED": "Cambios aplicados: {count}.",
        "NO_LABELS": "Este dataset no tiene etiquetas (no se dieron clases en el paso 2); puede seguir.",
        "LABEL_TABLE_NOT_FOUND": "No se encuentra labels.tsv en el dataset.",
        "LABELS_FINALIZED": "Las etiquetas están cerradas: reábralas para editarlas.",
        "LABELS_NOT_FINALIZED": "Las etiquetas no están cerradas.",
        "LABELS_INCOMPLETE": "No se puede cerrar: hay pares sin etiqueta o con defectos.",
        "LABELS_FIX_BY_HAND": (
            "labels.tsv tiene filas repetidas, ajenas o no válidas (editado a mano): corríjalo a mano antes de editar."
        ),
        "LABEL_UNKNOWN_CLASS": "Una clase no está en labels.json.",
        "LABEL_PAIR_UNKNOWN": "Un participante o sesión no está en el dataset.",
        "LABEL_EDIT_INVALID": "Cambio de etiqueta no válido.",
        "LABEL_FILES_INVALID": "labels.tsv o labels.json no son válidos.",
        "LABEL_FILES_IO": "No se pudieron leer o escribir los archivos de etiquetas del dataset.",
        "LABELS_NO_DATASET": "No se encuentra el dataset o no tiene participantes.",
        "LABELS_DISCARDED": "Se descartaron {count} cambios sin aplicar.",
        "LABELS_EDITS_PENDING": "Aplique o descarte los cambios antes de cerrar.",
        "LABELS_ERROR": "Error en las etiquetas ({error_type}).",
        # fixed service messages (``FIXED_MESSAGES``)
        "INPUT_NOT_FOUND": "No se encuentra la carpeta de entrada.",
        "CONFIG_NOT_FOUND": "No se encuentra el archivo de configuración.",
        "CORRECTIONS_NEED_CLASSES": "Las correcciones de etiquetas necesitan clases.",
        "CORRECTIONS_NOT_FOUND": "No se encuentra el archivo de correcciones.",
        "INVALID_CLASSES": "Clases no válidas (letras y números, sin repetir; la descripción tras «=»).",
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
        "NO_MAPPED_SERIES": "Ninguna serie de la entrada tiene un sufijo BIDS.",
        "NO_INPUT_STUDIES": "No hay estudios válidos en la entrada.",
        "OUTPUT_INSIDE_INPUT": "La carpeta de salida debe estar fuera de la entrada.",
        "PIPELINE_WITHOUT_ANONYMIZE": "El pipeline debe incluir el paso anonymize.",
    },
    "en": {
        "APP_TITLE": "MRI Dataset Tool: wizard",
        "MENU_LANGUAGE": "Language",
        "LANGUAGE_es": "Spanish",
        "LANGUAGE_en": "English",
        "BACK": "< Back",
        "NEXT": "Next >",
        "STEP_HEADER": "Step {number} of {total}: {title}",
        "STEP_input": "Input",
        "STEP_config": "Configuration",
        "STEP_mapping": "Series mapping",
        "STEP_run": "Run",
        "STEP_labels": "Labels",
        "STEP_export": "Exports and report",
        "STEP_PENDING": "This step is not available yet.",
        "TASK_RUNNING": "A task is running; wait for it to finish.",
        "CLOSE_TITLE": "Task running",
        "CLOSE_WHILE_RUNNING": (
            "A task is running. If you close now, the task stops and the output is left incomplete: "
            "empty or delete the output folder before retrying. Close anyway?"
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
        "KEY_DEFINED": "Anonymization key: defined in the environment (MRI_ANON_KEY).",
        "KEY_GENERATED": (
            "Anonymization key: generated for this session. The pseudonyms change each time the program is "
            "opened (see the manual)."
        ),
        "INPUT_OK": "Valid input and output.",
        "CHECKING_DISK_SPACE": "Checking the disk space…",
        "DISK_SPACE_OK": "Enough disk space for the estimated output.",
        "LOW_DISK_SPACE": (
            "Warning: the estimated output ({required} GiB) reaches 90 % of the free space of the output drive "
            "({free} GiB). Consider another drive; the run is not blocked."
        ),
        "INPUT_REQUIRED": "Choose the input folder.",
        "OUTPUT_REQUIRED": "Choose the output folder.",
        "NEW_FOLDER": "Name of the new folder",
        "OUTPUT_NOT_EMPTY": (
            "The output folder has content and is not overwritten: type the name of a new folder to create "
            "inside it."
        ),
        "INVALID_FOLDER_NAME": (
            "Invalid folder name: a plain name, without / \\ : * ? \" < > |, without \"..\" and without a "
            "trailing dot or space."
        ),
        "FOLDER_NAME_EXISTS": "A folder or file with that name already exists; choose another.",
        # step 2: configuration
        "CONFIG_FILE": "Configuration file (preset or your own)",
        "MEMORY_TITLE": "Memory use",
        "MEMORY_NOTICE": (
            "Before resampling (resample) or normalizing (normalize), the tool estimates the memory the output "
            "volume needs and compares it with the RAM available at that moment. If it is not enough, the study "
            "is marked as failed and the batch goes on with the others. You can force the run with the checkbox "
            "below, which is the same as the allow_insufficient_memory: true parameter of the resample and "
            "normalize steps in the configuration file; that consent is recorded in the run manifest. Do it at "
            "your own risk: if the memory is not enough, the computer may become very slow because the disk is "
            "used as memory, other programs may close, and the process may end abruptly without saving results "
            "(on Linux, the system may kill it). The check is an estimate at one moment and does not cover the "
            "memory of other steps or of other programs opened during the run. Large 4D volumes, such as "
            "diffusion series, may need several GB. Also, resample rejects any output larger than "
            "max_output_voxels voxels (2**32 by default, time axis included) even with enough memory; that limit "
            "is changed only in the configuration file."
        ),
        "ALLOW_MEMORY": "Allow the run to continue even if the available memory is not enough (at my own risk)",
        "CLASSES": "Label classes, one per line: NAME or NAME=description (empty = no labels)",
        "RATIOS": "Training / validation / test ratios",
        "SEED": "Split seed",
        "CONFIG_OK": "Valid configuration. Pipeline steps:",
        "INVALID_SEED": "The seed must be an integer.",
        # step 3: mapping
        "PREVIEW": "Preview",
        "LOAD_MAPPING": "Load table…",
        "SAVE_MAPPING": "Save table…",
        "MAPPING_HELP": (
            "Double-click a suffix, participant, session or label cell to edit it (empty = automatic). The suffix "
            "applies to the series; participant, session and label to the whole study. Then press \"Preview\" "
            "to check the changes; without a valid preview you cannot go on."
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
        "PREVIEW_RUNNING": "Reading headers…",
        "PREVIEW_OK": "Series: {series}; skipped: {skipped}; files skipped by the reader: {files}.",
        "EDIT_PENDING": "Unchecked changes: press \"Preview\".",
        "MAPPING_SAVED": "Table saved.",
        "MAPPING_LOADED": "Table loaded: press \"Preview\".",
        "MAPPING_FILE_EXISTS": "The file already exists; choose another name.",
        "SHARED_SERIES_FOLDER": (
            "Several series share this folder: the suffix cannot be set from here (use a table file)."
        ),
        "SHARED_STUDY_FOLDER": "The study folder also holds other studies: edit it with a table file.",
        # step 4: run
        "RUN": "Run",
        "RUN_HELP": (
            "Builds the anonymized BIDS dataset, the labels, the ML exports and the report in the output folder. "
            "The task cannot be cancelled; the window keeps responding."
        ),
        "RUN_RUNNING": "Running…",
        "RUN_DONE": "Done.",
        "RUN_FAILED_HINT": "Empty or delete the output folder before retrying.",
        "RUN_ERRORS": "Errors by type: {counts}.",
        "RUN_SKIPPED": "Input files skipped by the reader: {counts}.",
        "RUN_REPORT_ERRORS": "Report read errors: {counts}.",
        "NONE": "none",
        "EV_export": "Exporting the dataset (pipeline)…",
        "EV_exported": "Studies written: {studies}; series: {series}; participants: {participants}; errors: {errors}.",
        "EV_labels_skipped": "Labels: skipped (no classes).",
        "EV_label_template": "Label template written ({classes} classes).",
        "EV_mapping_labels_applied": "Table labels applied: {rows}.",
        "EV_corrections_skipped": "Label corrections: none.",
        "EV_corrections_applied": "Label corrections applied: {rows}.",
        "EV_labels_finalized": "Labels finalized ({labels} labels).",
        "EV_ml_exports_skipped": "ML exports: skipped (labels incomplete; complete them in the next step).",
        "EV_ml_exports": "ML export files written: {files}.",
        "EV_report": "Report files written: {files}.",
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
            "Double-click the class of a pair to change it (empty = unlabeled). \"Apply\" saves the changes (logged "
            "in labels_changes.tsv); \"Finalize\" needs every pair labeled and enables the exports; \"Reopen\" "
            "allows editing again."
        ),
        "APPLY": "Apply",
        "FINALIZE": "Finalize",
        "REOPEN": "Reopen",
        "RELOAD": "Reload",
        "COL_defect": "Defect",
        "DEFECT_UNLABELED": "unlabeled",
        "DEFECT_UNKNOWN_CLASS": "unknown class",
        "DEFECT_DUPLICATED": "repeated in the table",
        "DEFECT_MISSING": "missing from the table",
        "LABELS_OPEN": "Labels open: {labeled} of {pairs} pairs labeled.",
        "LABELS_CLOSED": "Labels finalized: {labeled} of {pairs} pairs labeled.",
        "LABELS_FOREIGN": "labels.tsv rows foreign to the dataset: {foreign}; with invalid ids: {invalid}.",
        "LABELS_PENDING": "Changes not applied: {count}.",
        "LABELS_APPLIED": "Changes applied: {count}.",
        "NO_LABELS": "This dataset has no labels (no classes were given in step 2); you can go on.",
        "LABEL_TABLE_NOT_FOUND": "labels.tsv was not found in the dataset.",
        "LABELS_FINALIZED": "The labels are finalized: reopen them to edit.",
        "LABELS_NOT_FINALIZED": "The labels are not finalized.",
        "LABELS_INCOMPLETE": "Cannot finalize: some pairs are unlabeled or have defects.",
        "LABELS_FIX_BY_HAND": (
            "labels.tsv has repeated, foreign or invalid rows (hand edited): fix it by hand before editing."
        ),
        "LABEL_UNKNOWN_CLASS": "A class is not in labels.json.",
        "LABEL_PAIR_UNKNOWN": "A participant or session is not in the dataset.",
        "LABEL_EDIT_INVALID": "Invalid label change.",
        "LABEL_FILES_INVALID": "labels.tsv or labels.json are not valid.",
        "LABEL_FILES_IO": "The label files of the dataset could not be read or written.",
        "LABELS_NO_DATASET": "The dataset was not found or has no participants.",
        "LABELS_DISCARDED": "{count} changes not applied were discarded.",
        "LABELS_EDITS_PENDING": "Apply or discard the changes before finalizing.",
        "LABELS_ERROR": "Label error ({error_type}).",
        # fixed service messages (``FIXED_MESSAGES``)
        "INPUT_NOT_FOUND": "The input folder was not found.",
        "CONFIG_NOT_FOUND": "The configuration file was not found.",
        "CORRECTIONS_NEED_CLASSES": "Label corrections need classes.",
        "CORRECTIONS_NOT_FOUND": "The corrections file was not found.",
        "INVALID_CLASSES": "Invalid classes (letters and digits, no repeats; the description after \"=\").",
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
        "NO_MAPPED_SERIES": "No input series has a BIDS suffix.",
        "NO_INPUT_STUDIES": "There are no valid studies in the input.",
        "OUTPUT_INSIDE_INPUT": "The output folder must be outside the input.",
        "PIPELINE_WITHOUT_ANONYMIZE": "The pipeline must include the anonymize step.",
    },
}


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
}
# Fixed messages of the label services that the GUI never triggers (corrections files, templates).
LABEL_MESSAGES_NOT_REACHABLE = (
    "Corrections file not found.", "Corrections have a duplicate participant/session.", "Label table already exists.",
)


def label_error(error: Exception) -> tuple[str, dict[str, object]]:
    """The code and values of an error of the label services (only its type name besides the code)."""
    code = LABEL_MESSAGES.get(str(error)) if isinstance(error, (ValueError, OSError)) else None
    return (code, {}) if code else ("LABELS_ERROR", {"error_type": type(error).__name__})
