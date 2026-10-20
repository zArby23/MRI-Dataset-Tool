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
- Processing pipeline core: step contract, streaming batch runner that reports errors and continues, JSON run manifest to reproduce a run
- YAML configuration (default < environment < run file)
- Data validation and organization
- Preparation for ML/DL pipelines

## Requirements

- Python 3.14 or newer
- pip
- Virtual environment support

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
source .venv/bin/activate.fish
```

3. Install the project and development dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

4. Verify the installation:

```bash
python -m pytest
```

## Documentation

- [Functional requirements](/docs/requierments/functional_requierments.md)
- [Non-functional requirements](/docs/requierments/non_functional_requirements.md)
- [Pipeline architecture](/docs/architecture/pipeline.md)
- [Configuration](/docs/architecture/config.md)

## Status

In development. Loading (DICOM, NIfTI, BIDS), DICOM <-> NIfTI conversion and the processing pipeline core (step contract, batch runner, run manifest, YAML configuration) are implemented as library code under `src/mri_dataset_tool`. No real processing steps exist yet (normalization, reorientation, resampling and anonymization come in stage 3), and there is no CLI or GUI. The generated DICOM does not conform to the strict MR IOD, and visual checks of converted volumes are pending.

---

# MRI Dataset Tool

Proyecto académico para cargar estudios de resonancia magnética y estructurarlos en datasets compatibles con ML/DL usando Python.

## Descripción

La herramienta automatiza la carga, validación, conversión, procesamiento, anonimización, etiquetado y organización de estudios MRI.

## Características

- Carga de estudios DICOM
- Manejo de datasets NIfTI
- Soporte para procesamiento por lotes
- Núcleo del pipeline de procesamiento: contrato de paso, runner por lotes en streaming que informa errores y continúa, manifiesto JSON para reproducir una corrida
- Configuración YAML (default < entorno < archivo de corrida)
- Validación y organización de datos
- Preparación para pipelines de ML/DL

## Requisitos

- Python 3.14 o superior
- pip
- Soporte para entornos virtuales

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
source .venv/bin/activate.fish
```

3. Instala las dependencias del proyecto:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

4. Verifica la instalación:

```bash
python -m pytest
```

## Documentación

- [Requisitos funcionales](/docs/requierments/functional_requierments.md)
- [Requisitos no funcionales](/docs/requierments/non_functional_requirements.md)
- [Arquitectura del pipeline](/docs/architecture/pipeline.md)
- [Configuración](/docs/architecture/config.md)

## Estado

En desarrollo. La carga (DICOM, NIfTI, BIDS), la conversión DICOM <-> NIfTI y el núcleo del pipeline de procesamiento (contrato de paso, runner por lotes, manifiesto de corrida, configuración YAML) están implementados como código de biblioteca en `src/mri_dataset_tool`. Aún no hay pasos de procesamiento reales (normalización, reorientación, remuestreo y anonimización llegan en la etapa 3), ni CLI ni GUI. El DICOM generado no es conforme al IOD MR estricto y la verificación visual de los volúmenes convertidos está pendiente.
