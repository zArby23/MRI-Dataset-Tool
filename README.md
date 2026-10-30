# MRI Dataset Tool

Academic project for loading MRI studies and structuring them into ML/DL-ready datasets using Python.

## Overview

This tool automates the loading, validation, conversion, processing, anonymization, labeling, and organization of MRI studies.

## Features

- DICOM study loading (headers; 3D/4D volume building)
- NIfTI dataset handling
- DICOM to NIfTI and NIfTI to DICOM (3D only) conversion
- BIDS reading (flexible mode, sidecar inheritance)
- Batch processing support
- Graphical wizard `mri-dataset-gui` (Tkinter, Spanish and English): input (BIDS, DICOM or loose NIfTI) → configuration → series mapping table → background run → label table with batch tools → ML exports and report; same validation and outputs as the command line, no patient data on screen or in logs; own purple theme, welcome screen, activity indicator, one-click cell editing, keyboard navigation and display scaling
- Processing pipeline core: step contract, streaming batch runner that reports errors and continues, JSON run manifest that records each step's parameters and computed outputs and reproduces a run
- Processing steps: integrity validation, reorientation to RAS+ (no interpolation), resampling to a fixed spacing (default 1 mm, linear), intensity normalization, and a technical metadata summary
- Anonymization (in development, tested only with synthetic data): model anonymization step and DICOM file anonymization with a version 1 policy and an audit report
- Lazy NIfTI loading (`lazy=True`) for batches, with linear-time reads of 4D `.nii.gz`
- Memory guard before large allocations in `resample` and `normalize` (explicit `allow_insufficient_memory` consent, recorded in the run manifest)
- Example runs: `scripts/run_stage3_pipeline.py` (loose NIfTI) and `scripts/run_stage3_bids_pipeline.py` with `config/stage3_bids.yaml` (BIDS; anatomical series at 1 mm, diffusion at 2 mm to bound RAM)
- YAML configuration (default < environment < run file)
- Data validation and organization
- Preparation for ML/DL pipelines

## Requirements

- Python 3.14 or newer
- pip
- Virtual environment support

### Dependencies

Installed automatically by `python -m pip install -e ".[dev]"` (declared in `pyproject.toml`; versions in the right column are the ones the tests were run with on Windows):

| Package | Minimum | Tested | Used for |
|---|---|---|---|
| `pydicom` | 3.0 | 3.0.2 | DICOM reading and writing |
| `nibabel` | 5.0 | 5.4.2 | NIfTI reading and writing |
| `numpy` | 2.0 | 2.5.2 | volumes |
| `scipy` | 1.0 | 1.18.0 | resampling |
| `pyyaml` | 6.0 | 6.0.3 | configuration files |
| `psutil` | 5.9 | 7.2.2 | free memory and disk checks |
| `openpyxl` | 3.1 | 3.1.5 | XLSX report |
| `pytest` (only with `[dev]`) | 9.1 | 9.1.1 | tests |

System requirements (not installed by pip):

- **Windows:** Python 3.14 from python.org (64-bit). Tkinter (the GUI) is included in the standard installer; leave "tcl/tk and IDLE" checked.
- **Linux:** Python 3.14 with `venv`, plus the Tkinter package of your distribution (needed only for `mri-dataset-gui`): Debian/Ubuntu `sudo apt install python3-tk`, Fedora `sudo dnf install python3-tkinter`, Arch `sudo pacman -S tk`. If your distribution does not ship Python 3.14, install it with `pyenv` or `uv`, making sure Tk is available when it is built. The wheels of `numpy`, `scipy` and the others come from PyPI; a C compiler should not be needed. A desktop session (X11 or Wayland) is required for the GUI; the command line (`mri-dataset`) works without it.
- **Linux status:** the GUI and the command line have been run by hand on Linux (CachyOS, from source) with the public samples; report any problem you find on other distributions.
- All outputs of real runs need free disk space: the tool warns when the estimate reaches 90 % of the free space.

