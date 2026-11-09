# Evaluación final independiente

Qué se evaluó, quién lo evaluó, qué encontró y cómo se resolvió cada hallazgo. Es el control que el proyecto dejó para el final: cubre la lógica de todo el código, también la unidad U01, que la revisión nativa no pudo tomar por tamaño.

## Quién evaluó y cómo

Un agente de Claude Code con el modelo Opus, **distinto de los agentes que construyeron el proyecto** y sin su contexto de trabajo. Trabajó en modo de solo lectura sobre el repositorio: leyó el código, la documentación y los resultados, y ejecutó sus sondas (pruebas hechas a propósito para intentar romper una afirmación) en una copia de trabajo en una carpeta temporal, no en el repositorio. Recalculó cifras del resultado desde los datos y comparó cada especificación y cada criterio de aceptación con lo que el código hace.

Los límites de esta evaluación, para no leer más de lo que dice: la lanzó la misma sesión que orquestó el proyecto, el evaluador es un modelo de la misma familia que los demás agentes, y no ejecutó `airflow dags test` ni el modo de Docker (Docker Desktop estaba apagado). Es un control independiente de quien escribió el código, no una auditoría externa.

## Veredicto por especificación

Las especificaciones S1 a S9 son las del documento de seguimiento del portafolio (`odd/tasks/portfolio-projects.md`).

| Especificación | Veredicto | Nota |
| --- | --- | --- |
| S1 Una carpeta por proyecto | Cumple | |
| S2 Un proyecto a la vez, agentes por fase | Cumple | |
| S3 La narrativa (problema, solución, resultados y camino interactivo) | Cumple | |
| S4 Un HTML donde la herramienta necesita al dueño | Cumple | El diseño del tablero en HTML (`dashboard/powerbi-design.html`). |
| S5 Las tecnologías del landing | **Cumple en parte** | Faltaba PostgreSQL, que usa el compose de Airflow, en `LANDING-EXPANSION.md`. Se agregó. |
| S6 Saltar un proyecto bloqueado | No aplica | Ningún proyecto estuvo bloqueado. |
| S7 Herramientas gratuitas | Cumple | |
| S8 Modelos por tipo de tarea | Cumple según el registro | Se verificó contra el documento de seguimiento, no contra los agentes. |
| S9 Fiel al sitio | **Cumple en parte** | Tres diferencias con el sitio no estaban en `SITE-UPDATES.md` (A9). Se agregaron. |

## Veredicto por criterio de aceptación

Los criterios AC01 a AC23 están en `docs/requirements.md`.

| Criterios | Veredicto | Nota |
| --- | --- | --- |
| AC01 a AC07 | Cumplen | Detección, descarga, rechazo sin daño, carga, correcciones y ajuste exacto de Arps. |
| AC08 | Cumple, con una condición | Solo con historias de 36 meses, como lo registra el documento de seguimiento (L8): con 24 meses la mediana del error a 12 meses es 7,1 % y supera el 5 % del criterio. |
| AC09 y AC10 | Cumplen | |
| AC11 sin fuga de información | **No cumplía antes de B1** | Ver B1. Con la corrección, cumple (prueba nueva con igualdad exacta). |
| AC12 | Cumple | |
| AC13 backtest completo | Cumple | Con 24, 22, 19 y 13 orígenes de evaluación para los horizontes de 1, 3, 6 y 12 meses (el mes objetivo debe estar publicado). |
| AC14 a AC18 | Cumplen | AC14 y AC15 son los criterios fijados de antemano; ambos se cumplen y el resumen también dice lo que no favorece. |
| AC19 DAG | **Sin probar** | El DAG nunca corrió en Docker (`airflow dags test`). Lo estático (identificadores, orden, programación diaria, una corrida activa) sí se verificó. |
| AC20 a AC23 | Cumplen | AC21 con los tiempos de la corrida real; AC23 con las pruebas de documentación. |

## Los tres bloqueantes y cómo se corrigieron

Cada corrección se hizo con la prueba primero: se observó que la prueba fallaba, se corrigió y se comprobó con una mutación que la prueba detecta el defecto. Las decisiones están en `docs/decisions.md`.

