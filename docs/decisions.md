# Registro de decisiones

Una entrada por decisión, con su contexto, las opciones, la decisión, el motivo, lo que afecta (campos, métricas, salidas) y quién la tomó. Las propuestas del agente de planificación (Opus) quedan para revisión del dueño; las del dueño citan el registro del documento de seguimiento (`odd/tasks/portfolio-projects.md`). Las cifras salen del perfilado del 2026-11-09 (`requirements.md`, sección 4).

Estados: **vigente**, **pendiente del dueño**, **reemplazada por Dxx**.

---

## D01 Enfoque: curvas y machine learning, comparados

- **Contexto**: el sitio promete curvas de Arps, un modelo de machine learning y una validación mes a mes que los compara.
- **Opciones**: (a) solo curvas de Arps; (b) solo machine learning; (c) los dos, comparados entre sí y con líneas base ingenuas sobre el mismo conjunto de evaluación.
- **Decisión**: (c).
- **Motivo**: (a) es lo que la industria ya usa y se explica con un gráfico, pero no dice si es mejor que repetir el último mes; (b) no se explica pozo por pozo y no puede proyectar más allá de lo que vio; (c) responde la pregunta del sitio, "cuándo suma algo a un método más simple", y obliga a medir las dos cosas contra una línea base.
- **Afecta**: métodos `naive_last`, `naive_mean3`, `arps_*`, `ml_hgb`; `fact_backtest_metrics`; `fact_model_summary`.
- **Quién**: agente de planificación. **Estado**: vigente.

## D02 Subconjunto: Neuquina no convencional, toda la historia

- **Contexto**: la investigación recomendó el archivo no convencional filtrado a Neuquina, no convencional y desde 2015 (L5). El perfilado mostró que 876 de los 4 937 pozos del subconjunto tienen filas antes de 2015 (30 155 filas) y que cortar en 2015 los dejaría sin su pico ni su primera producción.
- **Opciones**: (a) desde 2015, como en la investigación; (b) toda la historia de Neuquina (2006-01 en adelante); (c) todo el archivo, las cuatro cuencas.
- **Decisión**: (b): `cuenca = NEUQUINA`, `tipo_de_recurso = NO CONVENCIONAL`, todos los meses. 413 865 filas, 4 937 pozos, 2006-01 a 2026-09. Se proyectan petróleo y gas; el agua se carga y no se proyecta.
- **Motivo**: el corte en 2015 ahorra el 7 % de las filas y censura por la izquierda a 876 pozos: el pico detectado sería el de 2015-01 y el ajuste de Arps empezaría en mitad de la declinación. Las otras cuencas suman 17 457 filas (4,0 %) con otra geología y pocos pozos; mezclarlas no aporta a la comparación. El dato del sitio "Desde 2006" queda cierto.
- **Afecta**: `scope.*`; `stg_monthly_production`; `dim_well`; `dim_calendar`; todas las métricas.
- **Quién**: agente de planificación (cambia la recomendación de L5). **Estado**: vigente.

## D03 Clave del pozo, períodos y unidades

- **Contexto**: 167 siglas corresponden a más de un `idpozo`; ningún `idpozo` tiene más de una sigla. Los volúmenes vienen en m³ (petróleo, agua) y miles de m³ (gas).
- **Opciones**: clave `sigla` o `idpozo`; períodos como fecha, como `AAAAMM` o como índice de meses; un equivalente de barriles (BOE) o cada fluido por separado.
- **Decisión**: clave `idpozo` (`well_key`); `period_key = AAAAMM` para unir y mostrar, `period_index = año·12 + mes − 1` para la aritmética; petróleo en m³, gas en miles de m³, agua en m³, tasas por día calendario; nunca se suman fluidos ni se usa BOE.
- **Motivo**: `idpozo` es la única clave única y es la que une con el archivo de fractura y el de pozos. El índice de meses evita errores de calendario en los desplazamientos. Sumar fluidos exige un factor de conversión que el sitio no promete y que cambia los resultados.
- **Afecta**: `well_key`, `period_key`, `period_index`, `oil_m3`, `gas_thousand_m3`, `water_m3`; todas las medidas DAX.
- **Quién**: agente de planificación. **Estado**: vigente.

## D04 Almacenamiento: SQLite con archivos SQL

- **Contexto**: el sitio dice "Apache Airflow, Python, SQL" para la automatización. El landing declara SQL, dbt y BigQuery. En este equipo no hay DuckDB ni dbt; el flujo corre en Windows (CLI) y en Linux (contenedor de Airflow) sobre la misma carpeta.
- **Opciones**: (a) SQLite (biblioteca estándar de Python) con archivos SQL versionados en capas y controles en SQL; (b) DuckDB; (c) dbt con el adaptador de DuckDB; (d) dbt con BigQuery; (e) PostgreSQL en Docker.
- **Decisión**: (a), con capas `staging → marts` y controles que devuelven filas que violan (el estilo de las pruebas de dbt).
- **Motivo**: no agrega dependencias en Windows, es un archivo que se monta en el contenedor, soporta funciones de ventana y CTE recursivas, y 414 mil filas le sobran. (b) es más rápido, pero no está en el landing. (c) suma dbt (que sí está) pero también DuckDB y un adaptador. (d) necesita una cuenta de Google Cloud y la participación del dueño (S4). (e) obliga a tener Docker encendido también para la CLI. Las capas y los controles siguen las convenciones de dbt, así que pasar a dbt y BigQuery es mecánico. Riesgo conocido: SQLite sobre una carpeta montada en Docker Desktop; se mitiga con un solo escritor (`max_active_tasks=1`) y `journal_mode=DELETE`, y se verifica en U12.
- **Afecta**: `sql/**`; `warehouse.py`; `data/warehouse/production.sqlite`; `LANDING-EXPANSION.md` (SQLite).
- **Quién**: agente de planificación. **Estado**: vigente.

