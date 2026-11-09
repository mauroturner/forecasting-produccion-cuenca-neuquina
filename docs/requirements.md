# Requerimientos: producción de petróleo y gas, pozo por pozo

Fecha: 2026-11-09. Base: `docs/research.md` y el perfilado del archivo real descargado el 2026-11-09 (sección "Datos medidos"). Las suposiciones se marcan como **[Supuesto]**.

## 1. Problema

La Secretaría de Energía publica cada mes la producción de cada pozo del país. El dato es abierto (CC BY 4.0), pero llega crudo: un CSV de 149 MB con 431 322 filas y 40 columnas solo para los pozos no convencionales, con huecos, meses sin movimiento, valores negativos y republicaciones de meses anteriores.

Quién lo sufre:

- **Equipos de planificación de una operadora**: necesitan una proyección por pozo para presupuestos, compromisos de entrega y capacidad de instalaciones, y comparar su desempeño con el de otras operadoras con el mismo criterio.
- **Empresas de servicios**: anticipan actividad y declinación por yacimiento y por operadora.
- **Organismos públicos** (provincias, la propia Secretaría): proyectan producción y, con ella, regalías.

Qué cuesta hoy:

- Cada mes alguien descarga el archivo, lo filtra a mano, rearma las tablas y rehace las proyecciones en planillas. **[Supuesto]**: no se midieron las horas; el costo se describe como trabajo manual repetido, no como un número.
- Las proyecciones por pozo se hacen con criterios distintos según quién las arma, y casi nunca se mide cuánto se equivocaron. Sin esa medición no se sabe si una curva de declinación es mejor que repetir el último mes.
- Una republicación que cambia meses pasados o una columna renombrada pasan inadvertidas hasta que un número no cierra.

## 2. Objetivo

Un flujo que, sin intervención, descarga cada publicación, la valida, la carga, ajusta una curva de declinación de Arps a cada pozo, la compara con un modelo de machine learning y con dos líneas base ingenuas mediante validación walk-forward con bandas P10, P50 y P90, y deja las tablas listas para un tablero de Power BI en modelo estrella, junto con el diseño del tablero en HTML.

## 3. Alcance

Incluido:

- Recurso: `produccin-de-pozos-de-gas-y-petrleo-no-convencional.csv` del dataset "Producción de petróleo y gas por pozo (Capítulo IV)".
- Subconjunto: `cuenca = NEUQUINA` y `tipo_de_recurso = NO CONVENCIONAL`, **toda la historia publicada** (desde 2006-01 hasta el último mes; 2026-09 al perfilar). Ver la decisión D02 en `decisions.md`: el corte en 2015 de la investigación se descarta porque censuraría por la izquierda a 876 pozos.
- Fluidos proyectados: petróleo (m³) y gas (miles de m³), cada uno como una serie por pozo. El agua (m³) se carga y se muestra, no se proyecta.
- Métodos: dos líneas base ingenuas, tres variantes de Arps y un modelo de machine learning (sección 5).
- Orquestación en Apache Airflow sobre Docker Compose y una CLI equivalente que corre las mismas funciones en Windows sin Airflow.
- Tablas para Power BI en Parquet, diseño del tablero en HTML generado desde una especificación del modelo semántico, documentación completa.

Fuera de alcance:

- Pozos convencionales y las otras cuencas del archivo (Austral, Golfo San Jorge, Noroeste: 17 457 filas, 4,0 %).
- Los archivos anuales (2006-2026, 236-328 MB cada uno) y la duplicidad de recursos 2024/2025: no se usan.
- Datos de fractura en el modelo base. Se miden y quedan como ablación opcional (RF21, decisión D15).
- Construir el `.pbix` en Power BI Desktop (requiere la interfaz gráfica; S4). Publicar en el servicio de Power BI (requiere licencia).
- Equivalente de barriles de petróleo (BOE) y sumas entre fluidos.
- Pronósticos de reservas (EUR) y económicos.

## 4. Datos medidos (perfilado del 2026-11-09)

