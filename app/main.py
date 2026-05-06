from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import List
from pathlib import Path
from datetime import date
import json, csv, zipfile, io, os, math, shutil

# ── ReportLab for PDF ────────────────────────────────────────────────────────
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as rl_canvas

app = FastAPI(title="Receiptly API")

DATA_DIR   = Path(os.environ.get("DATA_DIR", "/data"))
STATIC_DIR = Path(os.environ.get("STATIC_DIR", Path(__file__).parent.parent / "static"))

COUNTER_FILE  = DATA_DIR / "counter.json"
ITEMS_FILE    = DATA_DIR / "items.json"
TRAVEL_FILE   = DATA_DIR / "travel.json"
CONFIG_FILE   = DATA_DIR / "config.json"
ACCOUNTS_FILE = DATA_DIR / "accounts.json"
BRAND_FILE    = DATA_DIR / "brand.json"

DEFAULT_BRAND = {
    "header":    "#3a2e22",
    "text":      "#3a2e22",
    "highlight": "#d4c4a0",
    "surface":   "#f5f0e8",
}

DEFAULT_ACCOUNTS = [
    {"code": "4401", "label": "Main Services"},
    {"code": "4410", "label": "Venue / Rental"},
    {"code": "4420", "label": "Other Services"},
    {"code": "4830", "label": "Ancillary Revenue"},
]

DEFAULT_CONFIG = {
    "owner_name":    "Jane Doe",
    "business_name": "My Business",
    "address":       "123 Main St  ·  12345 My City",
    "city":          "My City",
    "email":         "info@example.com",
    "tax_note":      "VAT not applicable (small business regulation).",
    "language":      "en",
}

# To add a language: add an entry here matching a /static/i18n/<code>.json file.
PDF_STRINGS: dict[str, dict] = {
    "en": {
        "title":           "RECEIPT",
        "receipt_no":      "No.",
        "receipt_for":     "RECEIPT FOR",
        "confirmation":    "I hereby confirm receipt of the following amount.",
        "col_service":     "SERVICE",
        "col_qty":         "QTY",
        "col_unit":        "UNIT",
        "col_total":       "TOTAL",
        "amount_received": "AMOUNT RECEIVED",
        "payment_label":   "Payment:",
        "proof":           "This receipt serves as proof of payment.",
        "footer_label":    "Receipt",
        "cash":            "Cash",
        "bank_transfer":   "Bank Transfer",
    },
    "de": {
        "title":           "QUITTUNG",
        "receipt_no":      "Nr.",
        "receipt_for":     "QUITTUNG FÜR",
        "confirmation":    "Hiermit bestätige ich den Erhalt des nachfolgend aufgeführten Betrags.",
        "col_service":     "LEISTUNG",
        "col_qty":         "ANZ.",
        "col_unit":        "EINZEL",
        "col_total":       "GESAMT",
        "amount_received": "BETRAG ERHALTEN",
        "payment_label":   "Zahlungsart:",
        "proof":           "Diese Quittung dient als Zahlungsbeleg.",
        "footer_label":    "Quittung",
        "cash":            "Barzahlung",
        "bank_transfer":   "Überweisung",
    },
}

DEFAULT_ITEMS = [
    {"name": "Consultation 60 min",  "price": 80.00,  "active": True, "account": "4401"},
    {"name": "Consultation 90 min",  "price": 110.00, "active": True, "account": "4401"},
    {"name": "Workshop (half day)",  "price": 200.00, "active": True, "account": "4401"},
    {"name": "Workshop (full day)",  "price": 350.00, "active": True, "account": "4401"},
    {"name": "Voucher",              "price": 80.00,  "active": True, "account": "4401"},
]
DEFAULT_TRAVEL_RATE = 0.41

# ── Accounts helpers ──────────────────────────────────────────────────────────
def load_accounts():
    if ACCOUNTS_FILE.exists():
        return json.loads(ACCOUNTS_FILE.read_text())
    return DEFAULT_ACCOUNTS

def save_accounts(accounts):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ACCOUNTS_FILE.write_text(json.dumps(accounts, ensure_ascii=False, indent=2))

# ── Brand helpers ─────────────────────────────────────────────────────────────
def load_brand() -> dict:
    if BRAND_FILE.exists():
        return {**DEFAULT_BRAND, **json.loads(BRAND_FILE.read_text())}
    return DEFAULT_BRAND.copy()

