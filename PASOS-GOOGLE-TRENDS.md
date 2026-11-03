# Google Trends en el Monitor Temas de Interés · Paraguay

Agrega una línea de **interés de búsqueda (Google Trends, 0-100)** por cada búsqueda,
con los mismos colores que el resto del dashboard. No reemplaza nada: convive con el
feed de Meltwater. Se muestran **4 vistas**:

- **Panel anual** (arriba de todo): el año en curso completo, resolución semanal.
  Reproduce el explore `q=dólar,Combustible,Presupuesto,BCP · geo=PY · año completo`.
- **3 ventanas por período** (30 días / 7 días / 24 horas): una línea de Trends al
  lado de la evolución de menciones de cada período.

## Cómo funciona

```
GitHub Action (self-hosted) --pytrends--> trends_collector.py
        |  POST /update-trends (x-sync-token)
        v
   [worker] --> KV key 'latest_trends_py'
        |
        +--> /api/latest adjunta data.trends --> dashboard dibuja la línea
```

- El worker Meltwater y el de Trends usan el **mismo KV** (`TEMASMONITOR`) pero
  **keys distintas** (`latest_temas_py` y `latest_trends_py`): una ingesta no pisa
  a la otra.
- Si todavía no hay datos de Trends, el panel simplemente no aparece (no rompe nada).

## Archivos

| Archivo | Dónde va |
|---|---|
| `worker_temas_py.js` | El worker (ya incluye `/update-trends` y el render del panel). |
| `trends_collector.py` | Raíz del repo (lo usa la Action). |
| `capture-trends.yml` | `.github/workflows/capture-trends.yml` |

## Pasos

1. **Subí el worker** actualizado (`worker_temas_py.js`) y redesplegá en Cloudflare.
   No hace falta tocar bindings: usa el mismo KV `TEMASMONITOR`.

2. **Subí al repo** `trends_collector.py` (raíz) y `capture-trends.yml`
   (en `.github/workflows/`).

3. **Secrets del repo** (Settings → Secrets and variables → Actions):
   - `WORKER_BASE_URL` → base del worker, p.ej. `https://temas-py.<cuenta>.workers.dev`
     (sin `/` final; el script agrega `/update-trends`).
   - `SYNC_TOKEN` → el mismo valor que ya usás para `/ingest` / `/update-url`
     (por defecto en el worker: `MAKE2026PY`; usá un secret real).

4. **Probá a mano**: pestaña **Actions → Capture Google Trends → Run workflow**.
   En el log tenés que ver algo como:
   `[trends] HTTP 200 · {"ok":true,"terms":["BCP","Dólar","Combustible","Presupuesto"],...}`

5. Entrá al dashboard: debajo de *"Evolución de menciones por tema"* aparece
   *"Interés de búsqueda · Google Trends"* en cada período.

## Ajustes

- **Keywords**: por defecto consulta `BCP`, `dólar`, `combustible`, `presupuesto`
  en geo `PY`. Para cambiarlas sin tocar código, definí la env `TRENDS_KEYWORDS`
  en el workflow con el formato `label=query;label=query`. El **label** tiene que
  coincidir con la búsqueda de Meltwater (BCP, Dólar, Combustible, Presupuesto)
  para que el color sea el mismo; el **query** es lo que se le pide a Google.
- **Año de la vista anual**: por defecto el año en curso. Para fijarlo (p.ej. 2026)
  definí la env `TRENDS_YEAR` en el workflow.
- **Frecuencia**: el cron está en cada 6 h (`17 */6 * * *`). Trends se actualiza
  lento y consultar muy seguido dispara bloqueos (429). No conviene bajarlo mucho.
- **Máximo 5 términos** por consulta (límite de Google Trends). Hoy usamos 4.

## Notas

- pytrends es una **API no oficial**; por eso corre en el **self-hosted runner**
  (IP propia, menos bloqueos). Si Google devuelve 429, el script reintenta con
  backoff y, si igual falla, el dashboard mantiene el último dato bueno.
- Cada timeframe de Trends se normaliza **por separado** (0-100 relativo dentro de
  su ventana), así que los valores no son comparables entre 30 d / 7 d / 24 h, pero
  sí entre búsquedas dentro del mismo período (que es lo que interesa).
