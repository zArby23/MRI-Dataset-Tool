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
- Processing pipeline core: step contract, streaming batch runner that reports errors and continues, JSON run manifest that records each step's parameters and computed outputs and reproduces a run
- Processing steps: integrity validation, reorientation to RAS+ (no interpolation), resampling to a fixed spacing (default 1 mm, linear), intensity normalization, and a technical metadata summary
- Anonymization (in development, tested only with synthetic data): model anonymization step and DICOM file anonymization with a version 1 policy and an audit report
- Lazy NIfTI loading (`lazy=True`) for batches
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
- [Processing steps: geometry](/docs/processing/geometry.md) and [intensity](/docs/processing/intensity.md)
- [Anonymization policy](/docs/anonymization/policy.md)

## Status

In development. Loading (DICOM, NIfTI, BIDS), DICOM <-> NIfTI conversion and the processing pipeline core (step contract, batch runner, run manifest, YAML configuration) are implemented as library code under `src/mri_dataset_tool`. Processing steps (validation, anonymization, reorientation, resampling, normalization) are implemented and run through `scripts/run_stage3_pipeline.py` (it needs the `MRI_ANON_KEY` environment variable, at least 32 characters); visual checks of their output are pending. Anonymization has been tested only with synthetic data, does not remove faces or text burned into pixels, and keeps quasi-identifiers (year, age range, sex, scanner model): review the report and the output before sharing real data. There is no CLI or GUI. The generated DICOM does not conform to the strict MR IOD, and visual checks of converted volumes are pending.

---

# MRI Dataset Tool

Proyecto académico para cargar estudios de resonancia magnética y estructurarlos en datasets compatibles con ML/DL usando Python.

## Descripción

La herramienta automatiza la carga, validación, conversión, procesamiento, anonimización, etiquetado y organización de estudios MRI.

## Características

- Carga de estudios DICOM
- Manejo de datasets NIfTI
- Soporte para procesamiento por lotes
- Núcleo del pipeline de procesamiento: contrato de paso, runner por lotes en streaming que informa errores y continúa, manifiesto JSON que registra parámetros y valores calculados de cada paso y reproduce una corrida
- Pasos de procesamiento: validación de integridad, reorientación a RAS+ (sin interpolar), remuestreo a un espaciado fijo (1 mm por defecto, lineal), normalización de intensidad y resumen técnico de metadatos
- Anonimización (en desarrollo, probada solo con datos sintéticos): paso sobre el modelo y anonimización de archivos DICOM con la política v1 e informe de auditoría
- Carga perezosa de NIfTI (`lazy=True`) para lotes
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
- [Pasos de procesamiento: geometría](/docs/processing/geometry.md) e [intensidad](/docs/processing/intensity.md)
- [Política de anonimización](/docs/anonymization/policy.md)

## Estado

En desarrollo. La carga (DICOM, NIfTI, BIDS), la conversión DICOM <-> NIfTI y el núcleo del pipeline de procesamiento (contrato de paso, runner por lotes, manifiesto de corrida, configuración YAML) están implementados como código de biblioteca en `src/mri_dataset_tool`. Los pasos de procesamiento (validación, anonimización, reorientación, remuestreo, normalización) están implementados y se ejecutan con `scripts/run_stage3_pipeline.py` (requiere la variable de entorno `MRI_ANON_KEY`, de al menos 32 caracteres); la verificación visual de su salida está pendiente. La anonimización se ha probado solo con datos sintéticos, no borra caras ni texto quemado en los píxeles y conserva cuasi-identificadores (año, rango de edad, sexo, modelo de escáner): revisa el informe y la salida antes de compartir datos reales. No hay CLI ni GUI. El DICOM generado no es conforme al IOD MR estricto y la verificación visual de los volúmenes convertidos está pendiente.