def save_brand(brand: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BRAND_FILE.write_text(json.dumps(brand, ensure_ascii=False, indent=2))

def hex_to_rgb(h: str) -> tuple:
    h = h.lstrip('#')
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)

def find_logo() -> "Path | None":
    for ext in ("png", "jpg", "jpeg"):
        p = DATA_DIR / f"logo.{ext}"
        if p.exists():
            return p
    return None

# ── Config helpers ────────────────────────────────────────────────────────────
def load_config() -> dict:
    if CONFIG_FILE.exists():
        return {**DEFAULT_CONFIG, **json.loads(CONFIG_FILE.read_text())}
    return DEFAULT_CONFIG.copy()

def save_config(cfg: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))

# ── Items helpers ─────────────────────────────────────────────────────────────
def load_items():
    if ITEMS_FILE.exists():
        return json.loads(ITEMS_FILE.read_text())
    return DEFAULT_ITEMS

def save_items(items):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ITEMS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2))

# ── Travel helpers ────────────────────────────────────────────────────────────
def load_travel_rate() -> float:
    if TRAVEL_FILE.exists():
        return json.loads(TRAVEL_FILE.read_text()).get("rate", DEFAULT_TRAVEL_RATE)
    return DEFAULT_TRAVEL_RATE

# ── Data models ───────────────────────────────────────────────────────────────
class LineItem(BaseModel):
    name: str
    price: float
    qty: float
    total: float
    account: str = "4401"

class Item(BaseModel):
    name: str
    price: float
    active: bool = True
    account: str = "4401"

class ReceiptRequest(BaseModel):
    date: str             # YYYY-MM-DD
    customer: str
    items: List[LineItem]
    payment_method: str   # Cash | Bank Transfer

class ReceiptResponse(BaseModel):
    receipt_nr: str
    pdf_url: str
    quarter: str

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_quarter(date_str: str) -> str:
    d = date.fromisoformat(date_str)
    q = math.ceil(d.month / 3)
    return f"{d.year}/Q{q}"

def get_next_number(date_str: str) -> str:
    d = date.fromisoformat(date_str)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = json.loads(COUNTER_FILE.read_text()) if COUNTER_FILE.exists() else {}
    year = str(d.year)
    data[year] = data.get(year, 0) + 1
    COUNTER_FILE.write_text(json.dumps(data))
    return f"{d.year}-{data[year]:03d}"

def quarter_dir(quarter: str) -> Path:
    p = DATA_DIR / quarter
    p.mkdir(parents=True, exist_ok=True)
    return p

def fmt_eur(val: float, language: str = "en") -> str:
    if language == "de":
        return f"{val:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{val:,.2f} €"