## Installation

1. Clone the repository:

```bash
git clone https://github.com/zArby23/MRI-Dataset-Tool.git
cd MRI-Dataset-Tool
```

2. Create and activate a virtual environment:

```bash
python -m venv .venv
```

Windows PowerShell:

```shell
.\.venv\Scripts\Activate.ps1
```

Windows Command Prompt:

```bash
.venv\Scripts\activate.bat
```

macOS:

```bash
source .venv/bin/activate
```

Linux:
```bash
source .venv/bin/activate   # bash/zsh (fish: activate.fish)
```

3. Install the project and development dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

4. Launch the graphical interface (on Linux, Tkinter may need the system package `python3-tk`):

```bash
mri-dataset-gui
# or: python -m mri_dataset_tool.presentation.gui
```

5. Verify the installation:

```bash
python -m pytest
```

## Troubleshooting

| Problem | Cause and fix |
|---|---|
| `error: externally-managed-environment` (Arch, CachyOS, Debian 12+, Ubuntu 23.04+) | The system Python refuses `pip install` outside a virtual environment. Create and activate one first: `python -m venv .venv`, then `source .venv/bin/activate` (the prompt starts with `(.venv)`). Repeat the `source` in every new terminal. Do not use `--break-system-packages`. To only use the program, `pipx install .` or `uv tool install .` also work (not verified yet). |
| `requires a different Python` or `No matching distribution` | The project needs Python 3.14 or newer (`python --version`). Install it with `uv venv --python 3.14` or `pyenv`, or from python.org on Windows. |
| `ModuleNotFoundError: No module named 'tkinter'` or the window does not open (`TclError`) | Tkinter is a system package on Linux: Debian/Ubuntu `python3-tk`, Fedora `python3-tkinter`, Arch/CachyOS `tk`. The GUI also needs a graphical session. On Windows, reinstall Python with "tcl/tk and IDLE" checked. |
| `.venv` copied from another operating system does not work | A virtual environment is not portable between Windows and Linux. Delete it (`rm -rf .venv`) and create it again. |
| `fish` does not accept `source .venv/bin/activate` | Use `source .venv/bin/activate.fish`. |
| "Anonymization key is not set or too short" in the command line | Set `MRI_ANON_KEY` to at least 32 characters (`export MRI_ANON_KEY=...`). The GUI creates a session key by itself. |
| "Open output folder" does nothing on Linux, or the font is not Verdana | Install `xdg-utils` and a DejaVu font package (`fonts-dejavu` on Debian/Ubuntu). |
| Windows executable: SmartScreen warning, `Failed to load Python DLL` | Click "More info" then "Run anyway" (the executable is not signed). Unzip it in a short path such as `C:\MRI-Dataset-Tool`: very deep folders exceed the 260-character limit. See `docs/user_manual/gui.md`. |

## Documentation

- [Functional requirements](/docs/requierments/functional_requierments.md)
- [Non-functional requirements](/docs/requierments/non_functional_requirements.md)
- [Pipeline architecture](/docs/architecture/pipeline.md)
- [Configuration](/docs/architecture/config.md)
- [Processing steps: geometry](/docs/processing/geometry.md) and [intensity](/docs/processing/intensity.md)
- [Anonymization policy](/docs/anonymization/policy.md)
- [NIfTI studies](/docs/nifti/nifti.md)
- Test samples: `data/samples/` (public BIDS, NIfTI and DICOM data, about 88 MB)
- [GUI user manual](/docs/user_manual/gui.md) and [GUI architecture](/docs/architecture/gui.md)
- [Stage 3 QA report](/docs/testing/qa_etapa3.md)

## Status

