# Revisi: BPMN Parser dan BPMN Diff

**Berkas ditinjau:** `core/bpmn_parser.py` dan `core/bpmn_diff.py`
**Acuan:** `PRD_bpmn_parser_diff.md` (v0.3)
**Status dokumen:** sudah diimplementasikan pada skema 1.1; dokumen dipertahankan sebagai catatan revisi
**Skema keluaran:** `1.1` (sebelumnya `1.0`; lihat OR-01)

---

## 0. Cara memakai dokumen ini

- Tiap butir punya **ID** (PR = parser, DR = diff, OR = format keluaran, GS = gaya kode, TS = tes, Q = keputusan).
- Kolom **Bukti** menyatakan bagaimana temuan didapat:
  - **Diuji**: saya menjalankan kode asli dengan fixture kecil dan melihat hasilnya.
  - **Dibaca**: ditemukan dari membaca kode, **belum dijalankan**. Buat tesnya dulu sebelum menganggapnya bug.
- Prioritas: **P1** = perbaiki sekarang (salah hasil atau risiko data), **P2** = perbaiki sebelum eksperimen, **P3** = rapikan bila ada waktu.
- Kalau dipakai sebagai instruksi untuk AI coding agent: kerjakan per butir, tulis tes (bagian 6) **sebelum** mengubah kode, dan jangan mengubah hal di luar butir yang diminta.

## 1. Ringkasan

