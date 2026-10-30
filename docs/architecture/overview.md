# Visión general de la arquitectura

El paquete vive en `src/mri_dataset_tool/` (layout `src` de setuptools) y se organiza en cuatro capas. Cada capa solo
depende de las de más abajo; la presentación nunca contiene lógica de negocio.

```
presentation/   cli/ (mri-dataset)         gui/ (mri-dataset-gui)
      │                    │                       │
application/    services/ (casos de uso)    pipeline/ (pasos, runner, manifiesto)
      │
infrastructure/ dicom/  nifti/  bids/  dataset/  processing/  anonymization/  config/  logging/
      │
domain/         models/ (MRIStudy, MRISeries, StepRecord, StudyReport)
```

| Capa | Responsabilidad | No debe |
|---|---|---|
| `domain/` | Modelos independientes de formatos, librerías y de la interfaz. Solo stdlib y `numpy` como tipo. | Importar `pydicom` ni `nibabel`. |
| `infrastructure/` | Adaptadores concretos: leer y escribir DICOM, NIfTI y BIDS; procesar volúmenes; anonimizar; escribir el dataset. Devuelve modelos del dominio. | Importar `application` ni `presentation`. |
| `application/` | Casos de uso y pipelines: orquesta lectores, pasos y escritores. | Contener detalles de formato ni de pantalla. |
| `presentation/` | CLI (`argparse`) y GUI (Tkinter): validan la entrada, llaman a un servicio y muestran estados y conteos. | Contener lógica de negocio. |

## Modelos del dominio

- `MRIStudy(study_uid, series, subject_id, session_id)` y `MRISeries(series_uid, modality, files, metadata, volume)`.
  `study_uid` es `None` para NIfTI y BIDS; `volume` es un `ndarray` o un objeto tipo arreglo perezoso (`VolumeLike`, p. ej. el
  proxy de nibabel).
- **Geometría canónica:** toda serie con volumen lleva en `metadata` `shape`, `voxel_size`, `affine` (4×4, RAS+,
  convención NIfTI) y `orientation`. Los escritores consumen solo este contrato.
- `StepRecord` y `StudyReport` (`domain/models/transformation.py`) registran cada transformación para el manifiesto.

## Flujo de datos

```
DICOM / NIfTI / BIDS ──lector──► MRIStudy ──pasos del pipeline──► MRIStudy ──escritor──► NIfTI / BIDS / DICOM
                                    │                                  │
                          validate, anonymize,                  dataset BIDS, etiquetas,
                          reorient, resample, normalize         particiones, índices ML, reporte
```

- Los lotes se procesan **de a un estudio** (streaming): no se cargan todos los volúmenes a la vez (RNF02).
- Un fallo aislado se informa (`on_error`) y el lote continúa (RF16). Los mensajes de error son fijos y no incluyen rutas,
  UIDs ni valores de cabeceras.
- Cada corrida deja un manifiesto JSON con la configuración, las versiones y los pasos, que permite reproducirla (RNF11).

## Dónde está cada cosa

| Tema | Código | Documento |
|---|---|---|
| Lectores DICOM, volúmenes y escritor | `infrastructure/dicom/` | `docs/dicom/` |
| Lectores y escritor NIfTI | `infrastructure/nifti/` | `docs/nifti/nifti.md` |
| Lectores BIDS | `infrastructure/bids/` | `docs/bids/` |
| Conversión DICOM ↔ NIfTI | `application/services/conversion.py` | `docs/dicom/conversion.md` |
| Pasos de procesamiento | `infrastructure/processing/`, `application/pipeline/steps/` | `docs/processing/`, `docs/architecture/pipeline.md` |
| Anonimización | `infrastructure/anonymization/`, `application/services/anonymize.py` | `docs/anonymization/policy.md` |
| Dataset, etiquetas, particiones, reportes | `infrastructure/dataset/`, `application/services/{dataset,labels,dataset_report}.py` | `docs/dataset/` |
| Entrada unificada DICOM/NIfTI → BIDS | `application/services/dataset_ingest.py`, `infrastructure/dataset/suffix_rules.py` | `docs/dataset/ingest.md` |
| Configuración YAML | `infrastructure/config/loader.py`, `config/*.yaml` | `docs/architecture/config.md` |
| Línea de comandos | `presentation/cli/` | `docs/architecture/cli.md`, `docs/user_manual/cli.md` |
| Interfaz gráfica y ejecutable de Windows | `presentation/gui/`, `packaging/` | `docs/architecture/gui.md`, `docs/user_manual/gui.md` |
| Decisiones de diseño y sus límites | — | `docs/architecture/design_decisions.md` |

## Reglas que cruzan las capas

- **Privacidad (RNF07, RNF15):** ningún mensaje, log, reporte ni salida lleva datos de pacientes, rutas, UIDs ni valores de
  cabeceras. La clave de anonimización (`MRI_ANON_KEY`) nunca se guarda ni se registra.
- **No destructivo (RNF13):** no se sobrescriben entradas ni salidas; las salidas se escriben de forma atómica en carpetas
  nuevas o vacías.
- **Validar antes de crear:** los argumentos, la clave y la configuración se comprueban antes de escribir nada.
- **Pruebas:** ver `docs/testing/README.md`.