In development. Stages 1 to 4 (loading, conversion, pipeline, processing, anonymization and dataset) are complete. Stage 5A adds the `mri-dataset` command line (inspect, convert, anonymize, process, labels, dataset); see `docs/user_manual/cli.md` and `docs/architecture/cli.md`. Stage 5B adds the `mri-dataset-gui` graphical wizard (six steps: input, configuration, series mapping, run, labels, ML exports and report); see `docs/user_manual/gui.md` and `docs/architecture/gui.md`. Stage 5C gives the GUI its visual style (theme, welcome screen, activity indicator, one-click editing, keyboard support, display scaling) and was audited (`docs/testing/qa_etapa8.md`). Stage 5D packages the GUI as a portable Windows executable (`.zip` with a folder, no Python needed; build with `python packaging/build_exe.py --out <folder outside the repository>`, see `docs/user_manual/gui.md` and `docs/architecture/gui.md`) and was audited (`docs/testing/qa_etapa9.md`). Pending: checks on a clean Windows machine, SmartScreen and antivirus, and closing (stage 6).

**Implemented** (library code under `src/mri_dataset_tool`)
- Loading of DICOM, NIfTI and BIDS studies, and DICOM <-> NIfTI conversion.
- Processing pipeline core: step contract, batch runner, run manifest and YAML configuration.
- Processing steps: validation, anonymization, reorientation, resampling and normalization.
- Dataset: BIDS writer, labels with review, correction and closing, train/val/test splits by participant, ML/DL index files (`dataset_index.csv`, `datalist.json`) and a statistical report in JSON, Markdown, XML and XLSX.
- Command line `mri-dataset` (stage 5A): `inspect`, `convert`, `anonymize`, `process`, `labels` and `dataset` (`build`, `export-ml`, `report`), with fixed messages, exit codes 0/1/2, no patient data on the console and a disk-space warning.
- Unified input: DICOM trees and loose NIfTI files are organized into the same anonymized BIDS dataset as a BIDS input, so labels, splits and reports work for all three formats.

**How to run**
- `mri-dataset dataset build` accepts a BIDS dataset, a DICOM tree or loose NIfTI files (`--format bids|dicom|nifti`) and organizes them into the same anonymized BIDS dataset, with labels, splits and report. For DICOM the participant is the pseudonymized PatientID and the BIDS suffix comes from conservative rules (doubtful series are skipped with a warning); an optional `--mapping` table fixes ids, suffixes and labels (see `docs/dataset/ingest.md`).
- `mri-dataset --help` (or `python -m mri_dataset_tool.presentation.cli`): command line for the whole flow; see the user manual.
- The scripts below are kept as thin wrappers and are superseded by the command line:
- `scripts/run_stage3_pipeline.py` for loose NIfTI files.
- `scripts/run_stage3_bids_pipeline.py` for BIDS datasets.
- `scripts/run_stage4_dataset.py` builds the full dataset (BIDS, labels, splits and report).
- All of them need the `MRI_ANON_KEY` environment variable (at least 32 characters).
- Before writing, the command line compares the size of the input with the free space on the output drive and warns (it does not block) if the output may reach 90% of it.

**Memory**
- Resampling a 4D diffusion series to 1 mm can need several GB of RAM.
- The tool checks the available memory first and refuses to continue.
- You can force it with `allow_insufficient_memory: true`; the choice is recorded in the run manifest.

**Verification so far**
- Stages 3 to 5A were audited with synthetic data and with the local test datasets; the command line has its own adversarial audit and end-to-end integration tests.
- The unified input (DICOM and loose NIfTI) has integration tests but no independent adversarial audit yet.
- The NIfTI output was checked in a viewer.
- Still pending: runs with compressed DICOM.