## D05 Formato de salidas para Power BI: Parquet

- **Contexto**: Power BI necesita tablas listas para cargar; la configuración regional en español usa coma decimal.
- **Opciones**: (a) CSV; (b) Parquet; (c) los dos.
- **Decisión**: (b), una tabla por archivo en `outputs/powerbi/`, con esquema explícito y metadatos de atribución. Se versionan mientras cada archivo pese ≤ 25 MB; los intermedios del backtest nunca.
- **Motivo**: Parquet conserva los tipos y evita que Power BI interprete mal los decimales con la configuración regional en español; se carga con `Parquet.Document` en Power Query. Escribir también CSV duplica archivos sin un uso definido (Looker Studio no está en el alcance). Versionar las tablas permite abrir el diseño sin correr el flujo; el tope de 25 MB evita archivos que GitHub rechaza.
- **Afecta**: `export.py`; `outputs/powerbi/*.parquet`; la carga en Power Query del diseño.
- **Quién**: agente de planificación. **Estado**: vigente.

## D06 Curvas de Arps: variantes, límites y ajuste

- **Contexto**: L5 fijó la hiperbólica modificada con b en [0, 2] como caso base y b ≤ 1 como sensibilidad, porque un b > 1 sin límite hace divergir la recuperación estimada. El sitio dice "exponencial o hiperbólica".
- **Opciones**: elegir la variante por pozo según el error de prueba, o preregistrar una variante base; ajustar la tasa o su logaritmo; tiempo calendario o tiempo productivo; mínimos cuadrados comunes o robustos.
- **Decisión**: tres variantes fijas: `arps_exp`, `arps_mh_b2` (base: Di en [1e-4, 3,0] por mes, b en [0,001, 2,0], declinación terminal 10 % efectiva anual = 0,0087800 nominal por mes) y `arps_mh_b1` (b en [0,001, 1,0]). Ajuste de `ln q` con `curve_fit` (`trf`, `soft_l1`, `f_scale = 0,3`), sobre el segmento posterior al pico, en tiempo calendario, con varios puntos de partida y arranque en caliente. Respaldo: hiperbólica modificada → exponencial → `naive_mean3`, informado por método.
- **Motivo**: elegir la variante por pozo con el error de prueba es una fuga; preregistrar la base hace justa la comparación. El logaritmo pesa parejo meses de 1 000 y de 10 m³/d y modela errores multiplicativos. El tiempo calendario es lo que proyecta un planificador mes a mes; los cierres se excluyen del ajuste pero no detienen el reloj. La pérdida robusta tolera meses parciales. Medido: 3,45 ms por solución y error mediano de 2,3 % a 12 meses en curvas sintéticas.
- **Afecta**: `arps.py`; `fact_well_fit` (`qi_rate_per_day`, `di_nominal_per_month`, `b`, `t_switch_months`, `status`); tasa de respaldo; WAPE y cobertura de `arps_*`.
- **Quién**: dueño (L5, a partir de la investigación) y agente de planificación (detalles). **Estado**: vigente.

## D07 Historia mínima para ajustar: 6 puntos desde el pico

- **Contexto**: el pico llega a una mediana de 2 meses desde la primera producción; 3 728 de 4 458 series de petróleo tienen ≥ 6 meses positivos desde el pico, y 3 416, ≥ 12.
- **Opciones**: 6, 12 o 24 puntos.
- **Decisión**: 6 puntos positivos desde el pico (incluido) hasta el origen y producción en alguno de los últimos 3 meses; por debajo, la serie es "joven" y la proyectan la línea base y el ML.
- **Motivo**: con 12 quedan fuera 312 de las 3 728 series de petróleo que tienen al menos 6 puntos (medido sobre toda la historia), justo las más nuevas, que son las que más interesan a un planificador; con 6 hay el doble de puntos que parámetros. Las métricas se informan por tramo de edad (`06-11`, `12-23`, `24-59`, `60+`), así que la debilidad de las series cortas queda a la vista en lugar de esconderse.
- **Afecta**: `arps.min_post_peak_points`; `segment`; `age_bucket`; tamaño del conjunto de evaluación.
- **Quién**: agente de planificación. **Estado**: vigente.

## D08 Modelo de machine learning: HistGradientBoosting cuantílico

