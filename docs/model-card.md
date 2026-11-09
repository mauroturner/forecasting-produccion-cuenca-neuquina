# Ficha del modelo

Qué hace cada método, con qué datos, cómo se validó, qué resultados dio y hasta dónde se puede confiar en él. Las cifras de resultados salen de `reports/backtest_summary.json` (la misma fuente del README) y los criterios de aceptación se fijaron antes de correr nada (`docs/decisions.md`, D10).

## Uso previsto y no previsto

**Para qué sirve.** Proyectar, pozo por pozo, la producción mensual de petróleo y de gas de los pozos no convencionales de la cuenca Neuquina para los próximos 12 meses, con una banda de incertidumbre, y medir con qué error lo hace cada método frente a repetir el último mes. Sirve para comparar métodos con un mismo criterio, para detectar pozos cuya curva se aparta de lo esperado y para alimentar un tablero de planificación.

**Para qué no sirve.**

- No certifica reservas ni calcula la recuperación final estimada (EUR). La curva hiperbólica modificada tiene una declinación terminal fija del 10 % anual precisamente para que la proyección a 12 meses no dependa de una cola que no se observa.
- No es un pronóstico económico ni de precios, y no proyecta agua.
- No cubre pozos convencionales ni las otras cuencas del archivo (4,0 % de las filas).
- No predice eventos de pozo (una fractura nueva, una intervención, un cierre) que todavía no ocurrieron.
- La suma de las bandas por pozo no es la banda del total (ver «Bandas»).

## Datos

Publicación de la Secretaría de Energía del 2026-10-22: 431.322 filas y 40 columnas para todos los pozos no convencionales; el proyecto usa el subconjunto de la cuenca Neuquina, 413.865 filas, 4.937 pozos, de 2006-01 a 2026-09. Petróleo y agua en m³; gas en miles de m³. Detalle de columnas y unidades en `docs/data-dictionary.md`; las 23 reglas de validación y sus recuentos reales, en `reports/validation/latest.md`.

Cada serie es un pozo y un fluido con su tasa mensual por día calendario (volumen dividido por los días del mes). Un mes sin fila es un dato faltante; un mes con volumen cero es un cero real.

## Métodos

Todos producen un volumen mensual y una banda P10-P50-P90 para cada pozo, fluido y horizonte de 1 a 12 meses.

**Repetir el último mes (`naive_last`).** La tasa del último mes con fila en los últimos tres, por los días del mes objetivo. Es la línea base que hay que superar.

**Promedio de los últimos tres meses (`naive_mean3`).** El promedio de las tasas de los últimos tres meses (los ceros cuentan), por los días del mes objetivo.

**Curvas de Arps.** Con `t` en meses desde el pico de producción y `q` la tasa:

- exponencial (`arps_exp`): `ln q(t) = ln qi − Di·t`;
- hiperbólica: `ln q(t) = ln qi − (1/b)·ln(1 + b·Di·t)`;
- **hiperbólica modificada (`arps_mh_b2`, caso base)**: hiperbólica hasta el tiempo de cambio `t_s = (Di/D_lim − 1)/(b·Di)` y exponencial con `D_lim` después, con `D_lim = −ln(1 − 0,10)/12 = 0,00878` por mes (10 % efectivo anual). `b` entre 0,001 y 2,0 y `Di` entre 1e-4 y 3,0 por mes;
- `arps_mh_b1` es la misma curva con `b` hasta 1,0 (sensibilidad).

El ajuste es por mínimos cuadrados en escala logarítmica de la tasa (`scipy.optimize.curve_fit`, método `trf`, pérdida `soft_l1` con `f_scale = 0,3`), sobre los meses con tasa positiva posteriores al pico, con varios puntos de partida y límites en `qi` (entre 1/5 y 5 veces el pico). Hacen falta al menos 6 puntos desde el pico; una serie activa con menos es «joven» y solo la pronostican las líneas base y el machine learning. Si el ajuste falla, la cadena de respaldo es `arps_mh_b2 → arps_exp → naive_mean3` y el estado del ajuste lo registra (`ok`, `fallback_exp`, `fallback_naive`). La variante no se elige pozo por pozo mirando el error de prueba: la base está fijada de antemano.

