# Receiptly

A self-hosted PWA + FastAPI backend for issuing receipts. Business details are configured at runtime via the admin UI.

---

## Features

- Mobile-friendly PWA to create receipts
- Auto-generated PDF with your business details
- Banana Buchhaltung import export (quarterly `.txt` per quarter)
- Admin UI to manage your price list and business settings
- Quarterly ZIP download

---

## Project structure

```
receiptly/
├── app/
│   └── main.py          # FastAPI backend
├── static/
│   ├── index.html       # PWA (create receipt)
│   └── admin.html       # Admin (price list + settings + overview)
├── setup.sh             # One-time setup for Alpine LXC
├── requirements.txt     # Python dependencies
└── README.md
```

**Runtime data** (not in repo, lives on the server under `/data/`):
```
/data/
├── config.json          # Business details (name, address, email — edit via admin)
├── items.json           # Price list (edit via admin)
├── travel.json          # Travel cost €/km
├── counter.json         # Receipt number counter per year
└── 2026/
    └── Q2/
        ├── Receipt_2026-001_John-Doe.pdf
        └── Import_2026_Q2.txt
```

---

## Development

### Prerequisites

- Python 3.11+

### Quick start

```bash
git clone https://github.com/your-username/receiptly.git
cd receiptly
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
DATA_DIR=./data uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000` (PWA) and `http://localhost:8000/admin.html` (admin).  
Runtime data is written to `./data/` (gitignored).

### VS Code

A launch configuration is included. Select the `.venv` interpreter (`Ctrl+Shift+P` → *Python: Select Interpreter*), then press `F5`.

---

## Setup

### 1. Create an LXC container (Proxmox example)

| Field    | Value                        |
|----------|------------------------------|
| Template | alpine-3.20-default          |
| Disk     | 1 GB                         |
| RAM      | 512 MB                       |
| Network  | Fixed IP, e.g. `192.168.1.40`|

### 2. Run the setup script

```bash
pct enter <CT-ID>
sh /root/setup.sh
```

### 3. Upload files

```bash
scp -r app   root@<IP>:/app/
scp -r static root@<IP>:/app/
```

### 4. Start services

```bash
rc-service nginx start
rc-service receiptly start
```

### 5. Optional: reverse proxy + SSL

Point a domain at the container IP, terminate TLS with your preferred proxy (nginx Proxy Manager, Caddy, Traefik, …).

### 6. Configure your business details

Open `http://<IP>/admin.html`, expand **Settings**, fill in your name, address, email, and save. These are stored in `/data/config.json` and used on every generated PDF.

---

## API endpoints

| Method   | Path                              | Description                   |
|----------|-----------------------------------|-------------------------------|
| `POST`   | `/api/receipt`                    | Create receipt (PDF + CSV)    |
| `GET`    | `/api/receipts`                   | List all receipts             |
| `GET`    | `/api/receipt/{year}/{q}/{file}`  | Fetch PDF                     |
| `GET`    | `/api/download/{year}/{q}`        | Download quarterly ZIP        |
| `GET`    | `/api/items`                      | Get price list                |
| `PUT`    | `/api/items`                      | Save price list               |
| `GET`    | `/api/travel`                     | Get travel rate               |
| `PUT`    | `/api/travel`                     | Save travel rate              |
| `GET`    | `/api/config`                     | Get business config           |
| `PUT`    | `/api/config`                     | Save business config          |

---

## Banana import format

The `.txt` files per quarter are importable directly into Banana Buchhaltung (UTF-8 BOM, semicolon-separated):

```
Date;Doc;Description;Income;Expenses;Account;Category;Notes
2026-05-03;2026-001;John Doe | Consultation 60 min;80,00;;1600;4401;Receipt 2026-001 · Cash
```

---

## Reset / delete test data

```bash
rm -rf /data/*

# Reset counter only
echo '{}' > /data/counter.json
```

---

## License

See [LICENSE](LICENSE).
