# Arquitectura de la CLI (`presentation/cli/`)

La CLI es una capa de presentación delgada: parsea argumentos con `argparse` (stdlib), valida todo antes de crear
nada, llama a un servicio de `application/` y traduce el resultado a texto (conteos) y a un código de salida. No
contiene lógica de negocio. Manual de uso: `docs/user_manual/cli.md`.

## Estructura

```text
src/mri_dataset_tool/presentation/cli/
├── __init__.py
├── __main__.py        # python -m mri_dataset_tool.presentation.cli
├── main.py            # parser raíz, opciones globales, COMMANDS, main(argv=None) -> int
├── _common.py         # códigos de salida, salida a consola, helpers compartidos
└── commands/
    ├── inspect.py     # RF04: lectores + summarize_study
    ├── convert.py     # RF05: convert_dicom_to_nifti / convert_nifti_to_dicom
    ├── anonymize.py   # RF09: anonymize_dicom_tree
    ├── process.py     # RF06–RF09, RF15: services/pipeline_run.run_pipeline
    ├── labels.py      # RF11, RF12: services/labels
    └── dataset.py     # RF10, RF13, RF14: write_ml_exports, report_dataset, services/dataset_build
```

Puntos de entrada: `mri-dataset` (`[project.scripts]` en `pyproject.toml` →
`mri_dataset_tool.presentation.cli.main:main`) y `python -m mri_dataset_tool.presentation.cli`.

## Contrato de un módulo de comando

- `add_parser(subparsers)`: crea su subparser con `_common.add_command(subparsers, name, ...)` (ayuda en español:
  `uso:`, `argumentos`, `opciones`, `-h`), define sus argumentos y registra `parser.set_defaults(run=run)`. Los
  grupos (`convert`, `labels`, `dataset`) crean sub-subparsers con el mismo helper.
- `run(args) -> int`: valida, llama al servicio y devuelve 0/1/2.
- Se registra en `main.COMMANDS`. `main(argv)` construye el parser, aplica `--quiet`/`--verbose`
  (`configure_output`) y llama a `args.run(args)`. `--help`/`--version` devuelven 0 y los errores de `argparse`
  devuelven 2 (se captura su `SystemExit`), así las pruebas llaman `main([...])` y comprueban el entero.

## `_common.py`

| Nombre | Uso |
|---|---|
| `EXIT_OK`, `EXIT_FAILED`, `EXIT_USAGE` | 0, 1, 2 |
| `configure_output(quiet, verbose)` | nivel del logger raíz (por defecto WARNING; `--quiet` ERROR; `--verbose` DEBUG) y bandera de silencio. No usa `basicConfig(force=True)` para no quitar los handlers existentes (p. ej. `caplog`) |
| `status(msg)`, `progress(n, total, label)` | líneas de estado; `--quiet` las oculta |
| `error_counter(label, echo=True)` | `on_error` que cuenta por tipo de excepción e imprime solo el tipo; `echo=False` para `--json` |
| `format_counts(counter)` | `{'Tipo': n}` ordenado o `none` |
| `check_key()` | `load_key()` con mensaje fijo; nunca imprime la clave |
| `is_discouraged_location`, `warn_if_discouraged(*paths)` | WARNING fijo si una salida cae en `C:` o en el temporal |
| `is_inside(path, parent)`, `is_non_empty_dir(path)` | validación previa de rutas |
| `add_command`, `spanish_help`, `SpanishHelpFormatter` | ayuda en español |

## Validación y códigos de salida

Cada `run` valida con mensajes fijos en inglés (sin valores del usuario) **antes de crear nada**; las pruebas
comprueban que el árbol de `tmp_path` queda intacto en cada caso de error.

| Situación | Código |
|---|---|
| Argumentos inválidos (`argparse`), entrada inexistente o de tipo incorrecto, salida dentro de la entrada, salida que es un archivo, clave ausente, configuración inválida, `InvalidBuildInput` | 2 |
| Salida previa (`FileExistsError`, `previous_outputs_exist`, carpeta no vacía en `convert`, informe existente en `anonymize`) | 1 |
| Fallo de una etapa completa: `StageFailed` (`Run failed at <etapa>: <Tipo>`) o cualquier otra excepción del servicio (`Run failed: <Tipo>`, `Labels <acción> failed: <Tipo>`, ...) | 1 |
| Corrida terminada, aunque haya estudios fallidos reportados (RF16) | 0 |
| `process`: `--verify` no reproduce, o hay un paso que redacta las fuentes y el manifiesto tiene rutas | 1 |

