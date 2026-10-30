# Pruebas

La suite usa `pytest` (`pytest>=9.1`, extra `[dev]`) y vive en `tests/`. Todo se ejecuta con datos **sintéticos** generados
en una carpeta temporal; ninguna prueba necesita datos de pacientes ni los de `data/samples/`.

## Cómo ejecutarlas

Desde la raíz del repositorio y con el entorno virtual activo:

```bash
python -m pytest -q tests                 # suite completa (unos 5 a 10 minutos)
python -m pytest -q tests/unit/test_nifti_reader.py        # un archivo
python -m pytest -q tests -k "dicom and not gui"           # por nombre
```

Use `python -m pytest -q tests`, no `pytest` a secas: este último puede recoger pruebas del `.venv`. Con poco espacio en el
disco del sistema, mande los temporales a otro disco con `--basetemp=<carpeta>/t` (la carpeta padre debe existir).

Resultado de referencia (Windows): **2141 pasan, 7 omitidas y 2 `xfail` documentados**. En Linux los números de omitidas y `xfail` cambian (ver abajo).

## Organización

| Carpeta | Contenido |
|---|---|
| `tests/unit/` | Una o varias pruebas por módulo: lectores, escritores, pasos, servicios, CLI y GUI (`test_cli_*`, `test_gui_*`, `test_service_*`, `test_step_*`, `test_dataset_*`). |
| `tests/integration/` | Recorridos de punta a punta por etapa (`test_stage3` a `test_stage5d`): DICOM, NIfTI y BIDS sintéticos con datos personales plantados y barridos de la salida. |
| `tests/qa/` | Auditorías adversariales: entradas hostiles, invariantes entre pasos y barridos de datos sensibles (`test_qa*`). Cada auditoría tiene su informe en `docs/testing/qa_etapa*.md`. |
| `tests/conftest.py` | Fixtures compartidas. |

## Qué comprueban las pruebas de privacidad

Las pruebas siembran valores reconocibles (nombres, IDs, fechas, UIDs, rutas) en las entradas y recorren la consola, los
logs, los reportes y todos los archivos de salida buscándolos. Una salida con un valor sembrado hace fallar la prueba.

## Omitidas y esperadas

- Las pruebas de **Tkinter** se omiten sin pantalla (p. ej. en un servidor); con sesión gráfica se ejecutan.
- Algunas pruebas son solo de Windows (rutas sin distinción de mayúsculas, unidades, uniones NTFS) o solo de Linux (enlaces
  simbólicos): por eso el número de omitidas cambia con el sistema.
- `tests/qa/test_qa9_bundle.py` audita el ejecutable ya compilado: se activa con la variable
  `MRI_QA9_BUNDLE=<carpeta dist/MRI-Dataset-Tool>` (si no está definida, 3 de sus pruebas se omiten).
- `tests/integration/test_stage5d_frozen_integration.py` prueba el script de empaquetado solo si PyInstaller está instalado
  (`importorskip`); no compila nada.
- Los 2 `xfail` son defectos conocidos que solo aparecen en Windows (QA4-03: orden de `find_nifti_files`; QA4-08: ids que solo difieren en mayúsculas), documentados en `qa_etapa4.md`. Están marcados `xfail(strict=True)`: si se corrigen, pasan a fallar para recordar quitar la marca. En Linux se omiten.

## Informes de auditoría

| Informe | Alcance |
|---|---|
| [`qa_etapa3.md`](qa_etapa3.md) | Etapas 1 a 3: carga, conversión, pipeline, procesamiento y anonimización. |
| [`qa_etapa4.md`](qa_etapa4.md) | Dataset: BIDS, etiquetas, particiones y reportes. |
| [`qa_etapa5.md`](qa_etapa5.md) | Línea de comandos. |
| [`qa_etapa6.md`](qa_etapa6.md) | Entrada unificada DICOM/NIfTI. |
| [`qa_etapa7.md`](qa_etapa7.md) | Interfaz gráfica. |
| [`qa_etapa8.md`](qa_etapa8.md) | Aspecto visual de la GUI. |
| [`qa_etapa9.md`](qa_etapa9.md) | Ejecutable portable de Windows. |

## Verificaciones manuales

Las pruebas automáticas no sustituyen estas, que se hacen a mano: abrir un volumen convertido en un visor, el recorrido de la
GUI con datos reales, la escala de pantalla al 125/150 %, el ejecutable en una máquina Windows limpia y el comportamiento
de SmartScreen y antivirus.