- **Contexto**: el sitio dice scikit-learn. El ejemplo del dueño usaba LightGBM, que no está en el landing.
- **Opciones**: (a) LightGBM; (b) `HistGradientBoostingRegressor` de scikit-learn con pérdida cuantílica; (c) bosque aleatorio; (d) una red recurrente en TensorFlow; (e) regresión cuantílica lineal.
- **Decisión**: (b), un modelo por fluido, horizonte y cuantil; objetivo `ln((r[t+h] + ε)/(m3[t] + ε))`; entrenado con todos los pozos; reentrenado cada 3 orígenes con una ventana de 60 meses y hasta 150 000 ejemplos; hiperparámetros fijos.
- **Motivo**: (b) es el mismo tipo de modelo que LightGBM y está en el landing; acepta categorías y nulos y da los tres cuantiles sin otro método. (a) suma una librería que el landing no declara. (c) no da cuantiles directamente. (d) es desproporcionado para unas 6 000 series mensuales. (e) no capta las interacciones entre edad, declinación y operadora. El objetivo relativo permite aprender de pozos de tamaños muy distintos. Reentrenar cada 3 orígenes baja el costo de unos 576 ajustes a 192; las variables se calculan igual en cada origen. Sin búsqueda de hiperparámetros, la comparación no se inclina hacia el modelo más ajustado.
- **Afecta**: `ml.py`; `features.py`; `ml_hgb` en todas las métricas.
- **Quién**: agente de planificación. **Estado**: vigente.

## D09 Bandas P10/P50/P90

- **Contexto**: hay que dar bandas para cada método y medir su cobertura.
- **Opciones**: (a) bootstrap de residuos por pozo (reajustar la curva sobre residuos remuestreados); (b) cuantiles de los residuos dentro de la muestra; (c) cuantiles empíricos de los errores ya realizados en orígenes anteriores, agrupados por método, fluido, horizonte y tramo de edad; (d) regresión cuantílica.
- **Decisión**: (c) para las líneas base y las curvas; (d) para el ML.
- **Motivo**: (a) multiplica por 100 o más los ajustes (ya son unos 200 000 pares serie-origen por variante de Arps) y, como (b), mide el error dentro de la muestra, que subestima el de pronóstico y no crece con el horizonte. (c) usa solo errores con objetivo anterior o igual al origen (sin fuga), crece con el horizonte por construcción y es barato. El P50 de la curva no se corrige: sigue siendo la curva.
- **Afecta**: `calibration.py`; `p10`, `p90`; cobertura P10-P90; pinball escalada.
- **Quién**: agente de planificación. **Estado**: vigente.

## D10 Validación walk-forward y métricas

- **Contexto**: el sitio dice "entrena con el pasado y prueba con el mes siguiente, avanzando de a un mes".
- **Opciones**: orígenes mensuales o trimestrales; MAPE o WAPE; evaluar cada método donde puede o en un conjunto común; umbrales fijados antes o después de ver los resultados.
- **Decisión**: 24 orígenes mensuales de evaluación (2024-09 a 2026-08) más 12 de calentamiento; horizontes 1, 3, 6 y 12; el mismo conjunto de pares para todos los métodos; MAE, RMSE, WAPE, sesgo, cobertura, pinball escalada, proporción de pozos que superan a la línea base y error del total de la cuenca; umbrales preregistrados en `config/pipeline.toml` (`[criteria]`): 60 % de pozos a 12 meses, WAPE menor a 6 y 12 meses, cobertura entre 0,70 y 0,90.
- **Motivo**: los orígenes mensuales son lo que promete el sitio. MAPE explota con los meses en cero (el 20,3 % de las filas no tiene petróleo ni gas); WAPE no. El conjunto común hace la comparación justa. Fijar los umbrales antes evita moverlos según el resultado. Límite conocido: el backtest usa los datos ya revisados de la publicación actual, no la versión que había en cada origen (no hay versiones archivadas).
- **Afecta**: `backtest.py`; `metrics.py`; `fact_backtest_metrics`; `fact_model_summary`; el bloque de resultados del README.
- **Quién**: agente de planificación. **Estado**: vigente.

## D11 Método en uso para el tablero

- **Contexto**: el tablero muestra una proyección por defecto; el sitio dice que cada mes se reajusta la curva de cada pozo.
- **Opciones**: siempre Arps; siempre el ML; el que mejor resulte en el backtest, por segmento.
- **Decisión**: por fluido y segmento, el método con menor pinball escalada promedio en los horizontes 1, 3, 6 y 12 (elegibles: `arps_mh_b2`, `ml_hgb`, `naive_mean3`; jóvenes: `ml_hgb`, `naive_mean3`); en empate, el más simple. Los tres métodos quedan en `fact_forecast` para compararlos.
- **Motivo**: elegir por los datos y con una regla escrita antes es honesto; la pinball mide a la vez el P50 y las bandas. Las curvas se reajustan cada mes igual, aunque no ganen.
- **Afecta**: `model_selection`; `fact_forecast[is_selected]`; las medidas P10/P50/P90.
- **Quién**: agente de planificación. **Estado**: vigente.

## D12 Orquestación: Airflow en Docker y una CLI equivalente

