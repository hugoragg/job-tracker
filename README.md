# Job Tracker

Un tracker personal de ofertas de empleo (Madrid + London) para perfiles early-careers de finance / IB / consulting / private equity. Cada día scrapea ~50 portales corporativos, filtra los resultados con una IA local según mis criterios, y me manda un email digest a las 07:00 de la mañana.

---

## El problema

Buscar prácticas en banca de inversión, PE, consultoría y mercados desde Madrid implica:

- **~50 portales distintos** (Workday, Greenhouse, SAP SuccessFactors, TalentLink, Cegid TalentSoft, Yello, Phenom, iCIMS, Pinpoint, custom WordPress…). Cada uno con su quirk: Cloudflare, HTTP/2 errors, JS heavy, paginación rara, location filtering inconsistente.
- **Ciclos de reclutamiento cortos**: muchas ofertas se cierran en 3-7 días. Si no las ves a tiempo, se pierden.
- **Mucha basura en cada portal**: una página de carreras puede tener 500 puestos de los que 20 son relevantes (un IB rechaza puestos de retail/recepción/audit senior).
- **No quiero gastar dinero**: el filtro AI tiene que ser local.
- **No quiero mantener infraestructura compleja**: cron de servidor remoto, K8s, etc. Solo un PC con Windows y un cron local.

---

## La solución

Pipeline diario en tres pasos:

```
┌─────────────┐    ┌──────────┐    ┌────────────┐    ┌────────────┐    ┌───────┐
│ Scrapers    │ →  │ Supabase │ →  │ AI filter  │ →  │ Email      │ →  │ Inbox │
│ (50 portales)│   │ (Postgres)│   │ (Ollama)   │    │ (Resend)   │    │       │
└─────────────┘    └──────────┘    └────────────┘    └────────────┘    └───────┘
```

1. **Scrape**: por cada empresa, un scraper específico (o uno genérico) extrae títulos + URLs + ubicación. Sólo los matches de Madrid (o Madrid + London según empresa).
2. **Upsert a Supabase**: la DB compara URLs contra lo que ya tenía. Las URLs nuevas pasan a la fase del filter; el resto ya tiene decisión persistida de días anteriores.
3. **Filter AI local**: `qwen2.5:7b` corriendo en Ollama lee `config/preferences.md` y decide KEEP / DROP para cada URL nueva. Las decisiones se persisten en la DB.
4. **Email digest**: dos secciones — *Nuevos hoy* (Section A) y *Últimos 7 días* (Section B). Resend manda el HTML al inbox.

El cron es Windows Task Scheduler, no Railway ni cron remoto. Cero coste, todo local salvo Supabase (free tier) y Resend (free tier).

---

## Arquitectura

```
job-tracker/
├── scraper/                    # Todo lo del scraper + filter + email
│   ├── config/
│   │   ├── companies.yaml      # Lista de empresas + URL + tipo de ATS
│   │   └── preferences.md      # Criterios de filtrado para la IA
│   ├── src/
│   │   ├── main.py             # Orquestación: scrape → upsert → filter → email
│   │   ├── models.py           # Pydantic: CompanyConfig, Job, FilterDecision
│   │   ├── db.py               # Supabase: upsert_jobs, record_filter_decisions, get_jobs_last_n_days
│   │   ├── ai_filter.py        # Ollama call con structured JSON output + batching
│   │   ├── email_digest.py     # Render HTML + Resend send
│   │   └── scrapers/           # Un scraper por ATS o por empresa con custom logic
│   │       ├── base.py             # Location matching (multi-city, peer-city rejection)
│   │       ├── playwright_scraper.py  # Genérico SPA: captura XHR JSON + DOM heuristics
│   │       ├── workday.py          # Workday CXS API
│   │       ├── greenhouse.py       # Greenhouse JSON API
│   │       ├── lever.py            # Lever JSON API
│   │       ├── html_scraper.py     # BeautifulSoup
│   │       ├── sap_successfactors.py  # Para CaixaBank/Deloitte/KPMG
│   │       ├── talentlink.py       # Atom feed + HTML fallback (Evercore, Jefferies, Lazard, Nomura)
│   │       ├── cegid_talentsoft.py # ASP.NET WebForms (Amundi, Credit Agricole)
│   │       ├── alantra.py          # WordPress admin-ajax
│   │       ├── bcg.py              # Phenom People /widgets
│   │       ├── mckinsey.py         # Real-Chrome + stealth bypass
│   │       ├── morgan_stanley.py   # JSON endpoint detrás del SPA
│   │       └── (... 8 scrapers más, uno por gotcha encontrada)
│   ├── run_scrape.ps1          # Wrapper PowerShell que invoca Task Scheduler
│   └── pyproject.toml          # uv-managed Python deps
├── supabase/
│   └── schema.sql              # DDL: companies, jobs, scrape_runs
├── frontend/                   # Next.js app que lee de Supabase (separada)
├── CLAUDE.md                   # Notas técnicas detalladas (lista verified scrapers, gotchas por ATS)
└── README.md                   # Este fichero
```

