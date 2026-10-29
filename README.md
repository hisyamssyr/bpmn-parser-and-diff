# BPMN Parser dan Diff

Alat Python untuk membaca file BPMN 2.0 lalu membandingkan dua versi diagram proses bisnis. Proyek ini merupakan komponen **Code Change Planning from BPMN Changes** (Kelompok 7, Enterprise Systems, ITS).

## Tujuan

- **Parser** mengubah satu file `.bpmn` menjadi model data ringkas berisi proses, participant, lane, node, flow, dan warning.
- **Diff** membandingkan model lama dan baru, lalu menghasilkan daftar perubahan terstruktur: node/flow ditambah, dihapus, atau berubah (`retyped`, `renamed`, `lane_moved`, `rewired_source`, dan seterusnya), termasuk perubahan lane dan proses.
- Hasil diff dipakai sebagai input bersama oleh setup eksperimen A/B/C, pembuat skenario, dan evaluator, sehingga harus **deterministik, dapat diulang, dan berversi** (`schema_version`).
- Tidak memakai LLM, tidak mengakses jaringan, dan mengabaikan tata letak diagram (bagian DI).

Detail kontrak keluaran dan perilaku tiap fungsi dijelaskan di [`core/README.md`](core/README.md) dan [`PRD_bpmn_parser_diff.md`](PRD_bpmn_parser_diff.md).

## Struktur Proyek

```
core/               # implementasi parser dan diff
  bpmn_parser.py    # parser BPMN -> model
  bpmn_diff.py      # diff dua model + CLI
tests/              # unit test dan fixture BPMN
  fixtures/         # pasangan *_old.bpmn / *_new.bpmn
bpmn/               # contoh file BPMN (old/new)
examples/           # contoh keluaran diff (JSON)
output/             # hasil diff yang di-generate (tidak di-commit)
```

## Prasyarat

- Python 3.10 atau lebih baru
- Dependensi: `defusedxml`, `pytest` (lihat `requirements.txt`)

## Cara Menjalankan

### 1. Siapkan lingkungan virtual

```bash
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### 2. Parse satu atau beberapa file BPMN

```bash
python -m core.bpmn_parser bpmn/new/p2p_test_new.bpmn
```

Keluaran berupa ringkasan JSON (jumlah proses, participant, lane, node, flow, dan warning).

### 3. Bandingkan dua versi BPMN

```bash
python -m core.bpmn_diff bpmn/old/p2p_test_old.bpmn bpmn/new/p2p_test_new.bpmn
```

Opsi yang tersedia:

| Opsi | Keterangan |
|---|---|
| `--md` | Menampilkan ringkasan Markdown, bukan JSON |
| `--strict` | Menganggap semua warning sebagai error |
| `--out FILE` | Menulis hasil ke file, bukan stdout |

Contoh:

```bash
python -m core.bpmn_diff bpmn/old/p2p_test_old.bpmn \
  bpmn/new/p2p_test_new.bpmn --md --out output/p2p_diff.md
```

Kode keluar: `0` sukses, `2` file gagal dibaca/di-parse atau pelanggaran `--strict`, `1` error lain.

### 4. Pakai sebagai library

```python
from core.bpmn_parser import parse_bpmn
from core.bpmn_diff import diff_files, get_context

old = parse_bpmn("bpmn/old/p2p_test_old.bpmn")
new = parse_bpmn("bpmn/new/p2p_test_new.bpmn")
result = diff_files("bpmn/old/p2p_test_old.bpmn", "bpmn/new/p2p_test_new.bpmn")

ctx = get_context(new, "TASK-ID")
```

### 5. Jalankan pengujian

```bash
python -m pytest
```

## Format Keluaran

Diff mengembalikan dict JSON dengan kunci `schema_version`, `old_file`, `new_file`, `summary`, `nodes`, `flows`, `lanes`, `processes`, dan `warnings`. Semua daftar diurutkan berdasarkan ID agar hasil stabil terhadap urutan XML. Contoh keluaran ada di `examples/s00_diff.json`.
