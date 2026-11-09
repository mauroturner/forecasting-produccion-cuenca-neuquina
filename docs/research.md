# Investigación previa: producción de petróleo y gas, pozo por pozo

Fecha de la investigación: 2026-11-09.

**Leyenda de etiquetas**

- **[Verificado]**: comprobado directamente (respuesta de la API CKAN, cabeceras HTTP, primeros bytes de un CSV real u oficial).
- **[Fuente secundaria]**: tomado de un resumen de búsqueda o de una herramienta de lectura, sin abrir la fuente original. Conviene confirmarlo antes de citarlo.
- **[Inferido]**: deducción propia a partir de datos observados. No está confirmado por una fuente.

---

## Objetivo

Verificar los datos, el entorno y las referencias necesarios para el proyecto "Producción de petróleo y gas, pozo por pozo": ingesta mensual automatizada con validación (Airflow, Python, SQL), curvas de declinación de Arps por pozo (SciPy `curve_fit`), comparación con un modelo de scikit-learn, validación walk-forward con bandas P10/P50/P90 y un dashboard de Power BI.

**Hallazgos principales**

1. El recurso útil para el proyecto es el archivo no convencional dentro del mismo dataset (149 MB). No hay un dataset separado de producción no convencional.
2. El dataset de fractura existe, está publicado con licencia CC BY 4.0 y su nota indica "Datos preliminares sujetos a revisión". Por eso el proyecto lo llama preliminar.
3. Airflow no se ejecuta de forma nativa en Windows. La vía oficial es Docker Compose (mínimo 4 GB de memoria para Docker) o WSL2.
4. La afirmación "b > 1 es común en shale" no está respaldada por las fuentes revisadas. Varias fuentes indican que b > 1 queda fuera del marco teórico de Arps. Ver la sección de Arps.
5. Durante la verificación, un intento de muestreo con cabecera `Range` devolvió el archivo completo de 328 MB. El archivo se borró de inmediato. Ver "Riesgos y huecos".

---

## Dataset

### Recursos del dataset

Dataset: "Producción de petróleo y gas por pozo (Capítulo IV)", `produccion-de-petroleo-y-gas-por-pozo`.

- Página del dataset: http://datos.energia.gob.ar/dataset/produccion-de-petroleo-y-gas-por-pozo y https://datos.gob.ar/dataset/produccion-de-petroleo-y-gas-por-pozo [Verificado: API CKAN]
- API CKAN: https://datos.gob.ar/api/3/action/package_show?id=produccion-de-petroleo-y-gas-por-pozo [Verificado]
- Organización: Secretaría de Energía [Verificado]
- Licencia (campo `license_id`): CC-BY-4.0 [Verificado]
- Última modificación de metadatos: 2026-11-08T09:01:43 [Verificado]
- Total de recursos en el dataset: 53 [Verificado]
- Documentación indicada en el dataset: https://github.com/datosenergia/produccion-de-petroleo-y-gas-por-pozo [Verificado: enlace en `extras`]. El contenido de ese repositorio se leyó con una herramienta de resumen; ver "Riesgos y huecos".

Todas las URL de descarga tienen el patrón `http://datos.energia.gob.ar/dataset/c846e79c-026c-4040-897f-1ad3543b407c/resource/<ID_RECURSO>/download/<archivo>`. Son HTTP, no HTTPS [Verificado].

**Recursos recomendados**

| Uso | Archivo | Formato | Tamaño | Última modificación (CKAN) | URL de descarga |
|---|---|---|---|---|---|
| Principal (no convencional, Neuquén) | `produccin-de-pozos-de-gas-y-petrleo-no-convencional.csv` | CSV | 148.9 MB (148 923 474 bytes) | 2026-10-22 | http://datos.energia.gob.ar/dataset/c846e79c-026c-4040-897f-1ad3543b407c/resource/b5b58cdc-9e07-41f9-b392-fb9ec68b0725/download/produccin-de-pozos-de-gas-y-petrleo-no-convencional.csv |
| Pozos: coordenadas y atributos del pozo | `capitulo-iv-pozos.csv` | CSV | 34.2 MB | 2026-10-21 | http://datos.energia.gob.ar/dataset/c846e79c-026c-4040-897f-1ad3543b407c/resource/cb5c0f04-7835-45cd-b982-3e25ca7d7751/download/capitulo-iv-pozos.csv |
| Fractura (preliminar) | `datos-de-fractura-de-pozos-de-hidrocarburos-adjunto-iv-actualizacin-diaria.csv` | CSV | 1.27 MB (1 271 429 bytes) | 2026-11-08 | http://datos.energia.gob.ar/dataset/71fa2e84-0316-4a1b-af68-7f35e41f58d7/resource/2280ad92-6ed3-403e-a095-50139863ab0d/download/datos-de-fractura-de-pozos-de-hidrocarburos-adjunto-iv-actualizacin-diaria.csv |
| Listado de pozos por operador (metadatos, coordenadas, datos iniciales) | `listado-de-pozos-cargados-por-empresas-operadoras.csv` | CSV | 27.1 MB | 2025-10-20 | http://datos.energia.gob.ar/dataset/c846e79c-026c-4040-897f-1ad3543b407c/resource/cbfa4d79-ffb3-4096-bab5-eb0dde9a8385/download/listado-de-pozos-cargados-por-empresas-operadoras.csv |

Todos los tamaños provienen de la cabecera `Content-Range` de peticiones HEAD [Verificado]. Las fechas de última modificación provienen de CKAN [Verificado].

**Series anuales principales (una por año)**

Sí, hay un CSV por año para la serie principal (Capítulo IV), desde 2006 hasta 2026 [Verificado]. Cada archivo tiene una URL fija por año (ID del recurso en CKAN):