- **Contexto**: Airflow no corre nativo en Windows (requiere WSL2 o contenedores; 4 GB mínimo para Docker). El equipo tiene Docker 28.5 con Compose.
- **Opciones**: (a) Docker Compose oficial; (b) `airflow standalone` en WSL2; (c) solo la CLI; programación mensual o diaria.
- **Decisión**: (a), a partir del archivo oficial de 3.4.0 con `LocalExecutor`, más una CLI que ejecuta la misma tupla `TASKS` sin Airflow. Programación diaria (`0 9 * * *` UTC) con un `HEAD` que corta el flujo si no hay cambios; sin catchup; una corrida y una tarea activas a la vez.
- **Motivo**: (a) es la vía oficial en Windows; (b) es solo para desarrollo y suma WSL; (c) no muestra Airflow, que el sitio promete. Las tareas como funciones puras se prueban con pytest sin Airflow. La programación diaria toma una publicación tardía el mismo día que aparece y recarga una republicación; una mensual elegiría un día arbitrario. Una tarea a la vez protege a SQLite. `LocalExecutor` baja la memoria frente a Celery y Redis.
- **Afecta**: `pipeline.py`; `airflow/**`; `pipeline_runs`; runbook R1, R8, R9.
- **Quién**: agente de planificación. **Estado**: vigente.

## D13 Detección de cambios en la fuente

- **Contexto**: verificado el 2026-11-09: el servidor responde a `HEAD` con `ETag`, `Last-Modified` y `Content-Range`, pero ignora `Range`, `If-None-Match` e `If-Modified-Since` (siempre 200). Las URLs son HTTP.
- **Opciones**: descargar siempre y comparar el SHA-256; descarga condicional; `HEAD` y manifiesto.
- **Decisión**: `HEAD` y comparación de ETag, Last-Modified y tamaño contra la última carga exitosa del manifiesto; descarga completa solo si algo cambió, con SHA-256 y tamaño verificados.
- **Motivo**: descargar 149 MB por día para descubrir que no cambió no tiene sentido, y la descarga condicional no funciona en este servidor. El SHA-256 cubre la falta de HTTPS.
- **Afecta**: `ingest.py`; `data/raw/manifest.json`; `pipeline_runs.source_*`.
- **Quién**: agente de planificación. **Estado**: vigente.

## D14 Power BI como diseño en HTML generado

- **Contexto**: Power BI Desktop es gratuito pero el informe se arma en una interfaz gráfica; S4 pide un HTML con el diseño del tablero, las relaciones y lo demás.
- **Opciones**: (a) HTML escrito a mano; (b) HTML generado desde una especificación del modelo semántico, con números reales; (c) un proyecto PBIP con TMDL escrito a mano.
- **Decisión**: (b). `dashboard/semantic_model.py` es la fuente única de las tablas, relaciones, medidas y páginas; de ahí salen el esquema de los Parquet, el diccionario de datos y el HTML.
- **Motivo**: un HTML a mano envejece apenas cambian los datos o una columna. La especificación permite probar lo que pidió el dueño ("verificar que las relaciones … sean de 1 a varios (1:\*) con filtro unidireccional"): claves únicas, integridad referencial y referencias de DAX. (c) no está verificado como práctico a mano (investigación) y no reemplaza ubicar los visuales.
- **Afecta**: `dashboard/**`; `outputs/powerbi/*`; `docs/data-dictionary.md`.
- **Quién**: dueño (S4) y agente de planificación (forma). **Estado**: vigente.

## D15 Datos de fractura: fuera del modelo base

- **Contexto**: el sitio menciona la decisión de sumar o no el dataset público de fractura, "que todavía es preliminar". Medido: 5 062 filas de 4 818 pozos; cubre 3 824 de los 4 937 pozos del subconjunto (77 %) y 3 129 de los 3 524 shale (89 %); 2 054 filas (41 %) con longitud de rama horizontal 0; 183 pozos con más de una fila. La nota oficial dice "Datos preliminares sujetos a revisión".
- **Opciones**: (a) sumarlo al modelo base; (b) dejarlo fuera; (c) dejarlo fuera del base y medir su aporte con una ablación del ML sobre el mismo conjunto de evaluación.
- **Decisión**: (b) para la versión base; (c) como unidad opcional U15.
- **Motivo**: con el 41 % de longitudes de rama en 0 y un 23 % de pozos sin fila, sumarlo al base mezcla un dato dudoso con la comparación principal. La ablación respondería con números si aporta, sin poner en riesgo el resultado base.
- **Afecta**: `features.py` (variables de fractura, opcionales); RF21; la narrativa de "Decisiones" en el README.
- **Quién**: agente de planificación. **Estado**: pendiente del dueño (correr o no U15).

## D16 Idioma

- **Contexto**: el sitio está en español por defecto; el código lo leen herramientas y personas de cualquier idioma.
- **Opciones**: todo en español; todo en inglés; mixto.
- **Decisión**: documentación en español neutro; código, identificadores, tablas, columnas y nombres de archivo en inglés; medidas DAX, títulos de visuales y textos del tablero en español.
- **Motivo**: es lo que fija el documento de seguimiento para todos los proyectos; quien abre el tablero lee español, quien abre el código lee identificadores estándar.
- **Afecta**: todo el proyecto.
- **Quién**: documento de seguimiento (supuesto común a los proyectos). **Estado**: vigente.

## D17 Entorno y versiones

