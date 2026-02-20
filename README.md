# Etsy Variant Engine

Rule-driven Etsy inventory automation engine with DB-backed SKU generation, 
multi-profile support (shiny / silveristic), 
automatic template analysis, 
and full variation matrix generation.

---

## 🚀 Overview

Etsy Variant Engine is a backend automation tool designed for advanced Etsy sellers 
who manage high-variation listings and structured SKU systems.

It connects Etsy inventory with a MySQL-based code table system and generates:

- Structured SKUs
- Full variation matrices
- DB-backed type/length/color/qty codes
- Automated readiness_state handling
- Intelligent pricing strategies

This is not a simple bulk editor — it is a rule-driven inventory engine.

---

## ✨ Features

- Dynamic Etsy template analysis
- Automatic readiness_state_id detection (no manual input required)
- Profile-based SKU segmentation
- DB-first architecture (i_type, i_length, i_color, etc.)
- Multi pricing modes:
  - Fixed
  - By color
  - By quantity
- Dry-run mode (safe simulation)
- FastAPI UI
- JSON API support
- Multi-profile support:
  - shiny
  - silveristic

---

## 🏗 Architecture

- Python 3.9+
- FastAPI
- Etsy API v3
- MySQL (pymysql)
- Rule-based variation builder
- Profile-driven SKU generator

---

## 📦 Installation

Clone repository:

```bash
git clone https://github.com/recyalcin/etsy-variant-engine.git
cd etsy-variant-engine
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## ⚙️ Environment Setup

Create a .env file based on .env.example:

```bash
ETSY_API_KEY=your_api_key
ETSY_REFRESH_TOKEN=your_refresh_token

MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASS=password
MYSQL_DB=etsy_db

DB_PROFILE=shiny
WRITE_ENABLED=true
```

⚠️ Never commit your real .env file.

## ▶️ Run Application

Start FastAPI server:

```bash
uvicorn app:app --reload
```

Open:

http://127.0.0.1:8000

## 🧪 Dry Run Mode

Dry-run simulates:

SKU generation

DB insert/update plan

Pricing resolution

Template analysis

Without writing to DB or pushing to Etsy.

Example CLI usage:

```bash
python run_inventory.py input.json --dry-run
```

📝 Workshop-Style Input Example
```bash
Type: Necklace Heart
Size: 10mm
Color: GOLD, SILVER, ROSE
Length: 14", 16", 18", 20"
Quantity: 1 heart, 2 heart, 3 heart
Price:
1 heart - $39
2 heart - $52
3 heart - $62
```

The engine automatically:

Detects variation structure

Maps DB codes

Generates SKU segments

Applies pricing rules

Builds full variation matrix

## 🏷 SKU Structure

SKU segments are generated according to active profile:

Example :

[type][length][color][qty][size][start][space]


Fully DB-backed and deterministic.

## 🔐 Safety

Dry-run prevents accidental Etsy overwrite

readiness_state_id auto-detected from listing

DB operations logged before execution

Controlled via WRITE_ENABLED flag

## 📌 Supported Profiles
shiny

Legacy profile with desc2-heavy mapping.

silveristic

Code-desc structured DB model optimized for structured SKU production.

## 📜 License

MIT License

## 💡 Future Direction

This project may evolve into a commercial-grade inventory orchestration platform
for high-variation handmade brands.

## 👤 Author

Recep Yalcin