**B1. Datos posteriores a un origen cambiaban un pronóstico de Arps anterior (rompía AC11).** El backtest saltaba el ajuste en un origen sin ningún mes objetivo con fila, y el ajuste de Arps usa la solución del origen anterior como arranque (que además cambia el conjunto de puntos de partida); entonces que un origen se ajustara dependía de filas posteriores a otro origen. Reproducción del evaluador: dos paneles idénticos hasta el mes 41, que difieren solo después, daban en el origen 41, a 12 meses, `arps_mh_b2` P50 2138,049860 contra 2138,047154. Corrección (commit `6f3adec`): cada variante elegible se ajusta en cada origen antes de mirar los objetivos, de modo que la cadena de arranques depende solo de datos hasta cada origen. Se midió quitar el arranque en caliente en vez de eso (+54 % sobre las etapas de Arps, por encima del 30 % que se había fijado como límite del costo) y no se hizo (D39). Prueba nueva: borrar las filas posteriores a un origen que sigue a un mes sin fila deja todos los pronósticos en ese origen exactamente iguales; rojo observado, y desactivar el ajuste previo la hace fallar.

**B2. `--adopt` se ignoraba en silencio con una configuración local.** `run --config <rápida> --adopt malo.csv` registraba la ruta adoptada, informaba `how=local`, cargaba el accesorio de la configuración y terminaba con código 0. Corrección (commit `dcf7ba1`): la combinación se rechaza con código 2 y un mensaje claro, antes de escribir ningún estado (D40). Probado por la CLI; rojo observado (la corrida terminaba bien) y mutación detectada.

**B3. El modo rápido escribía sobre las salidas versionadas.** `config/pipeline.quick.toml` no tenía `[paths]`: la corrida rápida documentada reescribía los 15 Parquet, el HTML y los reportes; con el almacén real presente terminaba rechazada (V09 y V10) y pisaba `reports/validation/latest.*`; el comando literal del README, sin `local_path`, fallaba con `PermissionError: '.'`. Corrección (commit `df4b771`): el modo rápido tiene su carpeta propia e ignorada por Git (`data/quick/`), la configuración rechaza el modo local sin archivo con un mensaje claro, `make-fixture` crea su carpeta y el README apunta a comandos que funcionan desde un clon limpio (D40). Prueba de punta a punta en un proceso aparte que verifica que todo lo versionado y generado queda intacto; rojo observado y mutación detectada.

## Las advertencias

| | Hallazgo | Resolución |
| --- | --- | --- |
| A1 (riesgo) | El compose de Airflow publicaba la interfaz en todas las interfaces, con claves por defecto y el proyecto montado con escritura. | Resuelta (`109a1de`): interfaz en `127.0.0.1`, claves obligatorias desde `.env`, `src/`, `sql/` y `config/` de solo lectura (D41). Sin probar en Docker. |
| A2 (riesgo) | La imagen instalaba rangos de versiones, no los `==` de la CLI; imágenes sin etiqueta de versión explícita. | Resuelta (`109a1de`): la imagen instala `requirements.txt`; `postgres:16.9`. No se pudo construir la imagen (Docker apagado). |
| A3 (riesgo, redacción) | El README y el runbook daban a entender que el SHA-256 verifica la descarga. | Resuelta (`109a1de`): dicen que se calcula y se guarda, que no se verifica contra un valor de confianza y que la fuente es HTTP. |
| A4 (resiliencia) | Una tarea que falla no deja su traza. | Resuelta (`109a1de`): `logger.exception`, la traza en el archivo de estado y la CLI la imprime con `-v` (D42). |
| A5 (resiliencia) | Un backtest interrumpido dentro de `pool.map` seguía con los grupos en cola. | Resuelta (`109a1de`): `shutdown(cancel_futures=True)` antes de relanzar. |
| A6 (RF20) | Las corridas sin cambios o atrasadas no se veían en los archivos que lee Power BI. | Resuelta (`109a1de`): reescriben la tabla de corridas exportada. El HTML no se vuelve a renderizar en esos casos (D42). |
| A7 | Si `report` fallaba tras renderizar el HTML, el HTML versionado seguía mostrando `ok`. | Resuelta (`109a1de`): la rama de fallo lo renderiza de nuevo. |
| A8 (documentación honesta) | Afirmaciones que el registro no respalda: pruebas y mutaciones en todas las unidades, Context7, el DAG, la ablación, la fuga. | Resuelta en la documentación (D43): se dice lo que consta, se quitó Context7 y se dice que el DAG no se corrió en Docker. |
| A9 | `SITE-UPDATES.md` no listaba tres diferencias con el sitio. | Resuelta: «El modelo en uso», `after`, `summary` y `seo`, y el rango de decisiones. |
| A10 | El backtest ajusta Arps con arranque en caliente y la proyección de producción en frío. | **No se cambió**: alinearlos costaba más del límite fijado (D39). |
| A11 | La suite rápida tarda unos 185 s contra los 180 s de RNF02; el pico de memoria (RNF03) no se midió. | Documentado en la ficha del modelo; no se persiguió. |