**Limits**
- Anonymization does not remove faces or text burned into the pixels.
- It keeps quasi-identifiers (year, age range, sex, scanner model).
- Review the report and the output before sharing real data.
- The generated DICOM does not conform to the strict MR IOD.
- Visual checks of converted DICOM volumes are pending.
- The exported dataset has no `.bval`/`.bvec` for `dwi` and no `EchoTime1/2` for `phasediff`: the official BIDS validator will flag them.
- Labels are assigned through files, the `--mapping` table or the label table of the GUI (with batch tools).
- The GUI generates a new anonymization key per session unless `MRI_ANON_KEY` is set: pseudonyms change between sessions and datasets from different sessions must not be combined.
- The GUI reads the display scale at startup: reopen the program after changing it.
- With very large DICOM trees the GUI preview and run steps can take more than 15 minutes, without cancellation.
- The BIDS suffix of DICOM and loose NIfTI series is deduced with conservative rules: doubtful series are skipped with a warning and can be fixed with the `--mapping` table.
- Files that are git-annex pointers without downloaded content are skipped as unreadable.

**Not implemented yet**
- Executable for Linux/macOS (the GUI runs from the source code there); code signing of the Windows executable.

---

# MRI Dataset Tool

Proyecto académico para cargar estudios de resonancia magnética y estructurarlos en datasets compatibles con ML/DL usando Python.

## Descripción

La herramienta automatiza la carga, validación, conversión, procesamiento, anonimización, etiquetado y organización de estudios MRI.

## Características

- Carga de estudios DICOM (cabeceras; construcción de volúmenes 3D/4D)
- Manejo de datasets NIfTI
- Conversión DICOM a NIfTI y NIfTI a DICOM (solo 3D)
- Lectura BIDS (modo flexible, herencia de sidecars)
- Soporte para procesamiento por lotes
- Asistente gráfico `mri-dataset-gui` (Tkinter, en español e inglés): entrada (BIDS, DICOM o NIfTI sueltos) → configuración → tabla de mapeo de series → ejecución en segundo plano → tabla de etiquetas con herramientas en lote → exportes para ML y reporte; las mismas validaciones y salidas que la línea de comandos, sin datos de pacientes en pantalla ni en logs; tema propio morado, pantalla de bienvenida, indicador de actividad, edición de celdas con un clic, navegación por teclado y escalado de pantalla
- Núcleo del pipeline de procesamiento: contrato de paso, runner por lotes en streaming que informa errores y continúa, manifiesto JSON que registra parámetros y valores calculados de cada paso y reproduce una corrida
- Pasos de procesamiento: validación de integridad, reorientación a RAS+ (sin interpolar), remuestreo a un espaciado fijo (1 mm por defecto, lineal), normalización de intensidad y resumen técnico de metadatos
- Anonimización (en desarrollo, probada solo con datos sintéticos): paso sobre el modelo y anonimización de archivos DICOM con la política v1 e informe de auditoría
- Carga perezosa de NIfTI (`lazy=True`) para lotes, con lectura lineal de 4D `.nii.gz`
- Comprobación de memoria antes de reservas grandes en `resample` y `normalize` (consentimiento explícito `allow_insufficient_memory`, registrado en el manifiesto)
- Corridas de ejemplo: `scripts/run_stage3_pipeline.py` (NIfTI sueltos) y `scripts/run_stage3_bids_pipeline.py` con `config/stage3_bids.yaml` (BIDS; anatómicas a 1 mm y difusión a 2 mm para acotar la RAM)
- Configuración YAML (default < entorno < archivo de corrida)
- Validación y organización de datos
- Preparación para pipelines de ML/DL

## Requisitos

- Python 3.14 o superior
- pip
- Soporte para entornos virtuales

### Dependencias

Se instalan solas con `python -m pip install -e ".[dev]"` (declaradas en `pyproject.toml`; la columna «Probada» son las versiones con las que se corrieron las pruebas en Windows):