| Año | ID del recurso (CKAN) | Tamaño | Última modificación |
|---|---|---|---|
| 2026 | fb7a47a0-cba9-4667-a004-6f6c1c346c23 | 241.7 MB | 2026-11-07 |
| 2025 (con identificador, ver nota) | 6f9f63bd-3f7e-43ab-8743-85997ae1380c | 327.9 MB | 2026-11-08 |
| 2025 (otro recurso con el mismo nombre) | d774b5d7-0756-48fe-88f2-8729b57b22da | 315.4 MB | 2026-10-03 |
| 2024 (con identificador, ver nota) | 94d82d18-488b-434c-806d-ee5e053ce1cd | 319.9 MB | 2026-11-08 |
| 2024 (otro recurso con el mismo nombre) | 43a09dce-1742-44d0-bc13-f193deaab563 | 319.9 MB | 2026-10-03 |
| 2023 | 231c39b3-e81e-4398-af8d-b115807f2c25 | 304.7 MB | 2026-06-05 |
| 2022 | 876b3746-85e2-4039-adeb-b1354436159f | 306.0 MB | 2026-10-22 |
| 2021 | 465be754-a372-4c31-b855-81dc5fe3309f | 303.7 MB | 2023-11-23 |
| 2020 | c4a4a6a0-e75a-4e12-ae5c-54d53a70348c | 301.8 MB | 2026-10-22 |
| 2019 | 8bc0d61c-0408-43d4-a7bc-7178fcb5d37e | 299.6 MB | 2026-09-22 |
| 2018 | 333fd72a-9b83-4bc1-bc94-0f5940b52331 | 296.8 MB | 2026-09-22 |
| 2017 | df4857e1-7c3f-4980-b5b5-184fe78bfcf0 | 291.6 MB | 2026-03-14 |
| 2016 | d8539ae8-0a71-4339-a16c-139b21bd2cd0 | 287.4 MB | 2026-10-13 |
| 2015 | e375aa35-fd8d-41d6-aa0c-e6879ca567a1 | 281.5 MB | 2026-09-12 |
| 2014 | cd9813a7-1e19-4f60-a02a-7903dd81aff7 | 275.3 MB | 2026-10-11 |
| 2013 | bc7ac8fe-2cec-4dab-acdd-322ea1ccc887 | 270.1 MB | 2025-12-10 |
| 2012 | 0dce0e75-1556-47ee-8615-1955fbd54ade | 265.3 MB | 2026-10-09 |
| 2011 | 4817272c-7365-4bdd-b02d-75b118218b10 | 258.6 MB | 2026-11-08 |
| 2010 | 364ca28e-d069-4bd6-8771-925f0db152a8 | 252.4 MB | 2026-11-07 |
| 2009 | 48585038-055a-4437-bb1d-4fe36073f453 | 245.8 MB | 2026-10-06 |
| 2008 | 3430b5a8-a516-42ca-a47d-2e1ce45925fb | 244.9 MB | 2026-10-05 |
| 2007 | be663a63-f020-4e28-8f31-c5f81d47554d | 238.7 MB | 2025-12-04 |
| 2006 | 4e1c55e5-1f1b-4fc8-aa37-2080d9795f29 | 235.9 MB | 2026-11-03 |

Los nombres de archivo siguen el patrón `produccin-de-pozos-de-gas-y-petrleo-<AÑO>.csv` (sin acentos). Las tildes están quitadas en la URL.

Nota sobre duplicados: 2024 y 2025 tienen dos recursos con el mismo nombre. Uno tiene la descripción "Producción de pozos de gas y petróleo con identificador". Solo se verificó la cabecera del recurso 2025 marcado como "con identificador" (contiene `idpozo`). El otro recurso no se abrió. Cuál es el canónico sigue sin verificarse.

**Series DDJJ abiertas y cerradas (2006-2026)**

Existe una segunda serie anual con el sufijo "(DDJJ abiertas y cerradas)", con tamaños muy similares (236 MB a 315 MB por año) [Verificado: tamaños y nombres]. Su contenido no se verificó. Por "DDJJ" se entiende declaraciones juradas. Es una inferencia por el nombre.

**Otros recursos del dataset**

- `listado-de-pozos-cargados-por-empresas-operadoras.csv` (27 MB): listado de pozos con coordenadas, profundidad y datos iniciales. Tiene 51 columnas [Verificado]. El resumen de GitHub decía "alrededor de 40"; eso no coincide.
- `produccin-de-captulo-iv-agrupada-por-yacimiento-y-formacin-productiva.csv` (125 MB): producción agrupada por yacimiento y formación [Verificado: tamaño y nombre].
- `produccin-de-petrleo-y-gas-captulo-iv-por-yacimiento-y-antigedad-de-pozo-productivo.csv` (75 MB): producción por yacimiento y antigüedad del pozo [Verificado: tamaño y nombre].
- `padrn-de-pozos-de-captulo-iv-con-fecha-de-primera-produccin.csv` (1.2 MB): padrón de pozos con fecha de primera producción [Verificado: tamaño y nombre].
- Series agregadas de gas y petróleo por cuenca y subtipo de recurso (32 KB cada una) [Verificado: tamaño].
- `shapefile-de-pozos.zip` (4.2 MB): capa geográfica de pozos, EPSG:4326 [Verificado: descripción en CKAN].

**Dataset separado para no convencionales**

No se encontró un dataset separado de producción no convencional. La búsqueda `pozos no convencional` devolvió 19 resultados en CKAN [Verificado]. Los relevantes son:

- `produccion-de-petroleo-y-gas-por-pozo`: el recurso `produccin-de-pozos-de-gas-y-petrleo-no-convencional.csv` está dentro de este dataset.
- `datos-de-fractura-de-pozos-adjunto-iv`: datos de fractura, ver la sección correspondiente.
- `trayectoria-de-pozos` ("Trayectorias de Pozo Vaca Muerta") y `estado-de-pozos-de-petroleo-y-gas`, `perforacion-de-pozos-de-petroleo-y-gas`, `pozos-de-petroleo-y-metros-perforados`. Aparecen en la búsqueda, pero no se revisó su contenido.

