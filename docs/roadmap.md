# Roadmap (Checklist)

## Phase 1: Foundation
- [x] Buat struktur folder `app/` sesuai target arsitektur
- [x] Pindahkan config ke `app/config.py`
- [x] Refactor `app.py` menjadi app factory + blueprints
- [x] Tambahkan repository layer untuk query DB
- [x] Pisahkan layanan email ke `services/`

## Phase 2: Performance & Stability
- [x] Tambah index DB sesuai query dashboard
- [x] Kurangi polling dashboard (interval lebih panjang / websocket)
- [x] Hilangkan side-effect email dari endpoint polling
- [x] Tambah cache untuk KPI dashboard

## Phase 3: Async & Scale
- [x] Implement background worker (inline + optional RQ/Redis)
- [x] Jadikan email job async
- [x] Monitoring untuk queue latency

## Phase 4: Data Model Cleanup
- [x] Rework kunci unik user berbasis email
- [x] Audit foreign key dan orphan data (script audit)
- [x] Dokumentasi migrasi data

## Phase 5: Product Hardening
- [x] Logging terstruktur + request tracing
- [x] Health check + metrics endpoint
- [x] Unit test untuk service utama
- [x] Integration test untuk flow talangan
- [x] Unifikasi login: satu form, redirect berdasar credential (admin vs pegawai)
- [x] Hapus/redirect legacy admin login page + update templates & links
- [x] Tambah pengujian untuk flow login terpadu (admin dan pegawai)

## Phase 6: UX & Reporting
- [x] Dashboard analytics (trend & cohort)
- [ ] Scheduled report export
- [ ] Role-based access (Admin/HR/User)