Publicación perfilada: `Last-Modified: Thu, 22 Oct 2026 21:00:56 GMT`, `ETag: "1792702856.77-148923474"`, 148 923 474 bytes. El servidor responde a `HEAD`, ignora `Range` y también ignora `If-None-Match` e `If-Modified-Since` (devuelve 200, nunca 304).

Archivo completo:

| Medida | Valor |
| --- | --- |
| Filas, columnas | 431 322, 40 |
| Codificación | UTF-8 con BOM, sin errores de decodificación |
| Períodos | 2006-01 a 2026-09 |
| Filas por cuenca | NEUQUINA 413 865; AUSTRAL 16 615; GOLFO SAN JORGE 657; NOROESTE 185 |

Subconjunto del proyecto (Neuquina, no convencional, toda la historia):

| Medida | Valor |
| --- | --- |
| Filas | 413 865 (383 710 desde 2015) |
| Pozos (`idpozo`) | 4 937; 876 tienen filas antes de 2015 (30 155 filas) |
| Siglas | 167 siglas corresponden a más de un `idpozo` (medido en 2015-2026): la clave es `idpozo` |
| Operadoras | 52 códigos `idempresa` (texto, por ejemplo `YPF`), relación 1:1 con `empresa` |
| Yacimientos, concesiones | 139 yacimientos (código y nombre 1:1, cada uno en una sola concesión); 107 concesiones, 2 abarcan dos provincias |
| Provincias (pozos) | Neuquén 4 659; Rio Negro 245 (así, sin tilde, en la fuente); Mendoza 33 |
| Subtipo (pozos) | SHALE 3 524; TIGHT 1 411; nulo 2 |
| Formación (pozos) | vaca muerta 3 453; lajas 589; mulichinco 259; los molles 216; punta rosada 114; quintuco 86; precuyo 81; agrio 78 |
| Atributos fijos por pozo | yacimiento, concesión, provincia, formación, subtipo, coordenadas y profundidad: ningún pozo tiene más de un valor |
| Atributos que cambian (2015-2026) | operadora en 979 pozos; tipo de pozo en 555; método de extracción en 2 231 |
| Último mes (2026-09) | 4 913 pozos informan; 3 604 con petróleo > 0; petróleo 3 355 749 m³; gas 2 901 557 miles de m³ |
| Petróleo anual | 2015: 1 534 530 m³; 2025: 29 319 874 m³ |
| Duplicados | 0 en (`idpozo`, `anio`, `mes`); 0 filas idénticas |
| `fecha_data` | siempre el último día de (`anio`, `mes`); 0 sin interpretar |
| `fechaingreso` | carga del operador: mediana 14 días después del fin del mes (p90 19); 526 filas cargadas antes del fin del período |
| Nulos | `vida_util` 405 260 (97,9 %); `observaciones` 389 744; `tipopozo`, `tipoestado`, `tipoextraccion` 601 cada una; `sub_tipo_recurso` 116; volúmenes 0 |
| Petróleo `prod_pet` | 0 negativos; 148 396 ceros; 265 469 positivos; máximo 26 593,261 m³ |
| Gas `prod_gas` | 2 negativos (pozos 153228 y 153227, 2020-05); 86 341 ceros; máximo 40 086,8 miles de m³ |
| Agua `prod_agua` | 0 negativos; 126 512 ceros |
| Meses sin petróleo ni gas | 84 178 filas (20,3 %); 7 421 con "Cargado automáticamente como [Sin movimientos]" |
| `tef` (días de extracción) | 70 filas con `tef` mayor que los días del mes (máximo 79,34; en varias `tef` repite el valor de `prod_gas`); 384 filas con `tef = 0` y producción > 0 |
| Huecos | 2 044 pozos con meses en cero dentro de su período productivo (22 085 meses); 703 pozos con meses sin fila (7 420 meses) |
| Pozos sin producción nunca | 172 |
| Meses con producción por pozo | mediana 58 (p25 25, p75 108, máximo 249); ≥ 6: 4 439 pozos; ≥ 12: 4 174; ≥ 24: 3 644; ≥ 60: 2 341 |
| Pico | mediana de 2 meses desde la primera producción hasta el pico (p90: 11 en petróleo, 12 en gas) |
| Series con ≥ 6 meses positivos desde el pico | petróleo 3 728 de 4 458; gas 4 205 de 4 749 |
| Coordenadas | 4 936 pozos dentro de la cuenca; 1 pozo con `coordenadax` y `coordenaday` intercambiadas |
| Profundidad | 172 pozos con 0; 4 con más de 8 000 m (máximo 378 939) |
| `rectificado` | 694 filas con `t`; `habilitado` siempre `t` |