Búsqueda en el portal web `https://datos.gob.ar/dataset?q=produccion+pozo`: confirma dos datasets relevantes (producción y fractura) y muestra fechas de actualización del 08-11-2026 [Fuente secundaria: lectura de página con herramienta de resumen].

**Portal de la Secretaría de Energía**

Las URLs de descarga apuntan a `datos.energia.gob.ar` [Verificado]. No se verificó de forma independiente la página de ese portal; la información del dataset se tomó de CKAN.

### Columnas

Fuente principal: cabecera (primera línea) del CSV, leída con streaming de 4 KB [Verificado]. Los significados se infieren del nombre, de los valores observados y de la nota del dataset cuando existe. Se indica la fuente de cada significado.

**A. Archivo anual principal (2025, con identificador): 39 columnas**

Codificación UTF-8 con BOM. Separador coma. Decimal con punto. Los valores vacíos son nulos.

| # | Columna | Significado | Unidad | Observación |
|---|---|---|---|---|
| 1 | `idempresa` | ID numérico de la empresa operadora | — | Ejemplo observado: 379 = PETROLERA DEL COMAHUE S.A. [Verificado] |
| 2 | `anio` | Año del período | — | [Verificado] |
| 3 | `mes` | Mes del período | — | [Verificado] |
| 4 | `idpozo` | ID numérico del pozo. Clave de unión con fractura y con el archivo de pozos | — | [Verificado] (presente en fractura y en `capitulo-iv-pozos.csv`) |
| 5 | `prod_pet` | Petróleo producido en el mes | m³ | Unidad según nota del dataset [Verificado] |
| 6 | `prod_gas` | Gas producido en el mes | miles de m³ | Unidad según nota del dataset [Verificado]. Valor de muestra 240.967 en un pozo no convencional |
| 7 | `prod_agua` | Agua producida en el mes | m³ | Unidad según nota del dataset [Verificado] |
| 8 | `iny_agua` | Agua inyectada | m³ | [Inferido por el nombre] |
| 9 | `iny_gas` | Gas inyectado | miles de m³ | [Inferido por el nombre] |
| 10 | `iny_co2` | CO2 inyectado | miles de m³ | [Fuente secundaria: resumen de GitHub] |
| 11 | `iny_otro` | Otros fluidos inyectados | m³ | [Inferido por el nombre] |
| 12 | `tef` | Tiempo de extracción efectiva | días | [Inferido]: vale 31 en enero y 0 en pozos sin actividad |
| 13 | `vida_util` | Vida útil estimada | — | [No verificado]. Vale 0 en la muestra |
| 14 | `tipoextraccion` | Método de extracción | texto | Valores observados: "Plunger Lift", "Sin Sistema de Extracción" [Verificado] |
| 15 | `tipoestado` | Estado del pozo | texto | Valores observados: "Abandonado", "Extracción Efectiva", "Inyección de Agua" [Verificado] |
| 16 | `tipopozo` | Tipo de pozo | texto | Valores observados: "Petrolífero", "Gasífero" [Verificado] |
| 17 | `observaciones` | Texto libre | texto | Valor observado: "Cargado automáticamente como [Sin movimientos]" [Verificado]. Señala registros generados sin actividad |
| 18 | `fechaingreso` | Fecha y hora de carga del registro | timestamp | [Inferido] |
| 19 | `rectificado` | Indicador de rectificación por el operador | t/f | [Fuente secundaria: resumen de GitHub] |
| 20 | `habilitado` | Indicador de registro publicado | t/f | [Inferido] |
| 21 | `idusuario` | ID del usuario que cargó el registro | — | [Inferido] |
| 22 | `empresa` | Nombre de la empresa | texto | [Verificado] |
| 23 | `sigla` | Código de texto del pozo | texto | Ejemplo: `YPF.GR.x-5`, `AEA.NQ.RCo-1038` [Verificado]. Carácter de identificador único: [Fuente secundaria] |
| 24 | `formprod` | Código de la formación productiva | texto | Ejemplos: `PREC`, `FIMP` [Verificado] |
| 25 | `profundidad` | Profundidad del pozo | m | [Inferido]: valores de 2 402 a 2 779 |
| 26 | `formacion` | Nombre de la formación productiva | texto | Ejemplos: "precuyo", "punta rosada", "formación improductiva" [Verificado] |
| 27 | `idareapermisoconcesion` | Código del área de permiso o concesión | texto | Ejemplo: `SDD`, `AGR` [Verificado] |
| 28 | `areapermisoconcesion` | Nombre del área de permiso o concesión | texto | Ejemplo: "GENERAL ROCA", "AL SUR DE LA DORSAL" [Verificado] |
| 29 | `idareayacimiento` | Código del yacimiento | texto | Ejemplo: `RQC` [Verificado] |
| 30 | `areayacimiento` | Nombre del yacimiento | texto | Ejemplo: "RANQUIL CO" [Verificado] |
| 31 | `cuenca` | Cuenca | texto | Ejemplo: "NEUQUINA" [Verificado] |
| 32 | `provincia` | Provincia | texto | Ejemplo: "Neuquén", "Rio Negro" [Verificado] |
| 33 | `tipo_de_recurso` | Tipo de recurso | texto | "CONVENCIONAL", "NO CONVENCIONAL" [Verificado] |
| 34 | `proyecto` | Proyecto | texto | "Sin Proyecto", "GAS PLUS" [Verificado] |
| 35 | `clasificacion` | Clasificación de la actividad | texto | "EXPLORACION", "EXPLOTACION" [Verificado] |
| 36 | `subclasificacion` | Subclasificación | texto | "DESARROLLO", "EXPLORACION" [Verificado] |
| 37 | `sub_tipo_recurso` | Subtipo de recurso | texto | "TIGHT" en no convencional [Verificado]. Vacío en convencional de la muestra |
| 38 | `fecha_data` | Fecha de referencia del período (último día del mes) | date | Ejemplo: 2025-01-31 [Verificado] |
| 39 | `id` | Clave compuesta `idpozo` + año + mes | texto | Patrón observado en tres filas, ej. `145622202501` [Verificado] |