La CLI no compara mensajes de excepción: decide por el tipo (`InvalidBuildInput`, `FileExistsError`,
`StageFailed`) o por su propia validación previa. Los mensajes de los servicios no se imprimen (salvo los de
`InvalidBuildInput` y el `FileExistsError` de `check_build_args`, que son texto fijo pensado para mostrarse).

## Servicios de orquestación (`application/services/`)

La lógica que antes vivía en `scripts/run_stage3_pipeline.py`, `run_stage3_bids_pipeline.py` y
`run_stage4_dataset.py` se extrajo a dos servicios que no imprimen ni parsean argumentos; los scripts quedaron
como envoltorios con el mismo comportamiento, mensajes y códigos (sus pruebas no cambiaron).

- `pipeline_run.py`: `read_studies(fmt, root, on_error)` (NIfTI/BIDS, `lazy=True`), `process_studies(...)`
  (escribe cada serie en `float32` con `output_name`), `previous_outputs_exist(out, manifest)` y
  `run_pipeline(pipeline, config, fmt, root, out, manifest, on_error, *, verify, on_replay_error, on_status)
  -> PipelineRunResult(reports, files_written, no_sources, reproduced)`. Etapas `process`, `manifest`, `verify`.
- `dataset_build.py`: `parse_classes`, `check_classes`, `check_build_args(...)` (→ `InvalidBuildInput` o
  `FileExistsError`), `load_build_pipeline(config, config_dir)` (exige `anonymize`), `label_defects(review)` y
  `build_dataset(...) -> DatasetBuildResult(exported, review, ml_files, report_files)`. Etapas `export`, `labels`,
  `ml exports`, `report`.
- Ambos informan el progreso con `on_status(evento, conteos)` (solo nombres y enteros) y un fallo de etapa con
  `StageFailed(stage, error)`: atributos `stage` y `error_type`, mensaje fijo `Stage failed: <etapa>.` y la causa
  encadenada (su traceback puede retener el estudio; la CLI termina enseguida).

## Política de consola (RNF07)

- Consola, logs y `--json`: solo conteos, tipos de excepción, códigos fijos (`UNLABELED`, ...) y metadatos de lista
  blanca (`summarize_study`). Nunca rutas, mensajes de excepción, UIDs, ids (ni siquiera seudonimizados) ni valores
  de cabecera.
- Las pruebas (`tests/unit/test_cli_*.py`) plantan identificadores (nombres, ids `sub-`/`ses-`, UIDs, valores de
  sidecar, la clave) y barren stdout, stderr, los logs en DEBUG, el `--json` y el manifiesto.
- Excepción aceptada: los errores de `argparse` repiten el argumento que tecleó el usuario.

## Memoria (RNF02)

Los comandos conservan el streaming de los servicios (un estudio vivo a la vez; `lazy=True`).
`allow_insufficient_memory` y `max_output_voxels` solo se cambian en la configuración: no hay opción de CLI.
`test_service_pipeline_run.py` comprueba con `weakref` que cada estudio se libera antes de leer el siguiente.

## Decisiones de C0–C6

1. `argparse` (stdlib), ayuda en español, mensajes fijos en inglés; los errores propios de `argparse` quedan en inglés.
2. Nivel de log por `--quiet`/`--verbose` (excluyentes); `logging.level` de la configuración no se usa en la CLI.
   Los resúmenes finales y los `WARNING` se imprimen también con `--quiet`.
3. `--version` usa `collect_versions()` del manifiesto.
4. `inspect`: un fallo de `summarize_study` (p. ej. `.nii.gz` truncado leído en lazy) se cuenta y el lote sigue;
   DICOM solo cabeceras.
5. `convert`: `OUT` existente y no vacía → 1 antes de convertir (más estricto que el servicio, para no mezclar salidas).
6. Entrada válida sin estudios → 1 (`Run failed...`), no 2: distinguirlo exigiría comparar el mensaje del lector.
7. `process`: `--verify` opcional (los scripts siempre reproducen); rutas relativas (`config/default.yaml`,
   `report.path`) desde el directorio actual; sin paso que redacte fuentes, que el manifiesto tenga rutas es lo
   esperado (aviso fijo, código 0); `--format dicom` → mensaje fijo que remite a `convert` y código 2.
8. `labels`: revisión solo por archivos; `review` muestra conteos, no ids; errores del servicio solo con el tipo.
9. `dataset build`: `IN` y `--config` obligatorios (sin los defectos del lanzador de la etapa 4). Sin `--classes`
   escribe los exportes para ML sin etiquetas (comportamiento de `build_dataset`), así que etiquetar después exige
   `build --classes` (etiquetas incompletas, exportes omitidos) → `labels apply`/`finalize` → `dataset export-ml`.
