# QA9: auditoría del ejecutable portable de Windows (etapa 5D)

Esta auditoría se hizo el 2026-10-30 sobre la rama `etapa-5d-exe` (commits `0337eba` y `1a4cd51`).
El objeto auditado es el primer bundle compilado: la carpeta `onedir` `MRI-Dataset-Tool/` (136 MB) y su `.zip` (58 MB), que
se compilaron con `packaging/build_exe.py` (PyInstaller 6.22.3, Python 3.14.4). El recorrido con el bundle
(`walk.py`/`compare.py`, fuera del repositorio) no se repite: se reutiliza y se amplía.

Pruebas en `tests/qa/test_qa9_bundle.py`. Hay dos pruebas que siempre se ejecutan: usan `monkeypatch` para simular
el modo congelado y no necesitan PyInstaller. Las otras tres auditan un bundle real y solo se ejecutan si
`MRI_QA9_BUNDLE` apunta a `dist/MRI-Dataset-Tool` (en Windows). Sin esa variable se omiten.

Las sondas exploratorias no forman parte de la suite y están en `E:/mri_qa9/tools/`:
- `sweep.py`: barrido de cadenas.
- `qa9_probe.py`: recorrido BIDS y consulta de la configuración, congelados con las mismas opciones que
  `build_exe.py` (con consola).
- `run_probe.py`: ejecuta un exe en un entorno limpio y anota dónde escribe.
- `launch_close.py`: abre el exe real, espera su ventana y la cierra con `WM_CLOSE`.

QA no tocó código de producción. Todos los valores son sintéticos y no se usaron datos reales. Las compilaciones y
los temporales están en `E:/mri_qa9/`.

Resultado: `test_qa9_bundle.py` con el bundle da 5 passed; sin el bundle, 2 passed y 3 skipped. Junto con
`tests/unit/test_service_inputs.py` dan 44 passed. La suite completa no se corrió en esta auditoría.

## 1. Hallazgos

No hay bloqueantes.

| Id | Severidad | Qué pasa | Reproducción mínima (sin PHI) | Esperado | Archivo / dueño | Estado |
|---|---|---|---|---|---|---|
| QA9-01 | importante (redistribución) | El bundle solo trae los avisos de licencia de los 4 paquetes de `copy_metadata` (mri-dataset-tool, numpy, nibabel, pydicom) y `_tk_data/license.terms`. Faltan los de scipy, con las bibliotecas que incluye en `scipy.libs` (OpenBLAS y otras), PyYAML, psutil, openpyxl y et_xmlfile, CPython (PSF), OpenSSL (`libssl`/`libcrypto`), libffi, requests, urllib3, certifi, idna, charset_normalizer, cffi y pycparser. Las licencias BSD/MIT/PSF/Apache exigen reproducir el aviso en las distribuciones binarias. No afecta al funcionamiento | `find _internal -iname "*licen*"`: solo aparecen los 4 `dist-info` y Tk | Que el `.zip` lleve los avisos de terceros: `copy_metadata` de los paquetes que faltan (sus `dist-info` llevan la licencia) o un `THIRD_PARTY_NOTICES` generado al compilar | `packaging/build_exe.py` (@empaque); decide @orquestador o el humano | Abierto |
| QA9-02 | menor (RNF04, RNF10) | El bundle no arranca si se descomprime en una carpeta muy profunda. (a) Con la ruta del exe por encima de 260 caracteres, `CreateProcess` falla (`WinError 206`). Es un límite de Windows y el Explorador tampoco lo abre. (b) Con la ruta de `_internal\python314.dll` por encima de 260, el bootloader da «Failed to load Python DLL … LoadLibrary: The filename or extension is too long». Con el exe en ventana se ve como un cuadro de error. En este equipo (`LongPathsEnabled=1`) funcionan una carpeta padre de 175 caracteres, con DLL internas de 264, y salidas de más de 300 caracteres. Con `LongPathsEnabled=0`, que es lo habitual, el límite probablemente baja a que la DLL más larga (`numpy.libs\libscipy_openblas64_-…dll`, 95 caracteres relativos) quepa en 260: la carpeta padre tendría que medir menos de ~165. Esto no está verificado | Copiar el bundle bajo una carpeta de 230 caracteres y ejecutarlo; sonda `run_probe.py` con `E:/mri_qa9/long2` | Que el manual diga que se descomprima en una ruta corta (p. ej. `C:\MRI-Dataset-Tool` o el Escritorio) | `docs/user_manual/gui.md` (@empaque, P5) | Abierto (documentación) |
| QA9-03 | menor (tamaño) | El bundle incluye paquetes que la GUI no usa. Entran por imports opcionales: requests, urllib3, certifi, idna, charset_normalizer y `_ssl` con `libssl`/`libcrypto` (por `pydicom.data.download`); unittest, doctest y pdb (por `numpy.testing` y `nibabel.optpkg`); setuptools (por el runtime hook `pyi_rth_setuptools` y cffi); cffi y pycparser. En `_internal` suman ~6,7 MB de 136, más sus módulos dentro del PYZ. El tamaño ya es razonable (136 MB, frente a la estimación de 150–250 MB), así que no es necesario quitarlos | `xref-MRI-Dataset-Tool.html` de `build/` (quién importa cada módulo) | Opcional: `--exclude-module` de requests/urllib3 y volver a hacer el humo y el recorrido. Cada exclusión puede romper un import perezoso | `packaging/build_exe.py` (@empaque) | Abierto (opcional) |
| QA9-04 | menor (RNF03) | Sin `config/` en el bundle (`_internal/config` borrado), el exe no se cierra ni crea nada. Se queda en el paso 1 con «No se encuentra el archivo de configuración.» (`CONFIG_NOT_FOUND`), aunque en el paso 2 se podría elegir una configuración externa. Además, en ese caso `project_config_dir()` recurre a `config/` del directorio de trabajo: con doble clic, una carpeta `config/` junto al exe se usaría en silencio. Es el diseño de P1 (docstring de `project_config_dir`) y solo pasa si el usuario borra `_internal/config`. Con `config/` presente, la del bundle siempre gana sobre la del directorio de trabajo (`test_bundled_config_wins_over_one_in_the_working_directory`) | Sonda `qa9_probe.py config` con el bundle sin `_internal/config`; `test_no_config_anywhere_stops_the_input_step_and_creates_nothing` | Documentar en el manual que `_internal/config` no se toca. Cambiar el comportamiento, si se quisiera, es decisión de @orquestador | `docs/user_manual/gui.md` (@empaque, P5) | Abierto (documentación) |
| QA9-05 | menor (documentación) | La carpeta `spec/` que genera PyInstaller lleva rutas absolutas del equipo de desarrollo (3 coincidencias de la ruta del repositorio en `MRI-Dataset-Tool.spec`; también en el `MRI-Walk.spec` de P3). No se distribuye: el `.zip` tiene exactamente los 1146 archivos de `dist/MRI-Dataset-Tool/`, sin `.spec` ni `direct_url.json`. Como dato aparte, el `RECORD` de `mri_dataset_tool-0.1.0.dist-info` cita artefactos de la instalación editable (`__editable__…pth`, `../../Scripts/mri-dataset.exe`) sin rutas del equipo: es cosmético | `grep -c Degree_Project spec/*.spec` → 3; comparación de los miembros del zip con `dist/` | Decir en las instrucciones de compilación que solo se distribuye el `.zip` (ni `build/` ni `spec/`) | `docs/architecture/gui.md` (@empaque, P5) | Abierto (documentación) |

