# Diccionario de datos

Qué significa cada columna del archivo de la fuente y de cada tabla que el flujo exporta para Power BI, con su unidad. La primera parte es de la fuente y se escribió a mano a partir de `docs/research.md` y del perfilado de la publicación real (`docs/requirements.md`, sección 4); la segunda se genera desde la especificación del modelo (`python -m oilgas docs-sync`) y una prueba verifica que coincide con los Parquet.

## Convenciones

- **Unidades.** Petróleo y agua en **m³** por mes; gas en **miles de m³** por mes. Las tasas son el volumen dividido por los días calendario del mes (m³/día o miles de m³/día). Nunca se suman fluidos distintos ni se convierte a barriles equivalentes (decisión D03).
- **Pozo.** La clave es `idpozo` (`well_key` en las tablas exportadas). La sigla (`sigla`, `well_code`) es solo una etiqueta: 167 siglas corresponden a más de un pozo.
- **Tiempo.** `period_key` es el mes como `AAAAMM` (por ejemplo `202609`), para unir y mostrar; `period_index` es `año × 12 + mes − 1`, para sumar y restar meses sin errores de calendario.
- **Vacíos.** Un valor vacío en la fuente es nulo. En los Parquet, un dato que no existe (por ejemplo los parámetros de una curva que no se pudo ajustar) queda nulo, no cero ni NaN.
- **Estado de cada columna de la fuente.** *Verificado*: lo dice la nota del dataset o se comprobó en el perfilado. *Inferido*: sale del nombre o de los valores observados y la fuente no lo documenta.

## Archivo de origen

Archivo `produccin-de-pozos-de-gas-y-petrleo-no-convencional.csv` del dataset «Producción de petróleo y gas por pozo (Capítulo IV)»: UTF-8 con BOM, separador coma, decimal con punto, 40 columnas. El flujo usa 34; las otras seis (`iny_agua`, `iny_gas`, `iny_co2`, `iny_otro`, `vida_util`, `idusuario`) no se leen.

| Columna | Nombre en el proyecto | Unidad | Significado | Estado |
| --- | --- | --- | --- | --- |
| `idempresa` | `company_code` | — | Código de la empresa operadora (texto, por ejemplo `YPF`). | Verificado |
| `anio` | `year` | — | Año del período. | Verificado |
| `mes` | `month` | — | Mes del período (1 a 12). | Verificado |
| `idpozo` | `well_id` | — | Identificador numérico del pozo. Es la clave y une con el archivo de fractura. | Verificado |
| `prod_pet` | `oil_m3` | m³ | Petróleo producido en el mes. | Verificado |
| `prod_gas` | `gas_thousand_m3` | miles de m³ | Gas producido en el mes. | Verificado |
| `prod_agua` | `water_m3` | m³ | Agua producida en el mes. | Verificado |
| `iny_agua` | — (no se usa) | m³ | Agua inyectada. | Inferido |
| `iny_gas` | — (no se usa) | miles de m³ | Gas inyectado. | Inferido |
| `iny_co2` | — (no se usa) | miles de m³ | CO₂ inyectado; la unidad no está verificada. | Inferido |
| `iny_otro` | — (no se usa) | m³ | Otros fluidos inyectados. | Inferido |
| `tef` | `effective_days` | días | Tiempo de extracción efectiva del mes. En 70 filas supera los días del mes y en 384 vale 0 con producción (reglas V13 y V14). | Inferido |
| `vida_util` | — (no se usa) | — | Vida útil estimada; está vacía en el 97,9 % de las filas. | No verificado |
| `tipoextraccion` | `extraction_method` | — | Método de extracción (por ejemplo «Plunger Lift», «Sin Sistema de Extracción»). Cambia en el tiempo. | Verificado |
| `tipoestado` | `well_status` | — | Estado del pozo (por ejemplo «Extracción Efectiva», «Abandonado», «Inyección de Agua»). Cambia en el tiempo. | Verificado |
| `tipopozo` | `well_type` | — | Tipo de pozo («Petrolífero», «Gasífero»). Cambia en el tiempo. | Verificado |
| `observaciones` | `remarks` | — | Texto libre. «Cargado automáticamente como [Sin movimientos]» marca un mes generado sin actividad (7.421 filas). | Verificado |
| `fechaingreso` | `loaded_at` | fecha y hora | Cuándo cargó el operador el registro; la mediana es 14 días después del fin del mes. | Inferido |
| `rectificado` | `is_rectified` | t/f | El operador rectificó el registro (694 filas con `t`). | Inferido |
| `habilitado` | `is_enabled` | t/f | Registro habilitado; siempre `t` en el subconjunto. | Inferido |
| `idusuario` | — (no se usa) | — | Usuario que cargó el registro. | Inferido |
| `empresa` | `company_name` | — | Nombre de la operadora (uno a uno con `idempresa`). | Verificado |
| `sigla` | `well_code` | — | Sigla del pozo. Etiqueta, no clave. | Verificado |
| `formprod` | `formation_code` | — | Código de la formación productiva. | Verificado |
| `profundidad` | `depth_m` | m | Profundidad del pozo. 172 pozos con 0 y 4 con más de 8.000 m pasan a nulo (V17). | Inferido |
| `formacion` | `formation_name` | — | Formación productiva (vaca muerta, lajas, mulichinco, entre otras). | Verificado |
| `idareapermisoconcesion` | `concession_code` | — | Código del área de permiso o concesión. | Verificado |
| `areapermisoconcesion` | `concession_name` | — | Nombre del área de permiso o concesión. | Verificado |
| `idareayacimiento` | `field_code` | — | Código del yacimiento. | Verificado |
| `areayacimiento` | `field_name` | — | Nombre del yacimiento. | Verificado |
| `cuenca` | `basin` | — | Cuenca. El proyecto filtra `NEUQUINA`. | Verificado |
| `provincia` | `province` | — | Provincia (Neuquén, Rio Negro —sin tilde en la fuente— y Mendoza). | Verificado |
| `coordenadax` | `lon` | grados | Longitud del pozo. En un pozo viene intercambiada con la latitud (V16). | Verificado |
| `coordenaday` | `lat` | grados | Latitud del pozo. | Verificado |
| `tipo_de_recurso` | `resource_type` | — | `CONVENCIONAL` o `NO CONVENCIONAL`. El proyecto filtra `NO CONVENCIONAL`. | Verificado |
| `proyecto` | `project` | — | Proyecto («Sin Proyecto», «GAS PLUS»). | Verificado |
| `clasificacion` | `classification` | — | Clasificación de la actividad («EXPLOTACION», «EXPLORACION»). | Verificado |
| `subclasificacion` | `subclassification` | — | Subclasificación («DESARROLLO», «EXPLORACION»). | Verificado |
| `sub_tipo_recurso` | `sub_resource_type` | — | `SHALE` o `TIGHT` (nulo en dos pozos). | Verificado |
| `fecha_data` | `period_end` | fecha | Último día del mes del período; coincide con `anio` y `mes` en todas las filas. | Verificado |