| Paquete | Mínima | Probada | Para qué |
|---|---|---|---|
| `pydicom` | 3.0 | 3.0.2 | lectura y escritura DICOM |
| `nibabel` | 5.0 | 5.4.2 | lectura y escritura NIfTI |
| `numpy` | 2.0 | 2.5.2 | volúmenes |
| `scipy` | 1.0 | 1.18.0 | remuestreo |
| `pyyaml` | 6.0 | 6.0.3 | archivos de configuración |
| `psutil` | 5.9 | 7.2.2 | comprobaciones de memoria y disco libres |
| `openpyxl` | 3.1 | 3.1.5 | reporte XLSX |
| `pytest` (solo con `[dev]`) | 9.1 | 9.1.1 | pruebas |

Requisitos del sistema (pip no los instala):

- **Windows:** Python 3.14 de python.org (64 bits). Tkinter (la GUI) viene en el instalador estándar; deja marcado «tcl/tk and IDLE».
- **Linux:** Python 3.14 con `venv`, más el paquete de Tkinter de tu distribución (solo para `mri-dataset-gui`): Debian/Ubuntu `sudo apt install python3-tk`, Fedora `sudo dnf install python3-tkinter`, Arch `sudo pacman -S tk`. Si tu distribución no trae Python 3.14, instálalo con `pyenv` o `uv` y asegúrate de que Tk esté disponible al compilarlo. Las ruedas de `numpy`, `scipy` y las demás vienen de PyPI; no debería hacer falta un compilador de C. La GUI necesita una sesión de escritorio (X11 o Wayland); la línea de comandos (`mri-dataset`) funciona sin ella.
- **Estado en Linux:** la GUI y la línea de comandos se han ejecutado a mano en Linux (CachyOS, desde el código fuente) con las muestras públicas; avisa de cualquier problema que encuentres en otras distribuciones.
- Las salidas de corridas reales necesitan espacio libre en disco: la herramienta avisa cuando la estimación alcanza el 90 % del espacio libre.

## Instalación

1. Clona el repositorio:

```bash
git clone https://github.com/zArby23/MRI-Dataset-Tool.git
cd MRI-Dataset-Tool
```

2. Crea y activa un entorno virtual:

```bash
python -m venv .venv
```

PowerShell:

```shell
.\.venv\Scripts\Activate.ps1
```

CMD:

```bash
.venv\Scripts\activate.bat
```

macOS:

```bash
source .venv/bin/activate
```

Linux:
```bash
source .venv/bin/activate   # bash/zsh (fish: activate.fish)
```

3. Instala las dependencias del proyecto:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

4. Abre la interfaz gráfica (en Linux, Tkinter puede necesitar el paquete del sistema `python3-tk`):

```bash
mri-dataset-gui
# o: python -m mri_dataset_tool.presentation.gui
```

5. Verifica la instalación:

```bash
python -m pytest
```

## Solución de problemas

| Problema | Causa y solución |
|---|---|
| `error: externally-managed-environment` (Arch, CachyOS, Debian 12+, Ubuntu 23.04+) | El Python del sistema no permite `pip install` fuera de un entorno virtual. Crea y activa uno antes: `python -m venv .venv` y luego `source .venv/bin/activate` (el prompt empieza con `(.venv)`). Repite el `source` en cada terminal nueva. No uses `--break-system-packages`. Si solo quieres usar el programa, también sirven `pipx install .` o `uv tool install .` (aún sin verificar). |
| `requires a different Python` o `No matching distribution` | El proyecto necesita Python 3.14 o superior (`python --version`). Instálalo con `uv venv --python 3.14` o `pyenv`, o desde python.org en Windows. |
| `ModuleNotFoundError: No module named 'tkinter'` o la ventana no abre (`TclError`) | En Linux, Tkinter es un paquete del sistema: Debian/Ubuntu `python3-tk`, Fedora `python3-tkinter`, Arch/CachyOS `tk`. La GUI también necesita una sesión gráfica. En Windows, reinstala Python con «tcl/tk and IDLE» marcado. |
| Un `.venv` copiado de otro sistema operativo no funciona | Un entorno virtual no es portable entre Windows y Linux. Bórralo (`rm -rf .venv`) y créalo de nuevo. |
| `fish` no acepta `source .venv/bin/activate` | Usa `source .venv/bin/activate.fish`. |
| «Anonymization key is not set or too short» en la línea de comandos | Define `MRI_ANON_KEY` con al menos 32 caracteres (`export MRI_ANON_KEY=...`). La GUI crea una clave de sesión por sí sola. |
| «Abrir la carpeta de salida» no hace nada en Linux, o la letra no es Verdana | Instala `xdg-utils` y un paquete de fuentes DejaVu (`fonts-dejavu` en Debian/Ubuntu). |
| Ejecutable de Windows: aviso de SmartScreen, `Failed to load Python DLL` | Pulsa «Más información» y «Ejecutar de todas formas» (el ejecutable no está firmado). Descomprímelo en una ruta corta como `C:\MRI-Dataset-Tool`: las carpetas muy profundas superan el límite de 260 caracteres. Ver `docs/user_manual/gui.md`. |