### Esquema de DB (Supabase)

```sql
companies   (id UUID PK, name UNIQUE, careers_url, ats_platform, created_at)
jobs        (id UUID PK, company_id FK, external_id, title, url, location, department,
             job_type, description,
             is_active, first_seen_at, last_seen_at,
             ai_keep BOOLEAN, ai_reason TEXT,
             UNIQUE (company_id, url))
scrape_runs (id UUID PK, started_at, completed_at, new_jobs_found, status, errors JSONB)
```

`ai_keep` es la persistencia de decisiones: `NULL`=pendiente/passthrough, `true`=keep, `false`=drop. El filtro de la query del Section B usa `ai_keep IS NOT FALSE` (incluye NULL y TRUE — lean-inclusive).

---

## Stack

| Capa | Herramienta | Por qué |
|---|---|---|
| Scraping | `playwright` + `httpx` + `BeautifulSoup` | Playwright para SPAs (Workday, Phenom, etc.); httpx + BS4 para APIs directas y server-rendered HTML |
| Browser-bypass | Playwright real-Chrome channel + stealth init | Algunas pages (DC Advisory, McKinsey) están detrás de Cloudflare; bundled Chromium se bloquea |
| DB | Supabase (Postgres + REST) | Free tier, API JS y Python, RLS para frontend |
| Filter LLM | Ollama (`qwen2.5:7b`) corriendo localmente | Gratis, no API key, structured JSON output, suficiente quality para el problema |
| Email | Resend | Free tier (3k/mes), dominio verificable, HTML emails |
| Orquestación | Python `asyncio` | Scrapers async, filter async, una sola event loop |
| Scheduling | Windows Task Scheduler | Local, cero infra, `WakeToRun` + `StartWhenAvailable` cubren los edge cases |
| Package mgmt | `uv` | Más rápido que pip, lockfile bueno |

---

## Workflow diario

### Primer día (DB vacía)

1. **07:00**: Task Scheduler dispara `run_scrape.ps1`
2. **07:00-07:20**: scrape de ~50 empresas. Returns ~450 ofertas matching Madrid/London.
3. **07:20-09:40**: `ai_filter` procesa los ~450 jobs en chunks de 25, llamando a Ollama. Cada chunk ~5-10 min en CPU. Las decisiones se persisten en `jobs.ai_keep` / `jobs.ai_reason`.
4. **~09:40**: email con Section A (234 jobs kept hoy) + Section B (236 = 234 + algunos previos).

### Día N (≥2)

1. **07:00**: dispara la tarea
2. **07:00-07:20**: mismo scrape de las ~50 empresas. **Crucial**: `upsert_jobs` compara cada URL contra la DB. Las que ya estaban no cuentan como "nuevas".
3. **07:20-07:30**: el filter sólo procesa el **delta** — típicamente 5-30 jobs nuevos por día. Tarda ~5-15 min.
4. **~07:30**: email con Section A (los nuevos kept) + Section B (todos los kept de los últimos 7 días).

Los jobs no se re-filtran nunca. Una decisión por (URL, modelo) y se queda.

---

## Filtro AI — cómo funciona

El system prompt incluye:

1. **Preámbulo fijo**: rol del modelo + regla *"when in doubt, KEEP"* + descripción del schema de output (estricto JSON con `url`, `keep`, `reason` por job).
2. **Contenido íntegro de `config/preferences.md`**: criterios reales del candidato — secciones STRONG KEEP / KEEP IF UNCERTAIN / DROP + ejemplos concretos.

El user prompt es la lista JSON de jobs a evaluar (título, empresa, ubicación, departamento, URL).

### Batching

448 jobs en una sola llamada satura el modelo (~14k tokens output, contexto sufrido en CPU). Splitea en **chunks de 25** y serializa. Cada chunk es independiente: si uno falla, sus 25 jobs pasan como passthrough (`is_real=False, keep=True`), los otros siguen.

