# Pipeline de procesamiento

Núcleo de la etapa 2: contrato de paso, runner por lotes y manifiesto de corrida. Cubre RF15
(registrar cada transformación), RF16 (informar errores y continuar), RNF02 (un estudio en memoria a
la vez), RNF06 y RNF11 (reproducibilidad). La configuración está en [config.md](config.md).

| Módulo | Contenido |
|---|---|
| `domain/models/transformation.py` | `StepRecord`, `StudyReport` (dataclasses puras, solo stdlib) |
| `application/pipeline/step.py` | Protocol `ProcessingStep`, `STEP_REGISTRY`, `register_step`, `build_step` |
| `application/pipeline/runner.py` | `Pipeline(steps).run(...)` |
| `application/pipeline/manifest.py` | `RunManifest`, `collect_versions`, `pipeline_from_config`, `pipeline_from_manifest` |

## Contrato de paso

```python
class ProcessingStep(Protocol):
    name: str              # nombre con el que se registró (propiedad de solo lectura)
    version: str           # súbela cuando cambie el resultado del paso
    params: dict[str, Any] # JSON puro; factory(**params) reconstruye el paso
    def apply(self, study: MRIStudy) -> MRIStudy: ...
```

- `apply` **no muta** la entrada: construye el resultado con `dataclasses.replace`.
- Es determinista dado `params`; sin estado oculto.
- `params` debe ser **JSON puro**: `dict`, `list`, `str`, `int`, `float`, `bool`, `None`. Una tupla
  vuelve del JSON como lista y rompe `from_json(to_json(m)) == m` y la reproducción.
- **Salidas calculadas (opcional, RF15):** un paso que calcula valores a registrar (media, forma
  resultante, orientación de origen...) define además
  `apply_with_outputs(study) -> tuple[MRIStudy, dict]`, y `apply` devuelve su primer elemento. El
  runner usa `apply_with_outputs` si existe y guarda el dict en `StepRecord.outputs`; si no, llama a
  `apply` y `outputs` queda `{}`. Convención obligatoria para los pasos de la etapa 3:
  `{"series": [{"index": i, ...}]}`, con `i` la posición en `study.series`, solo para las series
  transformadas. Solo tipos básicos JSON (convierte `np.float32`/`np.ndarray` con `float`/`tolist`);
  nunca PHI, rutas, UIDs ni mensajes.
  Las claves deben ser `str` (`json.dumps` convierte `{0: x}` en `{"0": x}` en silencio) y `apply` debe delegar en `apply_with_outputs(study)[0]`.
- **Rutas de origen fuera del registro (opcional, RNF07):** un paso cuya salida no debe poder
  vincularse con su entrada (p. ej. `anonymize`) declara `redacts_sources: ClassVar[bool] = True` en
  su clase. No es un parámetro, así que la configuración no puede desactivarlo. Ver «Runner».
- **Pasos incorporados:** viven en `application/pipeline/steps/`; su `__init__.py` importa cada módulo
  y `manifest.py` importa el paquete, así que `pipeline_from_config`/`pipeline_from_manifest` los
  encuentran por nombre sin importarlos a mano.
- `@register_step("nombre")` registra la factory (normalmente la clase). Un nombre repetido lanza
  `ValueError`. `name` debe coincidir con el nombre registrado.
- `build_step(name, params=None)`: un nombre desconocido lanza `ValueError("Unknown processing step.")`.
  Si los parámetros no encajan con la firma de la factory, lanza
  `ValueError("Invalid parameters for processing step.")`, con la causa. Un `TypeError` lanzado dentro
  de la factory se propaga tal cual.

## Registro de transformaciones

- `StepRecord(name, version, params, status, error_type=None, outputs={})`. `status` es `"ok"` o
  `"failed"`. `error_type` es `type(error).__name__` y está presente solo si falló. **Nunca** guarda el
  mensaje de la excepción.
