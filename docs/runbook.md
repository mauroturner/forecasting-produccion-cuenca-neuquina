# Runbook: qué hacer cuando algo no sale como se esperaba

Todos los comandos son para Windows (PowerShell), dentro de la carpeta `01-OilGas-Production-Forecast/` y con el entorno del proyecto. Una vez por sesión:

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python -m oilgas --help
```

Códigos de salida de la CLI: `0` terminó bien (también una publicación sin cambios), `1` falló una tarea, `2` uso o configuración incorrectos, `3` la publicación fue rechazada por la validación. Cada corrida deja su estado en `data/interim/runs/<run_key>.json` y, si cargó datos, una fila en `pipeline_runs`. Con `-v` la CLI muestra también el detalle de cada paso.

Un principio vale para todo el documento: **un rechazo o una falla no dejan el almacén ni las salidas a medias**. Si algo falla antes de la carga, el archivo SQLite, los Parquet y el HTML quedan byte por byte como estaban (AC04, decisión D35); si falla después, la corrida queda marcada `failed` y la siguiente rehace lo que falta.

## R1 Publicación atrasada

**Síntoma.** La corrida termina con estado `late`, o el tablero (página «Calidad y frescura») muestra que el último mes cargado tiene más de 55 días.

**Qué significa.** La publicación no cambió desde la última carga (mismo `ETag`, `Last-Modified` y tamaño) y el último mes cargado terminó hace más de 55 días. No es un error: el flujo sigue verificando todos los días y toma la publicación el mismo día en que aparece. El umbral de 55 días sale de una sola observación (el archivo del 2026-10-22 traía datos hasta 2026-09); si las publicaciones siguientes muestran otro ritmo, se ajusta `validation.freshness_max_days` en `config/pipeline.toml` y se anota en `decisions.md`.

**Qué hacer.**

1. Comprobar en el portal que de verdad no hay un archivo nuevo (R11 explica cómo consultar la API del portal).
2. Si lo hay y el flujo no lo vio, ejecutar `python -m oilgas run`: la verificación compara contra la última carga exitosa del manifiesto (`data/raw/manifest.json`).
3. Si no lo hay, esperar. No se rellenan meses ni se proyecta sobre un mes que no se publicó.

## R2 Cambio de forma del archivo

**Síntoma.** La corrida termina con código `3` y `rejected: ...`; la regla fallida es V02 (falta una columna usada), V01 (no se puede leer como UTF-8 o está mal formado) o V03/V04/V05/V06 (tipos, rangos, claves).

**Qué pasó.** El archivo no cumple el contrato de `src/oilgas/schema.py`. Quedó en `data/raw/quarantine/` (si estaba en `data/raw` se movió; si lo habías adoptado con `--adopt` se copió y el original sigue donde estaba), el manifiesto lo marca `rejected` y no se tocó nada más.

**Qué hacer.**

1. Leer el motivo en `reports/validation/latest.md` (o en `reports/validation/history/<run_key>.md`): cada regla trae hasta cinco ejemplos.
2. Si una columna se renombró en la fuente, agregar el renombre a `USED_COLUMNS` en `schema.py`, sumar una variante al generador `tests/fixtures/make_fixture.py` (`make_malformed` ya tiene `renamed_column`) y una prueba en `tests/contract/`. Es un cambio de contrato: se registra en `decisions.md`.
3. Si el archivo está dañado y no cambió de forma, esperar la próxima publicación (R5).
4. Volver a correr `python -m oilgas run --adopt <archivo>` cuando el contrato esté actualizado.

## R3 Republicación de meses anteriores

**Síntoma.** La regla V20 advierte que el total de la cuenca de un período con más de 3 meses de antigüedad cambió más de 1 % respecto de la carga previa; `pipeline_runs.revised_rows` es mayor que cero.

**Qué significa.** La Secretaría corrigió meses ya publicados. Es normal en pequeña medida (`rectificado = t` en 694 filas de la publicación perfilada). La carga reemplaza todo el subconjunto y deja el detalle de lo que cambió por período en `load_revisions`.

**Qué hacer.** Nada es obligatorio: la carga es idempotente y las proyecciones se rehacen con los datos revisados. Conviene mirar cuántas filas y qué períodos cambiaron (`SELECT * FROM load_revisions ORDER BY period_key`); si cambió un total grande, comprobar que no se trate de una publicación defectuosa (R5). Limitación conocida: el backtest usa los datos ya revisados, no las versiones que existían en cada mes (`docs/model-card.md`).

## R4 Descarga fallida o tamaño distinto

**Síntoma.** La tarea `download` falla con un error de descarga: el tamaño recibido no coincide con el anunciado, la conexión se cortó o el servidor respondió un error distinto de 404.

**Qué pasó.** La descarga se escribe en `data/raw/<nombre>.part` y solo se renombra si el tamaño coincide con el anunciado por `HEAD`; si no, el `.part` queda sin renombrar y no se agrega nada al manifiesto como descargado.

**Qué hacer.**

1. Reintentar: Airflow reintenta tres veces con 15 minutos de espera; en la CLI, `python -m oilgas run`.
2. Si el servidor responde bien pero el tamaño anunciado y el recibido siempre difieren, la publicación se está regenerando: esperar unos minutos y reintentar.
3. Si ya tenés el archivo completo, usarlo sin descargar: `python -m oilgas run --adopt data\raw\<archivo>.csv`. La integridad se comprueba con el tamaño y el SHA-256 que quedan en el manifiesto (la fuente solo ofrece HTTP, sin TLS; RNF11).
4. Un 404 es otro caso: ver R11.

## R5 Archivo truncado o último mes incompleto

**Síntoma.** Rechazo por V09 (el subconjunto tiene menos del 99 % de las filas o de los pozos de la carga previa), por V10 (el último período es anterior al ya cargado), o advertencia V11 (el último período tiene menos del 90 % de las filas del anterior).

**Qué hacer.**

- V09 o V10: el archivo está en cuarentena y el almacén intacto. No se fuerza la carga. Esperar una publicación nueva o, si la Secretaría republicó el mismo archivo, ejecutar de nuevo.
- V11 (solo advertencia): el archivo se cargó, pero el último mes tiene pocos pozos informando; las proyecciones usan ese mes como origen y pueden subestimar. Revisar `reports/validation/latest.md` y, si el mes está claramente incompleto, no usar esa corrida para decidir hasta que se complete: la publicación siguiente lo corrige (R3).

## R6 Muchas fallas de ajuste de Arps

**Síntoma.** En el resumen del backtest, la tasa de respaldo (`fallback_rate`) de una variante de Arps supera el 2 % (AC13), o el hecho `fact_well_fit` marca muchos ajustes con `needs_review` (error logarítmico mayor que 1,0).

**Qué hacer.**

1. Ver qué pozos fallan: `SELECT well_id, fluid, status, n_points, rmse_log FROM model_fit WHERE status <> 'ok'`.
2. Mirar las marcas de calidad de esos pozos en `stg_monthly_production.quality_flags` (`TEF_GT_DAYS`, `TEF_ZERO_WITH_PROD`, `NEG_VOLUME`) y los meses sin fila: un pozo con muchos huecos o con un reinicio tiene un ajuste pobre sin que el código falle.
3. Un pozo sin ajuste no se descarta: la cadena de respaldo pasa a la exponencial y, si también falla, al promedio de 3 meses (`fit_status` lo dice).
4. No se cambian los límites de Arps (`[arps]` en `config/pipeline.toml`) para que el criterio pase: los límites están preregistrados. Si hay una razón técnica, se cambian con una entrada nueva en `decisions.md` y se vuelve a correr el backtest completo.

## R7 Bandas descalibradas

**Síntoma.** El resumen marca una cobertura P10-P90 `descalibrada` (fuera de 0,70 a 0,90), o la cobertura de la cuenca (`basin_band_coverage`) es muy baja.

**Qué significa.** Las bandas de los métodos puntuales salen de los errores ya realizados en los 12 orígenes más recientes con objetivo conocido; si el comportamiento cambió (un cambio de operadora masivo, un mes anómalo), los errores recientes no representan el futuro. Las bandas del machine learning salen de la regresión cuantílica y pueden quedar angostas.

**Qué hacer.** Leer el veredicto escrito en `reports/backtest_summary.md`: se informa tal cual, también cuando es desfavorable. Revisar por horizonte y tramo de edad en `fact_backtest_metrics`. No se mueven los umbrales de `[criteria]` después de ver el resultado. Si el problema persiste en varias publicaciones, es una decisión de modelado: se registra en `decisions.md` y se rehace el backtest completo.

## R8 Airflow no arranca (Docker)

Airflow corre solo dentro de Docker Compose (`airflow/`); en Windows no se instala fuera de un contenedor o de WSL2. Para levantarlo:

```powershell
cd airflow
copy .env.example .env
docker compose build
docker compose up airflow-init
docker compose up -d
```

La interfaz queda en `http://localhost:8080` (usuario y contraseña: `airflow`). Si no arranca:

- **Docker Desktop apagado.** `docker info` falla: encenderlo y esperar a que diga que está corriendo.
- **Memoria.** Docker necesita 4 GB como mínimo (8 GB recomendado). En Docker Desktop: Settings, Resources. Síntoma típico: contenedores que se reinician o `airflow-init` que termina con código 137.
- **Puerto 8080 ocupado.** Cambiar el mapeo `"8080:8080"` de `docker-compose.yaml` o cerrar el programa que lo usa (`netstat -ano | findstr :8080`).
- **Permisos de la carpeta de registros.** `.env` debe tener `AIRFLOW_UID=50000`; si `airflow-init` se queja de permisos sobre `logs/`, borrar `airflow/logs/` (no se versiona) y repetir `docker compose up airflow-init`.
- **El DAG no aparece.** `docker compose logs airflow-dag-processor`: un error de importación aparece ahí. El DAG es solo el cableado de `oilgas.pipeline.TASKS`; para saber si el problema es del DAG o del proyecto, correr `python -m oilgas run` en Windows.

`airflow dags test` no se ejecutó dentro de este proyecto porque Docker Desktop no estaba encendido al construirlo (decisión D35, pendiente del dueño); el DAG se verifica de forma estática con pruebas sobre el árbol del código.

## R9 `database is locked`