Series elegibles para Arps por origen (≥ 6 meses positivos desde el pico hasta el origen y producción en alguno de los últimos 3 meses), y series activas "jóvenes" que no llegan a 6:

| Origen | Petróleo elegibles (jóvenes) | Gas elegibles (jóvenes) |
| --- | --- | --- |
| 2023-09 | 2 053 (251) | 2 556 (255) |
| 2024-09 | 2 369 (326) | 2 821 (367) |
| 2025-09 | 2 692 (346) | 3 231 (381) |
| 2026-08 | 3 153 (524) | 3 650 (397) |

Señales para el modelado: la mediana de la razón mes a mes del petróleo es 0,977 (un 2,3 % de declinación mensual) y un 2,1 % de los meses siguientes a un mes productivo vienen en cero. El gas cae todos los septiembres (2025-08 a 2025-09: de 3,20 a 2,59 millones de miles de m³; 2026-08 a 2026-09: de 3,32 a 2,90) **[Supuesto: estacionalidad de la demanda]**.

Fractura (archivo de 1,27 MB, "Datos preliminares sujetos a revisión"): 5 062 filas de 4 818 pozos; cubre 3 824 de los 4 937 pozos del subconjunto (77 %) y 3 129 de los 3 524 shale (89 %); 2 054 filas (41 %) con longitud de rama horizontal 0; 183 pozos con más de una fila.

Rendimiento medido: un ajuste acotado de la hiperbólica modificada con `scipy.optimize.curve_fit` (`trf`, `soft_l1`) toma 3,45 ms por solución, unos 10 ms por serie con tres puntos de partida (SciPy 1.11.4, este portátil). En 300 curvas sintéticas con ruido lognormal σ = 0,1, el error relativo a 12 meses tuvo mediana 2,3 % y p90 9,5 %.

Entorno medido: en el Python global, pyarrow 26.0.0 exige NumPy ≥ 2.0 pero NumPy es 1.26.4, y scikit-learn 1.7.2 no se puede importar porque importa pyarrow. SciPy 1.11.4 sí está instalado (la nota de la tarea decía lo contrario). SQLite 3.39.4. El proyecto debe usar su propio `.venv`.

## 5. Requerimientos funcionales

Cada RF tiene un identificador estable que usan el plan y las pruebas.

