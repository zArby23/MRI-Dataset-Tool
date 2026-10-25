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
- [Stage 3 QA report](/docs/testing/qa_etapa3.md)

## Status

In development. Stages 1 to 4 (loading, conversion, pipeline, processing, anonymization and dataset) are complete. Stage 5A adds the `mri-dataset` command line (inspect, convert, anonymize, process, labels, dataset); see `docs/user_manual/cli.md` and `docs/architecture/cli.md`. Pending: GUI (5B) and closing (stage 6).

**Implemented** (library code under `src/mri_dataset_tool`)
- Loading of DICOM, NIfTI and BIDS studies, and DICOM <-> NIfTI conversion.
- Processing pipeline core: step contract, batch runner, run manifest and YAML configuration.
- Processing steps: validation, anonymization, reorientation, resampling and normalization.
- Dataset: BIDS writer, labels with review, correction and closing, train/val/test splits by participant, ML/DL index files (`dataset_index.csv`, `datalist.json`) and a statistical report in JSON, Markdown, XML and XLSX.

**How to run**
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
- Stages 3 and 4 were audited with synthetic data and with the local test datasets.
- The NIfTI output was checked in a viewer.
- Still pending: runs on Linux and with compressed DICOM.

**Limits**
- Anonymization does not remove faces or text burned into the pixels.
- It keeps quasi-identifiers (year, age range, sex, scanner model).
- Review the report and the output before sharing real data.
- The generated DICOM does not conform to the strict MR IOD.
- Visual checks of converted DICOM volumes are pending.
- The exported dataset has no `.bval`/`.bvec` for `dwi` and no `EchoTime1/2` for `phasediff`: the official BIDS validator will flag them.
- Labels are assigned through files; there is no review interface yet.

**Not implemented yet**
- GUI.

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
- [Informe de QA de la etapa 3](/docs/testing/qa_etapa3.md)

## Estado

En desarrollo. Las etapas 1 a 4 (carga, conversión, pipeline, procesamiento, anonimización y dataset) están completas. La etapa 5A añade la línea de comandos `mri-dataset` (inspect, convert, anonymize, process, labels, dataset); ver `docs/user_manual/cli.md` y `docs/architecture/cli.md`. Pendiente: GUI (5B) y cierre (etapa 6).

**Implementado** (código de biblioteca en `src/mri_dataset_tool`)
- Carga de estudios DICOM, NIfTI y BIDS, y conversión DICOM <-> NIfTI.
- Núcleo del pipeline de procesamiento: contrato de paso, runner por lotes, manifiesto de corrida y configuración YAML.
- Pasos de procesamiento: validación, anonimización, reorientación, remuestreo y normalización.
- Dataset: escritura en formato BIDS, etiquetas con revisión, corrección y cierre, particiones train/val/test por participante, índices para ML/DL (`dataset_index.csv`, `datalist.json`) y reporte estadístico en JSON, Markdown, XML y XLSX.

**Cómo ejecutar**
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
- Las etapas 3 y 4 se auditaron con datos sintéticos y con los datasets locales de prueba.
- La salida NIfTI se revisó en un visor.
- Siguen pendientes las corridas en Linux y con DICOM comprimido.

**Límites**
- La anonimización no borra caras ni texto quemado en los píxeles.
- Conserva cuasi-identificadores (año, rango de edad, sexo, modelo de escáner).
- Revisa el informe y la salida antes de compartir datos reales.
- El DICOM generado no es conforme al IOD MR estricto.
- La verificación visual de los volúmenes DICOM convertidos está pendiente.
- El dataset exportado no incluye `.bval`/`.bvec` para `dwi` ni `EchoTime1/2` para `phasediff`: el validador oficial de BIDS los marcará.
- Las etiquetas las asigna el usuario por archivos; no hay interfaz de revisión todavía.

**Todavía no implementado**
- GUI.