- **Contexto**: en el Python global, pyarrow 26.0.0 exige NumPy ≥ 2.0 y NumPy es 1.26.4: scikit-learn 1.7.2 no se puede importar. SciPy 1.11.4 sí está instalado. Python 3.11, SQLite 3.39.4.
- **Opciones**: arreglar el entorno global; un `.venv` propio con rangos; un `.venv` propio con versiones exactas.
- **Decisión**: `.venv` del proyecto, instalado con rangos (`numpy>=2.1,<2.5`, `pandas>=2.2.3,<3.0`, `scipy>=1.14,<1.18`, `scikit-learn>=1.6,<1.10`, `pyarrow>=18`, `matplotlib>=3.9,<3.12`, `pytest>=8`) y luego fijado con `==` a lo resuelto. pandas por debajo de 3.0.
- **Motivo**: tocar el entorno global puede romper otros proyectos del dueño. Fijar versiones exactas da reproducibilidad (RNF01). pandas 3 cambia el tipo de texto por defecto y la semántica de copias; 2.2 evita sorpresas sin perder compatibilidad con NumPy 2. scikit-learn ≥ 1.6 para `categorical_features="from_dtype"`.
- **Afecta**: `requirements.txt`; `requirements-dev.txt`; `airflow/requirements-airflow.txt`.
- **Quién**: agente de planificación. **Estado**: vigente.

## D18 Correcciones de calidad de datos

- **Contexto**: medidas: 2 volúmenes de gas negativos; 70 filas con `tef` mayor que los días del mes (en varias `tef` repite `prod_gas`, como un corrimiento de columnas); 384 filas con `tef = 0` y producción; 1 pozo con coordenadas intercambiadas; 172 pozos con profundidad 0 y 4 con más de 8 000 m.
- **Opciones**: descartar filas; corregir sin marcar; corregir lo indefendible a nulo y marcar todo.
- **Decisión**: negativos y `tef` imposibles a nulo; coordenadas intercambiadas se intercambian; profundidades imposibles a nulo; todo con su marca en `quality_flags` y su recuento en el reporte de validación. Ninguna fila se descarta. `tef` no se usa en los ajustes.
- **Motivo**: descartar filas abre huecos falsos en las series; corregir sin marcar esconde el problema. Las correcciones viven en SQL, a la vista, y una prueba exige que coincidan con los recuentos de la validación.
- **Afecta**: `stg_monthly_production`; `dim_well`; `quality_flags`; reglas V12-V18.
- **Quién**: agente de planificación. **Estado**: vigente.

## D19 Bandas agregadas en el tablero

- **Contexto**: sumar P10 o P90 de varios pozos no da el P10 o el P90 del total.
- **Opciones**: (a) calcular bandas por grupo en Python para cada combinación de filtros; (b) mostrar la suma de los cuantiles por pozo, rotulada como tal, e informar su cobertura real a nivel de cuenca.
- **Decisión**: (b).
- **Motivo**: (a) no se puede precalcular para todas las combinaciones de filtros del tablero. La suma de cuantiles equivale a suponer que todos los pozos se mueven juntos y da una banda más ancha que la verdadera si son independientes; rotularla y medir su cobertura (`basin_band_coverage`) es honesto y barato.
- **Afecta**: medidas P10/P90; `fact_model_summary[basin_band_coverage]`; la ficha del modelo.
- **Quién**: agente de planificación. **Estado**: vigente.

## D20 Cómo se cuenta "Con IA, de punta a punta"

- **Contexto**: el sitio dice que un agente lee los CSV "a través de un servidor MCP" y que un "grafo de conocimiento" une campos, métricas y decisiones. El proceso real: agentes de Claude Code (investigación con Haiku, plan con Opus, programación con Sonnet, evaluación con Opus); el CSV se perfiló con Python desde la terminal; los servidores MCP usados fueron Context7 (documentación) y Engram (memoria); las decisiones viven en este registro.
- **Opciones**: (a) contar el proceso real y proponer los cambios de texto del sitio; (b) hacer verdad el texto actual con un grafo de decisiones generado desde las líneas "Afecta" de este registro; (c) las dos.
- **Decisión**: (c) propuesta: el README cuenta solo lo que figura en el registro del documento de seguimiento, el plan (sección 18) propone el texto nuevo para el sitio, y el grafo de decisiones se genera en U14 si el dueño elige la opción A.
- **Motivo**: S9 pide fidelidad al sitio y, cuando la construcción real difiere, registrar la diferencia para corregir el sitio. Afirmar un MCP que no leyó los CSV sería falso.
- **Afecta**: README ("Con IA, de punta a punta"); `docs/decision-graph.*` (opcional); el texto del sitio en `marca-personal`.
- **Quién**: agente de planificación. **Estado**: pendiente del dueño (texto del sitio y opción A o B).

## D21 Versiones resueltas del entorno (U01)

- **Contexto**: D17 fijó rangos de partida y pidió reemplazarlos por las versiones exactas resueltas. Se instaló un `.venv` de Python 3.11.1 en Windows y `pip check` no reportó conflictos.
- **Opciones**: fijar solo las dependencias directas; fijar también las transitivas.
- **Decisión**: `requirements.txt` fija con `==` las directas (`numpy 2.4.6`, `pandas 2.3.3`, `scipy 1.17.1`, `scikit-learn 1.9.1`, `pyarrow 26.0.1`, `matplotlib 3.11.2`) y las transitivas que resolvió pip; `requirements-dev.txt` incluye `-r requirements.txt` y agrega `pytest 9.2.0` con las suyas. Sin `requests` (la descarga usa `urllib.request`).
- **Motivo**: RNF01 pide reproducibilidad; sin las transitivas fijadas, una versión nueva de una librería secundaria puede cambiar el resultado. Se tomó la resolución más reciente que cae dentro de los rangos de D17; si una versión falla en U05-U09, se retrocede dentro del rango y se anota aquí.
- **Afecta**: `requirements.txt`; `requirements-dev.txt`; `airflow/requirements-airflow.txt` (U12 debe revisar la compatibilidad con la imagen de Airflow).
- **Quién**: agente de programación (Sonnet), U01. **Estado**: vigente.