- **RF01 Detección de publicación.** Con `HEAD` sobre la URL configurada se leen `ETag`, `Last-Modified` y el tamaño (de `Content-Range` o `Content-Length`). Si coinciden con la última carga exitosa del manifiesto, la corrida termina como `unchanged` sin descargar. Si la URL responde 404, la corrida falla con un mensaje que remite al runbook (R11).
- **RF02 Descarga íntegra.** La descarga es completa (el servidor ignora `Range`), en bloques, con SHA-256 calculado al vuelo, a un archivo `.part` que se renombra solo si el tamaño coincide con el anunciado. Se registra en `data/raw/manifest.json` (URL, ETag, Last-Modified, tamaño, SHA-256, fecha de descarga). Un archivo ya descargado con el mismo tamaño se puede adoptar sin volver a bajarlo.
- **RF03 Validación del archivo.** El archivo se valida contra un contrato de datos (columnas, tipos, claves, rangos) con las reglas V01-V20 del plan (V01-V10 bloqueantes, V11-V20 advertencias) y tres informativas (I01-I03). Se escribe un reporte JSON y Markdown por corrida.
- **RF04 Rechazo sin daño.** Si hay al menos una regla bloqueante, el archivo pasa a `data/raw/quarantine/`, la corrida termina como `rejected` y el almacén, las salidas y el tablero conservan la versión anterior, byte a byte.
- **RF05 Carga al almacén.** Las filas del subconjunto se cargan en SQLite con transformaciones en archivos SQL versionados (staging, marts, controles). La carga es transaccional e idempotente. Las correcciones de calidad (negativos y `tef` inválidos a nulo, coordenadas intercambiadas, profundidad inválida a nulo) se hacen en SQL y quedan marcadas por fila.
- **RF06 Revisiones.** Al cargar una publicación nueva se cuentan las filas de meses anteriores que cambiaron respecto de la carga previa, por período, y se guardan en el registro de la corrida.
- **RF07 Series.** Cada pozo y fluido forma una serie mensual con la tasa por día calendario (volumen / días del mes), el pico (máximo de la tasa con datos hasta el origen), el segmento posterior al pico y la elegibilidad por origen.
- **RF08 Líneas base.** `naive_last` (repite la tasa del último mes) y `naive_mean3` (promedio de la tasa de los últimos 3 meses), convertidas a volumen con los días del mes objetivo.
- **RF09 Curvas de Arps.** Por serie y origen se ajustan tres variantes con SciPy: exponencial (`arps_exp`), hiperbólica modificada con b en [0, 2] y declinación terminal de 10 % efectiva anual (`arps_mh_b2`, caso base) y la misma con b en [0, 1] (`arps_mh_b1`, sensibilidad). Ajuste en escala logarítmica, sobre el segmento posterior al pico, con límites, varios puntos de partida y una cadena de respaldo documentada.
- **RF10 Machine learning.** Un `HistGradientBoostingRegressor` de scikit-learn con pérdida cuantílica (0,1; 0,5; 0,9), un modelo por fluido y horizonte, entrenado con todos los pozos a la vez sobre ejemplos cuyo objetivo es anterior o igual al origen (`ml_hgb`).
- **RF11 Walk-forward.** 36 orígenes mensuales: los 12 primeros de calentamiento (solo calibran bandas) y los 24 últimos de evaluación. Horizontes de evaluación 1, 3, 6 y 12 meses. Todos los métodos se evalúan sobre el mismo conjunto de pares (serie, origen, horizonte).
- **RF12 Bandas P10/P50/P90.** Para los métodos puntuales (líneas base y Arps), P10 y P90 salen de cuantiles empíricos de los errores ya realizados antes del origen; para `ml_hgb`, de la regresión cuantílica. P10 ≤ P50 ≤ P90 siempre.
- **RF13 Métricas.** Por método, fluido, horizonte, origen, tramo de edad y subtipo: MAE, RMSE, WAPE, sesgo, cobertura P10-P90, pérdida pinball escalada, proporción de series en las que el método supera a cada línea base y error del total de la cuenca.
- **RF14 Resumen honesto.** Un resumen (`reports/backtest_summary.json` y `.md`) evalúa los criterios preregistrados de la sección 8 y redacta el veredicto según los resultados, incluido "no supera". El bloque de resultados del README se copia de ese resumen entre marcadores.
- **RF15 Selección del método en uso.** Una regla preregistrada elige, por fluido y segmento (elegible o joven), el método que alimenta la vista por defecto del tablero.
- **RF16 Pronóstico en uso.** Con cada publicación nueva se ajusta la curva de cada pozo con origen en el último mes publicado y se guardan P10/P50/P90 para los próximos 12 meses de `arps_mh_b2`, `ml_hgb` y `naive_mean3`, junto con lo producido. Las corridas se acumulan por origen.
- **RF17 Modelo estrella.** Se exportan a `outputs/powerbi/` las dimensiones y los hechos del plan en Parquet, con claves únicas en las dimensiones e integridad referencial completa en los hechos.
- **RF18 Diseño del tablero.** Se genera `dashboard/powerbi-design.html` desde una especificación del modelo semántico: tablas, relaciones con cardinalidad y dirección de filtro, medidas DAX, carga en Power Query y las páginas con sus visuales ubicados, con números reales de las salidas.
- **RF19 Orquestación.** Un DAG de Airflow (`oilgas_monthly_production`) en Docker Compose y una CLI (`python -m oilgas run`) ejecutan la misma lista de tareas, en el mismo orden, con las mismas funciones.
- **RF20 Frescura y forma.** Cada día se verifica la publicación. Si el último mes cargado tiene más de 55 días de antigüedad, la corrida se registra como `late` y el tablero lo muestra. Un cambio de forma se detecta en la validación (RF03).
- **RF21 Ablación con fractura (opcional).** `ml_hgb` con variables de fractura (etapas, longitud de rama si es > 0, arena, agua) frente a `ml_hgb` sin ellas, sobre el mismo conjunto de evaluación. Solo si el dueño lo aprueba (decisión D15).
- **RF22 Documentación.** README con la narrativa (problema, solución, resultados, el recorrido de siete secciones, cómo correrlo y el paso a paso), diccionario de datos con unidades, ficha del modelo, registro de decisiones, runbook y paso a paso, más figuras generadas.

