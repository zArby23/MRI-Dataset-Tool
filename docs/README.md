# Documentación

| Carpeta | Qué contiene |
|---|---|
| [`requierments/`](requierments/) | Requisitos funcionales (RF01 a RF22) y no funcionales (RNF01 a RNF16). El nombre de la carpeta se conserva. |
| [`architecture/`](architecture/) | [Visión general](architecture/overview.md), [pipeline](architecture/pipeline.md), [configuración](architecture/config.md), [línea de comandos](architecture/cli.md), [GUI y ejecutable](architecture/gui.md) y [decisiones de diseño](architecture/design_decisions.md). |
| [`user_manual/`](user_manual/) | Manuales de usuario de la [GUI](user_manual/gui.md) y de la [línea de comandos](user_manual/cli.md). |
| [`dicom/`](dicom/) | Lectores DICOM, construcción de volúmenes, escritor y conversión. |
| [`nifti/`](nifti/nifti.md) | Lectura, lote, escritura y uso de NIfTI. |
| [`bids/`](bids/) | Lectores BIDS y herencia de sidecars. |
| [`processing/`](processing/) | Geometría (reorientar, remuestrear) e intensidad (normalizar). |
| [`anonymization/`](anonymization/policy.md) | Política de anonimización v1 y riesgo residual. |
| [`dataset/`](dataset/) | Estructura BIDS, entrada unificada, etiquetas, exportes para ML y reporte. |
| [`testing/`](testing/README.md) | Guía de pruebas e informes de auditoría por etapa. |

Para instalar y empezar, vea el [`README.md`](../README.md) de la raíz.