**B. Archivo no convencional (149 MB): 40 columnas**

Es igual al archivo anual, con dos diferencias:

- No tiene la columna `id`.
- Tiene `coordenadax` y `coordenaday` (columnas 33 y 34, después de `provincia`). Son WGS84 en grados decimales. En la muestra, `coordenadax` vale -69.19 y `coordenaday` vale -39.08, es decir, longitud y latitud de Neuquén [Verificado por los valores]. El resumen de GitHub dice lo contrario, así que conviene confirmarlo al cargar los datos.

**C. Archivo de fractura (1.27 MB): 30 columnas**

`id_base_fractura_adjiv`, `idpozo`, `sigla`, `cuenca`, `areapermisoconcesion`, `yacimiento`, `formacion_productiva`, `tipo_reservorio`, `subtipo_reservorio`, `longitud_rama_horizontal_m`, `cantidad_fracturas`, `tipo_terminacion`, `arena_bombeada_nacional_tn`, `arena_bombeada_importada_tn`, `agua_inyectada_m3`, `co2_inyectado_m3`, `presion_maxima_psi`, `potencia_equipos_fractura_hp`, `fecha_inicio_fractura`, `fecha_fin_fractura`, `fecha_data`, `anio_if`, `mes_if`, `anio_ff`, `mes_ff`, `anio_carga`, `mes_carga`, `empresa_informante`, `mes`, `anio` [Verificado].

Valores observados: `tipo_reservorio` = "NO CONVENCIONAL", `subtipo_reservorio` = "SHALE", `tipo_terminacion` = "Punzado" [Verificado].

**D. Archivo de pozos `capitulo-iv-pozos.csv` (34 MB): 26 columnas**

`sigla`, `idpozo`, `area`, `cod_area`, `empresa`, `yacimiento`, `cod_yacimiento`, `formacion`, `cuenca`, `provincia`, `cota`, `profundidad`, `clasificacion`, `subclasificacion`, `tipo_recurso`, `sub_tipo_recurso`, `gasplus`, `tipopozo`, `tipoextraccion`, `tipoestado`, `adjiv_fecha_inicio_perf`, `adjiv_fecha_fin_perf`, `adjiv_fecha_inicio_term`, `adjiv_fecha_fin_term`, `geojson`, `geom` [Verificado].

Las coordenadas están en `geojson` como punto GeoJSON (`{"type":"Point","coordinates":[lon, lat]}`) y en `geom` como WKB hexadecimal [Verificado]. El resumen de GitHub decía que tenía `coordenadax`/`coordenaday`. Eso no coincide con la cabecera real.

**Columnas clave para el proyecto**

- Identificador de pozo para unir fuentes: `idpozo` y `sigla`, ambos presentes en todos los archivos revisados (anual, no convencional, fractura, pozos y listado) [Verificado].
- Clave temporal: `anio`, `mes`, `fecha_data` [Verificado].
- Producción: `prod_pet` (m³), `prod_gas` (miles de m³), `prod_agua` (m³) [Verificado por la nota del dataset].
- Filtros para el subconjunto: `tipo_de_recurso`, `sub_tipo_recurso`, `cuenca`, `provincia`, `tipoestado`, `tipoextraccion` [Verificado].
- Contexto de empresa, yacimiento y formación: `empresa`/`idempresa`, `areayacimiento`/`idareayacimiento`, `formacion`/`formprod` [Verificado].
- Coordenadas: solo en el archivo no convencional (`coordenadax`, `coordenaday`), en el archivo de pozos (`geojson`) y en el listado [Verificado]. El archivo anual 2025 no las incluye. Hay que unirlas.

**Filtros de limpieza sugeridos (inferidos)**

- Filas con `prod_pet` = 0, `prod_gas` = 0 y `observaciones` = "Cargado automáticamente como [Sin movimientos]" son registros sin actividad. Conviene decidir si se excluyen antes de ajustar curvas.
- `rectificado` y `habilitado` deben considerarse en la validación.

### Tamaño y cantidad de filas

Las cantidades de filas son **estimaciones** [Inferido]. Se calcularon dividiendo el tamaño del archivo entre la longitud media de línea observada en una muestra pequeña (8 a 10 líneas por archivo). La muestra no es representativa del total: los primeros registros de enero suelen tener muchas filas sin movimiento y son más cortas.

| Año | Tamaño | Filas estimadas (aprox.) |
|---|---|---|
| 2006 | 236 MB | ~640 mil |
| 2010 | 252 MB | ~690 mil |
| 2015 | 282 MB | ~770 mil |
| 2018 | 297 MB | ~810 mil |
| 2020 | 302 MB | ~820 mil |
| 2022 | 306 MB | ~830 mil |
| 2024 | 320 MB | ~870 mil |
| 2025 (con identificador) | 328 MB | ~890 mil |
| 2026 (parcial) | 242 MB | ~660 mil |
| No convencional (todos los años) | 149 MB | ~410 mil (con 364 B/línea de muestra) |
| Fractura (todos los años) | 1.27 MB | ~5 mil (con 253 B/línea de muestra) |

Total aproximado de la serie principal 2006-2026: 5.9 GB. Desde 2015: 3.6 GB [Inferido a partir de los tamaños verificados].

Nota: el archivo 2026 pesa menos porque, por la fecha de hoy (2026-11-09), probablemente tiene menos meses. Ese dato no se verificó.

### Subconjunto recomendado

