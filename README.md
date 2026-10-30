# BPMN Parser dan Diff

Alat Python untuk membaca file BPMN 2.0 lalu membandingkan dua versi diagram proses bisnis. Proyek ini merupakan komponen **Code Change Planning from BPMN Changes** (Kelompok 7, Enterprise Systems, ITS).

## Tujuan

- **Parser** mengubah satu file `.bpmn` menjadi model data ringkas berisi proses, participant, lane, node, flow, dan warning berlevel (`info`/`warning`).
- **Diff** membandingkan model lama dan baru, lalu menghasilkan daftar perubahan terstruktur: node/flow ditambah, dihapus, atau berubah (`retyped`, `renamed`, `lane_moved`, `event_detail_changed`, `loop_detail_changed`, `rewired_source`, dan seterusnya), termasuk perubahan lane, proses, dan participant.
- Hasil diff dipakai sebagai input bersama oleh setup eksperimen A/B/C, pembuat skenario, dan evaluator, sehingga harus **deterministik, dapat diulang, dan berversi** (`schema_version` saat ini `1.1`).
- Tidak memakai LLM, tidak mengakses jaringan, dan mengabaikan tata letak diagram (bagian DI).

Detail kontrak keluaran dan perilaku tiap fungsi dijelaskan di [`core/README.md`](core/README.md).

## Struktur Proyek

```
core/               # implementasi parser dan diff
  bpmn_parser.py    # parser BPMN -> model
  bpmn_diff.py      # diff dua model + CLI
  constants.py      # kode warning, level, label kinds, versi skema
  schema.py         # TypedDict untuk bentuk model dan hasil diff
  _cli.py           # helper bersama (UTF-8, path POSIX)
bpmn/               # contoh file BPMN (old/new)
```

## Prasyarat

- Python 3.10 atau lebih baru
- Dependensi: `defusedxml` (lihat `requirements.txt`)

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

Keluaran berupa ringkasan JSON (jumlah proses, participant, lane, node, flow, dan warning). Opsi parser:

| Opsi | Keterangan |
|---|---|
| `--strict` | Menganggap warning berlevel `warning` sebagai error; `info` tidak memblokir |
| `--types` | Menambahkan hitungan node per jenis BPMN |
| `--debug` | Mencetak traceback untuk error tak terduga |
| `--version` | Mencetak versi skema keluaran |

### 3. Bandingkan dua versi BPMN

```bash
python -m core.bpmn_diff bpmn/old/p2p_test_old.bpmn bpmn/new/p2p_test_new.bpmn
```

Opsi yang tersedia:

| Opsi | Keterangan |
|---|---|
| `--md` | Menampilkan ringkasan Markdown, bukan JSON |
| `--strict` | Menganggap warning berlevel `warning` sebagai error; `info` tidak memblokir |
| `--out FILE` | Menulis hasil ke file, bukan stdout |
| `--dir OLD_DIR NEW_DIR` | Membandingkan direktori, bukan dua file |
| `--recursive` | Menelusuri subfolder bersama `--dir` |
| `--debug` | Mencetak traceback untuk error tak terduga |
| `--version` | Mencetak versi skema keluaran |

Contoh:

```bash
python -m core.bpmn_diff bpmn/old/p2p_test_old.bpmn \
  bpmn/new/p2p_test_new.bpmn --md --out p2p_diff.md

python -m core.bpmn_diff --dir bpmn/old bpmn/new --recursive
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

## Format Keluaran

Diff mengembalikan dict JSON dengan kunci `schema_version`, `old_file`, `new_file`, `summary`, `nodes`, `flows`, `lanes`, `processes`, `participants`, dan `warnings`. Participant dipisahkan dari proses; `summary` juga memuat histogram `kinds`, daftar `touched_node_ids`, dan jumlah `warnings`. Semua daftar diurutkan berdasarkan ID agar hasil stabil terhadap urutan XML.

Setiap warning memuat `level` (`info` atau `warning`). Parser menandai elemen data/definisi sebagai `info`, sedangkan kehilangan data atau referensi yang tidak konsisten sebagai `warning`.