**Síntoma.** Una tarea falla con `sqlite3.OperationalError: database is locked`.

**Qué pasó.** SQLite admite un solo escritor. La conexión espera hasta 30 segundos el bloqueo de escritura (`busy_timeout`), así que el error aparece cuando dos corridas se superponen más tiempo que eso, por ejemplo una corrida manual mientras corre la programada.

**Qué hacer.**

1. Ver qué proceso la tiene: `Get-Process python`; el DAG ya limita a una corrida y una tarea activas (`max_active_runs=1`, `max_active_tasks=1`).
2. Esperar a que termine la otra y repetir (la carga es idempotente).
3. Si quedó un archivo `data/warehouse/production.sqlite-journal` de un proceso que murió, SQLite lo revierte solo la próxima vez que abre la base; no hay que borrarlo a mano.
4. El modo WAL no se usa a propósito (no funciona bien sobre las carpetas montadas de Docker Desktop).

## R10 Reconstruir desde cero

**Cuándo.** Si el esquema del almacén cambió y la carga lanza `SchemaDriftError` («The warehouse was created by an older version: rebuild it»), o si querés partir de una base limpia.

```powershell
Remove-Item -Recurse data\warehouse, data\interim
python -m oilgas run --adopt data\raw\produccin-de-pozos-de-gas-y-petrleo-no-convencional.csv
```

`data/raw/` (el CSV y el manifiesto) no se borra. `data/warehouse/` y `data/interim/` se regeneran por completo y no se versionan (RNF09). Una corrida completa sobre la publicación real tarda unos 40 minutos (ver «Rendimiento» en `docs/model-card.md`); `--config config\pipeline.quick.toml` hace la versión rápida sobre una publicación sintética (`python -m oilgas make-fixture data\quick\publication.csv`) y escribe solo en `data/quick/`, sin tocar las salidas versionadas.

## R11 La URL del recurso cambió

**Síntoma.** La verificación (`check_publication`) falla con un 404 y un mensaje que remite a este apartado.

**Qué hacer.**

1. Consultar la API del portal (CKAN) para ver los recursos vigentes del dataset: `https://datos.gob.ar/api/3/action/package_show?id=produccion-de-petroleo-y-gas-por-pozo`.
2. Buscar el recurso cuyo nombre sea «Producción de pozos de gas y petróleo no convencional» y copiar su `url` y su `id`.
3. Actualizar `source.url` y `source.resource_id` en `config/pipeline.toml`. Hay dos recursos con el mismo nombre en los archivos anuales de 2024 y 2025; este proyecto no usa los anuales, sino el archivo único de no convencionales.
4. Ejecutar `python -m oilgas run`. Si el archivo cambió de forma, sigue R2.
