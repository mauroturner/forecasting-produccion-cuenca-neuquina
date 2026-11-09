# Paso a paso: cómo se hizo este proyecto

Cronología real, desde la investigación hasta la corrida final, una sección por etapa o unidad de trabajo. Se escribió con el registro del documento de seguimiento del portafolio (`odd/tasks/portfolio-projects.md`), el registro de decisiones (`docs/decisions.md`) y el historial de Git; las horas son las de las confirmaciones del 2026-11-09. Donde algo no se hizo o no se verificó, el texto lo dice.

## Cómo se organizó el trabajo

El dueño del portafolio pidió, con sus palabras, desarrollar «de a un proyecto a la vez, con la posibilidad de lanzar agentes cuando lo necesites» para la investigación, los requerimientos, la programación y las pruebas, y usar un modelo distinto según la tarea: «Opus» para planes, arquitectura y evaluación, «Sonnet» para programar y «Haiku» para tareas sencillas y bien delimitadas como investigar. Así se repartió este proyecto:

| Etapa | Quién | Qué entregó |
| --- | --- | --- |
| Investigación | Agente de Claude Code con Haiku | `docs/research.md` |
| Requerimientos, arquitectura y plan | Agente con Opus | `docs/requirements.md`, `docs/plan.md`, `docs/decisions.md` (D01-D20) |
| Programación | Agente con Sonnet, en lotes de unidades, pruebas primero | Las unidades U01-U15 y el endurecimiento H1 |
| Revisión por unidad | Revisión nativa de Gentle AI | Un bloqueante en U04 y advertencias en U02, U03 y U04 |
| Orquestación | La sesión principal de Claude Code | El documento de seguimiento, los lotes y los controles de cada commit |
| Evaluación final independiente | Agente con Opus | **Pendiente**: todavía no se hizo |

Reglas que se mantuvieron en todas las unidades: primero la prueba (se observa que falla, luego se escribe el código), una comprobación de mutación por unidad (romper a propósito una línea de la lógica y ver qué prueba lo detecta), la suite completa en verde antes de cada commit y un commit por unidad con mensaje convencional.

## 1. Investigación (Haiku, 14:43)

Un agente con Haiku consultó la API del portal de datos (CKAN), las cabeceras HTTP y las primeras líneas de los CSV, y escribió `docs/research.md`. Encontró el archivo de no convencionales (149 MB, 40 columnas), el archivo de fractura (1,27 MB, «datos preliminares sujetos a revisión»), la licencia CC BY 4.0 y que el servidor ignora los pedidos por rangos, así que la descarga es siempre completa. También cuestionó un supuesto de partida: que «b mayor que 1 es común en shale». Las fuentes no lo respaldaban sin más, y de ahí salió la elección de la curva hiperbólica modificada con b acotado (D06). Un archivo de 328 MB se bajó por error y se borró.

## 2. Requerimientos y plan (Opus, 15:13)

Un agente con Opus descargó el CSV completo, lo perfiló con scripts de Python desde la terminal y escribió los requerimientos, el plan y las primeras 20 decisiones. Lo que midió cambió el plan en cuatro puntos:

- El corte en 2015 que proponía la investigación dejaba sin su pico a 876 pozos: se tomó toda la historia de la cuenca Neuquina (413.865 filas, 4.937 pozos; D02).
- El 20,3 % de las filas no tiene petróleo ni gas, así que el error relativo es el WAPE y no el MAPE (D10).
- El servidor tampoco responde a pedidos condicionales: el cambio de publicación se detecta comparando las cabeceras de un `HEAD` con un manifiesto (D13).
- El Python global de la máquina estaba roto (pyarrow pedía NumPy 2 y había NumPy 1.26): el proyecto exige su propio entorno virtual (D17).

Comparó tres enfoques (solo curvas, solo machine learning, los dos comparados; D01) y fijó los umbrales de aceptación **antes** de construir nada (D10): la curva de Arps debe superar a repetir el último mes en al menos el 60 % de los pozos a 12 meses, y las bandas P10-P90 deben cubrir entre el 70 % y el 90 % de los valores reales. Consultó la documentación de Airflow por el servidor MCP Context7. El plan quedó dividido en 15 unidades.

## 3. La programación, unidad por unidad (Sonnet)

### U01, andamiaje y contrato de datos (15:22)

Entorno virtual con versiones fijadas (D21), configuración con herencia y claves estrictas (D22), el contrato de las 40 columnas, un generador de publicaciones sintéticas con casos de datos malos en posiciones conocidas y una muestra real de cinco pozos con su atribución (D23). 2.823 líneas, 1.131 de ellas el accesorio de prueba.

### U02, detección y descarga (15:25)