## Tablas exportadas

Las ocho dimensiones y los siete hechos del modelo estrella (`outputs/powerbi/*.parquet`). Todas las relaciones son uno a varios, con filtro en un solo sentido de la dimensión al hecho. Cada archivo lleva en sus metadatos la corrida (`oilgas.run_key`), la huella de la publicación (`oilgas.source_sha256`) y la atribución (`oilgas.attribution`).

<!-- columns:start -->
### `dim_calendar`

Dimensión. Un mes por fila, desde el primero publicado hasta 12 meses después del último, sin huecos. Clave: `period_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `period_key` | entero 32 | AAAAMM | Mes como AAAAMM (clave). |
| `period_index` | entero 32 | meses | Número de mes (año × 12 + mes − 1), para sumar y restar meses. |
| `month_start` | fecha | — | Primer día del mes; la tabla de fechas se marca con esta columna. |
| `year` | entero 32 | — | Año. |
| `month` | entero 32 | — | Mes (1 a 12). |
| `month_name_es` | texto | — | Nombre del mes en español. |
| `quarter` | entero 32 | — | Trimestre (1 a 4). |
| `year_month_label` | texto | — | Mes como AAAA-MM, para ejes y segmentadores. |
| `days_in_month` | entero 32 | días | Días del mes. |
| `is_published` | verdadero/falso | — | Verdadero si el mes está en la publicación; falso para los 12 meses proyectados. |
| `is_last_published` | verdadero/falso | — | Verdadero solo para el último mes publicado. |

### `dim_well`

Dimensión. Un pozo por fila con sus atributos fijos. La jerarquía Provincia, Concesión, Yacimiento, Pozo vive aquí (estrella). Clave: `well_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `well_key` | entero 64 | — | Identificador del pozo en la fuente (idpozo; clave). |
| `well_code` | texto | — | Sigla del pozo (una etiqueta: no es única). |
| `province` | texto | — | Provincia. |
| `concession_code` | texto | — | Código de la concesión o permiso. |
| `concession_name` | texto | — | Nombre de la concesión o permiso. |
| `field_code` | texto | — | Código del yacimiento. |
| `field_name` | texto | — | Nombre del yacimiento. |
| `formation_code` | texto | — | Código de la formación productiva. |
| `formation_name` | texto | — | Formación productiva. |
| `sub_resource_type` | texto | — | Subtipo de recurso: SHALE o TIGHT. |
| `basin` | texto | — | Cuenca. |
| `lon` | decimal | grados | Longitud (coordenadax de la fuente), corregida si estaba intercambiada. |
| `lat` | decimal | grados | Latitud (coordenaday de la fuente), corregida si estaba intercambiada. |
| `depth_m` | decimal | m | Profundidad; vacía si estaba fuera de rango. |
| `operator_current_key` | texto | — | Código de la operadora en el último mes informado. |
| `operator_current_name` | texto | — | Nombre de la operadora en el último mes informado. |
| `well_type_latest` | texto | — | Tipo de pozo en el último mes informado. |
| `well_status_latest` | texto | — | Estado del pozo en el último mes informado. |
| `extraction_method_latest` | texto | — | Método de extracción en el último mes informado. |
| `first_production_period_key` | entero 32 | AAAAMM | Primer mes con producción. |
| `last_report_period_key` | entero 32 | AAAAMM | Último mes informado. |
| `months_with_production` | entero 32 | meses | Meses con petróleo o gas mayores que cero. |
| `cum_oil_m3` | decimal | m³ | Petróleo acumulado. |
| `cum_gas_thousand_m3` | decimal | miles de m³ | Gas acumulado. |
| `cum_water_m3` | decimal | m³ | Agua acumulada. |
| `quality_flags` | texto | — | Correcciones de calidad hechas al pozo, separadas por punto y coma (COORDS_SWAPPED, COORDS_OUTSIDE, DEPTH_INVALID, FIXED_ATTR_CHANGED). |