| ID | Judul | Berkas | Prioritas | Bukti |
|---|---|---|---|---|
| PR-01 | Node di lane bersarang memilih lane luar, bukan terdalam | parser | P1 | Diuji |
| PR-02 | Nilai bawaan BPMN menghasilkan perubahan palsu | parser | P1 | Diuji |
| DR-01 | Participant tercampur dengan proses; `process_ref` tidak dibandingkan | diff | P1 | Diuji |
| DR-02 | `possible_renames` menghasilkan petunjuk keliru | diff | P1 | Diuji |
| PR-03 | Container `adHocSubProcess` dan `transaction`: isinya hilang diam-diam | parser | P2 | Diuji |
| PR-04 | Warning tidak punya tingkat; elemen tidak berbahaya memblokir `--strict` | parser | P2 | Diuji |
| PR-05 | Detail event dan loop (durasi timer, kardinalitas, pesan) tidak dibandingkan | parser + diff | P2 | Diuji |
| DR-03 | `get_context` kuadratik pada diff besar | diff | P2 | Diuji |
| DR-04 | `diff_dirs` belum lengkap (CLI, strict, file identik, lintas-file) | diff | P2 | Dibaca |
| PR-06 | `subProcess` tanpa ID: anaknya ber-`parent` kosong | parser | P3 | Dibaca |
| PR-07 | `processRef` participant yang menggantung tidak dicek | parser | P3 | Dibaca |
| PR-08 | ID `laneSet`/`childLaneSet` tidak didaftarkan (duplikat lolos) | parser | P3 | Dibaca |
| PR-09 | `triggeredByEvent` (event sub-process) tidak dikenali | parser | P3 | Dibaca |
| DR-05 | `summary` kurang ringkas untuk konsumen (histogram `kinds`, daftar node tersentuh) | diff | P3 | Desain |
| DR-06 | Tidak ada peringatan bila `schema_version` kedua model berbeda | diff | P3 | Desain |
| OR-01 | Naikkan `schema_version` menjadi 1.1 dan kelola kompatibilitas | keduanya | P2 | Desain |
| OR-02 | Format Markdown (`--md`) lebih mudah dibaca | diff | P3 | Dibaca |
| OR-03 | Jalur file memuat pemisah OS (`\` vs `/`) | keduanya | P2 | Dibaca |
| OR-04 | Flag CLI tambahan | keduanya | P3 | Desain |
| GS-01 s.d. GS-10 | Gaya penulisan kode | keduanya | P3 | Dibaca |

Kerjakan dengan urutan: **P1 (PR-01, PR-02, DR-01, DR-02)** → uji asap pada 6 file asli Simple-ERP → **P2** → P3.

## 2. Yang sudah benar (jaga agar tidak regresi)

Perilaku berikut sudah diuji dan benar. Jadikan tes regresi.

| Perilaku | Dibuktikan oleh |
|---|---|
| Pasangan file uji: hasil sama dengan hasil harapan, `warnings` kosong | `p2p_test_old/new.bpmn` + `expected_diff.json` |
| Semua error menjadi `BpmnParseError` (ID duplikat, XML rusak, root bukan BPMN, string kosong, file tidak ada, path direktori) | uji error |
| DTD, entitas, dan *billion laughs* ditolak | `defusedxml` + `forbid_dtd` |
| UTF-8 BOM, UTF-16, ISO-8859-1 terbaca; prefix namespace berbeda menghasilkan model sama; NFC | uji encoding |
| `--strict` menaikkan warning menjadi error; kode keluar 2 untuk file tidak ada | uji CLI |
| `NO_OVERLAPPING_IDS` muncul untuk dua file tak berkaitan | uji diff |
| Referensi menggantung tidak membuat diff crash; model kosong tidak crash | uji diff |
| `condition_changed` terdeteksi | uji kontrol |

---

## 3. Revisi parser

### PR-01. Node di lane bersarang: pilih lane terdalam (P1, diuji)

**Masalah.** Kalau sebuah node terdaftar (`flowNodeRef`) di lane luar dan lane dalam sekaligus, parser memilih lane **luar** (yang terdaftar lebih dulu) dan mengeluarkan warning `MULTI_LANE`. PRD (FR-P7) meminta lane terdalam tanpa warning.

**Bukti.** `T1` terdaftar di `LA` (luar) dan `LB` (dalam) → hasil `lane_id = "LA"`, `lane_path = ["Luar"]`, warning `MULTI_LANE`.

**Perilaku yang diharapkan.**
- Bila satu lane adalah turunan lane lainnya, pakai yang **terdalam**, tanpa warning.
- Hanya bila dua lane **tidak** berhubungan (bukan leluhur), keluarkan `MULTI_LANE` dan pakai yang pertama (perilaku lama).

**Usulan perubahan** (di `_assign_lanes`, ganti cabang `elif current != lane_id`):

```python
elif current != lane_id:
    if self._is_ancestor(current, lane_id):
        assignments[node_id] = lane_id       # lane_id lebih dalam
    elif not self._is_ancestor(lane_id, current):
        self._warn("MULTI_LANE", ..., node_id)   # pesan lama

def _is_ancestor(self, ancestor: str, lane_id: str) -> bool:
    current = self.lanes.get(lane_id, {}).get("parent_lane", "")
    seen: set[str] = set()
    while current and current not in seen:
        if current == ancestor:
            return True
        seen.add(current)
        current = self.lanes.get(current, {}).get("parent_lane", "")
    return False
```

**Tes:** TS-01.

---

### PR-02. Nilai bawaan BPMN: normalisasi (P1, diuji)

**Masalah.** Atribut yang tidak ditulis dianggap berbeda dari nilai bawaannya yang ditulis eksplisit, padahal maknanya sama. Editor BPMN dapat menambahkan atribut eksplisit saat menyimpan ulang, sehingga muncul perubahan palsu.

**Bukti.** Versi lama tanpa atribut vs versi baru dengan `gatewayDirection="Unspecified"` dan `cancelActivity="true"` → muncul `gateway_direction_changed` dan `cancel_activity_changed`.

**Perilaku yang diharapkan.**

| Field | Nilai bawaan BPMN | Normalisasi di parser |
|---|---|---|
| `gateway_direction` | `Unspecified` | `""` dan `"Unspecified"` sama-sama disimpan sebagai `""` |
| `cancel_activity` (hanya `boundaryEvent`) | `true` | atribut kosong dan `"true"` sama-sama disimpan sebagai `"true"`; nilai dipaksa huruf kecil |
| `loop` (`isSequential`) | `false` | sudah benar (kosong dianggap paralel) |

**Usulan perubahan** (di `_parse_node`):

```python
gateway_direction = _normalize_text(element.get("gatewayDirection")) if local.endswith("Gateway") else ""
if gateway_direction == "Unspecified":
    gateway_direction = ""
cancel_activity = (_clean_ref(element.get("cancelActivity")).lower() or "true") if local == "boundaryEvent" else ""
```

Catat nilai bawaan lain yang dinormalisasi di README `core/`, supaya konsumen tahu `""` berarti "bawaan".

**Tes:** TS-02.

---

### PR-03. Container tak dikenal membuang isinya diam-diam (P2, diuji)

**Masalah.** `adHocSubProcess` dan `transaction` tidak ada di `NODE_TYPES`. Hanya wadahnya yang diberi warning `UNKNOWN_ELEMENT`; **seluruh node dan flow di dalamnya tidak terbaca dan tidak ada warning**.

**Bukti.** Task `DALAM` di dalam `adHocSubProcess` tidak muncul di `nodes`.

**Perilaku yang diharapkan.**
- `adHocSubProcess` dan `transaction` diperlakukan seperti `subProcess` (tercatat sebagai node dengan `type` aslinya, dan isinya dibaca rekursif dengan `parent` yang benar).
- Elemen tak dikenal lain yang **berisi** elemen alur (node atau flow di dalamnya) memunculkan warning `UNPARSED_CHILDREN` agar kehilangan isi tidak senyap.

**Usulan perubahan:**

```python
CONTAINER_TYPES = frozenset({"subProcess", "adHocSubProcess", "transaction"})
NODE_TYPES = NODE_TYPES | CONTAINER_TYPES

# _parse_flow_elements:
if local in NODE_TYPES:
    node_id = self._parse_node(child, process_id, parent_id)
    if local in CONTAINER_TYPES:
        self._parse_lane_sets(child, process_id)
        self._parse_flow_elements(child, process_id, node_id)
```

Selaraskan juga `NODE_TYPES` di PRD (FR-P4).

**Tes:** TS-03.

---

### PR-04. Tingkat keparahan warning (P2, diuji)

**Masalah.** `textAnnotation`, `dataObject`, dan `message` di tingkat atas semuanya menghasilkan `UNKNOWN_ELEMENT`. Dengan `--strict`, file yang memuat elemen yang tidak berarti bagi perencanaan kode akan ditolak. Di sisi lain, sebagian elemen yang tidak didukung memang perlu perhatian (lihat PR-03).

**Bukti.** Satu file berisi `message`, `textAnnotation`, `dataObject`, `adHocSubProcess` → empat warning setara.

**Perilaku yang diharapkan.** Tiap warning punya `level`:

| Kasus | Level | Alasan |
|---|---|---|
| `textAnnotation`, `association`, `group`, `category*` | diabaikan, tanpa warning | hanya catatan visual |
| `dataObject`, `dataObjectReference`, `dataStore*`, `property`, `ioSpecification` | `info` | data, belum dibandingkan |
| `message`, `signal`, `error`, `escalation`, `itemDefinition` di tingkat definitions | `info` (atau diresolusi, lihat PR-05) | definisi rujukan |
| Elemen berID yang tidak dikenal lainnya | `warning` | bisa berarti perubahan penting terlewat |
| `UNPARSED_CHILDREN`, `MULTI_LANE`, `DANGLING_REF`, `MISSING_ID`, `MISSING_ENDPOINT` | `warning` | data hilang atau tidak konsisten |

`--strict` hanya menaikkan warning ber-`level == "warning"` menjadi error. Level `info` tidak memblokir.

**Perubahan format** (OR-01): setiap objek warning mendapat field `level`.

**Tes:** TS-04.

---

### PR-05. Detail event dan loop (P2, diuji)

**Masalah.** `event_definition` hanya menyimpan jenis (`timer`, `message`) dan `loop` hanya jenisnya. Perubahan di dalamnya tidak terdeteksi.

**Bukti.**
- Timer `PT48H` menjadi `PT24H` → `identical: true`.
- `loopCardinality` 3 menjadi 10 → `identical: true`.

**Perilaku yang diharapkan.** Tambah dua field node (string, dapat kosong):

| Field | Isi | Label di diff |
|---|---|---|
| `event_detail` | pasangan `kunci=nilai` terurut, dipisah `"; "`. Timer: `timeDate`, `timeDuration`, `timeCycle`. Message/signal/error/escalation: ID rujukan, ditambah `name` bila ditemukan di definitions (misalnya `messageRef=M1; message=Pesan PO`). Conditional: teks kondisi. | `event_detail_changed` |
| `loop_detail` | `loopCardinality`, `completionCondition`, `loopMaximum`, `loopCondition`, `testBefore` bila ada | `loop_detail_changed` |

Contoh nilai: `"timeDuration=PT48H"`, `"loopCardinality=3"`.

Konsekuensi: `NODE_FIELDS` dan `NODE_KINDS` di diff bertambah dua entri; `schema_version` naik (OR-01).

> Ini keputusan lingkup: lihat Q-02. Minimal kerjakan timer dan loop, karena perubahan SLA dan kardinalitas paling mungkin memengaruhi kode.

**Tes:** TS-05, TS-06.

---

### PR-06. `subProcess` tanpa ID (P3, dibaca)

**Masalah.** Di `_parse_node`, node tanpa ID mengembalikan `""`. Untuk `subProcess` tanpa ID, anaknya diparse dengan `parent_id == ""`, jadi `parent` anak kosong dan struktur tidak jelas.

**Perilaku yang diharapkan.** Lewati seluruh isi container tanpa ID dan keluarkan warning `UNPARSED_CHILDREN` untuk container tersebut (konsisten dengan `MISSING_ID`).

**Tes:** TS-07 (buat tes dulu; pastikan memang bermasalah sebelum mengubah).

### PR-07. `processRef` participant menggantung (P3, dibaca)

`_check_dangling_references` tidak memeriksa participant. Tambahkan: bila `process_ref` ada tetapi tidak ada di `processes`, warning `DANGLING_REF` dengan `element_id` = ID participant. **Tes:** TS-08.

### PR-08. ID `laneSet`/`childLaneSet` (P3, dibaca)

Elemen ini punya `id` tetapi tidak didaftarkan lewat `_register_id`, jadi duplikat dengan elemen lain lolos. Daftarkan ID `laneSet` dan `childLaneSet` (jenis `"laneset"`). **Tes:** TS-09.

### PR-09. `triggeredByEvent` (P3, dibaca)

Event sub-process adalah `subProcess` dengan `triggeredByEvent="true"`, dan saat ini tampak sama dengan sub-process biasa. Tambah field node `triggered_by_event` (`""` atau `"true"`) dan label `triggered_by_event_changed`. Opsional; kerjakan hanya bila file asli memakainya (uji asap).

---

## 4. Revisi diff

### DR-01. Participant (P1, diuji)

**Masalah.** `_process_index` menggabungkan `participants` ke daftar proses dan hanya membandingkan `name`. Hasilnya:
- `PART-NTF2` muncul di `processes.added` dan ikut menaikkan hitungan proses;
- participant yang berpindah proses (`process_ref` berubah) dianggap `identical: true`.

**Bukti.** Participant `PART` dengan `process_ref` `P` menjadi `P2` → `summary.identical == True`.

**Perilaku yang diharapkan.** Kategori terpisah `participants`:
- field dibandingkan: `name`, `process_ref`;
- label: `name` → `renamed`, `process_ref` → `reparented`;
- `summary.participants` berisi hitungan `added`/`removed`/`changed`;
- `processes` hanya berisi proses sungguhan;
- `identical` ikut memperhitungkan `participants`.

**Usulan perubahan:**

```python
PARTICIPANT_FIELDS = ("name", "process_ref")
PARTICIPANT_KINDS = {"name": "renamed", "process_ref": "reparented"}

def _participant_index(model):
    return {p["id"]: p for p in model.get("participants") or [] if p.get("id")}

def _process_index(model):          # tanpa participant
    return {p["id"]: {"id": p["id"], "name": p.get("name", "")}
            for p in model.get("processes") or [] if p.get("id")}
```

Ubah juga `get_element` agar mencari participant di kategorinya (sudah mencari `"participants"`, cukup pastikan tidak bergantung pada penggabungan). Perbarui `expected_diff.json`/`expected_changes.md` (kategori participant 1 ditambah, proses 1 ditambah) dan PRD FR-D7.

**Tes:** TS-10.

---

### DR-02. `possible_renames` yang lebih ketat (P1, diuji)

**Masalah.**
1. Elemen **tanpa nama** dianggap cocok. Start/end event tanpa nama itu umum, jadi `SUB-START` (hilang) dan `OTHER-START` (baru) dilaporkan sebagai rename.
2. Bila ada beberapa kandidat identik, pasangan dipilih urut abjad, bukan berdasarkan bukti.

**Bukti.** Kedua kasus diuji dan menghasilkan petunjuk yang tidak berdasar.

**Perilaku yang diharapkan.** Laporkan sebuah pasangan **hanya jika**:
- `name` tidak kosong, dan
- kunci `(type, name, lane_id)` cocok persis, dan
- pasangan itu **unik di kedua sisi** (tepat satu elemen dihapus dan satu ditambah dengan kunci itu).

Selain itu tidak melaporkan apa pun (lebih baik tanpa petunjuk daripada petunjuk menyesatkan). Hasil diurutkan menurut `removed`.

**Usulan perubahan:**

```python
from collections import defaultdict

def _possible_renames(old_nodes, new_nodes, removed_ids, added_ids):
    def key(n):
        return (n.get("type"), n.get("name"), n.get("lane_id"))
    removed, added = defaultdict(list), defaultdict(list)
    for i in removed_ids:
        if old_nodes[i].get("name"):
            removed[key(old_nodes[i])].append(i)
    for i in added_ids:
        if new_nodes[i].get("name"):
            added[key(new_nodes[i])].append(i)
    return [
        {"removed": rs[0], "added": added[k][0], "basis": ["type", "name", "lane"]}
        for k, rs in sorted(removed.items(), key=lambda kv: kv[1][0])
        if len(rs) == 1 and len(added.get(k, [])) == 1
    ]
```

**Tes:** TS-11.

---

### DR-03. Konteks dengan indeks (P2, diuji)

**Masalah.** `get_context` mengurutkan dan memindai semua flow untuk **setiap** node, sehingga waktu tumbuh kuadratik. Pada 5.000 node dan 5.000 flow, diff dengan semua node berubah memakan sekitar 3,8 detik (batas PRD 5 detik). Diff biasa yang kecil tidak terpengaruh (identik: 0,03 detik).

**Perilaku yang diharapkan.** Bangun peta `incoming` dan `outgoing` sekali per model, lalu pakai untuk semua konteks. Hasil harus **persis sama** dengan sebelumnya (urutan tetap berdasarkan ID flow).

**Usulan perubahan:**

```python
def _build_flow_index(model):
    incoming, outgoing = defaultdict(list), defaultdict(list)
    flows = model.get("flows") or {}
    for flow_id in sorted(flows):
        flow = flows[flow_id]
        outgoing[flow.get("source", "")].append(flow_id)
        incoming[flow.get("target", "")].append(flow_id)
    return incoming, outgoing
```

`get_context(model, element_id, index=None)` tetap menjadi API publik; parameter `index` opsional dipakai oleh `diff_models`. Tambah tes kinerja (TS-12) dengan ambang 2 detik pada ukuran yang sama.

---

### DR-04. `diff_dirs` (P2, dibaca)

**Kekurangan saat ini.**
- Tidak ada di CLI.
- Tidak menerima `strict`.
- File yang identik tidak dicatat, jadi jumlah file tidak berubah tidak diketahui.
- Hanya `*.bpmn` di tingkat atas (tidak rekursif).
- Elemen yang berpindah antar-file tidak terlihat (keterbatasan di PRD 6.7).

**Perilaku yang diharapkan.**
- Parameter `strict` diteruskan ke `diff_files`.
- Keluaran `files` menambah `unchanged: <jumlah>` dan `identical_names` (opsional) selain `added`, `removed`, `changed`.
- CLI: `python -m core.bpmn_diff --dir OLD_DIR NEW_DIR`.
- Pencarian rekursif opsional (`--recursive`); kunci pasangan memakai jalur relatif (dengan `/`), bukan hanya nama berkas.
- **Opsional (Q-05):** laporkan `moved_between_files`: ID elemen yang `removed` di satu berkas dan `added` di berkas lain pada pasangan direktori yang sama.

**Tes:** TS-13.

---

### DR-05. `summary` yang lebih berguna (P3, desain)

Tambah di `summary` (tanpa mengubah field yang ada):

```json
"participants": {"added": 1, "removed": 0, "changed": 0},
"kinds": {"lane_moved": 3, "rewired_target": 3, "renamed": 4},
"touched_node_ids": ["BE-TIMEOUT", "CALL-NOTIF", "..."],
"warnings": 0
```

- `kinds`: histogram semua label (node, flow, lane, proses, participant), kunci terurut.
- `touched_node_ids`: ID semua node yang ditambah, dihapus, atau berubah, **ditambah** node yang menjadi ujung flow yang ditambah/dihapus/berubah. Berguna untuk evaluator (pembanding dengan ground truth) dan sebagai daftar awal untuk agen.
- `warnings`: jumlah warning (bukan isi).

### DR-06. Versi skema berbeda (P3, desain)

Bila `schema_version` kedua model berbeda, tambah warning `SCHEMA_MISMATCH` (`side: "diff"`, level `warning`). Mencegah perbandingan diam-diam antara dua model dengan bentuk berbeda.

---

## 5. Revisi format keluaran dan CLI

### OR-01. Skema 1.1

Perubahan dari 1.0 ke 1.1 (semuanya **penambahan**; field lama tidak berubah arti):

| Lokasi | Perubahan |
|---|---|
| model → node | tambah `event_detail`, `loop_detail`, (opsional) `triggered_by_event` |
| model → warning | tambah `level` (`"warning"` atau `"info"`) |
| diff → keluaran | tambah kategori `participants`; `processes` tidak lagi memuat participant |
| diff → `summary` | tambah `participants`, `kinds`, `touched_node_ids`, `warnings` |
| diff → label `kinds` | tambah `event_detail_changed`, `loop_detail_changed`, (opsional) `triggered_by_event_changed` |

**Aturan kompatibilitas.**
- Naikkan `SCHEMA_VERSION` ke `"1.1"` di parser (diff mengambilnya dari sana).
- **Umumkan ke kelompok** sebelum menggabungkan: pembuat `llm_view.py` dan evaluator bergantung pada bentuk ini.
- Perbarui `expected_diff.json`, `expected_changes.md`, dan PRD (7.1, 7.2, 7.3, FR-D7).
- Konsumen yang membaca field lama tetap berfungsi; hanya konsumen yang mengandalkan participant di `processes` yang perlu diubah.

Contoh bentuk baru:

```json
{
  "id": "EVT-WAIT",
  "kinds": ["event_definition_changed", "event_detail_changed"],
  "fields": {
    "event_definition": {"old": "message", "new": "timer"},
    "event_detail": {"old": "message=Invoice diterima", "new": "timeDuration=PT48H"}
  }
}
```

```json
"warnings": [
  {"side": "new", "code": "UNKNOWN_ELEMENT", "level": "info",
   "message": "BPMN element 'dataObject' with ID 'DO' is not supported", "element_id": "DO"}
]
```

### OR-02. Format Markdown (`--md`)

| Sekarang | Usulan |
|---|---|
| Baris flow hanya ID: `- FLOW-P2P-004 (sequence) PUR-PR-003 -> GW-P2P-APPROVED` | Pakai nama: `- FLOW-P2P-004: Review purchase request (PUR-PR-003) → Request approved? (GW-P2P-APPROVED)` |
| Participant dilabeli "Processes" | Bagian `Participants` terpisah (mengikuti DR-01) |
| Tidak ada penjelasan label | Di bawah ringkasan, tampilkan histogram `kinds` (DR-05) |
| Warning tanpa level | Tampilkan `[old/new/diff] [level] KODE (ID): pesan` |
| Tidak menampilkan konteks | Biarkan tanpa konteks (Markdown untuk dibaca cepat; konteks tersedia di JSON) |

Bahasa label Markdown tetap Inggris (konsisten dengan kode); lihat Q-07.

### OR-03. Jalur file di keluaran

**Masalah (dibaca).** `source_file` dan `old_file`/`new_file` berisi jalur seperti yang diberikan. Di Windows jalur memakai `\`, sehingga hasil berbeda byte per byte dari Linux/macOS (melanggar syarat deterministik di PRD bagian 10), dan jalur absolut membuat berkas contoh bergantung mesin.

**Perilaku yang diharapkan.**
- Simpan `Path(path).as_posix()` (pemisah selalu `/`).
- Dokumentasikan bahwa tes dan berkas contoh dijalankan dari **root repo dengan jalur relatif**.
- Tes golden-file membandingkan setelah memastikan jalur relatif.

### OR-04. Flag CLI

| Flag | Berkas | Fungsi |
|---|---|---|
| `--dir` | diff | mode direktori (DR-04) |
| `--recursive` | diff | telusuri subfolder bersama `--dir` |
| `--debug` | keduanya | cetak traceback penuh pada error tak terduga (kode keluar 1) |
| `--version` | keduanya | cetak versi skema |
| `--types` | parser | ringkasan jumlah node per jenis (sesuai contoh di PRD) |

Cantumkan arti kode keluar (0, 1, 2) di `--help` (epilog).

---

## 6. Gaya penulisan kode

Hal yang **sudah baik** dan dipertahankan: type hints dengan `from __future__ import annotations`, konstanta di atas berkas, fungsi pembantu privat kecil, `pathlib`, pesan error yang menyebut path dan sebab, penanganan `OSError` terpisah dari XML.

| ID | Temuan | Usulan |
|---|---|---|
| GS-01 | Tidak ada docstring di fungsi publik (PRD bagian 10 mewajibkannya) | Tambah docstring singkat (satu paragraf: tujuan, argumen, kembalian, error) di `parse_bpmn`, `parse_bpmn_string`, `diff_models`, `diff_files`, `diff_dirs`, `get_element`, `get_context` |
| GS-02 | `_force_utf8` ditulis dua kali (parser dan diff) | Pindah ke `core/_cli.py` dan impor di keduanya |
| GS-03 | `NODE_FIELDS` dan `NODE_KINDS` (juga flow/lane/proses) harus disinkronkan manual | Satu sumber: `NODE_FIELDS = tuple(NODE_KINDS)` |
| GS-04 | Kode warning dan label `kinds` berupa string tersebar | Konstanta bersama di `core/constants.py`, dipakai parser, diff, dan `llm_view` |
| GS-05 | Model berupa `dict` tak berjenis | `TypedDict` (`NodeDict`, `FlowDict`, `ParsedModel`, `DiffResult`) di `core/schema.py` (sesuai rencana struktur); tidak mengubah bentuk JSON |
| GS-06 | `diff_models` sekitar 150 baris | Pecah: `_diff_nodes`, `_diff_flows`, `_diff_lanes`, `_diff_processes`, `_diff_participants`, `_build_summary` |
| GS-07 | `except Exception` lebar di `parse_bpmn`/`main` dapat menyembunyikan bug | Persempit ke `ParseError`, `DefusedXmlException`, `ValueError`, `UnicodeError` untuk XML; biarkan lainnya naik dan dicetak lewat `--debug` |
| GS-08 | Sebagian baris lebih dari 88 karakter (mis. argumen `--out` di diff) | Pasang formatter dan linter (`ruff format`, `ruff check`) lewat `pyproject.toml`; jalankan di CI atau pra-komit |
| GS-09 | Tidak ada `__all__` | Tentukan API publik di tiap modul agar anggota kelompok tahu apa yang boleh dipanggil |
| GS-10 | Pembuat parser argumen berada di dalam `main()` | Pisah `build_arg_parser()` agar mudah diuji |

Tambahan konvensi yang perlu ditulis di README `core/`:
- Kode, identifier, dan pesan error berbahasa **Inggris**; dokumentasi berbahasa Indonesia (Q-07).
- Fungsi publik **murni** (tanpa efek samping, tanpa membaca environment variable); I/O hanya di `parse_bpmn`, `diff_files`, `diff_dirs`, dan `main`.
- Semua keluaran berurutan tetap (daftar terurut menurut ID, `kinds` terurut).

---

## 7. Rencana tes

Letakkan di `tests/`. Fixture XML sebaris di bawah memakai pembungkus `P(...)` = `<process id="P">...</process>` di dalam `definitions` BPMN (sama seperti uji saya).

| Tes | Isi fixture | Pernyataan |
|---|---|---|
| **TS-01** | node `T1` terdaftar di lane `LA` (luar) dan `LB` (dalam, `childLaneSet`) | `lane_id == "LB"`, `lane_path == ["Luar","Dalam"]`, tanpa `MULTI_LANE`. Kasus kedua: dua lane yang tidak berhubungan → tetap `MULTI_LANE` dan lane pertama |
| **TS-02** | lama: gateway tanpa `gatewayDirection`, boundary tanpa `cancelActivity`; baru: `Unspecified` dan `true` | `summary.identical == True`. Kontrol: ubah ke `Diverging` dan `false` → terdeteksi |
| **TS-03** | `adHocSubProcess` berisi `task` | task terbaca dengan `parent` = ID container; tipe container tercatat. `transaction` sama |
| **TS-04** | file dengan `textAnnotation`, `dataObject`, `message`, dan satu elemen berID tak dikenal | `textAnnotation` tanpa warning; `dataObject` dan `message` ber-`level: "info"`; elemen asing ber-`level: "warning"`. `strict=True` hanya gagal untuk yang terakhir |
| **TS-05** | timer `PT48H` vs `PT24H` | `event_detail_changed`, `identical == False`; sama persis → tanpa perubahan |
| **TS-06** | `loopCardinality` 3 vs 10; standard loop dengan `loopMaximum` berbeda | `loop_detail_changed` |
| **TS-07** | `subProcess` tanpa `id` berisi task | tidak ada node dengan `parent == ""`; warning `UNPARSED_CHILDREN` |
| **TS-08** | participant dengan `processRef` ke proses yang tidak ada | warning `DANGLING_REF` |
| **TS-09** | `laneSet` ber-ID sama dengan sebuah task | `BpmnParseError` ID duplikat |
| **TS-10** | participant pindah `process_ref`; participant ditambah | `participants.changed` dengan `reparented`; `processes` tidak berubah; `identical == False` |
| **TS-11** | (a) dua start event tanpa nama, satu dihapus dan satu ditambah; (b) dua kandidat identik bernama; (c) satu pasangan bernama unik | (a) dan (b) → `possible_renames == []`; (c) → satu pasangan |
| **TS-12** | 5.000 node dan 5.000 flow, semua node diganti nama | selesai di bawah 2 detik; hasil sama persis dengan implementasi tanpa indeks |
| **TS-13** | dua direktori dengan file ditambah, dihapus, identik, dan berubah | `files.unchanged` benar; CLI `--dir` berjalan; `strict` diteruskan |
| **TS-14** | pasangan `p2p_test_old/new.bpmn` | cocok dengan `expected_diff.json` (setelah diperbarui untuk DR-01) |
| **TS-15** | jalankan diff dengan jalur memakai `\` | `old_file`/`new_file` memakai `/` (OR-03) |
| **TS-16** | dua model berbeda `schema_version` | warning `SCHEMA_MISMATCH` (DR-06) |

Tes regresi (bagian 2) tetap dijalankan di setiap perubahan.

## 8. Urutan pengerjaan

1. **Tulis tes dulu** untuk P1 (TS-01, TS-02, TS-10, TS-11); pastikan gagal pada kode saat ini (kecuali bagian kontrolnya).
2. **P1:** PR-01, PR-02, DR-01, DR-02. Jalankan seluruh tes.
3. **Uji asap pada 6 file asli Simple-ERP**; catat semua warning. Hasilnya menentukan seberapa penting PR-03, PR-04, PR-05, dan PR-09.
4. **P2:** PR-03, PR-04, PR-05 (sesuai keputusan Q-02), DR-03, DR-04, OR-01, OR-03.
5. Umumkan skema 1.1 ke kelompok; perbarui `expected_diff.json`, PRD, dan contoh keluaran S00.
6. **P3** dan gaya kode (GS) bila waktu tersisa; pasang formatter paling awal agar diff kode berikutnya bersih.

## 9. Keputusan yang masih terbuka

| ID | Pertanyaan | Saran |
|---|---|---|
| Q-01 | Participant dipisah sebagai kategori sendiri atau tetap digabung dengan proses? | Dipisah (DR-01) |
| Q-02 | Seberapa jauh detail event/loop dibaca? | Minimal timer dan loop (PR-05); tambah pesan/sinyal/error bila uji asap menunjukkan dipakai |
| Q-03 | `adHocSubProcess` dan `transaction` diperlakukan seperti `subProcess` atau hanya diberi warning? | Seperti `subProcess` (PR-03) |
| Q-04 | Kapan skema 1.1 digabung, dan siapa yang diberi tahu? | Setelah P1 selesai dan uji asap; beri tahu pembuat `llm_view.py` dan evaluator |
| Q-05 | Perlu melaporkan elemen yang pindah antar-file di `diff_dirs`? | Tunda; periksa dulu apakah Simple-ERP punya hierarki L1/L2 lintas-file |
| Q-06 | Penamaan tingkat warning: `warning`/`info` cukup? | Cukup; hindari `error` karena error sudah berupa exception |
| Q-07 | Bahasa pesan dan label di kode | Inggris untuk kode dan keluaran alat; Indonesia untuk dokumentasi |

## 10. Batasan yang tetap (bukan bug)

- Perbandingan dilakukan **per pasangan file**; perpindahan elemen antar-file tidak dilacak (PRD 6.7).
- ID yang berganti dilaporkan sebagai hapus + tambah; `possible_renames` hanya petunjuk.
- Ekstensi vendor (Camunda/Bizagi), koordinat diagram, dan urutan elemen di XML sengaja diabaikan.
- Teks `documentation` dibandingkan setelah normalisasi spasi; perbedaan hanya di huruf besar/kecil dianggap perubahan.