**Machine learning (`ml_hgb`).** `HistGradientBoostingRegressor` de scikit-learn con pérdida cuantílica, un modelo por fluido, horizonte y cuantil (0,1; 0,5; 0,9), entrenado con todos los pozos a la vez (también los jóvenes). El objetivo es `y = ln((r[t+h] + 0,1)/(m3[t] + 0,1))`, el cambio logarítmico de la tasa respecto del promedio de los últimos tres meses. Variables (todas con datos hasta el mes `t`): las seis tasas más recientes, medias de 3 y 6 meses, tendencias, pico y relación con el pico, meses desde la primera producción y desde el pico, meses en cero, acumulados, relación gas-petróleo, proporción de agua, mes calendario del mes objetivo, coordenadas, profundidad, subtipo, formación, tipo de pozo, método de extracción y operadora. Hiperparámetros fijos, sin búsqueda (250 iteraciones, tasa de aprendizaje 0,06, 31 hojas, 200 muestras mínimas por hoja): ningún método se optimizó contra el resultado.

## Validación

**Walk-forward.** 36 orígenes mensuales hacia atrás desde el último mes publicado: los 12 primeros (2023-09 a 2024-08) solo calibran bandas y los 24 últimos (2024-09 a 2026-08) se evalúan. En cada origen se reajustan las curvas con datos hasta ese mes; el machine learning se reentrena cada tres orígenes de evaluación con ejemplos cuyo objetivo es anterior o igual al origen. Horizontes de evaluación: 1, 3, 6 y 12 meses, solo cuando el mes objetivo ya fue publicado.

**Mismo conjunto de evaluación.** Un par (serie, origen, horizonte) se evalúa solo si todos los métodos del segmento lo tienen; así cada celda compara los métodos sobre los mismos valores reales. El segmento «elegible» (serie activa con al menos 6 puntos desde el pico) compara los seis métodos; el segmento «joven», las dos líneas base y el machine learning.

**Sin fuga de información.** Una prueba perturba todos los datos posteriores a un origen y exige que ningún pronóstico de ningún método cambie en ese origen; otra comprueba que ningún ejemplo de entrenamiento ni error de calibración tiene un objetivo posterior al origen.

**Métricas.** WAPE = Σ|real − pronóstico| / Σ real (el error relativo del total; el MAPE no sirve con meses en cero). También MAE, RMSE, sesgo, cobertura de la banda P10-P90 (proporción de valores reales dentro de la banda), pérdida pinball escalada (la suma de las pérdidas de los tres cuantiles dividida por el total real) y la proporción de pozos en los que el método tiene un MAE menor que el de la línea base.

**Criterios fijados de antemano** (`[criteria]` de `config/pipeline.toml`; no se movieron después de ver los resultados):

1. La curva de Arps (`arps_mh_b2`) tiene un MAE por serie menor que repetir el último mes en al menos el 60 % de las series elegibles a 12 meses, y un WAPE menor a 6 y a 12 meses, en cada fluido. Si no, el resumen dice «no supera».
2. Cobertura P10-P90 con objetivo 0,80: «calibrado» entre 0,75 y 0,85, «aceptable» entre 0,70 y 0,90, «descalibrado» fuera de ese rango.
3. Se informa, sin umbral, si el machine learning supera a la curva de Arps en las series elegibles y al promedio de tres meses en las jóvenes.
4. La tasa de respaldo de cada variante de Arps debe ser menor que el 2 % o quedar informada.

## Bandas

- **Métodos puntuales.** El P50 es la curva (o la línea base). P10 y P90 salen de los cuantiles 0,1 y 0,9 del error logarítmico realizado, `e = ln((real + 0,1)/(P50 + 0,1))`, en los 12 orígenes más recientes cuyo objetivo ya se conocía, por método, fluido, horizonte y tramo de edad (o sin tramo si hay menos de 200 errores). El P50 no se corrige.
- **Machine learning.** Los tres modelos cuantílicos; los cuantiles se ordenan por fila para que P10 ≤ P50 ≤ P90.
- **Advertencia: la suma de P10 no es el P10 del total.** Sumar los P10 de varios pozos da el P10 del total solo si todos se movieran juntos; si fueran independientes, esa suma es más ancha que la banda verdadera. Los visuales agregados la rotulan «Suma de P10 por pozo» y el resumen informa la cobertura real a nivel de cuenca (`basin_band_coverage`: en qué proporción de los orígenes el total real cae entre la suma de los P10 y la suma de los P90).