## D22 Configuración: herencia con `extends`, claves estrictas y paquete sin instalar (U01)

- **Contexto**: el plan dice que `pipeline.quick.toml` "sobrescribe" valores de `pipeline.toml` y que `load_config(path, overrides)` recibe dos archivos, pero no dice cómo se usa el archivo rápido con `--config`. Tampoco dice cómo se importa el paquete en las pruebas.
- **Opciones**: (a) el archivo rápido es completo y repite todo; (b) el archivo rápido trae solo las diferencias y siempre se combina con el completo; (c) el archivo rápido trae solo las diferencias y declara de cuál parte con `extends = "pipeline.toml"`. Para el paquete: instalar en modo editable o agregar `src` al `pythonpath` de pytest.
- **Decisión**: (c). Un archivo puede abrir con `extends` (ruta relativa al propio archivo; cadenas y bucles se detectan); `overrides` se combina clave por clave sobre el resultado. Una sección o clave desconocida, una clave faltante, un tipo equivocado, un par de límites desordenado o `OILGAS_N_WORKERS` que no sea un entero positivo son `ValueError` con el nombre de la clave. `source.mode` solo admite `http` o `local`. El paquete se importa con `pythonpath = ["src", "."]` en `pyproject.toml`; no se instala.
- **Motivo**: (c) hace que `--config config/pipeline.quick.toml` funcione solo y que el archivo rápido muestre exactamente qué cambia. Rechazar claves desconocidas evita que un error de tipeo en una sobrescritura se ignore en silencio. Sin instalación editable no hay nada que reinstalar al cambiar de rama; U12 la agrega si hace falta para `python -m oilgas`.
- **Afecta**: `config.py`; `config/pipeline.quick.toml`; `pyproject.toml`; todas las pruebas que cargan configuración.
- **Quién**: agente de programación (Sonnet), U01. **Estado**: vigente.

## D23 Lectura del CSV y accesorios de prueba (U01)

- **Contexto**: el plan pide un generador de accesorios y una muestra real de los 5 pozos "con más meses de historia entre los shale de petróleo elegibles". No dice cómo se resuelve cada caso de datos malos en el generador ni qué significa "elegibles" para la muestra.
- **Opciones**: muestra (a) los 5 pozos shale con más meses de petróleo positivo, o (b) los 5 con más filas; accesorio válido con o sin pozos fuera del alcance.
- **Decisión**: la muestra son los 5 pozos shale de Neuquina con más meses de petróleo positivo que producen en alguno de los últimos tres meses (2026-07 a 2026-09): `3640`, `126808`, `135480`, `136060`, `136203` (1 130 filas, 379 KB, con su atribución). El accesorio válido trae 60 pozos del alcance más 3 fuera de él (otra cuenca, otro tipo de recurso) para que el filtro se pruebe, y registra en `FixtureTruth` dónde está cada caso: un gas negativo, un `tef` mayor que los días del mes, dos `tef = 0` con producción, un pozo con coordenadas intercambiadas, dos profundidades inválidas, dos cambios de operadora, meses en cero, meses sin fila, pozos jóvenes y pozos que dejan de informar. El accesorio no contiene filas con tope de volumen (V15 da 0, como en la publicación real); su prueba modifica un marco de datos en memoria. `read_source_csv` lee todo como texto (los vacíos son nulos), con `utf-8-sig`.
- **Motivo**: (a) coincide con la definición de serie elegible de D07 (positivos suficientes y actividad reciente); (b) incluiría pozos con muchos ceros. Con ceros, huecos y casos de calidad en posiciones conocidas, las pruebas de U03 y U04 verifican recuentos exactos en lugar de «alguno». Leer como texto permite que la validación cuente lo que no convierte (V03, V07). Medido: la publicación completa se lee en unos 1,4 s.
- **Afecta**: `schema.py`; `tests/fixtures/*`; pruebas de U03 (recuentos de V12-V16) y U04 (coherencia validación-SQL).
- **Quién**: agente de programación (Sonnet), U01. **Estado**: vigente.

## D24 Manifiesto, errores de descarga y modo local (U02)