## 2. Qué se probó (pasa)

- **Barrido de cadenas del bundle.** Cubrí 2908 miembros: los archivos, los miembros de `base_library.zip`, las
  entradas del CArchive del exe y los 1613 módulos del PYZ. Los módulos se leyeron en bytes marshal, así que sus
  constantes de texto aparecen literales. Busqué, en UTF-8 y UTF-16LE:
  - rutas del repositorio y de las compilaciones (`Degree_Project`, `mri_build`, `mri_qa9`, la ruta absoluta del
    repositorio);
  - el nombre de la carpeta personal;
  - el usuario y el nombre del equipo de Windows (sensible a mayúsculas, porque son palabras cortas que aparecen
    en texto inglés);
  - la PHI plantada (`Planted`).

  `MRI_ANON_KEY` no estaba definida al compilar ni a nivel de usuario. La prueba la busca si está definida.

  Hay 0 coincidencias propias. Solo aparecen textos de terceros:
  - en `numpy.__config__`, la ruta del CI que compiló la rueda de numpy (`C:\Users\runneradmin\…`);
  - en `pydoc_data.topics`, ejemplos de la documentación de Python.

  Un control positivo confirmó que el barrido encuentra un texto del propio código dentro del PYZ. Los nombres de
  archivo internos son relativos (`co_filename` = `mri_dataset_tool\application\services\inputs.py`).
- **Contenido.** No hay `direct_url.json`, `.spec`, fuentes `.py` del proyecto ni carpetas `tests`. Están los
  `dist-info` con `METADATA` de los 4 paquetes de versión. `_internal/config/*.yaml` es idéntica byte a byte a
  `config/` del repositorio.
- **Tamaño.** 136 MB la carpeta y 58 MB el `.zip`. Lo más grande es scipy (50 MB), seguido de `numpy.libs` y
  `scipy.libs` (21 y 20 MB) y del exe (14 MB, porque lleva el PYZ). Primer nivel de `_internal`: el runtime de
  Python, Tcl/Tk, numpy, scipy, pydicom, yaml, psutil, certifi y charset_normalizer, más los `dist-info`.
- **Manifiesto del exe.** `asInvoker`, `longPathAware=true`, Common Controls 6 y subsistema GUI. No declara DPI:
  la conciencia de DPI la fija el código (`enable_dpi_awareness`). Congelado, la llamada devuelve éxito, el
  proceso queda «system DPI aware» (1) y `tk scaling` vale 1,333 a 100 %, lo mismo que desde el código fuente.