## Resultados

Corrida real del 2026-11-09 sobre la publicación del 2026-10-22 (4.937 pozos; 2.879.616 pronósticos evaluados, sumando los métodos, los dos fluidos y los cuatro horizontes de los 24 orígenes de evaluación). Cada celda compara todos los métodos sobre exactamente los mismos pares (se verificó: en cada celda el número de pares es el mismo para todos los métodos). Los números salen de `reports/backtest_summary.json`; las tablas completas, más abajo, se generan con `python -m oilgas docs-sync`.

### Veredicto sobre los criterios fijados de antemano

| Criterio | Resultado | Veredicto |
| --- | --- | --- |
| Arps supera a repetir el último mes en al menos el 60 % de las series elegibles a 12 meses | petróleo 61,88 %, gas 64,09 % | **Cumple**, por poco en petróleo (1,9 puntos) |
| El WAPE de Arps es menor que el de repetir el último mes a 6 y a 12 meses | petróleo 44,92 % contra 53,04 % (6 meses) y 52,55 % contra 71,77 % (12); gas 43,73 % contra 54,42 % y 53,37 % contra 72,60 % | **Cumple** en los dos fluidos |
| Cobertura P10-P90 de Arps y del machine learning entre 0,75 y 0,85 («calibrado») | Arps entre 0,79 y 0,81; machine learning entre 0,77 y 0,79, en los dos fluidos y los cuatro horizontes | **Calibrado** en las 16 celdas |
| Aporte del machine learning (sin umbral: se informa) | supera a Arps en la pinball escalada en las 8 celdas de series elegibles y al promedio de 3 meses en las 8 de series jóvenes | Informado |
| Tasa de respaldo de cada variante de Arps menor que el 2 % | 0 % en las tres variantes y los dos fluidos | **Cumple** |

Ningún umbral ni método se cambió después de ver estos números.

### Lo que dicen los números, incluido lo que no favorece a la curva de Arps

- **A 12 meses, la curva de Arps le gana a repetir el último mes** en el 62 % de los pozos de petróleo y el 64 % de los de gas, y reduce el error total (WAPE) de 72 % a 53 %. Es lo que se había fijado como criterio y se cumple.
- **A 1 mes, repetir el último mes es mejor que la curva de Arps**: el WAPE de petróleo es 23,1 % contra 31,6 % y la curva solo le gana en el 20 % de los pozos. A 3 meses la ventaja es mínima (WAPE 39,2 % contra 40,9 % en petróleo) y la curva gana en el 46 % de los pozos de petróleo, es decir, en menos de la mitad. La curva empieza a pagar desde los 6 meses (59 % de los pozos de petróleo, 61 % de los de gas).
- **El machine learning es el mejor método en todas las celdas**: a 12 meses su WAPE es 42,2 % en petróleo y 46,7 % en gas, y le gana a repetir el último mes en el 72 % y el 74 % de los pozos. No es una comparación contra una curva mal ajustada: usa los mismos datos hasta el origen y tiene hiperparámetros fijos, sin búsqueda. Por eso la regla de selección (menor pinball escalada promedio) lo elige como método en uso en los cuatro segmentos.
- **Las dos curvas hiperbólicas rinden parecido**: con b hasta 1 o hasta 2 el WAPE de petróleo a 12 meses es 52,1 % y 52,6 %. El límite de b no es lo que decide el resultado. La exponencial es la peor de las tres a 12 meses (62,1 % en petróleo).
- **Series jóvenes** (activas con menos de 6 puntos desde el pico): el machine learning tiene un WAPE de 21 % a 1 mes y 46 % a 12 en petróleo, y de 24 % y 51 % en gas. El promedio de 3 meses y repetir el último mes tienen un WAPE de 105 % a 131 % a 12 meses. Es donde más aporta, porque las curvas de Arps no pueden ajustarse.
- **Cobertura.** Las bandas empíricas de los métodos puntuales cubren entre 0,79 y 0,81 de los valores reales, el objetivo de 0,80. Las del machine learning cubren algo menos (0,77 a 0,79; en las series jóvenes, 0,74 a 0,78): siguen en la zona «calibrado» de las series elegibles, pero con menos margen.
- **Cobertura de la cuenca.** La suma de los P10 a P90 por pozo contiene el total real de la cuenca en el 100 % de los orígenes y métodos: es la banda más ancha posible, no una medida de precisión del total (ver «Bandas»).

