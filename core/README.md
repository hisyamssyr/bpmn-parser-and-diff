# Core BPMN Parser dan Diff

Implementasi `core/bpmn_parser.py` dan `core/bpmn_diff.py` sesuai PRD.
Keduanya deterministik, tidak memakai LLM, dan tidak mengakses jaringan.

## Instalasi

Python 3.10+.

```bash
pip install -r requirements.txt
```

## API

```python
from core.bpmn_parser import BpmnParseError, parse_bpmn, parse_bpmn_string
from core.bpmn_diff import (
    diff_dirs,
    diff_files,
    diff_models,
    get_context,
    get_element,
)
```

- `parse_bpmn(path, strict=False)` membaca file `str`/`Path` dan mengembalikan
  model PRD 7.1.
- `parse_bpmn_string(xml_text, strict=False)` membaca isi XML; `source_file`
  bernilai `""`.
- `diff_models(old, new, strict=False)` membandingkan dua model.
- `diff_files(old_path, new_path, strict=False)` mem-parse kedua file lalu
  membandingkannya.
- `get_element(model, element_id)` mencari node, flow, lane, proses, atau
  participant berdasarkan ID. Mengembalikan `None` bila tidak ada.
- `get_context(model, element_id)` mengembalikan flow masuk/keluar sebuah node
  beserta node di seberang, diurutkan menurut ID flow.
- `diff_dirs(old_dir, new_dir)` memasangkan `*.bpmn` berdasarkan nama file
  (tidak rekursif). Perpindahan elemen antar-file tidak dilacak; elemen
  tersebut muncul sebagai `removed`/`added` pada pasangan masing-masing.

Semua fungsi tidak mengubah argumen dan tidak memakai state global. Mode
`strict=True` mengubah setiap warning parser maupun diff menjadi
`BpmnParseError`.

## Model Parser (PRD 7.1)

Kunci utama: `schema_version`, `source_file`, `processes`, `participants`,
`lanes`, `nodes`, `flows`, `warnings`.

- `nodes` dan `flows` berupa objek ber-ID.
- `lanes` berupa objek ber-ID; `parent_lane` menunjuk lane induk.
- Node memiliki `lane` (nama lane terdalam), `lane_id`, dan `lane_path`
  (terluar ke terdalam).
- `parent` menunjuk proses atau subProcess pemilik. `process` menunjuk proses
  teratas.
- Field khusus: `default_flow`, `gateway_direction`, `event_definition`,
  `loop`, `called_element`, `attached_to`, `cancel_activity`.
- Semua teks dinormalisasi NFC dan spasinya dirapikan. ID tetap
  case-sensitive dan tidak dinormalisasi.
- Bagian DI, `incoming`/`outgoing`, dan ekstensi vendor diabaikan.

Kode warning: `MISSING_ID`, `MISSING_ENDPOINT`, `DANGLING_REF`,
`MULTI_LANE`, `UNKNOWN_ELEMENT`.

Parser memakai `defusedxml`, menolak DTD/entitas, dan menolak file di atas
20 MB.

## Hasil Diff (PRD 7.2)

Kunci utama: `schema_version`, `old_file`, `new_file`, `summary`, `nodes`,
`flows`, `lanes`, `processes`, `warnings`.

- Pencocokan elemen hanya berdasarkan ID persis.
- `changed` node memuat `id`, `kinds`, `fields`, dan `context`.
- `changed` flow memuat `id`, `kinds`, `fields`, `endpoints`, dan
  `endpoints_old`.
- `context` berisi `incoming`/`outgoing`; `endpoints` berisi ringkasan node
  sumber dan tujuan (`id`, `type`, `name`).
- Lane dan proses yang berubah memuat `id`, `kinds`, dan `fields`.
- Participant dibandingkan pada kategori `processes` (field `name`), karena
  skema 7.2 tidak memiliki kategori participant terpisah.
- `summary.identical` bernilai `true` hanya bila seluruh kategori kosong.
- `summary.possible_renames` hanya petunjuk; daftar utama tidak berubah.
- `warnings` memuat warning kedua model dengan `side` `old`/`new`. Warning
  diff memakai `side` `diff`, termasuk `NO_OVERLAPPING_IDS`.
- Semua daftar diurutkan berdasarkan ID, sehingga urutan XML dan hash seed
  Python tidak memengaruhi hasil.

`diff_dirs` mengembalikan:

```json
{
  "schema_version": "1.0",
  "old_dir": "...",
  "new_dir": "...",
  "files": {"added": [], "removed": [], "changed": []}
}
```

`files.added`/`files.removed` berisi nama file. `files.changed` berisi hasil
diff lengkap untuk file bernama sama yang tidak identik.

## CLI

```bash
python -m core.bpmn_diff OLD.bpmn NEW.bpmn
python -m core.bpmn_diff OLD.bpmn NEW.bpmn --md
python -m core.bpmn_diff OLD.bpmn NEW.bpmn --strict --out hasil.json
python -m core.bpmn_parser FILE.bpmn [FILE2.bpmn ...]
```

- Keluaran JSON memakai UTF-8 dan `ensure_ascii=False`.
- `--md` menghasilkan ringkasan Markdown.
- `--out` menulis hasil ke file, bukan stdout.
- Kode keluar: `0` sukses, `2` file gagal dibaca/di-parse atau pelanggaran
  `strict`, `1` error lain.

## Uji Asap Simple-ERP

Salinan 6 file asli berada di `tests/fixtures/simple_erp/`. Semua ter-parse
tanpa warning: 9 proses, 9 participant, 12 lane, 104 node, dan 120 flow.
Elemen yang muncul: `task`, `userTask`, `serviceTask`, `callActivity`,
`startEvent`, `endEvent`, `exclusiveGateway`, `sequenceFlow`, `messageFlow`,
`participant`, `lane`, `laneSet`, `conditionExpression`, serta
`incoming`/`outgoing` yang diabaikan. Tidak ditemukan `boundaryEvent`,
`dataObject`, `textAnnotation`, lane bersarang, atau ekstensi vendor.
`callActivity` di l0 merujuk proses di file lain melalui `calledElement`;
referensi lintas-file disimpan apa adanya dan tidak di-resolve.

## Pengujian

```bash
python -m pytest
```

Fixture pasangan `*_old.bpmn` dan `*_new.bpmn` berada di `tests/fixtures/`.
Contoh keluaran S00 ada di `examples/s00_diff.json`. Fixture S00 diambil dari
`docs/bpmn/l1-core-processes.bpmn` pada commit `f5a556b` dan induknya.

```bash
python -m core.bpmn_diff tests/fixtures/s00_old.bpmn \
  tests/fixtures/s00_new.bpmn --out examples/s00_diff.json
```
