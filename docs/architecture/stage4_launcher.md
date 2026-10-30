# Lanzador de la etapa 4 (`scripts/run_stage4_dataset.py`)

> Este script es un envoltorio fino que quedó superado por `mri-dataset dataset build` (ver `docs/user_manual/cli.md`). Se conserva como verificación manual de extremo a extremo.

Verificación manual de extremo a extremo: entrada BIDS → pipeline de la etapa 3 → dataset BIDS,
etiquetas, exportaciones para ML/DL y reporte. Solo llama servicios de `application/`.

```powershell
$env:MRI_ANON_KEY = "<secreto de al menos 32 caracteres>"
python scripts/run_stage4_dataset.py --output-dir E:/mri/stage4
python scripts/run_stage4_dataset.py <dataset_root> --output-dir E:/mri/stage4 `
    --classes AD=Alzheimer CN=Control --corrections E:/mri/labels_fix.tsv --ratios 0.7 0.15 0.15 --seed 0
```

## Argumentos

| Argumento | Defecto | Qué hace |
|---|---|---|
| `dataset_root` | `data/raw/bids_test_studies` | BIDS de entrada, leído con `BIDSBatchReader(lazy=True)` |
| `--output-dir` | obligatorio | Directorio **nuevo**; si ya existe, código 1. Si la salida estimada (el tamaño de la entrada) alcanza el 90 % del espacio libre del disco de salida sale `WARNING INSUFFICIENT_DISK_SPACE` (no bloquea) |
| `--config` | `config/stage3_bids.yaml` | Configuración de la corrida (pasos del pipeline). **Debe incluir el paso `anonymize`**: si no, «The pipeline must include the anonymize step.» y código 2 antes de crear nada |
| `--classes NAME[=DESCRIPCIÓN] ...` | — | Clases de las etiquetas; escribe la plantilla (`write_label_template`, todas las sesiones sin etiquetar) |
| `--corrections` | — | TSV con las columnas de `labels.tsv`; se aplica con `apply_label_corrections`. Exige `--classes` |
| `--ratios TRAIN VAL TEST` | `0.7 0.15 0.15` | Proporciones de las particiones |
| `--seed` | `0` | Semilla de las particiones |
| `--allow-unfinalized` | no | Escribe las exportaciones para ML aunque las etiquetas estén incompletas (`write_ml_exports(..., allow_unfinalized=True)`) |

Los ids del dataset son seudónimos porque el lanzador exige el paso `anonymize` (HMAC con `MRI_ANON_KEY`); son deterministas para
la misma clave, así que un archivo de correcciones se prepara con el `labels.tsv` de una corrida previa
hecha con la misma clave.

## Flujo

1. `export_dataset(..., pipeline=pipeline_from_config(config), config=config, source_dir=dataset_root)`
   → `<output-dir>/dataset` (con `code/run_manifest.json`).
2. Con `--classes`: `write_label_template`; con `--corrections`: `apply_label_corrections`. Sin ellos
   la consola dice qué se omitió. Después, `review_labels`: si está completa se cierran con
   `finalize_labels` (`write_ml_exports` exige etiquetas cerradas); si no, se
   imprime `WARNING LABELS_INCOMPLETE: {código: conteo}` (`UNLABELED`, `UNKNOWN_CLASS`, `DUPLICATED`,
   `MISSING`, `NOT_IN_DATASET`, `INVALID_IDS`) y las etiquetas quedan abiertas.
3. `write_ml_exports(dataset, ratios, seed, allow_unfinalized=...)` (`dataset_index.csv`,
   `datalist.json`, `splits.tsv`, `splits.json`). Con etiquetas incompletas y sin
   `--allow-unfinalized` se **omite** (no es un error: código 0) y se dice en la consola. Sin
   `--classes` no hay `labels.tsv` y las particiones no se estratifican.
4. `report_dataset(dataset, <output-dir>/report)` (`dataset_report.{json,md,xml,xlsx}`). Se escribe
   también cuando se omitieron las exportaciones para ML: muestra las etiquetas que faltan.

Los argumentos (`--classes`, `--ratios`, archivos) se validan **antes** de crear nada. Un estudio o una
serie que falla se reporta por `on_error` (solo su tipo en la consola) y el lote sigue (RF16); un fallo de
una etapa entera la detiene: `Run failed at <export|labels|ml exports|report>: <Tipo>`. Ese fallo deja
salidas parciales en `--output-dir` y la corrida siguiente con el mismo directorio termina con código 1
(«Output directory already exists»): **borrar `--output-dir` antes de reintentar**. `--output-dir` dentro
de `dataset_root` (o igual) se rechaza antes de crear nada, con código 2.

## Conteos de la consola

Cada `on_error` se cuenta aparte y por tipo de excepción:

| Línea | Qué cuenta |
|---|---|
| `errors: n` (tras exportar) y `Errors by type` | Estudios o series que no entraron al dataset: fallos de un paso del pipeline o de escritura (`DatasetReport.errors`; las dos cifras coinciden) |
| `Input files skipped by the reader` | Archivos de la entrada que el lector omite (no NIfTI legibles: punteros de git-annex, archivos truncados); no son errores de exportación |
| `Report read errors` | Archivos del dataset ya escrito que el reporte no pudo leer |

`--classes` con un nombre repetido (`A=uno A=dos`) se rechaza como `Invalid --classes.` (código 2).

## Códigos de salida

| Código | Caso |
|---|---|
| 0 | Corrida completa |
| 1 | `--output-dir` ya existe, o falla una etapa |
| 2 | Falta `MRI_ANON_KEY`, argumentos inválidos, `--output-dir` dentro de la entrada, dataset o configuración inexistentes o inválidos, pipeline sin `anonymize` |

La consola muestra solo textos fijos, conteos y tipos de excepción: nunca rutas, ids ni mensajes.
Pruebas: `tests/unit/test_run_stage4_dataset.py`.