### Calidad de los ajustes de Arps en el último origen

Con el origen en 2026-09, la curva base (`arps_mh_b2`) se ajustó a 3.196 series de petróleo y 3.702 de gas: 6.897 de 6.898 con estado `ok` y una con la exponencial de respaldo. Aun así, el 16,3 % de los ajustes de petróleo y el 12,6 % de los de gas tienen un error logarítmico mayor que 1,0 y quedan marcados `needs_review` en `fact_well_fit`: son pozos con historia muy irregular (cierres, reinicios, volúmenes que saltan) en los que la curva sigue una tendencia, no el detalle. El ajuste converge, pero no siempre describe bien al pozo.

### Todas las celdas

<!-- methods:start -->
#### Petróleo, series elegibles

| Método | Horizonte (meses) | Series | WAPE | Pozos donde supera a repetir el último mes | Cobertura P10-P90 | Pinball escalada |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `naive_last` | 1 | 3433 | 23,11 % | — | 0,80 | 0,277 |
| `naive_last` | 3 | 3351 | 40,89 % | — | 0,80 | 0,469 |
| `naive_last` | 6 | 3237 | 53,04 % | — | 0,80 | 0,570 |
| `naive_last` | 12 | 2888 | 71,77 % | — | 0,79 | 0,679 |
| `naive_mean3` | 1 | 3433 | 29,59 % | 15,93 % | 0,80 | 0,326 |
| `naive_mean3` | 3 | 3351 | 42,63 % | 38,59 % | 0,80 | 0,446 |
| `naive_mean3` | 6 | 3237 | 53,42 % | 48,59 % | 0,80 | 0,522 |
| `naive_mean3` | 12 | 2888 | 72,28 % | 48,06 % | 0,80 | 0,638 |
| `arps_exp` | 1 | 3433 | 35,02 % | 13,87 % | 0,81 | 0,384 |
| `arps_exp` | 3 | 3351 | 43,82 % | 36,05 % | 0,81 | 0,485 |
| `arps_exp` | 6 | 3237 | 51,34 % | 49,06 % | 0,80 | 0,569 |
| `arps_exp` | 12 | 2888 | 62,1 % | 52,04 % | 0,80 | 0,682 |
| `arps_mh_b1` | 1 | 3433 | 32,32 % | 18,09 % | 0,80 | 0,362 |
| `arps_mh_b1` | 3 | 3351 | 39,67 % | 45,48 % | 0,81 | 0,448 |
| `arps_mh_b1` | 6 | 3237 | 45,04 % | 58,48 % | 0,81 | 0,515 |
| `arps_mh_b1` | 12 | 2888 | 52,1 % | 61,5 % | 0,80 | 0,592 |
| `arps_mh_b2` | 1 | 3433 | 31,62 % | 19,55 % | 0,81 | 0,358 |
| `arps_mh_b2` | 3 | 3351 | 39,24 % | 46,31 % | 0,81 | 0,448 |
| `arps_mh_b2` | 6 | 3237 | 44,92 % | 58,67 % | 0,81 | 0,522 |
| `arps_mh_b2` | 12 | 2888 | 52,55 % | 61,88 % | 0,80 | 0,610 |
| `ml_hgb` | 1 | 3433 | 21,85 % | 55 % | 0,79 | 0,226 |
| `ml_hgb` | 3 | 3351 | 33,25 % | 64,73 % | 0,78 | 0,335 |
| `ml_hgb` | 6 | 3237 | 37,56 % | 73,71 % | 0,78 | 0,373 |
| `ml_hgb` | 12 | 2888 | 42,18 % | 71,88 % | 0,78 | 0,417 |

#### Gas, series elegibles