- **Contexto**: el plan fija las firmas de `ingest.py` pero no el formato del manifiesto, lo que pasa al repetir una tarea, el error de un 404 ni cómo se detectan cambios sobre un archivo local.
- **Opciones**: manifiesto como lista JSON plana o como objeto con versión; repetir una tarea agrega otra entrada o reemplaza la de la misma corrida; en modo local, comparar el hash o el tamaño y la fecha de modificación.
- **Decisión**: `data/raw/manifest.json` es un objeto `{"version": 1, "entries": [...]}` con los nueve campos de `ManifestEntry`, escrito a un temporal y renombrado. Agregar una entrada con un `run_key` que ya existe la reemplaza (RNF05). Un 404 en `HEAD` o en `GET` lanza `SourceNotFoundError`, cuyo mensaje remite al runbook R11; cualquier otro error HTTP se propaga tal cual para que lo reintente el orquestador. Un manifiesto ilegible lanza `ValueError` y nunca se sobrescribe. El tamaño sale de `Content-Range` (lo que responde el servidor real) y, si falta, de `Content-Length`. La descarga lleva `User-Agent: oilgas-pipeline/0.1`, no manda `Range` ni cabeceras condicionales, y compara los bytes recibidos con el tamaño anunciado, o con `Content-Length` si no se pasó uno. En modo local `local_meta` usa tamaño y fecha de modificación (sin `ETag`), y `adopt_local_file` solo calcula el SHA-256 del archivo que ya está; no lo mueve ni lo copia. `is_changed` compara `ETag`, `Last-Modified` y tamaño; no compara la URL (AC01).
- **Motivo**: un objeto con versión deja espacio para migrar el formato sin romper el archivo. Reemplazar por `run_key` hace idempotente reintentar `download` después de una falla. El error de 404 es el único que tiene un procedimiento distinto (R11); el resto es transitorio y le toca a Airflow reintentar. Leer 149 MB para hacer el hash en modo local en cada chequeo diario sería un costo sin sentido: tamaño y fecha alcanzan, y el SHA-256 se calcula solo al adoptar.
- **Afecta**: `ingest.py`; `data/raw/manifest.json`; `pipeline_runs.source_*`; runbook R11.
- **Quién**: agente de programación (Sonnet), U02. **Estado**: vigente.

## D25 Cómo se evalúan y se informan las reglas de validación (U03)

- **Contexto**: el plan lista V01-V20 e I01-I03 con su severidad, pero deja sin definir qué cuenta como «fila afectada» en las reglas por pozo o por período, qué pasa con las reglas que no se pueden evaluar después de un fallo, ni qué hace «pasa» una regla informativa. Los recuentos del perfilado del 2026-11-09 sirven de referencia.
- **Opciones**: (a) evaluar todas las reglas siempre, con valores por defecto cuando falta información; (b) informar solo las reglas que se pudieron evaluar y listar el resto; para las reglas por pozo, contar pozos o contar filas de esos pozos.
- **Decisión**: (b). `ValidationReport.not_evaluated` lista las reglas que no se evaluaron; el Markdown las muestra en «No evaluadas». V01 cubre también un CSV que no se puede leer (archivo vacío o con comillas sin cerrar), no solo la decodificación. V19 se evalúa siempre que el archivo se lea, aunque V02 falle. El subconjunto se filtra por igualdad exacta de `cuenca` y `tipo_de_recurso`. V05 compara el texto de `fecha_data` con `AAAA-MM-DD` del último día del mes (con años bisiestos): un valor con otro formato cuenta como inconsistente. V06 cuenta las filas sobrantes, no las duplicadas. V07 cuenta las filas con algún volumen nulo o no convertible y falla si superan 0,1 % de las filas del subconjunto. V09 informa las filas y los pozos que faltan. Las reglas de pozo (V16, V17, V18) miran la última fila de cada pozo, cuentan `wells_affected` por pozo y `rows_affected` como las filas de esos pozos; V16 incluye coordenadas ausentes como «fuera de la cuenca»; V17 no cuenta una profundidad nula; V18 compara sigla, provincia, concesión, yacimiento, formación, subtipo, coordenadas y profundidad, y no el operador. V20 mira los períodos con más de 3 meses de antigüedad respecto del último período del archivo nuevo, compara petróleo y gas por separado, cuenta como cambio un período que desapareció, y cuenta `rows_affected` como las filas nuevas de esos períodos. I02 busca la marca `[Sin movimientos]` dentro de la observación, porque la publicación trae tres filas con la tilde dañada («autom?camente»). Una regla informativa siempre figura como «pasa» y solo cuenta. El marco validado conserva los valores tal como se publicaron, con tipos (enteros, decimales, fechas, booleanos) y nombres en inglés, más `period_key` y `period_index`. Cada corrida escribe `latest.json` y `latest.md` y una copia en `history/<run_key>`, también cuando se rechaza el archivo.
- **Motivo**: (b) evita informar como «pasa» una regla que nunca se evaluó, que es peor que no informarla. Contar filas de los pozos afectados permite comparar con las filas que marca el SQL (AC06). La comparación de V20 por antigüedad deja fuera las republicaciones normales de los últimos meses. Medido sobre la publicación real: V12 = 2 filas, V13 = 70, V14 = 384, V15 = 0, V16 = 1 pozo, V17 = 176 pozos (172 + 4), V18 = 0, I02 = 7 421, I03 = 7 420 meses en 703 pozos, todos iguales al perfilado; la validación completa tarda unos 5 s y usa unos 0,5 GB.
- **Afecta**: `validate.py`; `reports/validation/*`; `fact_validation`; coherencia entre validación y SQL (U04); runbook R5.
- **Quién**: agente de programación (Sonnet), U03. **Estado**: vigente.

## D26 Almacén: carga transaccional, revisiones y controles por grupo (U04)

