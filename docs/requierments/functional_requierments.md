# Requisitos funcionales

Este es el resúmen de los requsitos funcionales, que son obligatorios para el correcto funcionamiento del sistema.

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
| RF10 | El sistema debe organizar los estudios procesados en una estructura de carpetas estandarizada. | Organización |
| RF11 | El sistema debe permitir asignar etiquetas/clases a cada estudio. | Etiquetado |
| RF12 | El sistema debe permitir revisar y corregir etiquetas antes de finalizar el dataset. | Validación |
| RF13 | El sistema debe exportar el ***dataset*** final en un formato compatible con _frameworks_ de _ML/DL_ y herramientas de procesamiento de neuroimágen. | Exportación |
| RF14 | El sistema debe generar un reporte/resumen estadístico del ***dataset***. | Evaluación |
| RF15 | El sistema debe registrar cada transformación aplicada a un estudio. | Evaluación |
| RF16 | El sistema debe informar al usuario los errores encontrados durante el procesamiento y permitir continuar con los estudios restantes cuando el error no comprometa la ejecución general. | Evaluación |

---