### Structured output

Ollama soporta `format=<json_schema>` que **garantiza** que la respuesta valida contra el schema. Sin esto el modelo a veces emite JSON malformado y hay que reintentar. Con esto: parsing limpio siempre.

### Persistencia con escape para reintento

Sólo decisiones reales (`is_real=True`) se guardan en `ai_keep`/`ai_reason`. Las passthrough quedan con `ai_keep=NULL` — siguen apareciendo en la sección B durante 7 días, pero queda visible que no las pasó el filtro (debugging) y podrían reintentarse en una iteración futura.

---

## Setup (cómo reproducir)

### 1. Clonar y deps

```bash
git clone https://github.com/hugoragg/job-tracker.git
cd job-tracker/scraper
uv sync
uv run playwright install chromium --with-deps
# Para DC Advisory / McKinsey hace falta también Chrome real:
uv run playwright install chrome
```

### 2. Supabase

Crear proyecto en supabase.com (free tier), aplicar `job-tracker/supabase/schema.sql` en el SQL Editor.

### 3. Ollama

```bash
# Descargar de ollama.com/download
ollama pull qwen2.5:7b
```

(Necesita ~5GB de RAM en runtime. Para CPU sólo es viable con modelos ≤8B.)

### 4. Resend

Cuenta en resend.com, dominio verificado o usar `onboarding@resend.dev` para tests.

### 5. .env

```bash
cp scraper/.env.example scraper/.env
# Rellenar: SUPABASE_URL, SUPABASE_SERVICE_KEY, RESEND_API_KEY, EMAIL_FROM, EMAIL_TO
# Opcional: ANTHROPIC_API_KEY (NO se usa actualmente — eliminado), OLLAMA_HOST, OLLAMA_MODEL
```

### 6. preferences.md

Editar `scraper/config/preferences.md` con tus criterios reales. La estructura recomendada:

- Sección "About the candidate" — perfil/seniority/geografía
- "STRONG KEEP" — sectores y roles claramente target
- "KEEP IF UNCERTAIN" — marginales / borderline / ambiguous
- "DROP" — qué descartar explícitamente
- "Hard rule" — *"when in doubt, KEEP"*

### 7. Smoke test

```bash
uv run python -m src.smoke_filter   # 5 jobs de ejemplo, ~2 min
uv run python -m src.e2e_small      # 1 empresa real, full pipeline sin enviar email, ~3 min
uv run scrape                       # full Day 1: scrape + filter + email real, ~2h 30 min
```

### 8. Schedule diario (Windows)

```powershell
$ScriptPath = '<absolute path>\job-tracker\scraper\run_scrape.ps1'
$Action  = New-ScheduledTaskAction -Execute 'powershell.exe' `
            -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`""
$Trigger = New-ScheduledTaskTrigger -Daily -At '07:00'
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
              -ExecutionTimeLimit (New-TimeSpan -Hours 4)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
Register-ScheduledTask -TaskName 'JobTracker_Daily' -Action $Action -Trigger $Trigger `
                       -Settings $Settings -Principal $Principal -Force