- **Contexto**: el plan fija las tablas y las firmas de `warehouse.py` pero deja abiertos dónde viven los controles del modelo, qué cuenta como «fila revisada», cómo se reutiliza `previous_load` y qué parámetros necesita el SQL (los umbrales de V15 a V17 viven en la configuración, que `load_validated_subset(conn, frame, run_key)` no recibe).
- **Opciones**: controles en una carpeta plana con prefijos o en subcarpetas por grupo; contar como revisión solo los cambios y las filas que desaparecen, o también las filas que aparecen en un período ya publicado; derivar `previous_load` de `raw_monthly_production` o de `period_totals`.
- **Decisión**: los controles viven en `sql/checks/production/` y `sql/checks/model/`; `run_checks(conn, grupo)` ejecuta los `chk_*.sql` de la carpeta (un `SELECT` por archivo) y rechaza un grupo desconocido. `load_validated_subset` recibe además un argumento opcional `cfg` (por defecto la configuración vigente) para pasar los umbrales como parámetros con nombre al SQL. `stg_monthly_production` se declara en `001_core.sql` con su clave y `sql/staging/` la vacía y la vuelve a llenar; los marts se reconstruyen con `DROP` y `CREATE TABLE AS`. `002_model.sql` ya crea las tablas del modelo con las columnas del plan. Una revisión es una fila de un período anterior o igual al último ya cargado que cambió algún volumen en más de 1e-6 (o pasó de valor a nulo o al revés), que desapareció o que aparece sin haber estado: las tres suman a `revised_rows` y a `load_revisions`. `previous_load` se calcula siempre desde `raw_monthly_production`, que es lo que hoy tiene el almacén; `period_totals` queda como historial de lo que dijo cada publicación. Si cualquier control devuelve filas, la excepción `CheckFailedError` lleva todos los resultados y la transacción vuelve atrás: el almacén queda como estaba, incluidas las tablas de una primera carga. Se agregó `record_validation_results` para guardar las reglas de una corrida en `validation_results`.
- **Motivo**: las subcarpetas evitan una lista de prefijos que hay que mantener. Contar también las filas que aparecen en meses viejos es la lectura de «el dato de un mes pasado cambió» que importa a quien mira los totales, y cuesta una consulta más. Una sola fuente de verdad para `previous_load` evita que la tabla de totales y los datos diverjan. Medido sobre la publicación real: la carga completa (413 865 filas) tarda unos 25 s; los 10 controles dan 0 filas; las marcas del SQL coinciden con los recuentos de la validación (V12 = 2, V13 = 70, V14 = 384, V16 = 1 pozo, V17 = 176 pozos).
- **Afecta**: `warehouse.py`; `sql/**`; `pipeline_runs`; `load_revisions`; U10 (los controles del modelo van en `sql/checks/model/`); runbook R5.
- **Quién**: agente de programación (Sonnet), U04. **Estado**: vigente.

## D27 Panel de series, líneas base y métricas: convenciones (U05)

- **Contexto**: el plan fija las firmas de `series.py`, `baselines.py` y `metrics.py` pero deja abiertos qué columnas abarca el panel cuando se usa una muestra de pozos, cómo se completa una categoría que cambia por mes cuando un mes no tiene fila, qué devuelven las líneas base sin datos en la ventana, qué devuelve una métrica relativa a un total de cero y qué columnas lleva el marco largo del backtest.
- **Opciones**: panel con los meses de la muestra o de todo el almacén; dejar sin dato (-1) el mes sin fila o arrastrar el último valor conocido; NaN o excepción para las métricas indefinidas.
- **Decisión**: el panel abarca todos los meses del almacén, también cuando `well_sample > 0`, para que una muestra tenga las mismas columnas que el panel completo y el mismo último mes. Las categorías que cambian por mes (operadora, tipo de pozo, método de extracción) se guardan como códigos con el último valor informado hasta ese mes (nunca uno posterior) y -1 antes del primer informe; `SeriesPanel` suma el campo `categories` con las etiquetas de los códigos, y `assemble_panel` arma un panel desde arreglos densos (lo usa `build_panel` y lo usan las pruebas con series sintéticas). El pico es el primer máximo de las tasas positivas hasta el origen. La actividad mira las columnas [origen − 2, origen]. `age_bucket` trae un parámetro `young_below` (por defecto 6) para seguir el mínimo de puntos de la configuración. Si la ventana de las líneas base no tiene ninguna fila, el pronóstico es NaN (esa serie no está activa y nunca se evalúa). `wape`, `bias`, `coverage` y `scaled_pinball` de un conjunto vacío o de un total real de cero dan NaN. `additive_components` define el error con signo como pronóstico menos real (P50) y la pinball como la suma de los tres cuantiles. `share_beats(frame, método, base, by)` recibe el marco largo (`fluid, well_id, origin, horizon, method, actual, p50`), compara por serie sobre los pares (origen, horizonte) que tienen los dos métodos y devuelve `n_series`, `n_beats` y `share` por cada grupo de `by` (por defecto fluido y horizonte); un empate no cuenta como superar.
- **Motivo**: una muestra con otros meses cambiaría el índice de columnas y el `last_index` del backtest según los pozos sorteados. Arrastrar el último valor evita que un mes sin fila deje a una serie activa sin operadora ni método de extracción, sin mirar nunca hacia adelante. NaN en las métricas indefinidas evita que un grupo vacío rompa un resumen entero y deja visible que no hay dato. Comparar solo los pares comunes es lo que exige AC13 para que la comparación sea justa.
- **Afecta**: `series.py`; `baselines.py`; `metrics.py`; el marco del backtest (U07); las medidas de `fact_backtest_metrics`.
- **Quién**: agente de programación (Sonnet), U05. **Estado**: vigente.
