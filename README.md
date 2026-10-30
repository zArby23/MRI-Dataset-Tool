# MRI Dataset Tool

**English** · [Español](#español)

Academic project that loads MRI studies (DICOM, NIfTI, BIDS) and structures them into anonymized, ML/DL-ready datasets with Python. It ships a graphical wizard, a command line and a portable Windows executable.

> Status: version **0.1.0**, academic project; not a finished application. Stages 1 to 5 are complete (see [Status](#status)).

## Contents

[Quick start](#quick-start) · [Features](#features) · [Installation](#installation) · [Linux by distribution](#linux-by-distribution) · [Usage](#usage) · [Troubleshooting](#troubleshooting) · [Documentation](#documentation) · [Status](#status) · [Limits](#limits)

## Quick start

| I want to... | Do this |
|---|---|
| Use the GUI on **Windows**, without Python | Download `MRI-Dataset-Tool-v0.1.0-win64.zip` from the [latest release](https://github.com/zArby23/MRI-Dataset-Tool/releases/latest), unzip it fully in a **short path** (e.g. `C:\MRI-Dataset-Tool`) and open `MRI-Dataset-Tool.exe`. It is not signed: SmartScreen may ask for "More info" → "Run anyway". |
| Use the GUI or the command line on **Linux / macOS**, or develop | Install from source: see [Installation](#installation). |
| Try it with real data | Public samples are in `data/samples/` (BIDS, NIfTI and DICOM, about 88 MB). |

## Features

- **Input:** DICOM (headers, 3D/4D volume building), NIfTI (eager or lazy) and BIDS (flexible mode, sidecar inheritance), single or by batch.
- **Conversion:** DICOM → NIfTI and NIfTI → DICOM (3D only).
- **Unified input:** DICOM trees and loose NIfTI files are organized into the same anonymized BIDS dataset as a BIDS input, with labels, participant-level train/val/test splits and reports.
- **Processing pipeline:** integrity validation, reorientation to RAS+ (no interpolation), resampling, intensity normalization and a technical metadata summary. Streaming batch runner that reports errors and continues, and a JSON manifest that records every step and reproduces a run. YAML configuration (default < environment < run file).
- **Anonymization:** policy v1 with a whitelist, deterministic pseudonyms from a secret key (`MRI_ANON_KEY`) and an audit report.
- **Dataset:** BIDS writer, labels with review, correction and closing, `dataset_index.csv`, `datalist.json`, `splits.*`, and a statistical report in JSON, Markdown, XML and XLSX.
- **Interfaces:**
  - `mri-dataset-gui`: Tkinter wizard in Spanish and English with six steps (input → configuration → series mapping → run → labels → ML exports and report). Same validation and outputs as the command line, no patient data on screen or in logs.
  - `mri-dataset`: command line (`inspect`, `convert`, `anonymize`, `process`, `labels`, `dataset build | export-ml | report`) with fixed messages and exit codes 0/1/2.
  - Portable Windows executable of the GUI (`onedir` in a `.zip`, no Python needed).
- **Safety:** inputs and existing outputs are never overwritten, outputs are written atomically, free disk space and memory are checked before large writes, and nothing sensitive reaches the console or logs.

## Installation

### Requirements

- Python **3.14 or newer**, `pip` and virtual environment support.
- Tkinter, only for the GUI (a system package on Linux, see below).
- Free disk space for the outputs: the tool warns when the estimate reaches 90 % of the free space.

Python dependencies are installed by `pip` (declared in `pyproject.toml`; the "Tested" column is the version the tests ran with):

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

### Steps (all systems)

1. Clone the repository:

   ```bash
   git clone https://github.com/zArby23/MRI-Dataset-Tool.git
   cd MRI-Dataset-Tool
   ```

2. Create and activate a virtual environment (**always required on Linux**: most distributions block `pip` outside one, see [Troubleshooting](#troubleshooting)):

   | System | Create | Activate |
   |---|---|---|
   | Linux / macOS (bash, zsh) | `python3 -m venv .venv` | `source .venv/bin/activate` |
   | Linux (fish) | `python3 -m venv .venv` | `source .venv/bin/activate.fish` |
   | Windows PowerShell | `python -m venv .venv` | `.\.venv\Scripts\Activate.ps1` |
   | Windows CMD | `python -m venv .venv` | `.venv\Scripts\activate.bat` |

   The prompt starts with `(.venv)` when it is active. Repeat the activation in every new terminal.

3. Install the project:

   ```bash
   python -m pip install --upgrade pip
   python -m pip install -e ".[dev]"
   ```

4. Check it and open the GUI:

   ```bash
   python -m pytest -q
   mri-dataset-gui          # or: python -m mri_dataset_tool.presentation.gui
   mri-dataset --help
   ```

### Linux by distribution

Before step 2, install Python 3.14, `venv`, Tkinter and the small extras below. Only Arch/CachyOS has been tried by hand; the other rows come from the usual package names of each distribution and have **not been tested**: if a name is wrong for your release, search it with your package manager and tell us.

| Distribution | Install the system packages | Python 3.14 |
|---|---|---|
| **Arch, CachyOS, Manjaro, EndeavourOS** (tested on CachyOS) | `sudo pacman -S --needed python tk git xdg-utils ttf-dejavu` | Included in the repositories at the time of writing; check with `python --version`. |
| **Debian, Ubuntu, Linux Mint, Pop!_OS** | `sudo apt update && sudo apt install python3 python3-venv python3-tk git xdg-utils fonts-dejavu` | Usually older than 3.14 in stable releases: use `uv` (below). |
| **Fedora, RHEL-like (Rocky, Alma)** | `sudo dnf install python3 python3-tkinter git xdg-utils dejavu-sans-fonts` | Recent Fedora releases ship it; RHEL-like ones usually do not: use `uv`. |
| **openSUSE** | `sudo zypper install python3 python3-tk git xdg-utils dejavu-fonts` | Package names vary by release: use `uv` if `python3 --version` is older than 3.14. |
| **Any other** | Install Python, `venv`, Tk, `git`, `xdg-utils` and a DejaVu font with your package manager | Use `uv` (below). |

What the extras are for: `xdg-utils` makes "Open output folder" work, a DejaVu font replaces Verdana in the GUI if you do not have it. The command line (`mri-dataset`) needs neither Tkinter nor a desktop session; the GUI needs a graphical session (X11 or Wayland).

**If your distribution does not ship Python 3.14, use [`uv`](https://docs.astral.sh/uv/)** (not verified by us on every distribution):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh        # installs uv in your home folder
uv venv --python 3.14 .venv
source .venv/bin/activate                              # fish: activate.fish
uv pip install -e ".[dev]"
```

If the GUI then reports that `tkinter` is missing, install your distribution's Tk package from the table (some Python builds from `uv` or `pyenv` need the system Tk libraries).

## Usage

```bash
# Command line: whole flow on a public sample (output must be a new or empty folder)
export MRI_ANON_KEY=$(openssl rand -hex 32)            # at least 32 characters; fish: set -x MRI_ANON_KEY (openssl rand -hex 32)
mri-dataset dataset build data/samples/bids_test_studies \
    --format bids --config config/stage3_bids.yaml --output-dir ~/mri_out
```

- `--format bids|dicom|nifti` accepts any of the three inputs; `--mapping TSV` fixes participant, session, BIDS suffix and label when the rules are not enough ([`docs/dataset/ingest.md`](/docs/dataset/ingest.md)).
- Windows PowerShell: `$env:MRI_ANON_KEY = "<at least 32 characters>"`. The GUI creates a session key by itself unless the variable is set; sessions with different keys give different pseudonyms and their datasets must not be combined.
- Put large outputs on a disk with enough space. Resampling a 4D diffusion series to 1 mm can need several GB of RAM: the tool checks first and refuses unless you set `allow_insufficient_memory: true` (recorded in the run manifest).
- The scripts in `scripts/run_stage*.py` are thin wrappers superseded by the command line.

## Troubleshooting

| Problem | Cause and fix |
|---|---|
| `error: externally-managed-environment` (Arch, CachyOS, Debian 12+, Ubuntu 23.04+) | The system Python refuses `pip install` outside a virtual environment. Create and activate one first (step 2). Do not use `--break-system-packages`. To only use the program, `pipx install .` or `uv tool install .` may also work (not verified). |
| `requires a different Python` or `No matching distribution` | The project needs Python 3.14 or newer (`python --version`). Use `uv venv --python 3.14` or `pyenv`, or python.org on Windows. |
| `ModuleNotFoundError: No module named 'tkinter'` or the window does not open (`TclError`) | Install the Tk package of your distribution ([table](#linux-by-distribution)). The GUI needs a graphical session. On Windows, reinstall Python with "tcl/tk and IDLE" checked. |
| A `.venv` copied from another operating system does not work | Virtual environments are not portable between Windows and Linux. Delete it (`rm -rf .venv`) and create it again. |
| `fish` does not accept `source .venv/bin/activate` | Use `source .venv/bin/activate.fish`. |
| "Anonymization key is not set or too short" | Set `MRI_ANON_KEY` to at least 32 characters in the same terminal. The GUI does not need it. |
| "Open output folder" does nothing on Linux, or the font is not Verdana | Install `xdg-utils` and a DejaVu font package. |
| Windows executable: SmartScreen warning, `Failed to load Python DLL` | "More info" → "Run anyway" (not signed). Unzip in a short path such as `C:\MRI-Dataset-Tool`: very deep folders exceed the 260-character limit. See [`docs/user_manual/gui.md`](/docs/user_manual/gui.md). |

## Documentation

| Topic | Documents |
|---|---|
| Requirements | [Functional](/docs/requierments/functional_requierments.md) · [Non-functional](/docs/requierments/non_functional_requirements.md) |
| User manuals | [GUI](/docs/user_manual/gui.md) · [Command line](/docs/user_manual/cli.md) |
| Architecture | [Overview](/docs/architecture/overview.md) · [Pipeline](/docs/architecture/pipeline.md) · [Configuration](/docs/architecture/config.md) · [GUI](/docs/architecture/gui.md) · [Command line](/docs/architecture/cli.md) · [Design decisions](/docs/architecture/design_decisions.md) |
| Formats | [NIfTI](/docs/nifti/nifti.md) · [DICOM conversion](/docs/dicom/conversion.md) · [BIDS readers](/docs/bids/reader.md) and [sidecars](/docs/bids/sidecar_inheritance.md) |
| Processing and anonymization | [Geometry](/docs/processing/geometry.md) · [Intensity](/docs/processing/intensity.md) · [Anonymization policy](/docs/anonymization/policy.md) |
| Dataset | [Structure](/docs/dataset/structure.md) · [Unified input](/docs/dataset/ingest.md) · [Labels](/docs/dataset/labels.md) · [ML exports](/docs/dataset/export.md) · [Report](/docs/dataset/report.md) |
| Tests and quality audits | [Test guide](/docs/testing/README.md) · [Stage 3](/docs/testing/qa_etapa3.md) · [Stage 9: Windows bundle](/docs/testing/qa_etapa9.md) · [Index of all docs](/docs/README.md) |

## Status

Version 0.1.0. Stages 1 to 5 are complete:

| Stage | What it delivered |
|---|---|
| 1 to 4 | Loading, conversion, pipeline, processing, anonymization and dataset (BIDS, labels, splits, reports). |
| 5A | Command line `mri-dataset`, with the unified DICOM/NIfTI/BIDS input. |
| 5B | Graphical wizard `mri-dataset-gui`. |
| 5C | Visual style of the GUI (theme, welcome screen, activity indicator, one-click editing, keyboard, display scaling). |
| 5D | Portable Windows executable (`packaging/build_exe.py`), audited in [`docs/testing/qa_etapa9.md`](/docs/testing/qa_etapa9.md). |

Checked by hand: the GUI on Windows (executable and source) and on Linux (CachyOS), and the command line on Linux, with the three kinds of public samples. Automated suite: 2141 tests.

Still pending: a clean Windows machine without Python, SmartScreen and antivirus behavior, display scaling at 125/150 %, long paths with `LongPathsEnabled=0`, and runs with compressed DICOM.

To build the Windows executable yourself: `python -m pip install pyinstaller==6.22.3`, then `python packaging/build_exe.py --out <folder outside the repository>`; distribute only the resulting `.zip` ([`docs/architecture/gui.md`](/docs/architecture/gui.md)).

## Limits

- Anonymization does not remove faces or text burned into the pixels, and it keeps quasi-identifiers (year, age range, sex, scanner model). Review the report and the output before sharing real data.
- The generated DICOM does not conform to the strict MR IOD, and 4D volumes are not converted to DICOM.
- The exported dataset has no `.bval`/`.bvec` for `dwi` and no `EchoTime1/2` for `phasediff`: the official BIDS validator will flag them.
- The BIDS suffix of DICOM and loose NIfTI series is deduced with conservative rules: doubtful series are skipped with a warning and can be fixed with `--mapping`.
- The GUI reads the display scale at startup (reopen it after changing it). With very large DICOM trees its preview and run steps can take more than 15 minutes, without cancellation.
- Files that are git-annex pointers without downloaded content are skipped as unreadable.
- The unified DICOM/NIfTI input has integration tests but no independent adversarial audit.
- No executable for Linux or macOS (the GUI runs from source there); the Windows executable is not code-signed.

---

# Español

[English](#mri-dataset-tool) · **Español**

Proyecto académico que carga estudios de resonancia magnética (DICOM, NIfTI, BIDS) y los estructura en datasets anonimizados listos para ML/DL con Python. Incluye un asistente gráfico, una línea de comandos y un ejecutable portable de Windows.

> Estado: versión **0.1.0**, proyecto académico; no es una aplicación terminada. Las etapas 1 a 5 están completas (ver [Estado](#estado)).

## Contenido

[Inicio rápido](#inicio-rápido) · [Características](#características) · [Instalación](#instalación) · [Linux por distribución](#linux-por-distribución) · [Uso](#uso) · [Solución de problemas](#solución-de-problemas) · [Documentación](#documentación) · [Estado](#estado) · [Límites](#límites)

## Inicio rápido

| Quiero... | Haz esto |
|---|---|
| Usar la GUI en **Windows**, sin Python | Descarga `MRI-Dataset-Tool-v0.1.0-win64.zip` de la [última release](https://github.com/zArby23/MRI-Dataset-Tool/releases/latest), descomprímelo completo en una **ruta corta** (p. ej. `C:\MRI-Dataset-Tool`) y abre `MRI-Dataset-Tool.exe`. No está firmado: SmartScreen puede pedir «Más información» → «Ejecutar de todas formas». |
| Usar la GUI o la línea de comandos en **Linux / macOS**, o desarrollar | Instala desde el código fuente: ver [Instalación](#instalación). |
| Probarlo con datos reales | Hay muestras públicas en `data/samples/` (BIDS, NIfTI y DICOM, unos 88 MB). |

## Características

- **Entrada:** DICOM (cabeceras, construcción de volúmenes 3D/4D), NIfTI (completo o perezoso) y BIDS (modo flexible, herencia de sidecars), individuales o por lote.
- **Conversión:** DICOM → NIfTI y NIfTI → DICOM (solo 3D).
- **Entrada unificada:** los árboles DICOM y los NIfTI sueltos se organizan en el mismo dataset BIDS anonimizado que una entrada BIDS, con etiquetas, particiones train/val/test por participante y reportes.
- **Pipeline de procesamiento:** validación de integridad, reorientación a RAS+ (sin interpolar), remuestreo, normalización de intensidad y resumen técnico de metadatos. Runner por lotes en streaming que informa errores y continúa, y manifiesto JSON que registra cada paso y reproduce una corrida. Configuración YAML (default < entorno < archivo de corrida).
- **Anonimización:** política v1 con lista blanca, seudónimos deterministas con una clave secreta (`MRI_ANON_KEY`) e informe de auditoría.
- **Dataset:** escritura BIDS, etiquetas con revisión, corrección y cierre, `dataset_index.csv`, `datalist.json`, `splits.*` y reporte estadístico en JSON, Markdown, XML y XLSX.
- **Interfaces:**
  - `mri-dataset-gui`: asistente Tkinter en español e inglés con seis pasos (entrada → configuración → mapeo de series → ejecución → etiquetas → exportes para ML y reporte). Mismas validaciones y salidas que la línea de comandos, sin datos de pacientes en pantalla ni en logs.
  - `mri-dataset`: línea de comandos (`inspect`, `convert`, `anonymize`, `process`, `labels`, `dataset build | export-ml | report`) con mensajes fijos y códigos de salida 0/1/2.
  - Ejecutable portable de la GUI para Windows (`onedir` en un `.zip`, sin necesitar Python).
- **Seguridad:** no se sobrescriben entradas ni salidas existentes, las salidas se escriben de forma atómica, se comprueban el espacio en disco y la memoria antes de escrituras grandes, y nada sensible llega a la consola ni a los logs.

## Instalación

### Requisitos

- Python **3.14 o superior**, `pip` y soporte para entornos virtuales.
- Tkinter, solo para la GUI (en Linux es un paquete del sistema, ver abajo).
- Espacio libre en disco para las salidas: la herramienta avisa cuando la estimación alcanza el 90 % del espacio libre.

Las dependencias de Python las instala `pip` (declaradas en `pyproject.toml`; la columna «Probada» es la versión con la que se corrieron las pruebas):

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

### Pasos (todos los sistemas)

1. Clona el repositorio:

   ```bash
   git clone https://github.com/zArby23/MRI-Dataset-Tool.git
   cd MRI-Dataset-Tool
   ```

2. Crea y activa un entorno virtual (**siempre obligatorio en Linux**: la mayoría de las distribuciones bloquean `pip` fuera de uno, ver [Solución de problemas](#solución-de-problemas)):

   | Sistema | Crear | Activar |
   |---|---|---|
   | Linux / macOS (bash, zsh) | `python3 -m venv .venv` | `source .venv/bin/activate` |
   | Linux (fish) | `python3 -m venv .venv` | `source .venv/bin/activate.fish` |
   | Windows PowerShell | `python -m venv .venv` | `.\.venv\Scripts\Activate.ps1` |
   | Windows CMD | `python -m venv .venv` | `.venv\Scripts\activate.bat` |

   El prompt empieza con `(.venv)` cuando está activo. Repite la activación en cada terminal nueva.

3. Instala el proyecto:

   ```bash
   python -m pip install --upgrade pip
   python -m pip install -e ".[dev]"
   ```

4. Verifícalo y abre la GUI:

   ```bash
   python -m pytest -q
   mri-dataset-gui          # o: python -m mri_dataset_tool.presentation.gui
   mri-dataset --help
   ```

### Linux por distribución

Antes del paso 2, instala Python 3.14, `venv`, Tkinter y los extras de abajo. Solo Arch/CachyOS se ha probado a mano; las demás filas salen de los nombres de paquete habituales de cada distribución y **no se han probado**: si un nombre no existe en tu versión, búscalo con tu gestor de paquetes y avísanos.

| Distribución | Instala los paquetes del sistema | Python 3.14 |
|---|---|---|
| **Arch, CachyOS, Manjaro, EndeavourOS** (probado en CachyOS) | `sudo pacman -S --needed python tk git xdg-utils ttf-dejavu` | Está en los repositorios al momento de escribir esto; compruébalo con `python --version`. |
| **Debian, Ubuntu, Linux Mint, Pop!_OS** | `sudo apt update && sudo apt install python3 python3-venv python3-tk git xdg-utils fonts-dejavu` | En las versiones estables suele ser anterior a 3.14: usa `uv` (abajo). |
| **Fedora, derivadas de RHEL (Rocky, Alma)** | `sudo dnf install python3 python3-tkinter git xdg-utils dejavu-sans-fonts` | Las versiones recientes de Fedora lo traen; las de RHEL normalmente no: usa `uv`. |
| **openSUSE** | `sudo zypper install python3 python3-tk git xdg-utils dejavu-fonts` | Los nombres varían según la versión: usa `uv` si `python3 --version` es anterior a 3.14. |
| **Cualquier otra** | Instala Python, `venv`, Tk, `git`, `xdg-utils` y una fuente DejaVu con tu gestor de paquetes | Usa `uv` (abajo). |

Para qué sirven los extras: `xdg-utils` hace que funcione «Abrir la carpeta de salida», y una fuente DejaVu reemplaza a Verdana en la GUI si no la tienes. La línea de comandos (`mri-dataset`) no necesita Tkinter ni sesión de escritorio; la GUI necesita una sesión gráfica (X11 o Wayland).

**Si tu distribución no trae Python 3.14, usa [`uv`](https://docs.astral.sh/uv/)** (no lo hemos verificado en todas las distribuciones):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh        # instala uv en tu carpeta personal
uv venv --python 3.14 .venv
source .venv/bin/activate                              # fish: activate.fish
uv pip install -e ".[dev]"
```

Si después la GUI dice que falta `tkinter`, instala el paquete de Tk de tu distribución de la tabla (algunos Python de `uv` o `pyenv` necesitan las bibliotecas de Tk del sistema).

## Uso

```bash
# Línea de comandos: flujo completo sobre una muestra pública (la salida debe ser una carpeta nueva o vacía)
export MRI_ANON_KEY=$(openssl rand -hex 32)            # al menos 32 caracteres; fish: set -x MRI_ANON_KEY (openssl rand -hex 32)
mri-dataset dataset build data/samples/bids_test_studies \
    --format bids --config config/stage3_bids.yaml --output-dir ~/mri_out
```

- `--format bids|dicom|nifti` acepta cualquiera de las tres entradas; `--mapping TSV` corrige participante, sesión, sufijo BIDS y etiqueta cuando las reglas no bastan ([`docs/dataset/ingest.md`](/docs/dataset/ingest.md)).
- Windows PowerShell: `$env:MRI_ANON_KEY = "<al menos 32 caracteres>"`. La GUI crea una clave de sesión sola si la variable no está definida; sesiones con claves distintas dan seudónimos distintos y sus datasets no deben combinarse.
- Pon las salidas grandes en un disco con espacio suficiente. Remuestrear una difusión 4D a 1 mm puede necesitar varios GB de RAM: la herramienta lo comprueba y se niega salvo que pongas `allow_insufficient_memory: true` (queda registrado en el manifiesto de la corrida).
- Los scripts de `scripts/run_stage*.py` son envoltorios finos superados por la línea de comandos.

## Solución de problemas

| Problema | Causa y solución |
|---|---|
| `error: externally-managed-environment` (Arch, CachyOS, Debian 12+, Ubuntu 23.04+) | El Python del sistema no permite `pip install` fuera de un entorno virtual. Crea y activa uno antes (paso 2). No uses `--break-system-packages`. Si solo quieres usar el programa, `pipx install .` o `uv tool install .` también pueden servir (sin verificar). |
| `requires a different Python` o `No matching distribution` | El proyecto necesita Python 3.14 o superior (`python --version`). Usa `uv venv --python 3.14` o `pyenv`, o python.org en Windows. |
| `ModuleNotFoundError: No module named 'tkinter'` o la ventana no abre (`TclError`) | Instala el paquete de Tk de tu distribución ([tabla](#linux-por-distribución)). La GUI necesita una sesión gráfica. En Windows, reinstala Python con «tcl/tk and IDLE» marcado. |
| Un `.venv` copiado de otro sistema operativo no funciona | Los entornos virtuales no son portables entre Windows y Linux. Bórralo (`rm -rf .venv`) y créalo de nuevo. |
| `fish` no acepta `source .venv/bin/activate` | Usa `source .venv/bin/activate.fish`. |
| «Anonymization key is not set or too short» | Define `MRI_ANON_KEY` con al menos 32 caracteres en la misma terminal. La GUI no la necesita. |
| «Abrir la carpeta de salida» no hace nada en Linux, o la letra no es Verdana | Instala `xdg-utils` y un paquete de fuentes DejaVu. |
| Ejecutable de Windows: aviso de SmartScreen, `Failed to load Python DLL` | «Más información» → «Ejecutar de todas formas» (no está firmado). Descomprímelo en una ruta corta como `C:\MRI-Dataset-Tool`: las carpetas muy profundas superan el límite de 260 caracteres. Ver [`docs/user_manual/gui.md`](/docs/user_manual/gui.md). |

## Documentación

| Tema | Documentos |
|---|---|
| Requisitos | [Funcionales](/docs/requierments/functional_requierments.md) · [No funcionales](/docs/requierments/non_functional_requirements.md) |
| Manuales de usuario | [GUI](/docs/user_manual/gui.md) · [Línea de comandos](/docs/user_manual/cli.md) |
| Arquitectura | [Visión general](/docs/architecture/overview.md) · [Pipeline](/docs/architecture/pipeline.md) · [Configuración](/docs/architecture/config.md) · [GUI](/docs/architecture/gui.md) · [Línea de comandos](/docs/architecture/cli.md) · [Decisiones de diseño](/docs/architecture/design_decisions.md) |
| Formatos | [NIfTI](/docs/nifti/nifti.md) · [Conversión DICOM](/docs/dicom/conversion.md) · [Lectores BIDS](/docs/bids/reader.md) y [sidecars](/docs/bids/sidecar_inheritance.md) |
| Procesamiento y anonimización | [Geometría](/docs/processing/geometry.md) · [Intensidad](/docs/processing/intensity.md) · [Política de anonimización](/docs/anonymization/policy.md) |
| Dataset | [Estructura](/docs/dataset/structure.md) · [Entrada unificada](/docs/dataset/ingest.md) · [Etiquetas](/docs/dataset/labels.md) · [Exportes para ML](/docs/dataset/export.md) · [Reporte](/docs/dataset/report.md) |
| Pruebas y auditorías de calidad | [Guía de pruebas](/docs/testing/README.md) · [Etapa 3](/docs/testing/qa_etapa3.md) · [Etapa 9: bundle de Windows](/docs/testing/qa_etapa9.md) · [Índice de toda la documentación](/docs/README.md) |

## Estado

Versión 0.1.0. Las etapas 1 a 5 están completas:

| Etapa | Qué entregó |
|---|---|
| 1 a 4 | Carga, conversión, pipeline, procesamiento, anonimización y dataset (BIDS, etiquetas, particiones, reportes). |
| 5A | Línea de comandos `mri-dataset`, con la entrada unificada DICOM/NIfTI/BIDS. |
| 5B | Asistente gráfico `mri-dataset-gui`. |
| 5C | Estilo visual de la GUI (tema, bienvenida, indicador de actividad, edición con un clic, teclado, escalado de pantalla). |
| 5D | Ejecutable portable de Windows (`packaging/build_exe.py`), auditado en [`docs/testing/qa_etapa9.md`](/docs/testing/qa_etapa9.md). |

Verificado a mano: la GUI en Windows (ejecutable y código fuente) y en Linux (CachyOS), y la línea de comandos en Linux, con los tres tipos de muestras públicas. Suite automática: 2141 pruebas.

Siguen pendientes: una máquina Windows limpia sin Python, el comportamiento de SmartScreen y antivirus, la escala de pantalla al 125/150 %, rutas largas con `LongPathsEnabled=0` y corridas con DICOM comprimido.

Para compilar tú mismo el ejecutable de Windows: `python -m pip install pyinstaller==6.22.3` y luego `python packaging/build_exe.py --out <carpeta fuera del repositorio>`; distribuye solo el `.zip` resultante ([`docs/architecture/gui.md`](/docs/architecture/gui.md)).

## Límites

- La anonimización no borra caras ni texto quemado en los píxeles, y conserva cuasi-identificadores (año, rango de edad, sexo, modelo de escáner). Revisa el informe y la salida antes de compartir datos reales.
- El DICOM generado no es conforme al IOD MR estricto, y los volúmenes 4D no se convierten a DICOM.
- El dataset exportado no incluye `.bval`/`.bvec` para `dwi` ni `EchoTime1/2` para `phasediff`: el validador oficial de BIDS los marcará.
- El sufijo BIDS de las series DICOM y NIfTI sueltas se deduce con reglas conservadoras: las series dudosas se omiten con un aviso y se corrigen con `--mapping`.
- La GUI lee la escala de pantalla al arrancar (reábrela tras cambiarla). Con árboles DICOM muy grandes, su vista previa y su ejecución pueden tardar más de 15 minutos, sin cancelación.
- Los archivos que son punteros de git-annex sin contenido descargado se omiten como ilegibles.
- La entrada unificada DICOM/NIfTI tiene pruebas de integración pero no una auditoría adversarial independiente.
- No hay ejecutable para Linux ni macOS (allí la GUI se ejecuta desde el código fuente); el ejecutable de Windows no está firmado.