`HEAD` con comparación de `ETag`, fecha y tamaño contra un manifiesto, descarga completa en bloques con SHA-256 y un archivo `.part` que solo se renombra si el tamaño coincide; adopción de un archivo ya descargado (D24). Las pruebas levantan un servidor HTTP local en un hilo.

### U03, validación (15:32)

Las reglas V01 a V20 y las informativas I01 a I03, con un reporte JSON y Markdown por corrida (D25). Sobre la publicación real: ninguna regla bloqueante, y los recuentos coinciden con el perfilado (V12 = 2, V13 = 70, V14 = 384, V16 = 1 pozo, V17 = 176 pozos). Tarda unos 5 segundos.

### U04, almacén y SQL (15:42)

SQLite con SQL versionado en capas y controles que devuelven las filas que violan una regla; carga transaccional, idempotente y con recuento de revisiones (D26). Sobre la publicación real: unos 25 segundos, 10 controles en cero y marcas de calidad iguales a las de la validación. En la revisión nativa de esta unidad apareció un bloqueante real (sección 4).

### U05, series, líneas base y métricas (15:51) y U06, curvas de Arps (15:55)

El panel denso de pozos por meses (pensado para que la fuga de información sea fácil de evitar: todo cálculo en un origen mira solo hasta esa columna), las dos líneas base y las métricas (D27). La curva hiperbólica modificada con declinación terminal del 10 % anual, ajustada en escala logarítmica con `scipy.optimize.curve_fit` (D28). El escritor había puesto tolerancias del optimizador de 1e-12; se midió que duplicaban el tiempo del backtest sin recuperar nada y se volvió a las tolerancias por defecto (commit `52acc38`, 16:05).

### U07, backtest walk-forward y bandas empíricas (16:14)

36 orígenes mensuales (12 de calentamiento y 24 de evaluación), horizontes de 1, 3, 6 y 12 meses, paralelismo con `ProcessPoolExecutor` y bandas P10 y P90 que salen de los errores ya realizados antes de cada origen (D29). Pruebas de no fuga: perturbar todo lo posterior al origen no cambia ningún pronóstico en ese origen.

### U08, machine learning (16:26)

`HistGradientBoostingRegressor` con pérdida cuantílica (0,1; 0,5; 0,9) y variables que solo usan datos hasta el origen; reentrenamiento cada tres orígenes (D30). Con una muestra de 600 pozos, el ML tuvo la menor pinball escalada en todas las celdas; era una muestra, no un resultado.

### H1, endurecimiento tras las revisiones (16:43)

Las advertencias no bloqueantes de las revisiones de U02, U03 y U04 se decidieron una por una (D31): la mayoría se corrigió con una prueba cada una, dos se difirieron y dos se rechazaron, cada una con su motivo. Entre las corregidas: un temporal propio en cada escritura del manifiesto, el registro de eventos con `logging` en todos los módulos, un plazo de espera de 30 segundos para el bloqueo de SQLite y una excepción clara cuando el esquema del almacén cambió.

### U09, resumen, criterios y pronóstico en uso (17:04)

El resumen del backtest, la evaluación de los criterios fijados de antemano con plantillas de texto que dicen también el resultado desfavorable, la regla de selección del método en uso y el pronóstico a 12 meses con el último mes publicado como origen (D32).

### U10, modelo estrella (17:17)

Quince tablas en Parquet (ocho dimensiones y siete hechos) generadas desde una única especificación del modelo semántico, con verificación posterior de claves, relaciones uno a varios con filtro único y referencias DAX (D33). Un hallazgo de tamaño: con los 4.937 pozos, `fact_forecast` pesa unos 7 MB por origen, así que el límite de 25 MB por archivo permite unos tres orígenes completos y no los doce que estimaba el plan; la exportación recorta sola.

### U11, diseño del tablero en HTML (17:29)

Power BI Desktop necesita una persona frente a la interfaz y una licencia para publicar, así que, como pidió el dueño para estos casos, el diseño se entrega como un HTML autocontenido: pasos, diagrama del modelo, relaciones, consultas de Power Query, medidas DAX y las cinco páginas con vistas previas dibujadas con números reales de los Parquet (D34).

### U12, orquestación (17:44)

La tupla `TASKS` que recorren por igual la CLI (`python -m oilgas run`) y el DAG de Airflow, con el estado de cada corrida en un archivo y el rechazo sin daño comprobado por el hash del archivo SQLite y de cada Parquet (D35). El DAG se verificó de forma estática; `airflow dags test` en Docker quedó pendiente porque Docker Desktop estaba apagado.

## 4. La revisión nativa de Gentle AI

Cada unidad de código es un commit y Gentle AI puede revisar un commit aparte. Lo que pasó, tal cual consta en el registro:

- **U01** no pudo revisarse: 2.823 líneas con un accesorio de 1.131 superan el presupuesto de contexto de la revisión (`lens_context_budget_exceeded`) y dividirla obligaba a reescribir la historia. Queda cubierta por sus pruebas y por la evaluación final.
- **U02** y **U03** salieron aprobadas con 7 y 8 advertencias.
- **U04** tuvo un **bloqueante real**: si el subconjunto validado llegaba vacío, la carga confirmaba la transacción que vaciaba la tabla y recién después fallaba con un `TypeError` (`int(None)`), contra el propio contrato del módulo: «todo o nada». Se corrigió con la prueba primero (la carga vacía no abortaba: rojo; después, verde), el validador de la revisión aprobó la corrección y llegó a la rama como `5181abb` (`EmptySubsetError`).
- **U05 a U08** (3.389 líneas en conjunto): la evaluación de riesgo dio «medio» y por debajo del presupuesto de revisión; no se abrió una revisión.
- Para U09 a U12 el registro de seguimiento que usa este documento no consigna un resultado de revisión nativa; no se afirma uno.

Las advertencias de U02 a U04 están en su texto original en `docs/review-advisories.md`, y H1 (sección 3) les dio una resolución a cada una.

## 5. La corrida real y las figuras (U13, Sonnet)

La corrida de punta a punta sobre la publicación descargada (`python -m oilgas -v run --adopt ...`, sin descargar de nuevo), con la configuración completa del plan: validar (5,3 s), cargar (19,1 s), el backtest de 36 orígenes con 4 procesos (1.435,5 s, casi 24 minutos), el pronóstico con origen en 2026-09 (382,6 s), exportar, regenerar el HTML y escribir el resumen. En total 30,9 minutos, contra los 45 y los 90 que fijaba RNF02.

Lo que salió, tal cual: los dos criterios fijados de antemano se cumplen (D36). La curva de Arps le gana a repetir el último mes en el 61,88 % de los pozos de petróleo y el 64,09 % de los de gas a 12 meses, por 1,9 y 4,1 puntos sobre el umbral; las bandas P10-P90 quedan calibradas en las 16 celdas. Y lo que el criterio no preguntaba, pero hay que decir: a 1 mes repetir el último mes es mejor que la curva, y el machine learning es el mejor método en todas las celdas.

Se encontró y corrigió un defecto, con su prueba: la envoltura de las tareas pisaba el desglose de tiempos por etapa que devuelven el backtest y el pronóstico, y la corrida real ya había empezado, así que no quedó registrado cuánto tardó cada etapa del backtest. No se reconstruyó ese dato.

Se escribió `figures.py` (cuatro figuras con matplotlib, deterministas) y se miraron una por una: la primera versión de la proyección de la cuenca mostraba el gas con decimales sin sentido y no decía que la proyección no incluye pozos nuevos; ambas cosas se corrigieron. También se decidió qué se versiona: los 15 Parquet (19 MB en total, ninguno pasa de 25 MB), el HTML (560 KB, ahora con los 4.937 pozos y no con la muestra de 600), los reportes y las figuras; el almacén (455 MB) y los intermedios (202 MB) no.

## 6. La documentación (U14, Sonnet)

El README en el orden del plan, el diccionario de datos, la ficha del modelo, el runbook (R1 a R11), este paso a paso y las decisiones D36 y D37. Dos criterios: lo que se puede generar se genera (las tablas de columnas desde la especificación del modelo, las tablas de resultados desde el JSON, con `python -m oilgas docs-sync`) y lo que se escribe a mano se prueba contra la fuente (títulos, atribución, cifras, enlaces, campos de cada decisión; D37). La sección «Con IA, de punta a punta» cuenta solo lo que consta en el registro: qué agentes con qué modelo, la revisión nativa y lo que encontró, y que la evaluación final con Opus todavía no se hizo.

Se actualizaron además `LANDING-EXPANSION.md` (SciPy, NumPy, SQLite, Parquet con pyarrow, matplotlib y pytest) y `SITE-UPDATES.md` con los resultados reales.

## Lo que falta

- **Evaluación final independiente con Opus** de la lógica de todo el proyecto: todavía no se hizo. Es el control que cubre, entre otras cosas, la unidad U01, que la revisión nativa no pudo tomar.
- **El `.pbix`.** El diseño en HTML dice cómo armarlo; armarlo en Power BI Desktop es manual.
- **`airflow dags test` en Docker**, que no se pudo ejecutar porque Docker Desktop estaba apagado.
- **El texto del sitio** (alcance, «1 CSV por año», y los pasos de «Con IA, de punta a punta»), que decide el dueño: `SITE-UPDATES.md`.
