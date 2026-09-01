# MRI Dataset Tool

Academic project for loading MRI studies and structuring them into ML/DL-ready datasets using Python.

## Overview

This tool automates the loading, validation, conversion, processing, anonymization, labeling, and organization of MRI studies.

## Features

- DICOM study loading
- NIfTI dataset handling
- Batch processing support
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

## Status

In development.

---

# MRI Dataset Tool

Proyecto académico para cargar estudios de resonancia magnética y estructurarlos en datasets compatibles con ML/DL usando Python.

## Descripción

La herramienta automatiza la carga, validación, conversión, procesamiento, anonimización, etiquetado y organización de estudios MRI.

## Características

- Carga de estudios DICOM
- Manejo de datasets NIfTI
- Soporte para procesamiento por lotes
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

## Estado

En desarrollo.
