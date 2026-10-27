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
- Graphical wizard `mri-dataset-gui` (Tkinter, Spanish and English): input (BIDS, DICOM or loose NIfTI) → configuration → series mapping table → background run → label table with batch tools → ML exports and report; same validation and outputs as the command line, no patient data on screen or in logs
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

4. Launch the graphical interface (on Linux, Tkinter may need the system package `python3-tk`):

```bash
mri-dataset-gui
# or: python -m mri_dataset_tool.presentation.gui
```

5. Verify the installation:

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
- [GUI user manual](/docs/user_manual/gui.md) and [GUI architecture](/docs/architecture/gui.md)
- [Stage 3 QA report](/docs/testing/qa_etapa3.md)

## Status

In development. Stages 1 to 4 (loading, conversion, pipeline, processing, anonymization and dataset) are complete. Stage 5A adds the `mri-dataset` command line (inspect, convert, anonymize, process, labels, dataset); see `docs/user_manual/cli.md` and `docs/architecture/cli.md`. Stage 5B adds the `mri-dataset-gui` graphical wizard (six steps: input, configuration, series mapping, run, labels, ML exports and report); see `docs/user_manual/gui.md` and `docs/architecture/gui.md`. Pending: visual styling (stage 5C), a portable Windows executable and closing (stage 6).

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
- Still pending: runs on Linux and with compressed DICOM.

**Limits**
- Anonymization does not remove faces or text burned into the pixels.
- It keeps quasi-identifiers (year, age range, sex, scanner model).
- Review the report and the output before sharing real data.
- The generated DICOM does not conform to the strict MR IOD.
- Visual checks of converted DICOM volumes are pending.
- The exported dataset has no `.bval`/`.bvec` for `dwi` and no `EchoTime1/2` for `phasediff`: the official BIDS validator will flag them.
- Labels are assigned through files, the `--mapping` table or the label table of the GUI (with batch tools).
- The GUI generates a new anonymization key per session unless `MRI_ANON_KEY` is set: pseudonyms change between sessions and datasets from different sessions must not be combined.
- With very large DICOM trees the GUI preview and run steps can take more than 15 minutes, without cancellation.
- The BIDS suffix of DICOM and loose NIfTI series is deduced with conservative rules: doubtful series are skipped with a warning and can be fixed with the `--mapping` table.
- Files that are git-annex pointers without downloaded content are skipped as unreadable.

**Not implemented yet**
- Visual styling of the GUI and a portable executable (Windows).

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
- Asistente gráfico `mri-dataset-gui` (Tkinter, en español e inglés): entrada (BIDS, DICOM o NIfTI sueltos) → configuración → tabla de mapeo de series → ejecución en segundo plano → tabla de etiquetas con herramientas en lote → exportes para ML y reporte; las mismas validaciones y salidas que la línea de comandos, sin datos de pacientes en pantalla ni en logs
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

4. Abre la interfaz gráfica (en Linux, Tkinter puede necesitar el paquete del sistema `python3-tk`):

```bash
mri-dataset-gui
# o: python -m mri_dataset_tool.presentation.gui
```

5. Verifica la instalación:

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

En desarrollo. Las etapas 1 a 4 (carga, conversión, pipeline, procesamiento, anonimización y dataset) están completas. La etapa 5A añade la línea de comandos `mri-dataset` (inspect, convert, anonymize, process, labels, dataset); ver `docs/user_manual/cli.md` y `docs/architecture/cli.md`. La etapa 5B añade el asistente gráfico `mri-dataset-gui` (seis pasos: entrada, configuración, mapeo de series, ejecución, etiquetas, exportes para ML y reporte); ver `docs/user_manual/gui.md` y `docs/architecture/gui.md`. Pendiente: estilo visual (etapa 5C), ejecutable portable de Windows y cierre (etapa 6).

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
- Siguen pendientes las corridas en Linux y con DICOM comprimido.

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
- Con árboles DICOM muy grandes, la vista previa y la ejecución de la GUI pueden tardar más de 15 minutos, sin cancelación.

**Todavía no implementado**
- Estilo visual de la GUI y ejecutable portable (Windows).