## Documentación

- [Requisitos funcionales](/docs/requierments/functional_requierments.md)
- [Requisitos no funcionales](/docs/requierments/non_functional_requirements.md)
- [Arquitectura del pipeline](/docs/architecture/pipeline.md)
- [Configuración](/docs/architecture/config.md)
- [Pasos de procesamiento: geometría](/docs/processing/geometry.md) e [intensidad](/docs/processing/intensity.md)
- [Política de anonimización](/docs/anonymization/policy.md)
- [Estudios NIfTI](/docs/nifti/nifti.md)
- Muestras de prueba: `data/samples/` (datos públicos BIDS, NIfTI y DICOM, unos 88 MB)
- [Informe de QA de la etapa 3](/docs/testing/qa_etapa3.md)

## Estado

En desarrollo. Las etapas 1 a 4 (carga, conversión, pipeline, procesamiento, anonimización y dataset) están completas. La etapa 5A añade la línea de comandos `mri-dataset` (inspect, convert, anonymize, process, labels, dataset); ver `docs/user_manual/cli.md` y `docs/architecture/cli.md`. La etapa 5B añade el asistente gráfico `mri-dataset-gui` (seis pasos: entrada, configuración, mapeo de series, ejecución, etiquetas, exportes para ML y reporte); ver `docs/user_manual/gui.md` y `docs/architecture/gui.md`. La etapa 5C da a la GUI su estilo visual (tema, pantalla de bienvenida, indicador de actividad, edición con un clic, teclado y escalado de pantalla) y se auditó (`docs/testing/qa_etapa8.md`). La etapa 5D empaqueta la GUI como ejecutable portable de Windows (`.zip` con una carpeta, sin necesitar Python; se compila con `python packaging/build_exe.py --out <carpeta fuera del repositorio>`, ver `docs/user_manual/gui.md` y `docs/architecture/gui.md`) y se auditó (`docs/testing/qa_etapa9.md`). Pendiente: comprobaciones en una máquina Windows limpia, SmartScreen y antivirus, y cierre (etapa 6).

**Implementado** (código de biblioteca en `src/mri_dataset_tool`)
- Carga de estudios DICOM, NIfTI y BIDS, y conversión DICOM <-> NIfTI.
- Núcleo del pipeline de procesamiento: contrato de paso, runner por lotes, manifiesto de corrida y configuración YAML.
- Pasos de procesamiento: validación, anonimización, reorientación, remuestreo y normalización.
- Dataset: escritura en formato BIDS, etiquetas con revisión, corrección y cierre, particiones train/val/test por participante, índices para ML/DL (`dataset_index.csv`, `datalist.json`) y reporte estadístico en JSON, Markdown, XML y XLSX.
- Línea de comandos `mri-dataset` (etapa 5A): `inspect`, `convert`, `anonymize`, `process`, `labels` y `dataset` (`build`, `export-ml`, `report`), con mensajes fijos, códigos de salida 0/1/2, sin datos de pacientes en la consola y aviso de espacio en disco.
- Entrada unificada: los árboles DICOM y los NIfTI sueltos se organizan en el mismo dataset BIDS anonimizado que una entrada BIDS, de modo que etiquetas, particiones y reportes funcionan con los tres formatos.

