## Etsy Variant Engine

Rule-driven Etsy inventory automation engine with DB-backed SKU generation,

automatic template analysis, scale-property handling, and workshop-safe SKU fallback.

---

# 🚀 What This Project Is

Etsy Variant Engine is a backend inventory automation system designed for:

* High-variation Etsy shops
* Structured SKU production systems
* Workshop-driven manufacturing workflows
* Multi-shop (profile-based) architecture
* Future SaaS expansion

This is not a bulk editor.

This is a deterministic inventory orchestration engine.

---

# 🧠 Core Concept

The engine connects:

Etsy Listing Template

⬇

DB Code Tables (i_color, i_length, i_qty, i_type...)

⬇

Structured SKU Generator

⬇

Full Variation Matrix Builder

⬇

Safe Etsy Inventory Overwrite

---

# ✨ Features (v2)

* Dynamic Etsy template analysis
* Scale property support (length → numeric matching)
* Automatic scale_id / value_ids propagation
* SKU fallback logic (fixed length applied even if template has no length)
* Multi pricing strategies
* Workshop-safe SKU enforcement
* DB-backed deterministic code system
* Component & delimiter overrides
* Display label override engine
* Dry-run safe simulation mode
* FastAPI UI
* JSON CLI support
* Multi-profile architecture (future SaaS ready)

---

# 🏗 Architecture

* Python 3.9+
* FastAPI
* Etsy API v3
* MySQL (pymysql)
* Profile-driven SKU segmentation
* Rule-based template analyzer
* Deterministic DB resolver layer

---

# 📦 Installation (Fresh Setup)

## 1️⃣ Clone

<pre class="overflow-visible! px-0!" data-start="1797" data-end="1894"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span class="ͼl">git</span><span> clone https://github.com/recyalcin/etsy-variant-engine.git</span><br/><span class="ͼl">cd</span><span> etsy-variant-engine</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

## 2️⃣ Install dependencies

<pre class="overflow-visible! px-0!" data-start="1925" data-end="1968"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>pip install </span><span class="ͼn">-r</span><span> requirements.txt</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

Recommended requirements:

<pre class="overflow-visible! px-0!" data-start="1997" data-end="2115"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>fastapi</span><br/><span>uvicorn[standard]</span><br/><span>watchfiles</span><br/><span>pymysql</span><br/><span>requests</span><br/><span>python-dotenv</span><br/><span>jinja2</span><br/><span>python-multipart</span><br/><span>email-validator</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

---

# ⚙️ Environment Setup

Create `.env` file:

<pre class="overflow-visible! px-0!" data-start="2167" data-end="2374"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span class="ͼm">ETSY_API_KEY</span><span class="ͼg">=</span><span>your_api_key</span><br/><span class="ͼm">ETSY_REFRESH_TOKEN</span><span class="ͼg">=</span><span>your_refresh_token</span><br/><br/><span class="ͼm">MYSQL_HOST</span><span class="ͼg">=</span><span>localhost</span><br/><span class="ͼm">MYSQL_PORT</span><span class="ͼg">=</span><span class="ͼj">3306</span><br/><span class="ͼm">MYSQL_USER</span><span class="ͼg">=</span><span>root</span><br/><span class="ͼm">MYSQL_PASS</span><span class="ͼg">=</span><span>password</span><br/><span class="ͼm">MYSQL_DB</span><span class="ͼg">=</span><span>etsy_db</span><br/><br/><span class="ͼm">DB_PROFILE</span><span class="ͼg">=</span><span>belkymood</span><br/><span class="ͼm">WRITE_ENABLED</span><span class="ͼg">=</span><span class="ͼj">true</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

⚠ Never commit your real `.env`.

---

# ▶️ Running the App

This is NOT an npm project.

Do NOT run:

<pre class="overflow-visible! px-0!" data-start="2479" data-end="2504"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span class="ͼl">npm</span><span> run dev ❌</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

Instead run:

<pre class="overflow-visible! px-0!" data-start="2520" data-end="2556"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>uvicorn app:app </span><span class="ͼn">--reload</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

Open:

<pre class="overflow-visible! px-0!" data-start="2565" data-end="2594"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>http://127.0.0.1:8000</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

---

# 🧪 CLI Usage (Direct Engine Run)

<pre class="overflow-visible! px-0!" data-start="2637" data-end="2693"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>python run_inventory.py input.json </span><span class="ͼn">--dry-run</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

Without dry-run:

<pre class="overflow-visible! px-0!" data-start="2713" data-end="2759"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>python run_inventory.py input.json</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

---

# 🔐 Dry Run Mode (Important)

Dry-run:

* Does NOT write to Etsy
* Does NOT mutate DB
* Shows:
  * SKU preview
  * Template detection
  * Pricing resolution
  * DB insert plan
  * Mapping trace
  * SKU decode preview

Always dry-run before live overwrite.

---

# 📝 Workshop-Style Input Example

<pre class="overflow-visible! px-0!" data-start="3064" data-end="3270"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>Type : Necklace Heart</span><br/><span>Size : 10mm</span><br/><span>Color : GOLD, SILVER, ROSE</span><br/><span>Length : 14", 16", 18", 20"</span><br/><span>Quantity : 1 heart, 2 heart, 3 heart</span><br/><br/><span>Price :</span><br/><span>1 heart - $39</span><br/><span>2 heart - $52</span><br/><span>3 heart - $62</span><br/><br/><span>pricing_by : qty</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

Engine automatically:

* Detects template structure
* Resolves DB codes
* Normalizes display values
* Generates SKU matrix
* Applies pricing rule

---

# 🏷 SKU Structure

Profile-driven segmentation:

<pre class="overflow-visible! px-0!" data-start="3474" data-end="3528"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>[type][length][color][qty][size][start][space]</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

Example decoded:

<pre class="overflow-visible! px-0!" data-start="3548" data-end="3675"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>{</span><br/><span>  "type": </span><span class="ͼk">"24"</span><span>,</span><br/><span>  "length": </span><span class="ͼk">"03"</span><span>,</span><br/><span>  "color": </span><span class="ͼk">"7"</span><span>,</span><br/><span>  "qty": </span><span class="ͼk">"00"</span><span>,</span><br/><span>  "size": </span><span class="ͼk">"0"</span><span>,</span><br/><span>  "start": </span><span class="ͼk">"03"</span><span>,</span><br/><span>  "space": </span><span class="ͼk">"0"</span><br/><span>}</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

SKU is always DB-backed and deterministic.

---

# 🧩 Override System

Overrides allow template correction without changing DB.

---

## 1️⃣ Component Override

Force template property structure:

<pre class="overflow-visible! px-0!" data-start="3874" data-end="3948"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>{</span><br/><span>  "component_overrides": {</span><br/><span>    "513": [</span><span class="ͼk">"color"</span><span>, </span><span class="ͼk">"qty"</span><span>]</span><br/><span>  }</span><br/><span>}</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

---

## 2️⃣ Delimiter Override

Force join delimiter:

<pre class="overflow-visible! px-0!" data-start="4005" data-end="4064"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>{</span><br/><span>  "delim_overrides": {</span><br/><span>    "513": </span><span class="ͼk">" - "</span><br/><span>  }</span><br/><span>}</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

---

## 3️⃣ Display Value Override (Global)

<pre class="overflow-visible! px-0!" data-start="4111" data-end="4208"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>{</span><br/><span>  "display_value_overrides": {</span><br/><span>    "color": {</span><br/><span>      "ROSE": </span><span class="ͼk">"Rose Gold"</span><br/><span>    }</span><br/><span>  }</span><br/><span>}</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

---

## 4️⃣ Display Override Per Property

<pre class="overflow-visible! px-0!" data-start="4253" data-end="4457"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>{</span><br/><span>  "display_value_overrides_by_property": {</span><br/><span>    "513": {</span><br/><span>      "qty": {</span><br/><span>        "1 Taş": </span><span class="ͼk">"1 Birthstone"</span><span>,</span><br/><span>        "2 Taş": </span><span class="ͼk">"2 Birthstones"</span><span>,</span><br/><span>        "3 Taş": </span><span class="ͼk">"3 Birthstones"</span><br/><span>      }</span><br/><span>    }</span><br/><span>  }</span><br/><span>}</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

---

# 📏 Scale Property Handling (Length)

Etsy scale properties often return:

<pre class="overflow-visible! px-0!" data-start="4540" data-end="4552"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>"14"</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

But shop input may be:

<pre class="overflow-visible! px-0!" data-start="4578" data-end="4599"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>14"</span><br/><span>14 inches</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

Engine automatically normalizes:

<pre class="overflow-visible! px-0!" data-start="4635" data-end="4666"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>14" → 14</span><br/><span>14 inches → 14</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

And attaches:

* scale_id
* value_ids

automatically.

---

# 🛠 SKU Fixed-Length Fallback (v2 Feature)

