# Core BPMN Parser, Diff, dan LLM View

Implementasi `core/bpmn_parser.py`, `core/bpmn_diff.py`, dan
`core/llm_view.py`. Semuanya deterministik, tidak memakai LLM, dan tidak
mengakses jaringan.

Skema keluaran saat ini **1.1**. Perubahan dari 1.0 bersifat penambahan:
`event_detail`, `loop_detail`, `triggered_by_event`, warning berlevel,
kategori `participants`, dan ringkasan diff yang lebih kaya.

## Instalasi

Python 3.10+.

```bash
pip install -r requirements.txt
```

Untuk menjalankan tes:

```bash
pip install -r requirements-dev.txt
pytest
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
from core.llm_view import (
    ViewError,
    build_prompt_block,
    build_view,
    describe_view,
    estimate_tokens,
    render_view,
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
- `build_view(diff, level="standard", ...)` mengubah diff menjadi tampilan
  ringkas. Tingkat yang tersedia: `summary`, `lean`, `standard`, dan `full`.
  `models=(old, new)` opsional memperkaya nama node berubah dan nama lane.
- `render_view(view, fmt="json", pretty=False)` merender tampilan; `fmt`
  mendukung `json` dan `text`.
- `build_prompt_block(...)` mengembalikan legenda + tampilan di dalam pembatas
  `<bpmn_change>...</bpmn_change>`, dengan teks BPMN diperlakukan sebagai data.
- `describe_view(view, text)` dan `estimate_tokens(text)` menyediakan statistik
  ukuran untuk pencatatan biaya.
- `ViewError` menandai level, opsi, skema, atau bentuk diff yang tidak valid.

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

## LLM View

`core/llm_view.py` menyajikan hasil diff untuk konsumsi LLM tanpa mengubah isi
diff. Semua kunci dan daftar berurutan tetap.

- Tingkat `summary` berisi header, `counts`, `kinds`, warning, dan
  `touched_nodes`; `lean` menambahkan perubahan tanpa tetangga; `standard`
  menambahkan `in`/`out` dan `was`/`now`; `full` menambahkan field node yang
  tidak kosong.
- Nama node tambah/hapus dan endpoint flow diambil dari diff. Nama node
  berubah dan nama lane memerlukan `models=(old, new)`.
- `include`/`exclude` menyaring bagian `changes`; `filtered` mencatat bagian
  yang disaring. `max_chars` menurunkan tingkat dan mencatat `degraded_from`;
  pemotongan selalu ditandai di `truncated`.
- Teks dikontrol karakternya, dipotong sesuai `max_string_len`, dan di-escape
  di dalam blok prompt. `VIEW_LEGEND` menyatakan bahwa teks BPMN adalah data.
- `view_version` saat ini `1.0`, terpisah dari `schema_version` diff.
- `possible_renames` hanya muncul sebagai `hints` pada `standard`/`full`.

## CLI

`core.bpmn_parser` tidak memiliki CLI; modul itu hanya menyediakan API untuk
`core.bpmn_diff` dan pemakai library.

```bash
python -m core.bpmn_diff p2p_test_old.bpmn p2p_test_new.bpmn --json
python -m core.bpmn_diff p2p_test_old.bpmn p2p_test_new.bpmn --md
python -m core.bpmn_diff p2p_test_old.bpmn p2p_test_new.bpmn --json --strict
python -m core.llm_view --diff output/diff/<timestamp>.json --level summary
python -m core.llm_view --diff output/diff/<timestamp>.json --prompt --stats
```

- File lama diletakkan di `bpmn/old/` dan file baru di `bpmn/new/`. CLI hanya
  menerima nama file lengkap; path folder sudah di-hardcode. Kedua nama file
  pada diff wajib diberikan.
- Hasil diff selalu disimpan ke `output/diff/<timestamp>.json` atau
  `output/diff/<timestamp>.md`; stdout hanya menampilkan path file.
- Keluaran JSON memakai UTF-8 dan `ensure_ascii=False`.
- `--md` memilih format Markdown; `--json` memilih JSON. Salah satunya wajib
  diberikan.
- `--debug` mencetak traceback penuh untuk error tak terduga.
- `--version` mencetak versi skema.
- `core.llm_view` hanya menerima `--diff`, yaitu hasil `bpmn_diff` yang sudah
  tersimpan; ia tidak menjalankan parser/diff sendiri. Opsi lain: `--level`,
  `--include`, `--exclude`, `--max-chars`, `--max-string-len`, `--pretty`,
  `--text`, `--prompt`, `--stats`, dan `--out`.
- Hasil selalu disimpan ke file. Tanpa `--out`, file dibuat di
  `output/view/<timestamp>.<ext>`; dengan `--out`, path itu dipakai sebagai basis.
  Ekstensi mengikuti format: `.json` (default), `.txt` (`--text`), atau `.md`
  (`--prompt`); ekstensi lama diganti. Stdout hanya menampilkan path file.
- Kode keluar: `0` sukses, `2` file gagal dibaca/di-parse, JSON rusak,
  `ViewError`, atau pelanggaran `strict`, `1` error lain.

## Konvensi Kode

- Identifier, kode warning, nama label `kinds`, dan pesan error berbahasa
  Inggris; dokumentasi berbahasa Indonesia.
- Fungsi publik murni. I/O hanya di `parse_bpmn`, `diff_files`, dan `main`.
- Semua keluaran berurutan tetap: daftar terurut menurut ID, `kinds` terurut.
- Kode warning, level, label, dan versi skema berada di `core/constants.py`.
  Bentuk data didokumentasikan sebagai `TypedDict` di `core/schema.py`.