**Cómo ejecutar**
- `mri-dataset dataset build` acepta un dataset BIDS, un árbol DICOM o NIfTI sueltos (`--format bids|dicom|nifti`) y los organiza en el mismo dataset BIDS anonimizado, con etiquetas, particiones y reporte. En DICOM el participante es el PatientID seudonimizado y el sufijo BIDS se deduce con reglas conservadoras (lo dudoso se omite con aviso); una tabla opcional `--mapping` corrige ids, sufijos y etiquetas (ver `docs/dataset/ingest.md`).
- `mri-dataset --help` (o `python -m mri_dataset_tool.presentation.cli`): línea de comandos para todo el flujo; ver el manual de usuario.
- Los scripts siguientes se mantienen como envoltorios finos y quedan superados por la línea de comandos:
- `scripts/run_stage3_pipeline.py` para archivos NIfTI sueltos.
- `scripts/run_stage3_bids_pipeline.py` para datasets BIDS.
- `scripts/run_stage4_dataset.py` para construir el dataset completo (BIDS, etiquetas, particiones y reporte).
- Todos requieren la variable de entorno `MRI_ANON_KEY` (de al menos 32 caracteres).
- Antes de escribir, la línea de comandos compara el tamaño de la entrada con el espacio libre del disco de salida y avisa (no bloquea) si la salida podría llegar al 90 % de ese espacio.

**Memoria**
- Remuestrear una difusión 4D a 1 mm puede necesitar varios GB de RAM.
- La herramienta comprueba primero la memoria disponible y se niega a continuar.
- Puedes forzarlo con `allow_insufficient_memory: true`; la decisión queda registrada en el manifiesto de la corrida.

**Verificación hasta ahora**
- Las etapas 3 a 5A se auditaron con datos sintéticos y con los datasets locales de prueba; la línea de comandos tiene su propia auditoría adversarial y pruebas de integración de punta a punta.
- La entrada unificada (DICOM y NIfTI sueltos) tiene pruebas de integración pero todavía no una auditoría adversarial independiente.
- La salida NIfTI se revisó en un visor.
- Siguen pendientes las corridas con DICOM comprimido.

**Límites**
- La anonimización no borra caras ni texto quemado en los píxeles.
- Conserva cuasi-identificadores (año, rango de edad, sexo, modelo de escáner).
- Revisa el informe y la salida antes de compartir datos reales.
- El DICOM generado no es conforme al IOD MR estricto.
- La verificación visual de los volúmenes DICOM convertidos está pendiente.
- El dataset exportado no incluye `.bval`/`.bvec` para `dwi` ni `EchoTime1/2` para `phasediff`: el validador oficial de BIDS los marcará.
- Las etiquetas se asignan por archivos, con la tabla `--mapping` o con la tabla de etiquetas de la GUI (con herramientas en lote).
- El sufijo BIDS de las series DICOM y NIfTI sueltas se deduce con reglas conservadoras: las series dudosas se omiten con un aviso y se corrigen con la tabla `--mapping`.
- Los archivos que son punteros de git-annex sin contenido descargado se omiten como ilegibles.
- La GUI genera una clave de anonimización nueva por sesión salvo que `MRI_ANON_KEY` esté definida: los seudónimos cambian entre sesiones y los datasets de sesiones distintas no deben combinarse.
- La GUI lee la escala de pantalla al arrancar: reábrela tras cambiarla.
- Con árboles DICOM muy grandes, la vista previa y la ejecución de la GUI pueden tardar más de 15 minutos, sin cancelación.

**Todavía no implementado**
- Ejecutable para Linux/macOS (allí la GUI se ejecuta desde el código fuente); firma de código del ejecutable de Windows.
