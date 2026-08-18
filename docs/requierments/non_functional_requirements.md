| Requisito | Descripción | Categoría |
| :---: | :---: | :---: |
| RNF01 | El sistema debe procesar los estudios MRI de acuerdo con los tiempos de ejecución establecidos durante las pruebas del proyecto. | Rendimiento |
| RNF02 | El sistema debe permitir el procesamiento de estudios de manera individual o por lotes sin requerir que todos los volúmenes sean cargados simultáneamente en memoria. | Escalabilidad |
| RNF03 | La interfaz del sistema debe presentar las operaciones, estados de procesamiento, resultados y errores de forma comprensible para el usuario. | Usabilidad |
| RNF04 | El sistema debe poder ejecutarse en los sistemas operativos definidos como objetivo del proyecto, incluyendo Windows y Linux. | Portabilidad |
| RNF05 | El código fuente debe estar organizado de forma modular, separando las responsabilidades de carga, validación, conversión, procesamiento, anonimización, etiquetado y exportación. | Mantenibilidad |
| RNF06 | El sistema debe manejar errores de lectura, conversión y procesamiento evitando cierres inesperados de la aplicación. | Confiabilidad |
| RNF07 | El sistema debe proteger la información sensible de los estudios médicos y evitar la exposición de datos personales en los archivos procesados y generados. | Seguridad |
| RNF08 | El sistema debe mantener compatibilidad con los estándares y formatos de neuroimagen definidos para el proyecto, principalmente `DICOM` y `NIfTI`. | Compatibilidad |
| RNF09 | Los archivos generados por el sistema deben poder ser utilizados por bibliotecas y herramientas habituales para el procesamiento de neuroimágenes y aprendizaje automático. | Interoperabilidad |
| RNF10 | El proyecto debe incluir documentación técnica y de usuario que describa la instalación, configuración, ejecución, arquitectura y funcionalidades principales del sistema. | Documentación |
| RNF11 | El sistema debe registrar las configuraciones y transformaciones aplicadas durante el procesamiento para permitir reproducir el proceso sobre los mismos datos y parámetros. | Reproducibilidad |
| RNF12 | El sistema debe priorizar el uso de tecnologías y bibliotecas de código abierto compatibles con el carácter académico del proyecto. | Licenciamiento |