# ── PDF generation ────────────────────────────────────────────────────────────
def generate_pdf(path: Path, receipt_nr: str, date_str: str, customer: str,
                 line_items: List[LineItem], total: float, payment_method: str,
                 cfg: dict | None = None, brand: dict | None = None):
    if cfg is None:
        cfg = load_config()
    if brand is None:
        brand = load_brand()
    owner_name    = cfg.get("owner_name",    DEFAULT_CONFIG["owner_name"])
    business_name = cfg.get("business_name", DEFAULT_CONFIG["business_name"])
    address       = cfg.get("address",       DEFAULT_CONFIG["address"])
    city          = cfg.get("city",          DEFAULT_CONFIG["city"])
    email         = cfg.get("email",         DEFAULT_CONFIG["email"])
    tax_note      = cfg.get("tax_note",      DEFAULT_CONFIG["tax_note"])
    language      = cfg.get("language",      "en")
    s             = PDF_STRINGS.get(language, PDF_STRINGS["en"])
    payment_display = {"Cash": s["cash"], "Bank Transfer": s["bank_transfer"]}.get(payment_method, payment_method)

    d = date.fromisoformat(date_str)
    date_fmt = d.strftime("%Y-%m-%d")

    HEADER    = hex_to_rgb(brand.get("header",    DEFAULT_BRAND["header"]))
    TEXT      = hex_to_rgb(brand.get("text",      DEFAULT_BRAND["text"]))
    HIGHLIGHT = hex_to_rgb(brand.get("highlight", DEFAULT_BRAND["highlight"]))
    SURFACE   = hex_to_rgb(brand.get("surface",   DEFAULT_BRAND["surface"]))
    WHITE     = (1, 1, 1)

    def _lum(rgb): return 0.2126*rgb[0] + 0.7152*rgb[1] + 0.0722*rgb[2]
    # Text colours that sit on top of the header bar — auto-contrast
    ON_HEADER = SURFACE if _lum(HEADER) < 0.35 else TEXT

    W, H = A4
    ML = 56; MR = W - 56; TW = MR - ML

    c = rl_canvas.Canvas(str(path), pagesize=A4)

    def set_fill(rgb): c.setFillColorRGB(*rgb)
    def set_stroke(rgb): c.setStrokeColorRGB(*rgb)

    # Header bar
    set_fill(HEADER)
    c.rect(0, H - 110, W, 110, fill=1, stroke=0)

    # Logo (top-right of header, if present) — compute width first so text can avoid it
    logo_path = find_logo()
    logo_w = 0
    if logo_path:
        from reportlab.lib.utils import ImageReader
        img_reader = ImageReader(str(logo_path))
        iw, ih = img_reader.getSize()
        max_h, max_w = 80, 140
        scale = min(max_h / ih, max_w / iw)
        dw, dh = iw * scale, ih * scale
        logo_w = dw
        logo_x = MR - dw
        logo_y = H - 110 + (110 - dh) / 2
        c.drawImage(str(logo_path), logo_x, logo_y, width=dw, height=dh, mask='auto')

    text_right = MR - (logo_w + 10 if logo_w else 0)

    set_fill(ON_HEADER)
    c.setFont("Helvetica", 9)
    c.drawString(ML, H - 30, f"{owner_name.upper()} · {business_name.upper()}")
    c.setFont("Helvetica", 22)
    c.drawString(ML, H - 68, s["title"])

    set_fill(ON_HEADER)
    c.setFont("Helvetica", 9)
    c.drawRightString(text_right, H - 30, f"{s['receipt_no']} {receipt_nr}")
    c.drawRightString(text_right, H - 48, date_fmt)

    # Sender line
    y = H - 130
    set_fill(TEXT)
    c.setFont("Helvetica", 9)
    c.drawString(ML, y, f"{owner_name}  ·  {address}  ·  {email}")

    y -= 14
    set_stroke(HIGHLIGHT)
    c.setLineWidth(0.4)
    c.line(ML, y, MR, y)

    # Recipient
    y -= 16
    set_fill(TEXT)
    c.setFont("Helvetica", 8)
    c.drawString(ML, y, s["receipt_for"])
    y -= 14
    set_fill(TEXT)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(ML, y, customer)
    c.setFont("Helvetica", 10)

    # Confirmation text
    y -= 20
    set_fill(SURFACE)
    c.roundRect(ML, y - 8, TW, 24, 4, fill=1, stroke=0)
    set_fill(TEXT)
    c.setFont("Helvetica", 10)
    c.drawString(ML + 10, y + 2, s["confirmation"])

    # Table header
    y -= 30
    set_fill(HEADER)
    c.rect(ML, y - 6, TW, 22, fill=1, stroke=0)
    set_fill(ON_HEADER)
    c.setFont("Helvetica", 8)
    c.drawString(ML + 6, y + 4, s["col_service"])
    c.drawRightString(ML + 240, y + 4, s["col_qty"])
    c.drawRightString(ML + 320, y + 4, s["col_unit"])
    c.drawRightString(MR - 4, y + 4, s["col_total"])

    # Line items
    y -= 6
    for i, item in enumerate(line_items):
        row_h = 24
        set_fill(SURFACE if i % 2 == 0 else WHITE)
        c.rect(ML, y - row_h + 6, TW, row_h, fill=1, stroke=0)
        set_fill(TEXT)
        c.setFont("Helvetica", 10)
        name = item.name
        while c.stringWidth(name, "Helvetica", 10) > 170 and len(name) > 5:
            name = name[:-1]
        if name != item.name:
            name += "…"
        c.drawString(ML + 6, y - 8, name)
        qty_str = str(int(item.qty)) if item.qty == int(item.qty) else f"{item.qty:.1f}"
        c.drawRightString(ML + 240, y - 8, qty_str)
        c.drawRightString(ML + 320, y - 8, fmt_eur(item.price, language))
        c.setFont("Helvetica-Bold", 10)
        c.drawRightString(MR - 4, y - 8, fmt_eur(item.total, language))
        set_stroke(HIGHLIGHT)
        c.setLineWidth(0.2)
        c.line(ML, y - row_h + 6, MR, y - row_h + 6)
        y -= row_h

    # Total box
    y -= 14
    set_fill(HEADER)
    c.roundRect(MR - 180, y - 12, 180, 36, 4, fill=1, stroke=0)
    set_fill(ON_HEADER)
    c.setFont("Helvetica", 8)
    c.drawString(MR - 172, y + 10, s["amount_received"])
    set_fill(ON_HEADER)
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(MR - 8, y - 4, fmt_eur(total, language))

    # Payment method
    y -= 44
    set_fill(SURFACE)
    c.roundRect(ML, y - 6, 130, 24, 3, fill=1, stroke=0)
    set_fill(TEXT)
    c.setFont("Helvetica", 8)
    c.drawString(ML + 6, y + 6, s["payment_label"])
    set_fill(TEXT)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(ML + 6, y - 4, payment_display)

    # Tax note
    y -= 30
    set_stroke(HIGHLIGHT)
    c.setLineWidth(0.3)
    c.line(ML, y, MR, y)
    y -= 12
    set_fill(TEXT)
    c.setFont("Helvetica", 8)
    c.drawString(ML, y, tax_note)
    y -= 10
    c.drawString(ML, y, s["proof"])

    # Signature
    y -= 40
    set_stroke(HEADER)
    c.setLineWidth(0.5)
    c.line(ML, y, ML + 160, y)
    y -= 10
    set_fill(TEXT)
    c.setFont("Helvetica", 8)
    c.drawString(ML, y, f"{owner_name}  ·  {city}, {date_fmt}")

    # Footer
    set_fill(HEADER)
    c.rect(0, 0, W, 38, fill=1, stroke=0)
    set_fill(ON_HEADER)
    c.setFont("Helvetica", 8)
    c.drawCentredString(W/2, 22, f"{owner_name}  ·  {address}")
    c.drawCentredString(W/2, 10, f"{s['footer_label']} {receipt_nr}")

    c.save()