## 6. Requerimientos no funcionales

- **RNF01 Reproducibilidad.** Semillas fijas, versiones fijadas con `==` en `requirements.txt`. Dos corridas sobre la misma entrada producen Parquet con el mismo contenido (excepto las columnas de fecha de corrida).
- **RNF02 Rendimiento.** En este portátil con 4 procesos: backtest completo ≤ 45 min; flujo completo ≤ 90 min; modo rápido (`config/pipeline.quick.toml`) ≤ 5 min; pruebas sin marca `real_data` ni `docker` ≤ 3 min. Estimación base: unos 200 000 pares (serie, origen) por unos 16-20 ms de ajuste de Arps cada uno, unos 60 min en un solo proceso.
- **RNF03 Memoria.** Pico del proceso Python ≤ 4 GB, para que convivan Docker (4-8 GB), Power BI Desktop y el sistema en 16 GB.
- **RNF04 Portabilidad.** La CLI corre en Windows 10 nativo con Python 3.11; el DAG corre en Linux dentro de la imagen `apache/airflow:3.4.0`. Rutas con `pathlib`, sin dependencias de un shell.
- **RNF05 Idempotencia y atomicidad.** Repetir una tarea con la misma entrada no cambia el resultado; cada escritura de tablas es transaccional y cada archivo de salida se escribe a un temporal y se renombra.
- **RNF06 Trazabilidad.** Cada fila de hechos y cada archivo de salida llevan el `run_key` y la huella de la publicación de origen.
- **RNF07 Tecnologías.** Solo las del landing (S5) y las del sitio para este proyecto (SciPy, DAX). Las demás se justifican y se anotan en `LANDING-EXPANSION.md`.
- **RNF08 Licencia.** La atribución CC BY 4.0 aparece en el README, en el diseño del tablero y en los metadatos de cada Parquet.
- **RNF09 Versionado.** Nunca se versionan datos crudos, el almacén ni los intermedios. Cada Parquet versionado pesa ≤ 25 MB.
- **RNF10 Idioma.** Documentación en español neutro; código, identificadores, nombres de tablas y columnas en inglés; nombres de medidas y títulos de visuales en español.
- **RNF11 Seguridad.** Las URLs son HTTP: la integridad se controla con tamaño y SHA-256. No hay credenciales en el proyecto.
- **RNF12 Observabilidad.** Cada tarea registra inicio, fin, filas y duración; la tabla `pipeline_runs` guarda el estado de cada corrida.

## 7. Requerimientos de datos

- **Unidades**: petróleo y agua en m³; gas en miles de m³; tasas en m³/día y miles de m³/día por día calendario. Nunca se suman fluidos distintos.
- **Clave del pozo**: `idpozo` (entero). `sigla` es una etiqueta.
- **Clave temporal**: `period_key` = año·100 + mes (entero, por ejemplo 202609) y `period_index` = año·12 + mes − 1, para la aritmética de meses.
- **Contrato del archivo**: las 40 columnas del encabezado perfilado, en cualquier orden. Las columnas usadas por el proyecto son obligatorias; una columna nueva es una advertencia; una faltante es bloqueante.
- **Atributos fijos y variables**: yacimiento, concesión, provincia, formación, subtipo, coordenadas y profundidad van en `dim_well`; operadora, tipo de pozo, estado y método de extracción van por mes en el hecho de producción.
- **Licencia**: CC BY 4.0, con el texto de atribución de `docs/research.md`.

