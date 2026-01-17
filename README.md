# Gajiku

Aplikasi talangan gaji berbasis Flask + SQLite. Fokus proyek ini adalah perapihan arsitektur agar scalable, mudah dirawat, dan siap dioperasikan secara profesional.

## Goals
- Backend modular (routes, services, repositories, models terpisah)
- Performa stabil (job async, query terindeks, caching)
- Kualitas produksi (observability, testing, keamanan)

## Quickstart
```powershell
# venv opsional
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
python app.py
```

Aplikasi berjalan di `http://localhost:5001`.

## Proposed Structure (Target)
```
app/
  __init__.py
  config.py
  routes/
  services/
  repositories/
  models/
  tasks/
  utils/
static/
templates/
```

## Conventions
- Pisahkan logic bisnis ke `services/` dan query DB ke `repositories/`.
- Route hanya mengatur input/output dan delegasi ke service.
- Background job untuk email, export, dan proses berat.

## Pajak (PPN)
- Admin fee dikenakan PPN 11% untuk semua produk (REG dan URG).
- Untuk URG, PPN dihitung dari total admin fee (gabungan REG+URG), lalu ditambahkan.

## Testing
- Minimal: unit test untuk service utama.
- Lanjut: integration test untuk route kritikal.

## Docs
- `architecture.md`: rancangan arsitektur target
- `roadmap.md`: checklist pekerjaan menuju level pro

## Update Terbaru
- Standardisasi label tombol "setting" pada dashboard admin dan pegawai.
- Ikon menu settings sekarang dirender via CSS (burger icon) agar konsisten lintas font.
- Label tombol logout dashboard pegawai disederhanakan menjadi "LogOut".