# ── Accounting export (CSV) ───────────────────────────────────────────────────
def append_csv(qdir: Path, receipt_nr: str, date_str: str, customer: str,
               line_items: List[LineItem], total: float,
               payment_method: str, quarter: str):
    csv_path = qdir / f"Import_{quarter.replace('/', '_')}.txt"
    header = ["Date", "Doc", "Description", "Income", "Expenses", "Account", "Category", "Notes"]
    bank_account = "1600" if payment_method == "Cash" else "1800"

    from collections import defaultdict
    account_groups: dict = defaultdict(list)
    for item in line_items:
        account_groups[item.account or "4401"].append(item)

    write_header = not csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        if write_header:
            w.writerow(header)
        for account, items in account_groups.items():
            subtotal = sum(i.total for i in items)
            desc_parts = ", ".join(
                f"{i.name} ×{int(i.qty)}" if i.qty > 1 else i.name
                for i in items
            )
            income = f"{subtotal:.2f}".replace(".", ",")
            row = [date_str, receipt_nr, f"{customer} | {desc_parts}",
                   income, "", bank_account, account,
                   f"Receipt {receipt_nr} · {payment_method}"]
            w.writerow(row)

# ── API endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/receipt", response_model=ReceiptResponse)
def create_receipt(req: ReceiptRequest):
    quarter = get_quarter(req.date)
    receipt_nr = get_next_number(req.date)
    qdir = quarter_dir(quarter)
    total = sum(i.total for i in req.items)

    customer_slug = req.customer.replace(" ", "-").replace("/", "-")
    pdf_name = f"Receipt_{receipt_nr}_{customer_slug}.pdf"
    pdf_path = qdir / pdf_name

    generate_pdf(pdf_path, receipt_nr, req.date, req.customer,
                 req.items, total, req.payment_method, load_config(), load_brand())
    append_csv(qdir, receipt_nr, req.date, req.customer,
               req.items, total, req.payment_method, quarter)

    return ReceiptResponse(
        receipt_nr=receipt_nr,
        pdf_url=f"/api/receipt/{quarter}/{pdf_name}",
        quarter=quarter,
    )