- `outputs` guarda los valores calculados por el paso en su forma JSON (copia profunda; las tuplas
  pasan a listas, así que `from_json(to_json(m)) == m`). Un paso `failed` no tiene `outputs`. Un valor
  no serializable o no finito lanza `ValueError("Step outputs must be JSON-serializable.")` sin causa
  ni valor; dentro del runner eso hace fallar el paso para ese estudio y el lote continúa.
  `to_dict()` omite la clave cuando está vacío (un manifiesto sin salidas es idéntico al de la etapa 2)
  y `from_dict()` acepta registros antiguos sin ella. `outputs` entra en la igualdad del manifiesto.
- `StudyReport(index, source_path, steps)`. `index` empieza en 1 y sigue el orden de entrada.
  `source_path` es `str(series[0].files[0])`, o `None` si el estudio no tiene archivos. `steps`
  sigue el orden de ejecución; el último es el que falló, si alguno falló.
- `to_dict()` / `from_dict()` en ambos usan solo tipos básicos; `from_dict` valida en `__post_init__`.

## Runner

```python
Pipeline(steps).run(
    studies: Iterable[MRIStudy],
    on_result: Callable[[MRIStudy, StudyReport], None],
    on_error: Callable[[Path, Exception], None] | None = None,
) -> list[StudyReport]
```

- **Streaming:** consume `studies` de forma perezosa (p. ej. `NIfTIBatchReader.iter_studies` o
  `BIDSBatchReader.iter_studies`). Suelta cada estudio, de entrada y de salida, antes de leer el
  siguiente. No acumula estudios: solo los reportes, que son pequeños.
- **Éxito:** se llama a `on_result(estudio_procesado, report)`.
- **Fallo:** el borde es por estudio (`except Exception` alrededor de cada `apply`). Al fallar un
  paso, los siguientes de ese estudio no corren ni se registran. Se llama a
  `on_error(series[0].files[0], error)`, o a `on_error(Path(), error)` si el estudio no tiene
  archivos, y el lote continúa. `on_result` no se llama.
- **Callbacks que lanzan:** se capturan y solo se registra su tipo (`"on_result callback failed
  (KeyError)"`); el lote sigue.
- **Errores del iterable** (p. ej. `ValueError("No valid NIfTI studies were found.")` al agotarlo):
  se propagan, porque son globales.
- **Devuelve** un `StudyReport` por estudio, éxitos y fallos, en orden de entrada.
- **Redacción de rutas:** si algún paso del pipeline declara `redacts_sources` con valor verdadero
  (se evalúa con `bool()` una vez por corrida), **todos** los `StudyReport` de la corrida guardan
  `source_path=None`, también los de estudios que fallan antes de llegar a ese paso. `on_error`
  sigue recibiendo la ruta real, solo en memoria; no se persiste. `StudyReport`, el manifiesto y
  `from_json` no cambian. Al reproducir desde el manifiesto el paso se reconstruye desde su clase y
  vuelve a redactar, así que la igualdad se mantiene. **Riesgo residual:** `index` sigue el orden
  determinista del lector, así que quien tenga acceso al directorio de entrada puede volver a
  vincular cada `index` con su archivo; exige acceso a los datos originales.
- **Logs:** un warning por fallo con el tipo de excepción y un resumen final
  (`Pipeline finished: N studies, M failed`). Nunca rutas, UIDs ni mensajes.
- **Advertencia de memoria:** si `on_error` guarda la excepción, su `__traceback__` mantiene vivo el
  estudio que falló (y su volumen). Guarda solo lo necesario, p. ej. `type(error).__name__`.

## Manifiesto de corrida

`RunManifest(config, versions, steps, reports, timestamps)`:

- `config`: configuración efectiva (`load_config`), copiada en profundidad.
- `versions`: `mri_dataset_tool`, `python`, `numpy`, `nibabel` y `pydicom`, leídas con
  `importlib.metadata`. Si un paquete no está instalado, su valor es `"unknown"`.