## 8. Criterios de aceptación

Cada criterio indica cómo se verifica. "Sintético" significa datos generados por las pruebas con parámetros conocidos; "real" significa la publicación descargada (marca `real_data`).

| ID | Criterio | Umbral | Verificación |
| --- | --- | --- | --- |
| AC01 | Detección de cambios | `unchanged` si ETag, Last-Modified y tamaño coinciden con la última carga exitosa; `changed` si cambia cualquiera | Unitaria con un servidor HTTP local |
| AC02 | Descarga íntegra | Un tamaño distinto del anunciado deja el `.part` sin renombrar y lanza error; el SHA-256 del manifiesto coincide con el del archivo | Unitaria |
| AC03 | Rechazo de archivos malformados | Cada accesorio malformado (columna faltante, columna renombrada, `idpozo` no numérico, `mes = 13`, clave duplicada, `fecha_data` inconsistente, archivo truncado con < 99 % de las filas previas, último mes anterior al vigente, bytes no UTF-8) da al menos una regla bloqueante con el identificador esperado; el accesorio válido da 0 bloqueantes | Contrato |
| AC04 | Sin daño tras un rechazo | El SHA-256 del archivo SQLite y de cada Parquet es idéntico antes y después de una corrida rechazada | Integración |
| AC05 | Carga correcta | Filas de `stg_monthly_production` = filas del subconjunto contadas en la validación; pozos = `idpozo` distintos; todos los controles SQL devuelven 0 filas; recargar la misma publicación deja el mismo contenido | Integración (sintético) y real |
| AC06 | Correcciones consistentes | Las filas marcadas por SQL para cada corrección coinciden con el recuento de la regla equivalente del reporte de validación | Integración |
| AC07 | Ajuste exacto de Arps | Sobre una hiperbólica modificada sin ruido (qi = 500 m³/d, Di = 0,15/mes, b = 1,2, 48 meses): qi ± 1 %, Di ± 3 %, b ± 0,05 y tasa a 12 meses ± 1 %; exponencial sin ruido: Di ± 1 % | Unitaria |
| AC08 | Ajuste con ruido | En 200 curvas sintéticas con ruido lognormal σ = 0,1 (semilla 0), la mediana del error relativo a 12 meses de `arps_mh_b2` ≤ 5 % y el p90 ≤ 15 % | Unitaria |
| AC09 | Forma de la hiperbólica modificada | Continuidad en el cambio (diferencia relativa < 1e-9), declinación nominal igual al límite después del cambio, parámetros siempre dentro de los límites | Unitaria |
| AC10 | Líneas base | Valores exactos sobre accesorios calculados a mano, incluidos meses en cero y meses sin fila | Unitaria |
| AC11 | Sin fuga de información | Perturbar todos los datos posteriores a un origen no cambia ningún pronóstico de ningún método en ese origen (igualdad exacta); el objetivo máximo de los ejemplos de entrenamiento y de los errores de calibración es ≤ origen | Unitaria |
| AC12 | Calibración de bandas | Cobertura P10-P90 de las bandas empíricas en 300 pozos sintéticos: 0,80 ± 0,04 | Unitaria |
| AC13 | Backtest completo | Real: hay resultados para los 6 métodos × 2 fluidos × 4 horizontes × 24 orígenes de evaluación; el número de pares evaluados es igual entre métodos en cada celda; la tasa de respaldo de cada variante de Arps es < 2 % o queda informada | Real |
| AC14 | Arps frente a la línea base (preregistrado) | `arps_mh_b2` tiene un MAE por serie menor que `naive_last` en ≥ 60 % de las series elegibles a 12 meses, y un WAPE menor que `naive_last` a 6 y 12 meses, en cada fluido. Si no se cumple, el resumen y el README lo dicen ("no supera") | Real, y prueba de consistencia entre el resumen y el README |
| AC15 | Cobertura P10-P90 (preregistrado) | Objetivo 0,80. `arps_mh_b2` y `ml_hgb`: "calibrado" entre 0,75 y 0,85, "aceptable" entre 0,70 y 0,90, "descalibrado" fuera, por fluido y horizonte; el veredicto escrito coincide con el número | Real, y prueba de consistencia |
| AC16 | Aporte del machine learning | Se informa, por fluido y horizonte, si `ml_hgb` supera a `arps_mh_b2` (pinball escalada) en las series elegibles y a `naive_mean3` en las jóvenes. Sin umbral: el criterio es que el resultado esté escrito y sea consistente | Real, y prueba de consistencia |
| AC17 | Modelo estrella | Claves de dimensiones únicas y no nulas; 100 % de las claves foráneas de cada hecho existen en su dimensión; todas las relaciones de la especificación son 1:* con filtro unidireccional de la dimensión al hecho; el esquema de cada Parquet coincide con la especificación; cada referencia `tabla[columna]` de las medidas DAX existe | Contrato |
| AC18 | Diseño del tablero | El HTML contiene todas las páginas, visuales, medidas y relaciones de la especificación; no carga recursos externos (solo enlaces de atribución); pesa < 2 MB | Unitaria |
| AC19 | DAG | Los identificadores y el orden de las tareas del DAG coinciden con la lista de tareas de la CLI; programación diaria, sin catchup, una corrida activa a la vez; `airflow dags test` termina con éxito en modo rápido | Estática (sin Airflow) y Docker (manual) |
| AC20 | Punta a punta en modo rápido | Sobre el accesorio sintético, `python -m oilgas run --config config/pipeline.quick.toml` produce todas las salidas y el HTML en ≤ 3 min | E2E |
| AC21 | Punta a punta real | Con la publicación real el flujo completo termina en ≤ 90 min y cada Parquet versionado pesa ≤ 25 MB | Real (manual) |
| AC22 | Reproducibilidad | Dos corridas seguidas sobre la misma entrada producen Parquet con el mismo hash de contenido (sin columnas de fecha de corrida); el backtest da lo mismo con 1 y con 2 procesos | Integración |
| AC23 | Documentación | El README tiene los títulos de la sección 10 del plan en ese orden; el diccionario de datos cubre cada columna de cada Parquet exportado, con unidad; el registro de decisiones tiene todos los campos por entrada; el runbook cubre R1-R11 | Unitaria sobre los Markdown |