If template has NO length variation

but input provides a single fixed length:

Engine:

* Does NOT send length to Etsy
* BUT writes length code into SKU

This prevents workshop cutting errors.

If multiple lengths are provided without template support → engine throws error.

---

# 💰 Pricing Modes

Supported pricing_by:

* fixed
* color
* qty
* length

Example:

<pre class="overflow-visible! px-0!" data-start="5141" data-end="5212"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>pricing_by : color</span><br/><br/><span>Price :</span><br/><span>Gold - 32</span><br/><span>Silver - 32</span><br/><span>Rose - 32</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

---

# 🗄 DB Tables

Core tables:

* i_type
* i_color
* i_length
* i_qty
* i_size
* i_start
* i_space

Engine auto-inserts missing values (unless dry-run).

---

# 🔐 Safety

* Dry-run mode
* WRITE_ENABLED flag
* readiness_state auto-detected
* SKU decode preview before overwrite
* DB plan summary before execution

---

# 👥 Multi-Shop Ready

Profile-based system:

* belkymood
* future profiles possible

Future SaaS expansion supported.

---

# 🧪 Typical Workflow

1. Clone project
2. Configure .env
3. Start FastAPI
4. Paste workshop-style input
5. Dry-run
6. Review SKU + DB plan
7. Run live

---

# 🧠 If You Forget How To Use It

Run:

<pre class="overflow-visible! px-0!" data-start="5859" data-end="5895"><div class="relative w-full my-4"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼd ͼr"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>uvicorn app:app </span><span class="ͼn">--reload</span></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

Then:

* Paste workshop input
* Ensure pricing_by is set
* Add overrides if needed
* Click dry-run first
* Confirm mapping trace
* Then run live

Never use npm.

This is Python.

---

# 📜 License

MIT License

---

# 👤 Author

Recep Yalcin

## 💡 Override Examples

{
  "component_overrides": {
    "54142602013": ["length"]
  },
  "display_value_overrides_by_property": {
    "513": {
      "color": {
        "GOLD": "Gold",
        "SILVER": "Silver",
        "ROSE": "Rose"
      },
      "qty": {
        "1 Option": "1 Stone",
        "2 Options": "2 Stones",
        "3 Options": "3 Stones",
        "4 Options": "4 Stones",
        "5 Options": "5 Stones",
        "6 Options": "6 Stones",
        "7 Options": "7 Stones",
        "8 Options": "8 Stones",
        "9 Options": "9 Stones",
        "10 Options": "10 Stones",
        "11 Options": "11 Stones",
        "12 Options": "12 Stones",
        "13 Options": "13 Stones"
      }
    }
  }
}

---

{
  "component_overrides": {
    "47626759838": ["length"]
  },
  "delim_overrides": {
    "513": " - "
  },

    "47626759838": {
      "length": {
        "14\"": "14",
        "16\"": "16",
        "18\"": "18",
        "20\"": "20",
        "22\"": "22",

    "14 inches": "14",
        "16 inches": "16",
        "18 inches": "18",
        "20 inches": "20",
        "22 inches": "22"
      }
    }
  }
}

---

{
  "display_value_overrides": {
    "color": {
      "Rose": "Rose Gold",
      "ROSE": "Rose Gold"
    }
  }
}

{
  "component_overrides": {
    "513": ["color", "qty"]
  },
  "delim_overrides": {
    "513": " - "
  },
  "display_value_overrides_by_property": {
    "513": {
      "qty": {
        "1 Taş": "1 Birthstone",
        "2 Taş": "2 Birthstones",
        "3 Taş": "3 Birthstones",
        "4 Taş": "4 Birthstones",
        "5 Taş": "5 Birthstones"
      }
    }
  },
  "display_value_overrides": {
    "color": {
      "GOLD": "Gold",
      "SILVER": "Silver",
      "ROSE": "Rose"
    }
  }
}

---

{
  "component_overrides": {
    "513": ["color", "qty"]
  },
  "delim_overrides": {
    "513": " - "
  },
  "display_value_overrides_by_property": {
    "513": {
      "qty": {
        "1 Taş": "1 Birthstone",
        "2 Taş": "2 Birthstones",
        "3 Taş": "3 Birthstones",
        "4 Taş": "4 Birthstones",
        "5 Taş": "5 Birthstones"
      }
    }
  },
  "display_value_overrides": {
    "color": {
      "GOLD": "Gold",
      "SILVER": "Silver",
      "ROSE": "Rose"
    }
  }
}