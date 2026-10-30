# Decisiones de diseño y su justificación

Guía para sustentar el proyecto: por cada bloque, qué hace, por qué se diseñó así y qué alternativas se descartaron. El detalle técnico de cada módulo está en `docs/` (enlazado en cada sección).

## 1. Arquitectura en capas
- **Qué:** `domain` (modelos), `infrastructure` (formatos, procesamiento, dataset), `application` (servicios y pipeline) y `presentation` (CLI y GUI).
- **Por qué:** los modelos `MRIStudy`/`MRISeries` no dependen de `pydicom` ni `nibabel`; cualquier formato de entrada termina en ellos y cualquier escritor los consume. Se pueden cambiar lectores y escritores sin tocar el procesamiento.
- **Descartado:** funciones sueltas por formato (cada paso tendría que conocer DICOM y NIfTI) y lógica de negocio en la CLI.

## 2. Geometría canónica (RAS+, `affine` 4x4)
- **Qué:** toda serie con volumen lleva `shape`, `voxel_size`, `affine` y `orientation` coherentes.
- **Por qué:** DICOM (LPS) y NIfTI (RAS) usan convenciones distintas; un único contrato evita errores de orientación al convertir, reorientar y remuestrear.
- **Descartado:** conservar la geometría de cada formato y convertir al escribir (propenso a errores silenciosos).

## 3. Pipeline por pasos con manifiesto
- **Qué:** `validate → anonymize → reorient → resample → normalize`; cada paso es determinista, no muta su entrada y registra versión, parámetros y salidas. El runner procesa un estudio a la vez; un fallo se reporta y el lote sigue. (`docs/architecture/pipeline.md`)
- **Por qué:** reproducibilidad (RNF11), trazabilidad de cada transformación (RF15) y memoria acotada (RNF02).
- **Descartado:** un script monolítico y cargar todo el lote en memoria.

## 4. Carga perezosa y control de memoria
- **Qué:** los lectores pueden devolver un proxy del volumen; `resample` y `normalize` estiman la RAM antes de reservar y rechazan el estudio si no alcanza, salvo consentimiento explícito. (`docs/processing/`)
- **Por qué:** una difusión 4D de 144x144x78x140 ocupa unos 2 GB en `float64`; sin control, una corrida llenaba el disco o la RAM.
- **Descartado:** cargar siempre en `float64` y confiar en que quepa.

## 5. Anonimización
- **Qué:** lista blanca de metadatos (lo desconocido se descarta), seudónimos con HMAC-SHA256 y clave externa (`MRI_ANON_KEY`), fechas generalizadas, sin tabla de correspondencia. (`docs/anonymization/policy.md`)
- **Por qué:** una lista blanca falla de forma segura; los seudónimos deterministas permiten reproducir una corrida sin guardar el mapeo original.
- **Límites declarados:** no borra caras ni texto quemado en los píxeles; conserva cuasi-identificadores (año, rango de edad, sexo, modelo de escáner).
- **Descartado:** lista negra de etiquetas conocidas (deja pasar lo no previsto) y una tabla de correspondencia (es en sí un dato sensible).

## 6. Dataset en formato BIDS
- **Qué:** `sub-*/ses-*/{anat,dwi,fmap}` con NIfTI `float32`, sidecar JSON filtrado, `participants.tsv` con solo `participant_id`, `dataset_description.json` y el manifiesto de la corrida en `code/`. Sufijo repetido en una sesión → `run-<n>`. (`docs/dataset/structure.md`)
- **Por qué:** BIDS es el estándar de neuroimagen; las herramientas habituales lo leen sin conversión (RNF09).
- **Límites declarados:** `dwi` sin `.bval/.bvec` y `phasediff` sin `EchoTime1/2` (el validador oficial los marcará); `bold` no se escribe porque exige `task-`.
- **Descartado:** carpetas propias (obligan a escribir un lector por herramienta) y adivinar el sufijo por el texto de la descripción de serie.

## 7. Etiquetas con revisión, bitácora y cierre
- **Qué:** una clase por (participante, sesión), lista cerrada; `labels.tsv` + `labels.json`; correcciones todo o nada con bitácora `labels_changes.tsv`; el cierre (`labels_final.json`) guarda una huella SHA-256 de la tabla. (`docs/dataset/labels.md`)
- **Por qué:** RF12 pide revisar antes de finalizar; la huella detecta ediciones posteriores y la exportación para ML la exige.
- **Descartado:** editar `labels.tsv` a mano sin control (la edición manual sigue posible pero no queda registrada, y la huella lo delata al exportar).
- **Seguridad:** las clases no pueden empezar por `= + - @` para que abrir el TSV en Excel no ejecute fórmulas.

## 8. Particiones y archivos para ML/DL
- **Qué:** 70/15/15 por participante, estratificadas y deterministas (semilla registrada); `dataset_index.csv`, `datalist.json` (estilo MONAI) y `splits.*`. (`docs/dataset/export.md`)
- **Por qué:** partir por participante evita que sesiones de una misma persona queden en entrenamiento y prueba (fuga de datos).
- **Descartado:** partir por imagen (fuga) y exportar tensores (`.pt`/`.npy`): no abren en visores ni herramientas de neuroimagen, pierden el `affine` salvo con sidecars propios, y MONAI/TorchIO/nnU-Net ya cargan NIfTI. Se reabre solo si una medición muestra que leer `.nii.gz` es el cuello de botella.