### `dim_company`

Dimensión. Una operadora por fila. Clave: `company_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `company_key` | texto | — | Código de la operadora (clave). |
| `company_name` | texto | — | Nombre de la operadora en su último mes informado. |

### `dim_fluid`

Dimensión. Los dos fluidos que se proyectan. Nunca se suman entre sí. Clave: `fluid_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `fluid_key` | texto | — | oil o gas (clave). |
| `fluid_name_es` | texto | — | Petróleo o Gas. |
| `unit` | texto | — | Unidad del volumen de ese fluido. |

### `dim_method`

Dimensión. Los seis métodos comparados. Clave: `method_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `method_key` | texto | — | Identificador del método (clave). |
| `method_name_es` | texto | — | Nombre del método. |
| `family` | texto | — | Línea base, Arps o machine learning. |
| `description_es` | texto | — | Qué hace el método. |
| `is_base` | verdadero/falso | — | Verdadero para las líneas base ingenuas. |
| `sort_order` | entero 32 | — | Orden de aparición. |

### `dim_horizon`

Dimensión. Horizontes del pronóstico. Clave: `horizon`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `horizon` | entero 32 | meses | Meses hacia adelante (1 a 12; clave). |
| `horizon_label` | texto | — | Texto del horizonte (1 mes, 3 meses…). |
| `is_headline` | verdadero/falso | — | Verdadero para los horizontes validados (1, 3, 6 y 12). |

### `dim_origin`

Dimensión. Los últimos 12 orígenes del pronóstico en uso. Clave: `origin_period_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `origin_period_key` | entero 32 | AAAAMM | Mes desde el que se proyectó (clave). |
| `origin_label` | texto | — | Origen como AAAA-MM. |
| `is_latest` | verdadero/falso | — | Verdadero para el origen más reciente. |
| `run_key` | texto | — | Corrida que generó ese origen. |

### `dim_pipeline_run`

