# Configuración

Cargador: `mri_dataset_tool.infrastructure.config.loader.load_config`. Lee YAML con `yaml.safe_load`
(PyYAML, nunca `yaml.load`) y devuelve un `dict` de tipos básicos.

```python
load_config(
    run_config: Path | None = None,
    *,
    environment: str | None = None,
    config_dir: Path = Path("config"),
) -> dict[str, Any]
```

## Precedencia

De menor a mayor, clave por clave:

1. `config_dir/default.yaml` (obligatorio).
2. `config_dir/<environment>.yaml`, solo si se pasa `environment` (p. ej. `"development"`).
3. `run_config`, el archivo de la corrida, si se pasa.

Los mapeos se fusionan de forma recursiva. Cualquier otro valor, **listas incluidas**, reemplaza
entero al de la capa inferior (las listas no se concatenan). Un archivo vacío no cambia nada.

## Esquema

Solo existen estas claves; cualquier otra lanza `ValueError`.

| Clave | Tipo | Defecto (`default.yaml`) | `development.yaml` |
|---|---|---|---|
| `logging.level` | nombre de nivel de `logging` (`DEBUG`, `INFO`, `WARNING`, ...) | `INFO` | `DEBUG` |
| `pipeline.steps` | lista de `{name: str, params: dict}` (`params` opcional) | `[]` | — |
| `report.path` | `str` o `null` | `data/output/run_manifest.json` | — |

- Cada elemento de `pipeline.steps` es lo que recibe `build_step(name, params)`
  (`application/pipeline/step.py`); los pasos corren en el orden de la lista.
- `report.path` se devuelve tal cual, sin resolver. Lo interpreta el manifiesto de corrida.

Cómo usa estos valores el pipeline: [pipeline.md](pipeline.md).

## Archivos de `config/`

| Archivo | Uso |
|---|---|
| `default.yaml` | Base obligatoria (tabla anterior). |
| `development.yaml` | Sobrescritura de desarrollo (`environment="development"`): `logging.level: DEBUG`. |
| `stage3_example.yaml` | Pipeline para NIfTI sueltos: validate → anonymize → reorient → resample (1 mm) → normalize. |
| `stage3_bids.yaml` | Pipeline para BIDS: igual, con `resample` a 1 mm para anatómicas y `fmap` y a 2 mm para `dwi`. Solo remuestrea las modalidades que lista; no sirve para NIfTI sueltos (su `modality` es `None`). Es la configuración por defecto de la GUI. |
| `example_run.yaml` | Archivo de corrida de `scripts/run_example_pipeline.py`. |

La CLI y la GUI exigen que el pipeline incluya el paso `anonymize` al construir un dataset.

Ejemplo de archivo de corrida:

```yaml
pipeline:
  steps:
    - name: some.step
      params: {factor: 2.0}
report:
  path: data/output/run-01.json
```

## Errores

Todos con mensaje fijo, sin rutas, nombres de clave ni contenido del archivo (RNF07):

- Archivo ausente: `FileNotFoundError` (`Default`/`Environment`/`Run configuration file not found.`).
- Archivo ilegible (p. ej. un directorio, sin permisos): `OSError("Configuration file could not be read.")`,
  sin causa encadenada (cita la ruta).
- YAML inválido, archivo no UTF-8 o con etiquetas no seguras (`!!python/...`):
  `ValueError("Invalid YAML configuration file.")`, sin causa encadenada (el error original cita el contenido).
- Raíz que no es un mapeo, clave desconocida o valor de tipo incorrecto: `ValueError`.

**Límite conocido:** una clave YAML repetida dentro del mismo mapeo no da error ni aviso.
Gana la última aparición, que es el comportamiento de PyYAML. Por ejemplo,
`pipeline: {steps: [], steps: [{name: validate}]}` ejecuta `validate`. El manifiesto registra la
configuración que se ejecutó realmente, así que conviene revisarlo cuando un archivo de corrida se edita a mano.

## Decisiones de diseño (etapa 2)

1. El entorno se elige con el parámetro explícito `environment`; no hay variable de entorno. Con
   `None` solo se aplican `default.yaml` y el archivo de corrida. Un entorno sin archivo lanza
   `FileNotFoundError`.
2. `pipeline.steps` es una lista de `{name, params}`; al fusionar, las listas se reemplazan enteras y
   los mapeos se fusionan clave por clave.
3. `config_dir` es `Path("config")` relativo al directorio actual: la línea de comandos se ejecuta desde la
   raíz del repositorio. La GUI no depende del directorio actual: usa `project_config_dir()`
   (`application/services/inputs.py`), que apunta a la carpeta `config/` del proyecto o, en el ejecutable
   portable de Windows, a la `config/` empaquetada junto al programa. Los valores por defecto son los de la tabla.