| Método | Horizonte (meses) | Series | WAPE | Pozos donde supera a repetir el último mes | Cobertura P10-P90 | Pinball escalada |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `naive_last` | 1 | 3884 | 28,75 % | — | 0,81 | 0,343 |
| `naive_last` | 3 | 3794 | 44,55 % | — | 0,81 | 0,536 |
| `naive_last` | 6 | 3681 | 54,42 % | — | 0,81 | 0,635 |
| `naive_last` | 12 | 3381 | 72,6 % | — | 0,80 | 0,763 |
| `naive_mean3` | 1 | 3884 | 33,21 % | 19,72 % | 0,81 | 0,369 |
| `naive_mean3` | 3 | 3794 | 42,78 % | 46,26 % | 0,81 | 0,467 |
| `naive_mean3` | 6 | 3681 | 51,42 % | 55,72 % | 0,80 | 0,538 |
| `naive_mean3` | 12 | 3381 | 72,69 % | 47,35 % | 0,79 | 0,676 |
| `arps_exp` | 1 | 3884 | 36,19 % | 14,39 % | 0,80 | 0,409 |
| `arps_exp` | 3 | 3794 | 41,8 % | 40,88 % | 0,80 | 0,489 |
| `arps_exp` | 6 | 3681 | 45,88 % | 52,05 % | 0,80 | 0,571 |
| `arps_exp` | 12 | 3381 | 55,81 % | 54,19 % | 0,79 | 0,723 |
| `arps_mh_b1` | 1 | 3884 | 34,87 % | 19,44 % | 0,80 | 0,394 |
| `arps_mh_b1` | 3 | 3794 | 39,88 % | 49,92 % | 0,80 | 0,461 |
| `arps_mh_b1` | 6 | 3681 | 43,37 % | 59,9 % | 0,80 | 0,521 |
| `arps_mh_b1` | 12 | 3381 | 52,14 % | 64,06 % | 0,79 | 0,628 |
| `arps_mh_b2` | 1 | 3884 | 34,77 % | 20,34 % | 0,80 | 0,392 |
| `arps_mh_b2` | 3 | 3794 | 39,89 % | 51,45 % | 0,80 | 0,458 |
| `arps_mh_b2` | 6 | 3681 | 43,73 % | 61,18 % | 0,80 | 0,524 |
| `arps_mh_b2` | 12 | 3381 | 53,37 % | 64,09 % | 0,79 | 0,642 |
| `ml_hgb` | 1 | 3884 | 27,24 % | 58,11 % | 0,78 | 0,271 |
| `ml_hgb` | 3 | 3794 | 35,32 % | 73,12 % | 0,78 | 0,350 |
| `ml_hgb` | 6 | 3681 | 38,77 % | 78,21 % | 0,79 | 0,383 |
| `ml_hgb` | 12 | 3381 | 46,7 % | 73,62 % | 0,77 | 0,453 |

#### Petróleo, series jóvenes

| Método | Horizonte (meses) | Series | WAPE | Pozos donde supera a repetir el último mes | Cobertura P10-P90 | Pinball escalada |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `naive_last` | 1 | 1476 | 30,86 % | — | 0,81 | 0,455 |
| `naive_last` | 3 | 1223 | 56,99 % | — | 0,80 | 0,828 |
| `naive_last` | 6 | 1063 | 87,4 % | — | 0,80 | 0,999 |
| `naive_last` | 12 | 813 | 131,4 % | — | 0,80 | 1,129 |
| `naive_mean3` | 1 | 1476 | 44,99 % | 10,03 % | 0,81 | 0,624 |
| `naive_mean3` | 3 | 1223 | 62,62 % | 26,9 % | 0,81 | 0,904 |
| `naive_mean3` | 6 | 1063 | 84,43 % | 53,9 % | 0,81 | 1,003 |
| `naive_mean3` | 12 | 813 | 120,28 % | 64,45 % | 0,80 | 1,087 |
| `ml_hgb` | 1 | 1476 | 21,16 % | 73,37 % | 0,76 | 0,214 |
| `ml_hgb` | 3 | 1223 | 32,86 % | 85,04 % | 0,77 | 0,330 |
| `ml_hgb` | 6 | 1063 | 41,26 % | 86,74 % | 0,77 | 0,410 |
| `ml_hgb` | 12 | 813 | 46,08 % | 87,45 % | 0,74 | 0,460 |

#### Gas, series jóvenes