**Recomendación: usar el archivo no convencional (`produccin-de-pozos-de-gas-y-petrleo-no-convencional.csv`) filtrado a `cuenca = NEUQUINA`, `tipo_de_recurso = NO CONVENCIONAL` y `anio >= 2015`.** Se unen `idpozo` con el archivo de fractura para las variables de longitud de rama y número de etapas.

**Razones**

- Es un solo archivo de 149 MB, cerca de la mitad de la serie anual de un solo año (328 MB). Cabe bien en un portátil de 16 GB, incluso con Airflow y Power BI.
- Ya está separado por tipo de recurso. Evita filtrar la serie completa de 5.9 GB.
- Contiene coordenadas WGS84 en el mismo archivo.
- La muestra confirma registros de 2015 y 2018 para pozos de Neuquén con `sub_tipo_recurso = TIGHT` [Verificado]. Las curvas de declinación necesitan historias de varios años, así que 2015 en adelante da historias largas.
- El no convencional de Vaca Muerta comienza su desarrollo intensivo alrededor de 2013-2014 [Inferido por conocimiento general; no verificado en esta investigación]. Empezar en 2015 suele dar historia suficiente para pozos de cinco a diez años.

**Alternativas**

- Mismo filtro sobre los archivos anuales 2015-2026: ~3.6 GB. Más trabajo de ingesta, pero incluye convencional si se necesita comparar. No recomendado para el alcance inicial.
- Si el ajuste tiene pocos pozos con historia suficiente, ampliar a 2012 o antes con los archivos anuales.

**Cosas por confirmar antes de fijar el subconjunto**

- El último año presente en el archivo no convencional (no verificado; solo se vio el inicio).
- Si el archivo no convencional es un subconjunto exacto de los anuales, o si difiere en algún registro. Para la ingesta, esto afecta a la validación cruzada.
- Distribución de `sub_tipo_recurso` y `formacion` dentro de Neuquén: no verificada.

### Licencia y atribución

- Licencia: **CC BY 4.0**. Confirmado en el campo `license_id` de CKAN (`CC-BY-4.0`) tanto para el dataset principal como para el de fractura [Verificado].
- Texto de licencia: https://creativecommons.org/licenses/by/4.0/ [Verificado].
- Obligaciones de la CC BY 4.0 (Creative Commons, sección "Attribution" de la licencia): dar crédito al creador, incluir el aviso de copyright y el de licencia, enlazar la licencia, enlazar el material, e indicar si se modificó el material y conservar las indicaciones de modificaciones previas [Verificado en la página de licencia, a través de una herramienta de resumen].
- Texto de atribución sugerido (redacción propia, en el formato habitual de CC BY 4.0; no es un texto exigido por el publicador, no se encontró ningún texto específico):

  > Fuente de datos: Secretaría de Energía de la Nación, "Producción de petróleo y gas por pozo (Capítulo IV)", datos.gob.ar, licencia CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Modificaciones: se filtró por cuenca y tipo de recurso, se validaron registros, se estimaron curvas de declinación de Arps y se calcularon proyecciones y bandas P10/P50/P90.

- El resumen de GitHub decía "el contenido no indica licencia". Eso contradice CKAN. Usar CKAN como fuente de la licencia, y confirmar en la página del dataset antes de publicar.

---

## Dataset de fractura

**Nombre oficial**: "Datos de fractura de pozos de hidrocarburos (Adjunto IV)" [Verificado].

**Página**: https://datos.gob.ar/dataset/datos-de-fractura-de-pozos-adjunto-iv [Verificado: API CKAN y página]. API: https://datos.gob.ar/api/3/action/package_show?id=datos-de-fractura-de-pozos-adjunto-iv

**Licencia**: CC-BY-4.0 [Verificado].

**Organización**: Secretaría de Energía [Verificado].

**Recurso principal**: CSV "Actualización diaria", 1.27 MB, última modificación 2026-11-08 (CKAN). Descarga: ver tabla de recursos recomendados [Verificado].

**Por qué se llama preliminar**: la nota del dataset dice textualmente **"Datos preliminares sujetos a revisión."** [Verificado]. No se encontró una explicación más detallada en las fuentes revisadas. Es la razón oficial que se puede citar.

**Contenido** (según la nota del dataset y la cabecera): detalle por pozo, formación, tipo de reservorio, yacimiento, concesión y provincia; longitud de rama horizontal (m); cantidad de etapas de fractura; tipo de terminación; toneladas de arena nacional e importada (t); agua inyectada (m³); CO2 inyectado (m³); presión máxima (psi); potencia de equipos (hp); fechas de inicio y fin de fractura; empresa informante [Verificado].

**Observaciones de la muestra** [Verificado con las primeras 10 filas]:

- Las fechas de fractura observadas son de 2018-2019. El histórico puede ser corto o incompleto.
- Hay filas con `longitud_rama_horizontal_m = 0` y varias etapas (`cantidad_fracturas = 3`). Eso puede ser un error de carga o un pozo vertical. Hay que validarlo.
- La clave de unión con producción es `idpozo` (y `sigla` como respaldo) [Verificado].

**Cómo lo usa el proyecto**: como variable explicativa o de control (longitud de rama, número de etapas, arena, agua inyectada), no como fuente de producción. Como los datos son preliminares, conviene tratarlos como opcionales en el modelo y documentar la limitación.

**Infografía relacionada**: "Infografía Hidrocarburos No Convencionales" (PDF, 2019) en el mismo dataset [Verificado].

---

## Stack y entorno

### Airflow en Windows

**Hallazgo**: Airflow no se ejecuta de forma nativa en Windows [Verificado].