## 9. Reporte estadístico
- **Qué:** resumen JSON, Markdown, XML y XLSX con las mismas cifras; se genera leyendo el dataset ya escrito. (`docs/dataset/report.md`)
- **Por qué:** el reporte describe lo que realmente se exporta, no lo que se pretendía exportar.
- **Seguridad:** el XLSX guarda todo texto como cadena (sin fórmulas ni macros) y el XML no usa datos como nombres de etiqueta.

## 10. Errores y privacidad como regla transversal
- **Qué:** mensajes de error fijos, sin rutas ni valores de cabecera; logs con tipos y contadores; escritura atómica (temporal + `os.replace`) sin sobrescribir; todo o nada en los archivos de nivel superior.
- **Por qué:** RNF07 y RNF06; una excepción o un log no debe filtrar datos de paciente ni dejar archivos a medias.
- **Verificación:** pruebas con datos personales plantados y barrido de todo el árbol de salida, nombres y logs; auditoría adversarial en `docs/testing/qa_etapa3.md` y `qa_etapa4.md`.

## 11. Línea de comandos
- **Qué:** `mri-dataset` (`argparse`) con un subcomando por caso de uso; cada comando valida, llama a un servicio y muestra conteos. La orquestación de los scripts se extrajo a `pipeline_run` y `dataset_build`, con eventos de estado y excepciones tipadas (`StageFailed`, `InvalidBuildInput`). (`docs/architecture/cli.md`)
- **Por qué:** sin lógica de negocio en la presentación, la futura GUI reutilizará los mismos servicios. Los códigos 0/1/2 se deciden por tipo de excepción, no comparando mensajes. Toda la validación ocurre antes de crear nada, así un error no deja salidas a medias.
- **Límites declarados:** la consola no muestra rutas (el usuario ya conoce las que pasó). Los errores de `argparse` repiten lo tecleado. Las rutas de la configuración son relativas al directorio actual. `--verify` es opcional porque duplica el tiempo.
- **Descartado:** duplicar la orquestación de los scripts en la CLI, hacer importable `scripts/` y añadir dependencias como `click` o `typer` (RNF12).

## 12. Interfaz gráfica
- **Qué:** asistente Tkinter de seis pasos (`mri-dataset-gui`) sobre los mismos servicios de la CLI, con tema propio (`ttk` estándar, sin dependencias nuevas), pantalla de bienvenida, indicador de actividad, edición de celdas con un clic, navegación por teclado y escalado de pantalla. (`docs/architecture/gui.md`, `docs/user_manual/gui.md`)
- **Por qué:** el controlador no usa Tk y la ventana solo pinta y delega; así la lógica se prueba sin pantalla y los mensajes, validaciones y salidas son los de la CLI. Los colores, fuentes y espacios salen de un solo módulo de tema, con el contraste calculado en una prueba. Tras «Aplicar», si todas las filas tienen etiqueta, la GUI ofrece finalizarlas en el momento, porque exigir un botón aparte no era intuitivo.
- **Límites declarados:** la escala de pantalla se lee al arrancar (hay que reabrir el programa para cambiarla). Las pruebas con foco real del sistema pueden fallar de forma intermitente si otro programa tiene el foco; las de escala heredan las fuentes de la raíz Tk anterior (`docs/testing/qa_etapa8.md`). Falta verificar Linux.
- **Descartado:** un marco de interfaz externo (dependencia nueva, RNF12) y mensajes con texto de excepciones (podrían filtrar rutas o datos).

## 13. Ejecutable portable de Windows
- **Qué:** la GUI se distribuye como carpeta `onedir` en un `.zip`, generada con `packaging/build_exe.py` (PyInstaller solo como herramienta de build, instalado a mano; no es dependencia del paquete). `project_config_dir()` lee los YAML de `sys._MEIPASS/config` cuando el programa está congelado.
- **Por qué:** `onefile` se autoextrae en `%TEMP%` (poco espacio en `C:`), arranca más lento y levanta más avisos de antivirus. Los metadatos de los paquetes viajan en el bundle para que el manifiesto registre versiones reales y no `unknown`, y con ellos las licencias de terceros.
- **Límites declarados:** solo Windows, sin firma de código (SmartScreen puede avisar), ruta de descompresión corta (límite de 260 caracteres), sin actualización automática; `build/` y `spec/` llevan rutas absolutas y no se distribuyen.
- **Descartado:** `onefile`, instalador MSI, ejecutable de la CLI y binario de Linux.

## Qué no cubre el proyecto (para declararlo con honestidad)
- Defacing y texto quemado en los píxeles.
- Verificación de la GUI en Linux y en pantallas reales de 125/150 % (las pruebas simulan la escala).
- Validación con `bids-validator` oficial sin avisos, y verificación en Linux.
- Medición de rendimiento formal (RNF01).