## 9. Plan de pruebas

Cuatro niveles, todos con pytest dentro del `.venv` del proyecto. Las marcas `real_data` (necesita `data/raw/`) y `docker` (necesita Docker) se omiten por defecto.

| Nivel | Qué prueba | Requerimientos | Criterios |
| --- | --- | --- | --- |
| Unitarias | Configuración, detección y descarga (servidor HTTP local), series y pico, líneas base, las tres variantes de Arps, calibración empírica, métricas, variables y ejemplos del ML, selección, especificación del modelo semántico, render del HTML, DAG estático | RF01, RF02, RF07-RF15, RF18, RF19 | AC01, AC02, AC07-AC12, AC18, AC19 |
| Contrato de datos | Contrato del CSV y reglas de validación sobre accesorios válidos y malformados; esquema de cada Parquet; integridad referencial; referencias de DAX | RF03, RF17 | AC03, AC17 |
| Integración | Carga a SQLite con los archivos SQL, controles, revisiones, consistencia entre validación y correcciones, sin daño tras un rechazo, reproducibilidad, tareas encadenadas sobre el accesorio | RF04-RF06, RF16, RF17, RF20 | AC04-AC06, AC22 |
| Punta a punta | CLI completa en modo rápido (sintético); flujo completo real (`real_data`); `airflow dags test` en Docker (`docker`); consistencia entre el resumen y el README; documentación | RF14, RF19, RF22 | AC13-AC16, AC20, AC21, AC23 |

Accesorios: un generador (`tests/fixtures/make_fixture.py`) arma un CSV con las 40 columnas reales y unos 60 pozos sintéticos con curvas conocidas, más variantes malformadas; una muestra real de 5 pozos completos (con atribución CC BY 4.0) prueba la lectura del formato verdadero (BOM, tildes, punto decimal).