## Las cifras que el evaluador recalculó

El evaluador recalculó desde las salidas de la primera corrida real (antes de corregir B1) estas cifras, y **coincidieron con las publicadas**:

- 2.879.616 pronósticos evaluados.
- La curva de Arps le gana a repetir el último mes a 12 meses en el 61,88 % de los pozos de petróleo (2.888 series) y el 64,09 % de los de gas; a 1 mes en el 19,55 %, a 3 meses en el 46,31 % (petróleo) y a 6 meses en el 58,67 % (petróleo) y el 61,18 % (gas).
- WAPE a 12 meses en petróleo: Arps 52,55 %, repetir el último mes 71,77 %, machine learning 42,18 %; en gas, el machine learning 46,70 %.
- WAPE a 1 mes en petróleo: repetir el último mes 23,11 %, Arps 31,62 %, machine learning 21,85 %.
- El machine learning le gana a repetir el último mes a 12 meses en el 71,88 % de los pozos de petróleo y el 73,62 % de los de gas.
- Cobertura P10-P90: Arps entre 0,787 y 0,808; machine learning entre 0,773 y 0,789.

## La corrida repetida con el código corregido

Con los tres bloqueantes y las advertencias corregidos (commits `6f3adec`, `dcf7ba1`, `df4b771`, `109a1de` y `6d45148`) se repitió el flujo completo sobre la misma publicación ya descargada (`run --adopt`, sin descargar de nuevo), desde un almacén y un manifiesto vacíos, como la primera vez. El resultado se guardó en el commit `a48f5a8`.

**Ninguna cifra publicada cambió.** Las 72 celdas de `reports/backtest_summary.json` son idénticas a las de la primera corrida en todas sus métricas (WAPE, MAE, sesgo, cobertura, proporción de pozos, pinball y tasa de respaldo); los 2.879.616 pronósticos evaluados son los mismos; el README, la ficha del modelo y `SITE-UPDATES.md` no necesitaron cambios de cifras; las figuras y las tablas generadas de la documentación salieron iguales. De las 15 tablas Parquet, 7 tienen exactamente el mismo contenido y las otras 8 difieren solo en la columna `run_key` (la tabla de corridas, además, en las fechas de inicio y de fin); los metadatos de los archivos también llevan la clave de la corrida. Tiene sentido: la corrección de B1 solo agrega ajustes de Arps en orígenes que antes se saltaban (series sin ningún mes objetivo con fila), y en los datos reales ese cambio no alteró ningún pronóstico evaluado. La corrección importa porque garantiza la propiedad, no porque moviera un número.

Tiempos de la corrida repetida (Ryzen 9 5950X de 16 núcleos y 64 GB, 4 procesos para el backtest):

| Tarea | Tiempo |
| --- | ---: |
| `check_publication`, `download` (adopción) | 0,3 s |
| `validate` | 5,3 s |
| `load` | 18,7 s |
| `backtest` | 1.376,5 s (22,9 min): panel 1,9 s, métodos puntuales 919,2 s, bandas 24,0 s, machine learning 414,8 s |
| `forecast` | 374,3 s (6,2 min): ajustes 186,6 s, machine learning 180,6 s |
| `export`, `render_dashboard`, `report` | 11,5 s |
| **Total** | **1.786,7 s (29,8 min)** |

La primera corrida había tardado 30,9 minutos (backtest 23,9); la diferencia está dentro de lo que varía entre dos corridas en la misma máquina. Esta vez quedó registrado el desglose del backtest, que la primera no conservó (D36): los métodos puntuales son el 67 % de su tiempo.


## Lo que queda

- El evaluador todavía tiene que volver a comprobar los tres bloqueantes corregidos.
- AC19 sigue sin probarse: falta correr `airflow dags test` en Docker, y con ello probar el compose endurecido y la imagen con los `==` (D41).
- El pico de memoria (RNF03) no se midió y la suite rápida supera por unos segundos los 180 s de RNF02 (A11).
- El `.pbix` sigue sin armarse: el diseño en HTML dice cómo.