```

---

## Verified scrapers

Detalle por empresa (con gotchas y notas específicas) en **`CLAUDE.md`** — tabla con ~50 entries y nota de cómo se resolvió cada caso particular (Cloudflare, HTTP/2 errors, slug parsing, etc.).

Resumen agregado:

| ATS | # empresas | Aproach |
|---|---|---|
| Workday | 5 | API `CXS` directa, paginación por `appliedFacets` |
| Greenhouse | 1 | API JSON, simple |
| Playwright genérico | ~25 | Captura XHR JSON + scrape DOM con heurísticas |
| Scraper custom dedicado | 15+ | Cada uno con su gotcha (real-Chrome, ASP.NET Forms, MongoDB IDs, etc.) |
| Skipped (revisitar) | 4 | Bain, BNP Paribas CIB, Arthur D. Little, Greenhill — bloqueos no triviales |

---

## Limitaciones

### Del filtro AI

- **Modelo 7B en CPU es lento**: ~5-10 min por chunk de 25 jobs. Día 1 tarda ~2h 30min total. Aceptable porque es batch nocturno.
- **A veces el modelo omite decisiones**: en el Día 1 real (448 jobs), 62 jobs (~14%) no recibieron decisión en el JSON output. Quedan como passthrough (mostrados en email, no persistidos). Lean-inclusive por diseño.
- **Patrón Compliance**: con `qwen2.5:7b`, los roles de Compliance en bancos/fondos a veces se descartan a pesar de estar en STRONG KEEP. Mejoró notablemente con `preferences.md` explícito pero no es 100% fiable. Modelos más grandes (qwen2.5:14b, gpt-oss:20b) deberían arreglar esto a costa de más latencia.
- **Sin retry para passthroughs**: jobs con `ai_keep=NULL` no se reprocesan en runs posteriores. Caducan por la ventana de 7 días.

### De los scrapers

- **Cloudflare hard**: Bain está totalmente bloqueado (incluso real-Chrome + stealth). Necesitaría `cloudscraper` o `undetected-chromedriver`.
- **HTTP/2 errors**: BNP Paribas CIB aborta la conexión incluso con HTTP/2 deshabilitado. Sin solución actual.
- **iCIMS sub-frame**: Arthur D. Little renderiza dentro de un iframe que sólo se sirve con cierto Referer/cookie state. Pendiente.
- **Verificación manual de cada empresa**: cada portal nuevo requiere debugging individual. `src/debug_one.py` y `src/diagnose.py` ayudan, pero no es trivial.

### Del scheduling

- **PC requerido encendido + sesión iniciada**: `LogonType=Interactive`. No corre con sesión cerrada o PC apagado/hibernado, sólo a la próxima vez que se inicie sesión.
- **Sin retry automático en errores transitorios**: si Ollama no responde una vez, el filter pasa todo como passthrough y el email va sin filtrar (fail-open). Mejorable.
- **Supabase free tier pausa proyectos** tras 7 días sin actividad. Con el daily run esto no debería pasar, pero hay que restaurar manualmente si ocurre.

### De la calidad del filtro

- **Depende fuertemente de `preferences.md`**: con un fichero vago el modelo será permisivo. Con uno demasiado restrictivo, perderá marginales. Iterar el fichero observando el output real.
- **No hay feedback loop**: si el modelo descarta una oferta interesante, no hay forma de marcar y reentrenarlo. Sería interesante un mecanismo "no, esta sí era buena" → ajusta prefs automáticamente.

---

## Pendientes / ideas

- [ ] **Retry para passthroughs**: en cada run, también pasar por el filter los jobs con `ai_keep=NULL` (no sólo los `all_new`).
- [ ] **Bain via cloudscraper**: probar `curl_cffi` o `cloudscraper` para el bypass de Cloudflare.
- [ ] **Feedback loop**: link en el email para marcar "esta sí era buena" o "esta no" → ajusta `preferences.md` automáticamente.
- [ ] **Modelo más grande**: probar `qwen2.5:14b` (si la RAM permite) o `gpt-oss:20b` con quantization para arreglar el Compliance miss.
- [ ] **Frontend interactivo**: actualmente sólo emails. Una página Next.js con dashboard de jobs activos / archive / search.
- [ ] **Filtros server-side por empresa**: algunas empresas exponen filtros en URL (location, role) que no aprovecho. Reduciría el tiempo de scrape.
- [ ] **Reintentos exponenciales** para errores de red transitorios en scrapers Playwright.

---

## Estructura de los commits

Si miras `git log`, el desarrollo siguió esta progresión:

1. **Scaffolding inicial**: estructura básica + 3 scrapers (Greenhouse, Lever, HTML).
2. **Verificación por empresa**: una empresa a la vez, identificar gotchas, escribir scraper custom si el genérico no servía. ~50 empresas, documentadas en `CLAUDE.md`.
3. **Email digest plan**: diseño del pipeline diario con AI filter.
4. **Implementación inicial con Anthropic SDK**: filter via API Claude Sonnet 4.6.
5. **Swap a Ollama local**: para no pagar por inferencia. Mismo contrato, infra distinta.
6. **Refactor a filter-only-on-delta**: el insight clave — sólo filtrar jobs nuevos vs DB ayer, persistir decisiones. Reduce Día N de ~2h a ~10 min.
7. **Validación end-to-end**: smoke test, e2e_small, Día 1 completo.

Cada paso commiteado por separado, con mensaje describiendo qué y por qué.

---

## Licencia

Proyecto personal. Sin licencia explícita. Si te sirve de inspiración para tu propio tracker, adelante — pero el `config/preferences.md` es mío y los scrapers están afinados para portales que me interesan a mí; tu kilometraje variará.