| Método | Horizonte (meses) | Series | WAPE | Pozos donde supera a repetir el último mes | Cobertura P10-P90 | Pinball escalada |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `naive_last` | 1 | 1374 | 30,82 % | — | 0,80 | 0,470 |
| `naive_last` | 3 | 1278 | 54,32 % | — | 0,80 | 0,827 |
| `naive_last` | 6 | 1108 | 72,99 % | — | 0,81 | 0,976 |
| `naive_last` | 12 | 858 | 112,49 % | — | 0,81 | 1,108 |
| `naive_mean3` | 1 | 1374 | 43,23 % | 9,61 % | 0,80 | 0,638 |
| `naive_mean3` | 3 | 1278 | 60,55 % | 27,46 % | 0,81 | 0,921 |
| `naive_mean3` | 6 | 1108 | 72,54 % | 50 % | 0,81 | 0,949 |
| `naive_mean3` | 12 | 858 | 105,21 % | 61,89 % | 0,81 | 1,077 |
| `ml_hgb` | 1 | 1374 | 24,17 % | 78,24 % | 0,78 | 0,241 |
| `ml_hgb` | 3 | 1278 | 38,25 % | 80,67 % | 0,77 | 0,379 |
| `ml_hgb` | 6 | 1108 | 42,56 % | 85,92 % | 0,78 | 0,424 |
| `ml_hgb` | 12 | 858 | 50,86 % | 86,71 % | 0,78 | 0,508 |
<!-- methods:end -->

### Rendimiento

Medido en esta máquina (AMD Ryzen 9 5950X de 16 núcleos y 64 GB, Windows 10) con la configuración completa, 4 procesos para el backtest y la publicación ya descargada (`--adopt`):

| Tarea | Tiempo |
| --- | ---: |
| `check_publication` | 0,1 s |
| `download` (adopción del archivo ya descargado) | 0,1 s |
| `validate` | 5,3 s |
| `load` | 19,1 s |
| `backtest` | 1.435,5 s (23,9 min) |
| `forecast` | 382,6 s (6,4 min) |
| `export` | 10,8 s |
| `render_dashboard` | 0,4 s |
| `report` | 0,1 s |
| **Total** | **1.854 s (30,9 min)** |

Contra RNF02: backtest completo 23,9 min (tope 45 min) y flujo completo 30,9 min (tope 90 min). No incluye la descarga real de 149 MB, que depende de la red. El pico de memoria (RNF03, tope 4 GB) no se midió. Los topes del modo rápido (5 min) y de las pruebas (3 min) se verifican en las pruebas del proyecto.

## Limitaciones

- **Datos ya revisados.** El backtest usa la publicación de hoy, con las correcciones que la Secretaría hizo después; no las versiones que existían en cada mes. Los errores reales en producción pueden ser algo mayores.
- **Tiempo calendario.** La curva avanza en meses calendario desde el pico; los meses en cero o sin fila no entran al ajuste pero el tiempo sigue corriendo. Un pozo cerrado un año y reabierto se ajusta a lo producido, no a una curva nueva.
- **Cierres, intervenciones y operadoras.** Una nueva fractura, un cierre largo o un cambio de operadora (979 pozos cambiaron en la historia) rompen la hipótesis de una declinación continua. El pico se recalcula si hay uno mayor, pero el modelo no sabe por qué.
- **Fractura fuera del modelo base.** El archivo de fractura es preliminar («sujeto a revisión») y el 41 % de sus longitudes de rama figuran como 0. Su aporte se mide en una ablación aparte (unidad U15 del plan).
- **Horizontes intermedios sin validar.** El backtest evalúa 1, 3, 6 y 12 meses; los horizontes 2, 4, 5 y 7 a 11 del pronóstico en uso salen del mismo procedimiento pero no se validaron uno por uno.
- **Estacionalidad del gas.** El gas cae cada septiembre; solo el machine learning conoce el mes del año (`target_month`). Las curvas de Arps no tienen estacionalidad.
- **Series jóvenes.** Con menos de 6 puntos desde el pico no hay curva de Arps; el pronóstico viene del promedio o del machine learning.
- **Un solo backtest, una sola ventana.** Los 24 orígenes cubren 2024-09 a 2026-08. No se midió la estabilidad del resultado con otras ventanas.

## Reproducibilidad

Semillas fijas (42), versiones fijadas con `==` en `requirements.txt`, y el backtest da el mismo resultado con 1 y con 2 procesos (prueba AC22). Los Parquet de dos corridas sobre la misma entrada tienen el mismo contenido salvo las columnas de fecha y clave de la corrida.