Dimensión. Una corrida del flujo por fila. Clave: `run_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `run_key` | texto | — | Identificador de la corrida (clave). |
| `started_at` | texto | — | Inicio (ISO 8601, UTC). |
| `finished_at` | texto | — | Fin (ISO 8601, UTC). |
| `status` | texto | — | unchanged, late, rejected, failed u ok. |
| `source_url` | texto | — | URL de la publicación. |
| `source_etag` | texto | — | ETag de la publicación. |
| `source_last_modified` | texto | — | Last-Modified de la publicación. |
| `source_size` | entero 64 | bytes | Tamaño de la publicación. |
| `source_sha256` | texto | — | SHA-256 de la publicación. |
| `last_period_key` | entero 32 | AAAAMM | Último mes de la publicación. |
| `rows_subset` | entero 64 | filas | Filas del subconjunto cargado. |
| `wells_subset` | entero 64 | pozos | Pozos del subconjunto cargado. |
| `revised_rows` | entero 64 | filas | Filas de meses anteriores que cambiaron respecto de la carga previa. |
| `message` | texto | — | Mensaje de la corrida. |

### `fact_production_monthly`

Hecho. Producción mensual de cada pozo. Grano: `well_key`, `period_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `well_key` | entero 64 | — | Pozo. |
| `period_key` | entero 32 | AAAAMM | Mes. |
| `company_key` | texto | — | Operadora del pozo en ese mes. |
| `oil_m3` | decimal | m³ | Petróleo producido (corregido). |
| `gas_thousand_m3` | decimal | miles de m³ | Gas producido (corregido). |
| `water_m3` | decimal | m³ | Agua producida (corregida). |
| `effective_days` | decimal | días | Días de extracción efectiva; vacío si era imposible. |
| `is_producing` | verdadero/falso | — | Verdadero si el pozo produjo petróleo o gas en el mes. |
| `well_type` | texto | — | Tipo de pozo en ese mes. |
| `well_status` | texto | — | Estado del pozo en ese mes. |
| `extraction_method` | texto | — | Método de extracción en ese mes. |
| `quality_flags` | texto | — | Correcciones hechas a la fila (NEG_VOLUME, TEF_GT_DAYS, TEF_ZERO_WITH_PROD, VOLUME_CEILING). |
| `run_key` | texto | — | Corrida que cargó la fila. |

### `fact_forecast`

Hecho. Pronóstico de 12 meses por pozo, fluido, método y origen. Grano: `well_key`, `fluid_key`, `method_key`, `origin_period_key`, `horizon`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `well_key` | entero 64 | — | Pozo. |
| `fluid_key` | texto | — | Fluido. |
| `method_key` | texto | — | Método. |
| `origin_period_key` | entero 32 | AAAAMM | Mes desde el que se proyectó. |
| `target_period_key` | entero 32 | AAAAMM | Mes proyectado. |
| `horizon` | entero 32 | meses | Meses entre el origen y el mes proyectado. |
| `company_key` | texto | — | Operadora del pozo en el origen. |
| `p10` | decimal | m³ o miles de m³ | Volumen P10 del mes proyectado (en la unidad del fluido). |
| `p50` | decimal | m³ o miles de m³ | Volumen P50 (la curva o la mediana). |
| `p90` | decimal | m³ o miles de m³ | Volumen P90. |
| `segment` | texto | — | eligible (≥ 6 meses desde el pico) o young. |
| `is_selected` | verdadero/falso | — | Verdadero para el método elegido por el backtest para ese fluido y segmento. |
| `fit_status` | texto | — | ok, fallback_exp o fallback_naive. |
| `run_key` | texto | — | Corrida que generó la fila. |

### `fact_well_fit`

Hecho. Parámetros de las curvas de Arps ajustadas en cada origen. Grano: `well_key`, `fluid_key`, `method_key`, `origin_period_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `well_key` | entero 64 | — | Pozo. |
| `fluid_key` | texto | — | Fluido. |
| `method_key` | texto | — | Variante de Arps. |
| `origin_period_key` | entero 32 | AAAAMM | Mes del ajuste. |
| `run_key` | texto | — | Corrida que generó el ajuste. |
| `peak_period_key` | entero 32 | AAAAMM | Mes del pico usado. |
| `log_qi` | decimal | — | Logaritmo natural de la tasa inicial (qi). |
| `qi_rate_per_day` | decimal | m³/día o miles de m³/día | Tasa inicial qi. |
| `di_nominal_per_month` | decimal | 1/mes | Declinación inicial nominal (Di). |
| `b` | decimal | — | Exponente de la hiperbólica (0 en la exponencial). |
| `d_lim_nominal_per_month` | decimal | 1/mes | Declinación terminal nominal. |
| `t_switch_months` | decimal | meses | Meses desde el pico hasta el cambio a la declinación terminal. |
| `d_effective_annual_initial` | decimal | fracción | Declinación efectiva anual inicial. |
| `n_points` | entero 32 | meses | Puntos usados en el ajuste. |
| `rmse_log` | decimal | — | Raíz del error cuadrático medio en escala logarítmica. |
| `status` | texto | — | ok, fallback_exp o fallback_naive. |
| `needs_review` | verdadero/falso | — | Verdadero si rmse_log supera 1,0: se conserva pero se marca para revisión. |

### `fact_fitted_curve`

Hecho. La curva base sobre los meses ajustados, solo del último origen. Grano: `well_key`, `fluid_key`, `period_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `well_key` | entero 64 | — | Pozo. |
| `fluid_key` | texto | — | Fluido. |
| `period_key` | entero 32 | AAAAMM | Mes entre el pico y el origen. |
| `origin_period_key` | entero 32 | AAAAMM | Origen del ajuste. |
| `fitted_volume` | decimal | m³ o miles de m³ | Volumen de la curva base (arps_mh_b2) en el mes. |