@app.get("/api/receipt/{year}/{q}/{filename}")
def get_pdf(year: str, q: str, filename: str):
    path = DATA_DIR / year / q / filename
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(path, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{filename}"'})

@app.get("/api/receipts")
def list_receipts():
    result = []
    if not DATA_DIR.exists():
        return result
    for year_dir in sorted(DATA_DIR.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for q_dir in sorted(year_dir.iterdir()):
            if not q_dir.is_dir():
                continue
            quarter = f"{year_dir.name}/{q_dir.name}"
            for pdf in sorted(q_dir.glob("Receipt_*.pdf")):
                parts = pdf.stem.split("_", 2)
                result.append({
                    "quarter":  quarter,
                    "nr":       parts[1] if len(parts) > 1 else "?",
                    "customer": parts[2].replace("-", " ") if len(parts) > 2 else "?",
                    "pdf_url":  f"/api/receipt/{quarter}/{pdf.name}",
                    "filename": pdf.name,
                })
    return result

@app.get("/api/download/{year}/{q}")
def download_quarter_zip(year: str, q: str):
    qdir = DATA_DIR / year / q
    if not qdir.exists():
        raise HTTPException(404, "Quarter not found")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in qdir.iterdir():
            zf.write(f, f.name)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="Receipts_{year}_{q}.zip"'},
    )

@app.get("/api/counter")
def get_counter():
    if COUNTER_FILE.exists():
        return json.loads(COUNTER_FILE.read_text())
    return {}

@app.get("/api/travel")
def get_travel():
    return {"rate": load_travel_rate()}

@app.put("/api/travel")
def update_travel(body: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TRAVEL_FILE.write_text(json.dumps({"rate": float(body["rate"])}))
    return {"rate": float(body["rate"])}

@app.get("/api/items")
def get_items():
    return load_items()

@app.put("/api/items")
def update_items(items: List[Item]):
    save_items([i.dict() for i in items])
    return {"ok": True}

@app.put("/api/items/{idx}/price")
def update_price(idx: int, body: dict):
    items = load_items()
    if idx < 0 or idx >= len(items):
        raise HTTPException(404, "Item not found")
    items[idx]["price"] = float(body["price"])
    save_items(items)
    return items[idx]

@app.put("/api/items/{idx}/active")
def toggle_active(idx: int, body: dict):
    items = load_items()
    if idx < 0 or idx >= len(items):
        raise HTTPException(404, "Item not found")
    items[idx]["active"] = bool(body["active"])
    save_items(items)
    return items[idx]

@app.post("/api/items")
def add_item(item: Item):
    items = load_items()
    items.append(item.dict())
    save_items(items)
    return {"idx": len(items) - 1, **item.dict()}

@app.delete("/api/items/{idx}")
def delete_item(idx: int):
    items = load_items()
    if idx < 0 or idx >= len(items):
        raise HTTPException(404, "Item not found")
    items.pop(idx)
    save_items(items)
    return {"ok": True}

@app.get("/api/accounts")
def get_accounts():
    return load_accounts()

@app.put("/api/accounts")
def update_accounts(body: list):
    save_accounts(body)
    return {"ok": True}

@app.get("/api/config")
def get_config():
    return load_config()

@app.put("/api/config")
def update_config(body: dict):
    allowed = {"owner_name", "business_name", "address", "city", "email", "tax_note", "language"}
    cfg = load_config()
    for k, v in body.items():
        if k in allowed:
            cfg[k] = str(v)
    save_config(cfg)
    return cfg

@app.get("/api/brand")
def get_brand():
    return load_brand()

@app.put("/api/brand")
def update_brand(body: dict):
    allowed = {"header", "text", "highlight", "surface"}
    brand = load_brand()
    for k, v in body.items():
        if k in allowed and isinstance(v, str) and v.startswith('#') and len(v) == 7:
            brand[k] = v
    save_brand(brand)
    return brand

@app.get("/api/logo")
def get_logo():
    logo = find_logo()
    if not logo:
        raise HTTPException(404, "No logo uploaded")
    media_type = "image/png" if logo.suffix == ".png" else "image/jpeg"
    return FileResponse(logo, media_type=media_type)

@app.post("/api/logo")
async def upload_logo(file: UploadFile = File(...)):
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg"):
        raise HTTPException(400, "Only PNG/JPG files are allowed")
    for old_ext in ("png", "jpg", "jpeg"):
        old = DATA_DIR / f"logo.{old_ext}"
        if old.exists():
            old.unlink()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dest = DATA_DIR / f"logo.{ext}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"ok": True}

@app.delete("/api/logo")
def delete_logo():
    logo = find_logo()
    if logo:
        logo.unlink()
    return {"ok": True}

# ── Static files (PWA + Admin) ────────────────────────────────────────────────
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