- **El exe real en un entorno limpio.** PATH solo con `System32` y `Windows`, sin `python` (comprobado con
  `where`), sin variables `PYTHON*`/`MRI_*`, TEMP/TMP redirigidas a una carpeta vigilada y un directorio de
  trabajo vacío. La ventana aparece en ~0,5 s con el título «MRI Dataset Tool - Paso 1 de 5: Entrada» y
  `WM_CLOSE` la cierra con código 0. No escribe nada en ninguno de estos sitios:
  - la carpeta del exe;
  - el directorio de trabajo;
  - TEMP;
  - el primer nivel del `%TEMP%` real, `%LOCALAPPDATA%`, `%APPDATA%` y la carpeta personal.

  Lo mismo pasa con el `.zip` descomprimido en `E:/mri_qa9/unzip ñandú 日本/`. Ahí el primer arranque tardó
  1,5 s en mostrar la ventana y a los 3 s aún no había terminado la carga inicial (el título seguía sin el paso),
  probablemente por el antivirus revisando las DLL nuevas. El segundo arranque tardó 0,5 s.
- **Recorrido BIDS sintético congelado** (sonda con las opciones de `build_exe.py`, en el mismo entorno limpio y
  con una clave centinela). Los seis pasos, con exportes ML y reporte, y 28 archivos de salida:
  - Solo escribe en la carpeta elegida: nada en TEMP, el directorio de trabajo, la carpeta del bundle ni las
    carpetas del perfil.
  - La configuración se lee de `_internal/config`.
  - El manifiesto lleva versiones reales: `mri_dataset_tool` 0.1.0, numpy 2.5.2, nibabel 5.4.2, pydicom 3.0.2 y
    python 3.14.4.
  - Comparado con el mismo recorrido desde el código fuente (misma clave): 30 archivos, 26 idénticos byte a byte.
    Los otros 4 difieren solo en marcas de tiempo: `run_manifest.json` (igual sin `timestamps`),
    `labels_changes.tsv` (columna `timestamp_utc`) y los dos `.xlsx` (no deterministas, ya documentado).
  - Barrido de las salidas: ni la clave, ni `Planted`, ni las rutas de la salida o del bundle.
- **Rutas con espacios, tildes y Unicode.** Bundle en `Carpeta con espacios ñandú 日本 é/` y salida en
  `r2 salida con tildes ñ 日本/`: el recorrido pasa y sus salidas coinciden con las del recorrido congelado
  normal (salvo marcas de tiempo).
- **Rutas largas.** Una salida de más de 300 caracteres pasa. Una carpeta del bundle de 175 caracteres, con DLL
  internas de más de 260, pasa en este equipo. Los límites están en QA9-02.
- **`config/` de solo lectura.** La copia del bundle tenía la ACL solo con lectura y ejecución para el usuario,
  como en `Program Files`, y los `.yaml` con el atributo de solo lectura. Se comprobó que la escritura estaba
  denegada. El recorrido completo pasa: el exe nunca escribe en su carpeta.
- **`config/` ausente.** Ver QA9-04: el exe no se cierra ni crea la salida, y muestra un mensaje fijo sin ruta.
- **Temporales del código** (revisión estática, no ejecutada con DICOM ni NIfTI). Los únicos usos de `tempfile`
  (`labels_table.py`, `infrastructure/dicom/writer.py`) y el TSV temporal de etiquetas de `dataset_build.py`
  escriben en carpetas que eligió el usuario, nunca en `%TEMP%`. No hay otro `__file__` que el de
  `project_config_dir`, y ese no se usa congelado.

## 3. Sospechas sin probar

- Con `LongPathsEnabled=0`, el límite de profundidad de la carpeta es probablemente menor (QA9-02) y las salidas de
  más de 260 caracteres fallarían. Lo segundo pasa igual desde el código fuente: no es propio del exe.
- El recorrido congelado solo usó BIDS. DICOM y NIfTI comparten los mismos servicios y la revisión estática no
  encontró escrituras en otros sitios, pero no lo ejecuté.
- La sonda congelada no es el binario distribuido: es la misma compilación con otra entrada y con consola. El exe
  distribuido solo se probó al arrancar y al cerrar, porque los clics quedan para la verificación manual.

## 4. Verificaciones manuales pendientes (humano)

1. Descomprimir el `.zip` en una máquina Windows limpia sin Python, ejecutarlo y hacer un recorrido completo con
   clics.
2. SmartScreen y el antivirus sobre el exe sin firmar, incluido el primer arranque, que fue más lento.
3. Escala de pantalla real al 125 % y al 150 % (aquí solo se midió a 100 %; cambiar la escala exige cerrar la
   sesión).
4. Recorrido con datos reales de `data/raw` (solo lectura, salida en `E:/`).
5. Comprobar en una máquina con `LongPathsEnabled=0` desde qué longitud de carpeta deja de arrancar (QA9-02).
