# Requisitos funcionales

Estos requisitos son obligatorios para el correcto funcionamiento del sistema.

| Requisito | Descripción | Categoría |
| :---: | :---: | :---: |
| RF01 | El sistema debe permitir cargar estudios MRI individuales o por lote en formato `DICOM`. | Carga |
| RF02 | El sistema debe permitir cargar estudios MRI en formato `NIfTI`. | Carga |
| RF03 | El sistema debe validar la integridad de los archivos cargados y detectar archivos corruptos o incompletos. | Validación |
| RF04 | El sistema debe extraer y mostrar los metadatos relevantes de cada estudio. | Validación |
| RF05 | El sistema debe convertir estudios MRI en formato `DICOM` a `NIfTI`. | Conversión |
| RF06 | El sistema debe normalizar la intensidad de las imágenes. | Normalización |
| RF07 | El sistema debe reorientar los volúmenes a un sistema de coordenadas estándar definido para el procesamiento. | Normalización |
| RF08 | El sistema debe realizar remuestreo _(resampling)_ para homogenizar resolución y espaciado entre estudios de distintas fuentes. | Normalización |
| RF09 | El sistema debe anonimizar o eliminar los metadatos sensibles del paciente presentes en los archivos `DICOM`. | Anonimización |
| RF10 | El sistema debe organizar los estudios procesados en una estructura de carpetas estandarizada, siguiendo la organización BIDS. | Organización |
| RF11 | El sistema debe permitir asignar etiquetas/clases a cada estudio. | Etiquetado |
| RF12 | El sistema debe permitir revisar y corregir etiquetas antes de finalizar el dataset. | Validación |
| RF13 | El sistema debe exportar el ***dataset*** final en un formato compatible con _frameworks_ de _ML/DL_ y herramientas de procesamiento de neuroimágen (dataset BIDS con NIfTI, particiones y archivos de índice para ML/DL). | Exportación |
| RF14 | El sistema debe generar un reporte/resumen estadístico del ***dataset*** en formatos JSON, Markdown, XML y XLSX. | Evaluación |
| RF15 | El sistema debe registrar cada transformación aplicada a un estudio. | Evaluación |
| RF16 | El sistema debe informar al usuario los errores encontrados durante el procesamiento y permitir continuar con los estudios restantes cuando el error no comprometa la ejecución general. | Evaluación |
| RF17 | El sistema debe cargar datasets organizados en BIDS (un archivo, un sujeto/sesión o un dataset completo), incluyendo la herencia de los metadatos de los archivos `.json` asociados. | Carga |
| RF18 | El sistema debe convertir estudios `NIfTI` a `DICOM`, además de `DICOM` a `NIfTI` (RF05), conservando la geometría del volumen. | Conversión |
| RF19 | El sistema debe construir un dataset BIDS anonimizado a partir de `DICOM`, `NIfTI` o BIDS con una sola operación, deduciendo participante, sesión y tipo de imagen con reglas conservadoras, omitiendo con aviso lo dudoso y permitiendo corregirlo con una tabla de mapeo. | Organización |
| RF20 | El sistema debe ofrecer una interfaz de línea de comandos (`mri-dataset`) que cubra la inspección, conversión, anonimización, procesamiento, etiquetado y construcción del dataset. | Interfaz |
| RF21 | El sistema debe ofrecer una interfaz gráfica guiada (`mri-dataset-gui`, en español e inglés) que recorra el flujo completo: entrada, configuración, mapeo de series, ejecución, etiquetas, exportes y reporte. | Interfaz |
| RF22 | El sistema debe poder distribuirse como un ejecutable portable de Windows que no requiera instalar Python. | Distribución |

---