### `fact_backtest_metrics`

Hecho. Componentes sumables del backtest: cualquier métrica es un cociente de sumas bajo cualquier filtro. Grano: `method_key`, `fluid_key`, `horizon`, `origin_period_key`, `age_bucket`, `sub_resource_type`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `method_key` | texto | — | Método. |
| `fluid_key` | texto | — | Fluido. |
| `horizon` | entero 32 | meses | Horizonte evaluado. |
| `origin_period_key` | entero 32 | AAAAMM | Origen evaluado. |
| `age_bucket` | texto | — | Tramo de edad de la serie: young, 06-11, 12-23, 24-59 o 60+. |
| `sub_resource_type` | texto | — | Subtipo del pozo. |
| `run_key` | texto | — | Corrida del backtest. |
| `n` | entero 64 | pares | Pares evaluados. |
| `sum_actual` | decimal | m³ o miles de m³ | Suma de lo real. |
| `sum_p10` | decimal | m³ o miles de m³ | Suma de los P10. |
| `sum_p50` | decimal | m³ o miles de m³ | Suma de los P50. |
| `sum_p90` | decimal | m³ o miles de m³ | Suma de los P90. |
| `sum_abs_error` | decimal | m³ o miles de m³ | Suma del error absoluto del P50. |
| `sum_sq_error` | decimal | (m³ o miles de m³)² | Suma del error cuadrático del P50. |
| `sum_error` | decimal | m³ o miles de m³ | Suma del error con signo del P50 (pronóstico − real). |
| `n_covered` | entero 64 | pares | Pares con lo real entre P10 y P90. |
| `sum_pinball` | decimal | m³ o miles de m³ | Suma de la pérdida pinball de los tres cuantiles. |

### `fact_model_summary`

Hecho. Métricas del backtest por método, fluido, horizonte y segmento, con su veredicto. Grano: `method_key`, `fluid_key`, `horizon`, `segment`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `method_key` | texto | — | Método. |
| `fluid_key` | texto | — | Fluido. |
| `horizon` | entero 32 | meses | Horizonte. |
| `segment` | texto | — | eligible o young. |
| `run_key` | texto | — | Corrida del backtest. |
| `n_series` | entero 64 | series | Series evaluadas. |
| `n_points` | entero 64 | pares | Pares evaluados. |
| `mae` | decimal | m³ o miles de m³ | Error absoluto medio. |
| `rmse` | decimal | m³ o miles de m³ | Raíz del error cuadrático medio. |
| `wape` | decimal | fracción | Suma del error absoluto sobre la suma de lo real. |
| `bias` | decimal | fracción | Suma de (pronóstico − real) sobre la suma de lo real. |
| `coverage` | decimal | fracción | Proporción de pares con lo real entre P10 y P90. |
| `scaled_pinball` | decimal | fracción | Pinball de los tres cuantiles sobre la suma de lo real. |
| `share_beats_naive_last` | decimal | fracción | Proporción de series cuyo MAE es menor que el de repetir el último mes. |
| `share_beats_naive_mean3` | decimal | fracción | Proporción de series cuyo MAE es menor que el del promedio de 3 meses. |
| `fallback_rate` | decimal | fracción | Proporción de ajustes de Arps que cayeron a la cadena de respaldo. |
| `basin_band_coverage` | decimal | fracción | Proporción de orígenes en que el total real cae entre la suma de P10 y la de P90. |
| `coverage_verdict` | texto | — | calibrado, aceptable o descalibrado. |
| `verdict_es` | texto | — | Veredicto en palabras. |

### `fact_validation`

Hecho. Resultado de cada regla de validación en cada corrida. Grano: `run_key`, `rule_id`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `run_key` | texto | — | Corrida. |
| `rule_id` | texto | — | Regla de validación (V01 a V20, I01 a I03). |
| `name_es` | texto | — | Qué comprueba la regla. |
| `severity` | texto | — | bloqueante, advertencia o informativa. |
| `status` | texto | — | pasa, falla (bloqueante) o advierte. |
| `rows_affected` | entero 64 | filas | Filas afectadas. |
| `wells_affected` | entero 64 | pozos | Pozos afectados. |
<!-- columns:end -->
