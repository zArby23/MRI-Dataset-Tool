# MRI-Dataset-Tool
# *Esp*

## Descripción

Proyecto académico que carga estudios MRI y los estructura en _datasets_ compatibles con _ML/DL_ utilizando Python.

## Objetivo

Automatizar la carga, validación, conversión, procesamiento, anonimización, etiquetado y organización de estudios MRI.

## Technologias

- `pydicom`
- `NiBabel`
- `NumPy`
- `SciPy`

## Instalación

**Requisito:** Python 3.14 o superior. Verifica la versión instalada:

```bash
python --version
```

1. Clona el repositorio y entra en su directorio:

   ```bash
   git clone https://github.com/zArby23/MRI-Dataset-Tool.git
   cd MRI-Dataset-Tool
   ```

2. Crea un entorno virtual:

   ```bash
   python -m venv .venv
   ```

3. Actívalo según tu sistema operativo:

   Windows PowerShell:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   Windows Command Prompt:

   ```bat
   .venv\Scripts\activate.bat
   ```

   Linux o macOS (usando Bash):

   ```bash
   source .venv/bin/activate
   ```

   Linux (usando Fish):
   ```bash
   source .venv/bin/activate.fish
   ```

4. Instala el proyecto y las dependencias de desarrollo:

   ```bash
   python -m pip install --upgrade pip
   python -m pip install -e ".[dev]"
   ```

   La opción `-e` instala el proyecto en modo editable: los cambios en `src/` quedan disponibles sin reinstalarlo. Para instalar solo las dependencias de ejecución, usa `python -m pip install -e .`.

5. Verifica la instalación ejecutando las pruebas:

   ```bash
   python -m pytest
   ```

## Requisitos funcionales y no funcionales.

Estos se encuentran en los siguientes enlaces:
- **[Requisitos Funcionales](/docs/requierments/functional_requierments.md)**
- **[Requisitos No Funcionales](/docs/requierments/non_functional_requirements.md)**

## Estado

En desarrollo.

---
# *Eng*

## Description

Academic project that loads MRI studies and formats them into compatible ML/DL datasets using Python.

## Objective

Automate loading, validation, convertion, processing, anonymization, labeling and structure of MRI studies.

## Technologies

- pydicom
- NiBabel
- NumPy
- SciPy

## Installation

**Requirement:** Python 3.14 or later. Check the installed version:

```bash
python --version
```

1. Clone the repository and enter its directory:

   ```bash
   git clone https://github.com/zArby23/MRI-Dataset-Tool.git
   cd MRI-Dataset-Tool
   ```

2. Create a virtual environment:

   ```bash
   python -m venv .venv
   ```

3. Activate it for your operating system:

   Windows PowerShell:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   Windows Command Prompt:

   ```bat
   .venv\Scripts\activate.bat
   ```

   Linux or macOS (using Bash):

   ```bash
   source .venv/bin/activate
   ```

   Linux (using Fish):
   ```bash
   source .venv/bin/activate.fish

4. Install the project and development dependencies:

   ```bash
   python -m pip install --upgrade pip
   python -m pip install -e ".[dev]"
   ```

   The `-e` option installs the project in editable mode, so changes in `src/` are available without reinstalling. To install only runtime dependencies, use `python -m pip install -e .`.

5. Verify the installation by running the tests:

   ```bash
   python -m pytest
   ```

## Functional and non functional requierements

These are found on the following links:
- **[Functional Requirements (ESP)](/docs/requierments/functional_requierments.md)**
- **[Non Functional Requirements (ESP)](/docs/requierments/non_functional_requirements.md)**

## Status

In development. 
