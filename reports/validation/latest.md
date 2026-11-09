# Reporte de validación

- Corrida: `20261109T225601Z`
- Resultado: **Aceptado: ninguna regla bloqueante falla.**
- SHA-256 del archivo: `61cecc31c8dd81fd474c4094f2605b2b01b5a5d157e2089db7f3c548c410deae`
- Filas del archivo: 431322; filas del subconjunto: 413865; pozos: 4937
- Períodos del subconjunto: 200601 a 202609

## Reglas

| ID | Regla | Severidad | Estado | Filas | Pozos |
| --- | --- | --- | --- | ---: | ---: |
| V01 | El archivo se lee como CSV en UTF-8 | bloqueante | pasa | 0 | 0 |
| V02 | Están todas las columnas que usa el proyecto | bloqueante | pasa | 0 | 0 |
| V03 | idpozo, anio y mes son enteros y no nulos | bloqueante | pasa | 0 | 0 |
| V04 | El mes está entre 1 y 12 y el período está dentro del alcance y no es futuro | bloqueante | pasa | 0 | 0 |
| V05 | fecha_data es el último día del mes de la fila | bloqueante | pasa | 0 | 0 |
| V06 | La clave (idpozo, anio, mes) es única | bloqueante | pasa | 0 | 0 |
| V07 | Los volúmenes no convertibles o nulos no superan el umbral | bloqueante | pasa | 0 | 0 |
| V08 | El subconjunto (cuenca y tipo de recurso) no está vacío | bloqueante | pasa | 0 | 0 |
| V09 | El subconjunto no se achica respecto de la carga previa | bloqueante | pasa | 0 | 0 |
| V10 | El último período no es anterior al de la carga previa | bloqueante | pasa | 0 | 0 |
| V11 | El último período trae filas comparables con las del anterior | advertencia | pasa | 0 | 0 |
| V12 | Volumen negativo (se corrige a nulo) | advertencia | advierte | 2 | 2 |
| V13 | Días efectivos mayores que los días del mes (se corrigen a nulo) | advertencia | advierte | 70 | 58 |
| V14 | Días efectivos en cero con producción (se conserva y se marca) | advertencia | advierte | 384 | 131 |
| V15 | Volumen mensual por encima del tope plausible (se conserva y se marca) | advertencia | pasa | 0 | 0 |
| V16 | Coordenadas intercambiadas o fuera de la cuenca | advertencia | advierte | 70 | 1 |
| V17 | Profundidad fuera de rango (se corrige a nulo) | advertencia | advierte | 6235 | 176 |
| V18 | Atributo fijo con más de un valor en un mismo pozo | advertencia | pasa | 0 | 0 |
| V19 | Columnas que no están en el contrato | advertencia | pasa | 0 | 0 |
| V20 | Total de un período antiguo revisado más allá de la tolerancia | advertencia | pasa | 0 | 0 |
| I01 | Meses sin producción con estado de extracción efectiva | informativa | pasa | 15870 | 886 |
| I02 | Filas cargadas automáticamente como sin movimientos | informativa | pasa | 7421 | 421 |
| I03 | Meses sin fila dentro del período de un pozo | informativa | pasa | 7420 | 703 |

## Ejemplos

### V12: Volumen negativo (se corrige a nulo)

- `{"well_id": 153228, "period_key": 202005, "value": -12.267}`
- `{"well_id": 153227, "period_key": 202005, "value": -7.519}`

### V13: Días efectivos mayores que los días del mes (se corrigen a nulo)

- `{"well_id": 154790, "period_key": 201905, "value": 79.34}`
- `{"well_id": 161532, "period_key": 202106, "value": 36.67}`
- `{"well_id": 161531, "period_key": 202106, "value": 36.67}`
- `{"well_id": 161427, "period_key": 202506, "value": 31.583}`
- `{"well_id": 160933, "period_key": 202506, "value": 30.379}`

### V14: Días efectivos en cero con producción (se conserva y se marca)

- `{"well_id": 153918, "period_key": 201503, "value": 0.0}`
- `{"well_id": 156504, "period_key": 201603, "value": 0.0}`
- `{"well_id": 156389, "period_key": 201603, "value": 0.0}`
- `{"well_id": 156503, "period_key": 201603, "value": 0.0}`
- `{"well_id": 156607, "period_key": 201605, "value": 0.0}`

### V16: Coordenadas intercambiadas o fuera de la cuenca

- `{"well_id": 162058, "lon": -38.59007, "lat": -69.41577, "reason": "swapped"}`

### V17: Profundidad fuera de rango (se corrige a nulo)

- `{"well_id": 162407, "value": 0.0}`
- `{"well_id": 162410, "value": 0.0}`
- `{"well_id": 162486, "value": 0.0}`
- `{"well_id": 162568, "value": 0.0}`
- `{"well_id": 162574, "value": 0.0}`

### I01: Meses sin producción con estado de extracción efectiva

- `{"well_id": 131718, "period_key": 201501}`
- `{"well_id": 130517, "period_key": 201601}`
- `{"well_id": 137075, "period_key": 201601}`
- `{"well_id": 130517, "period_key": 201602}`
- `{"well_id": 137075, "period_key": 201602}`

### I02: Filas cargadas automáticamente como sin movimientos

- `{"well_id": 145330, "period_key": 201801}`
- `{"well_id": 145330, "period_key": 201802}`
- `{"well_id": 145330, "period_key": 201803}`
- `{"well_id": 145330, "period_key": 201804}`
- `{"well_id": 145330, "period_key": 201805}`

### I03: Meses sin fila dentro del período de un pozo

- `{"well_id": 8043, "missing_months": 1}`
- `{"well_id": 11641, "missing_months": 1}`
- `{"well_id": 11642, "missing_months": 1}`
- `{"well_id": 11643, "missing_months": 1}`
- `{"well_id": 34833, "missing_months": 1}`
