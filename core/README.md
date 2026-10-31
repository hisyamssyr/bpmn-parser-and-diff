# Core BPMN Parser dan Diff

Implementasi `core/bpmn_parser.py` dan `core/bpmn_diff.py`.
Keduanya deterministik, tidak memakai LLM, dan tidak mengakses jaringan.

Skema keluaran saat ini **1.1**. Perubahan dari 1.0 bersifat penambahan:
`event_detail`, `loop_detail`, `triggered_by_event`, warning berlevel,
kategori `participants`, dan ringkasan diff yang lebih kaya.

## Instalasi

Python 3.10+.

```bash
pip install -r requirements.txt
```

## API

```python
from core.bpmn_parser import BpmnParseError, parse_bpmn, parse_bpmn_string
from core.bpmn_diff import (
    diff_files,
    diff_models,
    get_context,
    get_element,
)
```

- `parse_bpmn(path, strict=False)` membaca file `str`/`Path` dan mengembalikan
  model pada bagian berikut.
- `parse_bpmn_string(xml_text, strict=False)` membaca isi XML; `source_file`
  bernilai `""`.
- `diff_models(old, new, strict=False)` membandingkan dua model.
- `diff_files(old_path, new_path, strict=False)` mem-parse kedua file lalu
  membandingkannya.
- `get_element(model, element_id)` mencari node, flow, lane, proses, atau
  participant berdasarkan ID. Mengembalikan `None` bila tidak ada.
- `get_context(model, element_id, index=None)` mengembalikan flow masuk/keluar
  sebuah node beserta node di seberang, diurutkan menurut ID flow. Parameter
  `index` opsional dipakai `diff_models` agar pemindaian flow tidak kuadratik.

Semua fungsi tidak mengubah argumen dan tidak memakai state global. Mode
`strict=True` hanya mengubah warning berlevel `warning` menjadi
`BpmnParseError`; warning `info` tidak memblokir.

## Model Parser

Kunci utama: `schema_version`, `source_file`, `processes`, `participants`,
`lanes`, `nodes`, `flows`, `warnings`.

- `nodes` dan `flows` berupa objek ber-ID.
- `lanes` berupa objek ber-ID; `parent_lane` menunjuk lane induk.
- Node memiliki `lane` (nama lane terdalam), `lane_id`, dan `lane_path`
  (terluar ke terdalam). Bila node terdaftar di lane luar dan lane turunannya,
  lane terdalam dipakai tanpa warning. `MULTI_LANE` hanya muncul untuk lane
  yang tidak berhubungan.
- `parent` menunjuk proses atau container pemilik. Container yang dibaca:
  `subProcess`, `adHocSubProcess`, dan `transaction`.
- Field khusus: `default_flow`, `gateway_direction` (`Unspecified` dan atribut
  kosong sama-sama menjadi `""`), `event_definition`, `event_detail`, `loop`,
  `loop_detail`, `called_element`, `attached_to`, `cancel_activity`
  (`boundaryEvent` tanpa atribut dianggap `"true"`), dan `triggered_by_event`.
- `event_detail` berisi pasangan `kunci=nilai` terpisah `"; "` untuk detail
  timer (`timeDate`, `timeDuration`, `timeCycle`), message/signal/error/
  escalation (ID rujukan dan nama dari definisi), serta kondisi conditional.
- `loop_detail` berisi `loopCardinality`, `completionCondition`,
  `loopMaximum`, `loopCondition`, dan `testBefore` bila ada.
- Semua teks dinormalisasi NFC dan spasinya dirapikan. ID tetap
  case-sensitive dan tidak dinormalisasi.
- Bagian DI, `incoming`/`outgoing`, elemen visual (`textAnnotation`,
  `association`, `group`, `category*`), dan ekstensi vendor diabaikan.
- `source_file` diserialisasi dengan pemisah `/` agar keluaran lintas-platform.

Kode warning: `MISSING_ID`, `MISSING_ENDPOINT`, `DANGLING_REF`,
`MULTI_LANE`, `UNKNOWN_ELEMENT`, `UNPARSED_CHILDREN`.
Setiap warning berbentuk `{code, message, element_id, level}` dengan `level`
`info` atau `warning`.

Parser memakai `defusedxml`, menolak DTD/entitas, dan menolak file di atas
20 MB.

## Hasil Diff

Kunci utama: `schema_version`, `old_file`, `new_file`, `summary`, `nodes`,
`flows`, `lanes`, `processes`, `participants`, `warnings`.

- Pencocokan elemen hanya berdasarkan ID persis.
- `changed` node memuat `id`, `kinds`, `fields`, dan `context`.
- `changed` flow memuat `id`, `kinds`, `fields`, `endpoints`, dan
  `endpoints_old`.
- `context` berisi `incoming`/`outgoing`; `endpoints` berisi ringkasan node
  sumber dan tujuan (`id`, `type`, `name`).
- Lane, proses, dan participant yang berubah memuat `id`, `kinds`, dan
  `fields`. Participant dibandingkan pada kategori `participants` dengan field
  `name` (label `renamed`) dan `process_ref` (label `reparented`).
- `summary.identical` bernilai `true` hanya bila seluruh kategori kosong.
- `summary.possible_renames` hanya petunjuk: nama harus tidak kosong, kunci
  `(type, name, lane_id)` harus cocok, dan pasangan harus unik di kedua sisi.
- `summary.kinds` adalah histogram label perubahan; `summary.touched_node_ids`
  memuat node yang berubah atau menjadi ujung flow yang berubah;
  `summary.warnings` adalah jumlah warning.
- `warnings` memuat warning kedua model dengan `side` `old`/`new`. Warning
  diff memakai `side` `diff`, termasuk `NO_OVERLAPPING_IDS` dan
  `SCHEMA_MISMATCH`.
- Semua daftar diurutkan berdasarkan ID, sehingga urutan XML dan hash seed
  Python tidak memengaruhi hasil.

## CLI

```bash
python -m core.bpmn_diff OLD.bpmn NEW.bpmn
python -m core.bpmn_diff OLD.bpmn NEW.bpmn --md
python -m core.bpmn_diff OLD.bpmn NEW.bpmn --strict
python -m core.bpmn_parser FILE.bpmn [FILE2.bpmn ...] --types
```

- Hasil diff selalu disimpan ke `output/<timestamp>.json` atau
  `output/<timestamp>.md`; stdout hanya menampilkan path file.
- Keluaran JSON memakai UTF-8 dan `ensure_ascii=False`.
- `--md` memilih format Markdown; `--json` memilih JSON (default).
- `--debug` mencetak traceback penuh untuk error tak terduga.
- `--version` mencetak versi skema.
- `--types` menambahkan hitungan node per jenis pada ringkasan parser.
- Kode keluar: `0` sukses, `2` file gagal dibaca/di-parse atau pelanggaran
  `strict`, `1` error lain.

## Konvensi Kode

- Identifier, kode warning, nama label `kinds`, dan pesan error berbahasa
  Inggris; dokumentasi berbahasa Indonesia.
- Fungsi publik murni. I/O hanya di `parse_bpmn`, `diff_files`, dan `main`.
- Semua keluaran berurutan tetap: daftar terurut menurut ID, `kinds` terurut.
- Kode warning, level, label, dan versi skema berada di `core/constants.py`.
  Bentuk data didokumentasikan sebagai `TypedDict` di `core/schema.py`.