- Documentación de requisitos (Airflow 3.4.0): Airflow "currently can be run on POSIX-compliant Operating Systems". "On Windows you can run it via WSL2 (Windows Subsystem for Linux 2) or via Linux Containers." Dicen que el soporte nativo para Windows "is not a high priority" [Verificado: https://airflow.apache.org/docs/apache-airflow/stable/installation/prerequisites.html].
- Página de seguridad (Airflow 3.3.2): Windows "is not supported for deployment", y WSL2 solo es aceptable para desarrollo [Fuente secundaria: resumen de búsqueda].
- Guía de inicio rápido: en Windows, `wsl --install` en PowerShell como administrador, y luego ejecutar los comandos en la terminal de Ubuntu [Verificado: https://airflow.apache.org/docs/apache-airflow/stable/start.html].

**Vía oficial recomendada: Docker Compose**

- Página: https://airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/index.html [Verificado].
- Versión actual indicada: Airflow 3.4.0 [Verificado]. Imagen `apache/airflow:3.4.0`.
- Archivo de Compose: `https://airflow.apache.org/docs/apache-airflow/3.4.0/docker-compose.yaml` [Verificado].
- Memoria mínima: **4 GB** para los contenedores de Airflow. La página recomienda **8 GB** para el motor de Docker [Verificado: cita literal "allocate at least 4GB memory for the Docker Engine (ideally 8GB)"].
- Docker Compose v2.14.0 o superior [Verificado].
- La pila completa incluye scheduler, DAG processor, API server, worker, triggerer, Postgres y Redis. Flower es opcional [Verificado].
- Con 16 GB de RAM, 4 a 8 GB para Docker dejan 8 a 12 GB para Windows, Power BI y el resto. Es viable, pero conviene vigilar la memoria [Inferido].

**Alternativas para desarrollo local**

1. **Airflow Standalone dentro de WSL2**: `airflow standalone` ejecuta scheduler, DAG processor, triggerer y API server sobre SQLite. La documentación indica que "is for development purposes only. Do not use this in production!" [Verificado]. Es lo más ligero, pero no es la configuración de producción.
2. **Probar las funciones de las tareas como Python puro** (pytest): extraer, validar y transformar en módulos sin dependencias de Airflow, y dejar en el DAG solo el cableado. Funciona en Windows nativo y no requiere Docker [Inferido: práctica habitual; no verificada con fuente en esta investigación].
3. **Docker Desktop con backend WSL2** para la prueba de integración. El backend WSL2 es el predeterminado en Docker Desktop para Windows [Inferido; no verificado en esta investigación].

**Versión de Python**: la documentación de Airflow 3.4.0 lista Python 3.11, 3.12, 3.13 y 3.14 como versiones probadas [Verificado]. Python 3.11 es compatible con el proyecto.

**Docker 28**: la versión de Docker no se verificó contra la documentación de Airflow, que no la menciona. Docker Compose v2.14 o superior es el requisito que sí aparece [Verificado].

### Power BI Desktop

- **Gratis**: Microsoft Learn indica "Download Power BI Desktop for free" y permite instalarlo desde Microsoft Store o como ejecutable directo [Verificado: https://learn.microsoft.com/en-us/power-bi/fundamentals/desktop-get-the-desktop].
- **Requisitos mínimos** [Verificado]: Windows 10 o Windows Server 2016 o posterior; .NET 4.7.2 o posterior; Microsoft Edge WebView2 Runtime 95.0.1020.30 o posterior; RAM mínima 2 GB disponible, 4 GB o más recomendado; resolución mínima 1440x900 o 1600x900; CPU x64.
- **Solo 64 bits**: la versión de 32 bits ya no tiene soporte [Verificado].
- **Compartir**: se requiere licencia para publicar en el servicio de Power BI. El precio exacto no se verificó; un resumen de terceros citó alrededor de 10 USD por usuario al mes (2023), dato que puede estar desactualizado [Fuente secundaria].
- **Construcción del informe**: Power BI Desktop es una aplicación de interfaz gráfica. Un informe `.pbix` se crea arrastrando campos y configurando visuales [Inferido de la naturaleza de la herramienta].
- **Formatos de texto**: al guardar como proyecto PBIP, el modelo semántico se expone como archivos TMDL y el informe como PBIR, aptos para control de versiones [Fuente secundaria: resumen de búsqueda sobre Microsoft Learn]. La vista TMDL está disponible en Power BI Desktop de forma general según el resumen. El estado de disponibilidad general de PBIR no se confirmó.
- **Conclusión para el proyecto**: el diseño del informe sigue siendo una tarea manual en la interfaz gráfica. El PBIP permite versionar el modelo y parte del informe, pero no está verificado que sea práctico generar visuales a mano. Entregar un diseño en HTML como representación del dashboard es una decisión razonable [Inferido].

---

## Curvas de Arps

### Ecuaciones

Forma general (Arps, 1945), con q_i la tasa inicial, D_i la declinación inicial y b el exponente de declinación [Fuente secundaria: resumen de IHS y PetroWiki no abierto]:

- **Exponencial (b = 0)**: q(t) = q_i · exp(−D_i · t).
- **Hiperbólica (0 < b < 1)**: q(t) = q_i / (1 + b · D_i · t)^(1/b).
- **Armónica (b = 1)**: q(t) = q_i / (1 + D_i · t).

Las fórmulas de producción acumulada (N_p) siguen las formas estándar de Arps. No se verificaron contra una fuente abierta en esta investigación; conviene confirmarlas en la referencia original antes de implementarlas.

**Hiperbólica modificada con declinación exponencial terminal**: la curva es hiperbólica hasta que la declinación efectiva cae a un límite fijo (por ejemplo, 10% anual, cita de IHS) y luego pasa a exponencial con esa tasa. La transición se atribuye a Robertson en la documentación de IHS [Fuente secundaria]. No se encontró la referencia primaria de Robertson en esta investigación.

### Referencias

1. **Arps, J.J. (1945)**. "Analysis of Decline Curves". *Transactions of the AIME* 160, pp. 228-247. Técnico 1758 de *Petroleum Technology* (1944). Fuente: índice del volumen 160 de AIME [Fuente secundaria: resultado de búsqueda que cita las páginas; no abierto]. https://aimehq.org/themes/custom/aime/doclibrary/transactions/vol160.html
2. **Fetkovich, M.J. (1980)**. "Decline Curve Analysis Using Type Curves". SPE 4629. *Journal of Petroleum Technology* 32(6), pp. 1065-1077. DOI 10.2118/4629-PA. Fuente: registro bibliográfico en scilit y búsqueda [Fuente secundaria]. La versión PDF en NTNU no pudo abrirse durante la verificación (conexión rechazada). https://scilit.com/publications/790a4bce100aebc399ab5b964626b788
3. **PetroWiki (SPE)**, "Production forecasting: decline curve analysis". No se pudo leer: la página redirige a `onepetro.org/pages/petrowiki` y la lectura no se completó. https://petrowiki.spe.org/Production_forecasting_decline_curve_analysis
4. **IHS Harmony, "Decline Analysis Theory"** [Verificado: página leída con herramienta de resumen]. Contiene las definiciones de b (0, entre 0 y 1, 1), la nota sobre b > 1 y la transición a exponencial. https://www.ihsenergy.ca/support/documentation_ca/Harmony/content/html_files/reference_material/analysis_method_theory/decline_theory.htm
5. **ResSmith, "Model Selection Guide for Reservoir Engineers"** [Verificado: página leída con herramienta de resumen]. Da rangos de b por tipo de reservorio y dice que b > 1 es físicamente irreal. https://ressmith.readthedocs.io/en/stable/model_selection_guide.html
6. **Zhang (SPEE, 2016)**, presentación sobre pronóstico de producción de shale. Argumenta que el supuesto de b constante no es válido para shale. [Fuente secundaria: solo resultado de búsqueda]. https://www.spee.org/pdf/2016-10-houston-zhang_spee-oct-5.pdf

### Rangos de b

| Caso | Rango de b (fuente) | Observación |
|---|---|---|
| Exponencial | b = 0 | "Rare in practice" en ResSmith; "Constant decline" [Fuente secundaria: ResSmith, IHS] |
| Hiperbólica | 0 < b < 1 | "Most common type for oil and gas wells". Petróleo en gas en solución: 0.3-0.7. Petróleo con empuje de agua: 0.5-0.8. Gas convencional: 0.5-1.0 [Fuente secundaria: ResSmith] |
| Armónica | b = 1 | "Rare, but can occur in some gas wells" [Fuente secundaria: ResSmith] |
| b > 1 | — | ResSmith: "Physically unrealistic (check data quality)". IHS: "not consistent with decline curve theory, but they are sometimes encountered" [Fuente secundaria] |

### Shale y b > 1: lo que dicen las fuentes

El supuesto del proyecto es que b > 1 es común en shale. **Las fuentes revisadas no lo respaldan**:

- ResSmith señala b > 1 como físicamente irreal, y no da rangos de b para shale. En cambio sugiere alternativas: el modelo de ley de potencias (exponente n, típicamente 0.1-0.5 para shale) y el modelo de Duong (pendiente m, típicamente 0.5-1.0) [Fuente secundaria].
- IHS dice que b > 1 aparece a veces, pero no es consistente con la teoría. Sugiere que la interpretación puede estar mal o que otro valor de b < 1 ajusta los datos mejor [Fuente secundaria].
- Zhang (SPEE 2016) argumenta que el supuesto de b constante no es válido para shale. Propone un método de exponencial extendida que no necesita elegir un punto de cambio [Fuente secundaria].
- Hay fuentes de la industria que sí reportan b cercano a 2 en shale, pero no se pudo verificar en esta investigación la calidad de esos datos ni su metodología [Fuente secundaria].

**Implicación para el proyecto**

- Ajustar Arps con `curve_fit` y restringir b al intervalo [0, 1] como caso base. Así el modelo es físicamente acotado.
- Reportar los ajustes con b > 1 solo como diagnóstico. Un ajuste sin restricción que dé b > 1 señala un problema de datos o de modelo.
- Incluir la hiperbólica modificada (con límite de declinación terminal) como variante, con el límite explícito y documentado.
- Comparar con Duong o ley de potencias si el número de pozos lo justifica. Es una alternativa razonable para no convencional, no solo un añadido.
- Tradeoff: restringir b a [0, 1] reduce el ajuste en pozos con historia corta o ruido, pero evita reservas irreales por extrapolación. Recomiendo restringir y documentar la decisión.

---

## Riesgos y huecos

**Riesgos técnicos**

1. **El servidor ignora las cabeceras `Range`.** Una petición `GET` con `Range: bytes=0-4095` devolvió HTTP 200 y el archivo completo de 328 MB [Verificado]. Durante la verificación, esto descargó el archivo 2025 completo por error; se borró de inmediato. Para muestrear cabeceras conviene usar streaming con corte (`curl ... | head -c 4096`) o una lectura parcial en el cliente, nunca `Range` contando con que funcione. Lo mismo aplica al diseño de la ingesta: no contar con descargas parciales.
2. **Re-publicación de años anteriores.** Varios años antiguos tienen fecha de modificación de 2026 (por ejemplo, 2006, 2011, 2010, 2024) [Verificado con CKAN]. La ingesta mensual debe detectar cambios en años ya cargados, no solo filas nuevas. Conviene comparar `ETag` (observado en el archivo 2025: `"1794211360.73-327850453"`) o `Last-Modified`, y comprobar si el servidor responde a `If-None-Match` con 304 (no verificado).
3. **URLs HTTP y no HTTPS.** Todas las URLs de descarga son `http://` [Verificado]. Mitigación: validar checksum y tamaño, y guardar hash de cada archivo cargado.
4. **Duplicados de nombre**: los años 2024 y 2025 tienen dos recursos con el mismo nombre. Hay que elegir un recurso canónico y documentar la regla [Verificado]. La decisión queda abierta.
5. **Contradicciones entre el resumen de GitHub y los archivos reales**:
   - La licencia: el resumen dice "no indicada", CKAN dice CC-BY-4.0. Se usa CKAN [Verificado].
   - La fecha de actualización de la página: el resumen dice 2019-10-03, CKAN dice 2026-11-08 [Verificado]. Se usa CKAN.
   - Las coordenadas en `capitulo-iv-pozos.csv`: el resumen dice `coordenadax/coordenaday`, la cabecera real tiene `geojson/geom` [Verificado].
   - El listado de pozos: el resumen dice unas 40 columnas, la cabecera tiene 51 [Verificado].
   - El sentido de `coordenadax` y `coordenaday`: el resumen dice que `coordenadax` es latitud, los valores muestran que es longitud (≈ -69) [Verificado por valores].
6. **Datos de fractura preliminares.** Pueden cambiar. Ya hay filas con longitud de rama 0 (ver sección de fractura). Tratar como variable opcional.
7. **Estimaciones de filas**: son inferidas de muestras pequeñas (8 a 10 líneas). No se contaron las filas reales. Hay que medirlas en la primera carga.
8. **Significado de algunas columnas no verificado**: `vida_util`, unidad de `iny_co2`, significado exacto de `tef` (inferido como días), `rectificado` y `habilitado`. Confirmar con el diccionario de datos oficial, si existe.

**Huecos**

- No se encontró un diccionario de datos oficial en PDF o CSV separado. El resumen de GitHub sugiere que existe documentación en el repositorio, pero no se leyó directamente.
- No se verificó el último año presente en el archivo no convencional.
- No se verificó la cantidad real de pozos de Vaca Muerta. Una nota periodística citó 1 472 pozos no convencionales en Vaca Muerta [Fuente secundaria: LM Neuquén, https://mase.lmneuquen.com/petroleo/vaca-muerta-tiene-1472-pozos-no-convencionales-n657544]. Es un orden de magnitud, no una cifra oficial.
- No se leyó la página de PetroWiki ni el PDF de Fetkovich (1980) en la fuente original.
- No se verificó el estado de disponibilidad general de PBIR en Power BI Desktop.
- No se verificó el precio de la licencia Pro de Power BI.
- No se encontró una explicación detallada de por qué la fractura es preliminar, más allá de la nota del dataset.

**Riesgos de entorno**

- Airflow en Windows exige WSL2 o contenedores. Docker Desktop con 4 a 8 GB asignados, más Power BI y el resto del equipo, es ajustado con 16 GB, pero viable [Inferido].
- Power BI Desktop solo funciona en 64 bits y Windows 10 o posterior. Para compartir se necesita licencia [Verificado].

---

## Fuentes

**Datos (verificados directamente)**

- API CKAN, dataset principal: https://datos.gob.ar/api/3/action/package_show?id=produccion-de-petroleo-y-gas-por-pozo
- API CKAN, dataset de fractura: https://datos.gob.ar/api/3/action/package_show?id=datos-de-fractura-de-pozos-adjunto-iv
- Búsqueda CKAN de no convencionales: https://datos.gob.ar/api/3/action/package_search?q=pozos%20no%20convencional
- Página del dataset: https://datos.gob.ar/dataset/produccion-de-petroleo-y-gas-por-pozo
- Página de búsqueda: https://datos.gob.ar/dataset?q=produccion+pozo
- Archivos CSV (cabeceras, tamaños): URLs de la sección Dataset.

**Documentación (fuente secundaria o parcialmente verificada)**

- Repositorio del dataset (enlazado en CKAN; contenido leído con herramienta de resumen): https://github.com/datosenergia/produccion-de-petroleo-y-gas-por-pozo
- Licencia CC BY 4.0: https://creativecommons.org/licenses/by/4.0/
- Airflow, requisitos: https://airflow.apache.org/docs/apache-airflow/stable/installation/prerequisites.html
- Airflow, inicio rápido: https://airflow.apache.org/docs/apache-airflow/stable/start.html
- Airflow, Docker Compose: https://airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/index.html
- Power BI Desktop, instalación y requisitos: https://learn.microsoft.com/en-us/power-bi/fundamentals/desktop-get-the-desktop
- Power BI, TMDL: https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-tmdl-view
- Power BI, proyectos de informe (enhanced report format): https://learn.microsoft.com/en-us/power-bi/developer/embedded/projects-enhanced-report-format

**Referencias de Arps y declinación**

- Arps (1945), Transactions AIME 160: https://aimehq.org/themes/custom/aime/doclibrary/transactions/vol160.html
- Fetkovich (1980), SPE 4629: https://scilit.com/publications/790a4bce100aebc399ab5b964626b788 (PDF de referencia: https://www.ipt.ntnu.no/~curtis/courses/Reservoir-Recovery/2018-TPG4150/Handouts/Material-Balance/Required/1973-Fetkovich-DCA(1980-JPT).pdf, no se pudo abrir)
- PetroWiki, decline curve analysis: https://petrowiki.spe.org/Production_forecasting_decline_curve_analysis (no se pudo leer)
- IHS Harmony, decline analysis theory: https://www.ihsenergy.ca/support/documentation_ca/Harmony/content/html_files/reference_material/analysis_method_theory/decline_theory.htm
- ResSmith, model selection guide: https://ressmith.readthedocs.io/en/stable/model_selection_guide.html
- Zhang (SPEE 2016): https://www.spee.org/pdf/2016-10-houston-zhang_spee-oct-5.pdf

**Contexto (secundaria, no usado para decisiones técnicas)**

- LM Neuquén, cifra de pozos no convencionales de Vaca Muerta: https://mase.lmneuquen.com/petroleo/vaca-muerta-tiene-1472-pozos-no-convencionales-n657544