- `steps`: `{"name", "version", "params"}` de cada paso tal como se ejecutó.
- `reports`: la lista que devuelve `run`, con los `outputs` de cada paso por estudio (no van en `steps`).
- `timestamps`: `{"created_at": ISO 8601 UTC}`. Se guarda en el JSON pero **no entra en la
  igualdad** (`compare=False`), así que dos corridas reproducidas son iguales.

Operaciones:

- `RunManifest.from_run(config, pipeline, reports)`: crea el manifiesto de una corrida.
- `to_json()`: JSON con `sort_keys=True` e `indent=2`, determinista.
- `from_json(text)`: un JSON inválido o una estructura incorrecta (claves que faltan, tipos de los
  pasos, `StepRecord` inválido) lanzan `ValueError("Invalid run manifest.")`, sin causa encadenada.
- `write(path, overwrite=False)`: el llamador pasa `Path(config["report"]["path"])`. Escribe de forma
  atómica: un temporal en el mismo directorio que se mueve con `os.replace`, sin dejar temporales.
  Un archivo existente sin `overwrite` lanza `FileExistsError`; otro fallo lanza
  `OSError("Run manifest file could not be written.")`. Los mensajes no llevan la ruta. No crea
  directorios.
- `pipeline_from_config(config)`: construye el `Pipeline` con `build_step` desde `pipeline.steps`.
- `pipeline_from_manifest(manifest)`: reconstruye el `Pipeline` con los `params` registrados. Un paso
  desconocido lanza `ValueError`. Si la versión del paso registrado cambió, lanza
  `ValueError("Processing step version differs from the run manifest.")`.

El JSON contiene rutas de origen, nombres y parámetros de pasos y tipos de excepción. **Nunca**
contiene mensajes de excepción ni valores de cabecera.

## Ejemplo

Es el criterio de cierre de la etapa 2; la versión ejecutable está en
`tests/unit/test_pipeline_example.py`.

```python
@register_step("example.scale")
@dataclass(frozen=True)
class ScaleStep:
    factor: float = 1.0
    name: ClassVar[str] = "example.scale"
    version: ClassVar[str] = "1"

    @property
    def params(self) -> dict[str, Any]:
        return {"factor": self.factor}

    def apply(self, study: MRIStudy) -> MRIStudy:
        return replace(study, series=[replace(s, volume=s.volume * self.factor) for s in study.series])


config = load_config(Path("run.yaml"))  # pipeline.steps: [{name: example.scale, params: {factor: 2.0}}]
pipeline = pipeline_from_config(config)
reports = pipeline.run(
    NIfTIBatchReader().iter_studies(batch_dir),
    on_result=lambda study, report: ...,           # guardar o seguir procesando el estudio
    on_error=lambda path, error: ...,              # el lote continúa
)
RunManifest.from_run(config, pipeline, reports).write(Path(config["report"]["path"]))

# Reproducir desde el manifiesto guardado
saved = RunManifest.from_json(Path(config["report"]["path"]).read_text(encoding="utf-8"))
replay = pipeline_from_manifest(saved)
replay_reports = replay.run(NIfTIBatchReader().iter_studies(batch_dir), on_result=...)
assert RunManifest.from_run(saved.config, replay, replay_reports) == saved
```

## Verificación manual

Desde la raíz del repositorio:

```shell
python scripts/run_example_pipeline.py
```

El script corre `example.scale` sobre `data/raw/nifti_test_studies` con la configuración
`config/example_run.yaml`. Escribe el manifiesto en `data/output/example_run_manifest.json`, que git
ignora. Después reconstruye el pipeline desde ese manifiesto y lo vuelve a correr, e imprime
`reproduced from manifest: True` si ambas corridas coinciden. Revisa que el JSON solo contenga rutas,
pasos, parámetros, versiones y tipos de excepción, nunca mensajes ni valores de cabecera.
