# TEMAS-PY-capture-data

Captura automática del reporte **Temas de Interés · Paraguay** de Meltwater.
Misma arquitectura que BROU:

```
cron-job.org → GitHub Actions (capture_meltwater.py baja y valida el .gz)
  → webhook de Make
  → módulo HTTP POST /update-url {"url": "...", "sync": true} + x-sync-token
  → Cloudflare Worker (monitortemaspy) → KV → Dashboard /monitor-temas
```

## Archivos
- `capture_meltwater.py` — genérico (todo por secrets), idéntico al de BROU.
- `.github/workflows/meltwater.yml` — workflow (dispatch manual + cron externo).

## Secrets del repo (Settings → Secrets → Actions → Repository secrets)

| Secret | Descripción |
|---|---|
| `MELTWATER_URL` | URL **pública** del reporte de Meltwater (Temas PY) |
| `MELTWATER_PASSWORD` | contraseña del gate (vacío si no hay) |
| `MAKE_WEBHOOK_URL` | URL del webhook de Make (TEMAS-PY-DATA) |

> Todos los valores sensibles (webhook de Make, sync-token, contraseñas) van
> **solo** en GitHub Secrets / Cloudflare, nunca en el repo.

## Disparo (cron-job.org, cada 30 min)
POST a `…/repos/Eyewatch4U/TEMAS-PY-capture-data/actions/workflows/meltwater.yml/dispatches`
con header `Authorization: Bearer <PAT Actions RW>` y body `{"ref":"main"}`.
