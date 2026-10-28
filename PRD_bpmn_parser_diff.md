# PRD: BPMN Parser dan BPMN Diff

**Proyek:** Code Change Planning from BPMN Changes (Kelompok 7, Enterprise Systems, ITS)
**Komponen:** `core/bpmn_parser.py` dan `core/bpmn_diff.py`
**Versi dokumen:** 0.2 (draft, setelah pemeriksaan kelengkapan)
**Pemilik:** Hisyam (parser dan diff). Pengguna hasilnya: seluruh anggota kelompok.

Penanda status: **[ASUMSI]** = dugaan belum diverifikasi, **[TERBUKA]** = pertanyaan yang perlu dijawab (ke kelompok atau Mas Abim), **[TERVERIFIKASI]** = sudah dicek dari repo.

### Perubahan dari v0.1
Pemeriksaan menemukan celah berikut, semuanya sudah ditambahkan:
- **Perubahan lane dan proses belum dibahas.** Lane diganti nama membuat semua node di dalamnya terlihat "pindah lane" secara keliru. Kini lane dan proses punya bagian diff sendiri, dan node dibandingkan lewat `lane_id`.
- **Atribut penting yang terlewat:** jenis event (timer, message, dan lainnya), arah gateway, loop/multi-instance, `attachedToRef` pada boundary event, `calledElement` pada callActivity.
- **Format keluaran tidak konsisten:** konteks tetangga hanya didefinisikan untuk node, padahal flow juga perlu. Ditambah `endpoints` untuk flow.
- **Tidak ada `schema_version`**, padahal risiko menyebut "naikkan versi skema".
- **Kasus tepi baru:** file tidak berkaitan, lane bersarang, urutan XML berbeda, BOM/encoding, path Windows, ekstensi vendor, referensi menggantung, ID case-sensitive, perpindahan antar-file, serangan entity-expansion.
- **Keamanan XML:** `ElementTree` bawaan rentan terhadap entity-expansion. Kini memakai `defusedxml`.
- **Kompatibilitas Windows** (encoding keluaran, path) ditambahkan.
- **Mode `--strict`**, `parse_bpmn_string`, struktur `warnings` terstruktur, dan batas ukuran file.

---

## 1. Ringkasan

Dua program Python **deterministik** (tanpa LLM, tanpa jaringan):

1. **BPMN Parser** membaca satu file `.bpmn` (BPMN 2.0 XML) dan mengubahnya menjadi model data ringkas: proses, lane, node, dan flow.
2. **BPMN Diff** membandingkan dua model (versi lama dan baru) lalu menghasilkan daftar perubahan terstruktur.

Hasil diff menjadi **input bersama** untuk ketiga setup eksperimen (A: single tanpa RAG, B: single + RAG, C: multi-agent + RAG), pembuat skenario, dan evaluator. Karena itu hasilnya harus **pasti, bisa diulang, dan terdokumentasi**. Perbedaan hasil antar setup tidak boleh berasal dari diff yang berubah-ubah.

## 2. Tujuan dan non-tujuan

### Tujuan
- T1. Membaca 6 file BPMN asli Simple-ERP tanpa error dan tanpa kehilangan node, flow, atau lane.
- T2. Mendeteksi dan mengklasifikasi perubahan proses secara akurat dan dapat diulang.
- T3. Menyediakan format keluaran stabil dan berversi sebagai kontrak dengan komponen lain.
- T4. Mudah dibungkus menjadi tool MCP atau function calling tanpa mengubah logika inti.

### Non-tujuan
- Menggunakan AI/LLM dalam bentuk apa pun.
- Memvalidasi kebenaran BPMN terhadap standar (cukup membaca dengan toleran).
- Membandingkan tata letak diagram (bagian DI diabaikan).
- Menebak elemen yang ID-nya berganti (hanya memberi petunjuk, lihat 6.5).
- Memetakan perubahan ke kode (tugas agen dan RAG).
- Melacak elemen yang berpindah antar-file BPMN (lihat 6.7).
- Antarmuka MCP/server (tahap berikutnya, bungkus tipis di atas modul ini).

## 3. Pengguna dan konsumen

| Konsumen | Memakai apa | Kebutuhan |
|---|---|---|
| Setup A, B, C (agen) | Diff + detail elemen | Format tetap, ringkas, tidak ambigu |
| Server/tool MCP atau function calling | Fungsi publik | Fungsi murni, mudah dibungkus, keluaran dict JSON |
| Pembuat skenario | Parser | Membuktikan BPMN hasil patch masih terbaca |
| Evaluator | Diff | Daftar elemen berubah sebagai pembanding ground truth |
| Anggota kelompok | CLI | Menjalankan diff dari terminal (Windows maupun Linux/macOS) |

## 4. Konteks data

- Format: BPMN 2.0 XML, namespace model `http://www.omg.org/spec/BPMN/20100524/MODEL`.
- Simple-ERP memiliki 6 file BPMN di `docs/bpmn` (39 task level-2 dan 22 aksi; **[TERVERIFIKASI]** dari analisis repo sebelumnya).
- ID elemen mengikuti konvensi semantik, contoh `PUR-PR-001`. Flow memakai konvensi `FLOW-P2P-008A` dengan akhiran huruf untuk percabangan. Diff mencocokkan elemen **berdasarkan ID**, jadi konvensi ini yang membuat diff bersih.
- Lane ditentukan lewat `flowNodeRef` di dalam `lane`.
- Contoh perubahan nyata: commit `f5a556b` mengubah `subProcess` menjadi `task` (skenario S00).
- **[ASUMSI]** Prefix namespace bisa berbeda antar file (`bpmn:`, `bpmn2:`, tanpa prefix), jadi pencocokan memakai **URI namespace**.
- **[TERBUKA]** Apakah file asli memuat `collaboration`/`participant`/`messageFlow`, `boundaryEvent`, `callActivity`, `dataObject`, `textAnnotation`, lane bersarang, atau ekstensi vendor? Dijawab oleh uji asap (T5).
- **[TERBUKA]** Apakah ada hubungan lintas-file (misalnya `callActivity` yang merujuk proses di file lain, atau hierarki L1 ke L2 yang terpisah file)? Menentukan apakah 6.7 perlu diperluas.

## 5. Persyaratan fungsional: Parser

| ID | Persyaratan |
|---|---|
| FR-P1 | `parse_bpmn(path)` menerima `str` atau `pathlib.Path`, mengembalikan model (7.1). |
| FR-P2 | `parse_bpmn_string(xml_text)` menerima isi XML sebagai string (untuk tes dan pembuat skenario). |
| FR-P3 | Elemen dicocokkan lewat **URI namespace**, tidak bergantung pada prefix. |
| FR-P4 | Jenis node yang dibaca: `task`, `userTask`, `serviceTask`, `manualTask`, `scriptTask`, `businessRuleTask`, `sendTask`, `receiveTask`, `subProcess`, `callActivity`, `startEvent`, `endEvent`, `intermediateCatchEvent`, `intermediateThrowEvent`, `boundaryEvent`, `exclusiveGateway`, `parallelGateway`, `inclusiveGateway`, `eventBasedGateway`, `complexGateway`. |
| FR-P5 | Field per node: `id`, `type`, `name`, `lane` (nama), `lane_id`, `lane_path`, `parent`, `process`, `documentation`, `default_flow`, `gateway_direction`, `event_definition`, `loop`, `called_element`, `attached_to`, `cancel_activity`. Arti tiap field di 7.4. |
| FR-P6 | `sequenceFlow` dibaca dengan field: `id`, `type` (`sequence`), `source`, `target`, `name`, `condition`, `parent`, `process`. |
| FR-P7 | Lane dibaca dari `laneSet`/`lane`/`flowNodeRef`, termasuk `childLaneSet` (lane bersarang). `lane` pada node = lane **terdalam** yang memuatnya; `lane_path` = daftar nama dari terluar ke terdalam. Nama lane kosong diganti ID lane. Daftar lane disimpan di model dengan `id`, `name`, `parent_lane`, `process`. |
| FR-P8 | `subProcess` bersarang dibaca rekursif; `parent` menunjuk ke subProcess pemilik. |
| FR-P9 | Lebih dari satu `process` dalam satu file dibaca semua; tiap elemen mencatat `process` asalnya. |
| FR-P10 | Bila ada `collaboration`: `participant` dibaca (`id`, `name`, `process_ref`) dan `messageFlow` dibaca sebagai flow bertipe `message`. **[TERBUKA]** wajib atau tidak, tergantung isi file asli. |
| FR-P11 | Seluruh bagian DI (`BPMNDiagram`, `BPMNShape`, `BPMNEdge`) dan atribut tata letak diabaikan. |
| FR-P12 | Elemen anak `incoming`/`outgoing` pada node diabaikan; daftar flow adalah satu-satunya sumber kebenaran hubungan. |
| FR-P13 | Ekstensi vendor (`extensionElements`, atribut ber-namespace non-BPMN seperti Camunda/Bizagi) diabaikan tanpa error. Pengecualian: teks `documentation` tetap dibaca. |
| FR-P14 | `warnings` berbentuk objek `{code, message, element_id}`. Kode: `MISSING_ID`, `MISSING_ENDPOINT`, `DANGLING_REF`, `MULTI_LANE`, `UNKNOWN_ELEMENT`. Elemen bertag tak dikenal yang punya `id` menghasilkan `UNKNOWN_ELEMENT` (bukan error). |
| FR-P15 | ID duplikat di antara **semua** elemen berID dalam satu file (node, flow, lane, proses) menghasilkan `BpmnParseError`. |
| FR-P16 | Nilai teks (`name`, `condition`, `documentation`) dinormalisasi: `strip()`, spasi dan baris baru berulang menjadi satu spasi, Unicode NFC. **ID tidak dinormalisasi** (case-sensitive, dibandingkan persis). Kapitalisasi pada nama **dianggap perubahan**. |
| FR-P17 | Mode `strict=True`: setiap warning dinaikkan menjadi `BpmnParseError`. Default `False`. |
| FR-P18 | Model memuat `schema_version` dan `source_file` (kosong untuk `parse_bpmn_string`). |
| FR-P19 | Encoding ditangani oleh parser XML (BOM, deklarasi `encoding=`, UTF-8/UTF-16). File lebih besar dari **20 MB** ditolak dengan pesan jelas. |
| FR-P20 | Aman terhadap XML berbahaya: tidak memuat DTD/entitas eksternal dan tahan terhadap entity-expansion; memakai `defusedxml`. |

## 6. Persyaratan fungsional: Diff

| ID | Persyaratan |
|---|---|
| FR-D1 | Menerima dua model hasil parser (atau dua path), mengembalikan hasil diff (7.2). |
| FR-D2 | Elemen dicocokkan **hanya berdasarkan ID**, persis (case-sensitive). |
| FR-D3 | Node: `added` (ID hanya di baru), `removed` (ID hanya di lama), `changed` (ID di keduanya, ada field berbeda). |
| FR-D4 | Field node yang dibandingkan: `type`, `name`, `lane_id`, `parent`, `documentation`, `default_flow`, `gateway_direction`, `event_definition`, `loop`, `called_element`, `attached_to`, `cancel_activity`. Perubahan lane dinilai dari **`lane_id`**, bukan nama lane, sehingga ganti nama lane tidak membuat node tampak pindah. |
| FR-D5 | Flow: `added`, `removed`, `changed`. Field dibandingkan: `type`, `source`, `target`, `name`, `condition`, `parent`. |
| FR-D6 | **Lane**: `added`, `removed`, `changed` (field `name`, `parent_lane`). Keanggotaan node di lane **tidak** dilaporkan di sini; itu muncul sebagai `lane_moved` pada node. |
| FR-D7 | **Proses** (dan `participant` bila ada): `added`, `removed`, `changed` (field `name`). |
| FR-D8 | Setiap `changed` memuat `fields` (nilai lama dan baru) dan `kinds`: label yang diturunkan secara deterministik (7.3). |
| FR-D9 | Konteks: node mendapat `context` (flow masuk dan keluar beserta node di seberang); flow mendapat `endpoints` (ringkasan node sumber dan tujuan). Sumber konteks: model baru untuk `added`/`changed`, model lama untuk `removed`. Flow `changed` juga membawa `endpoints_old`. |
| FR-D10 | `summary` memuat jumlah tiap kategori (node, flow, lane, proses) dan `identical`. `identical` bernilai `true` hanya bila **semua** kategori kosong. |
| FR-D11 | Dua file identik menghasilkan diff kosong dengan `identical: true` (bukan error). |
| FR-D12 | Keluaran **deterministik**: semua daftar diurutkan menurut `id`; kunci JSON berurutan tetap; tidak bergantung urutan elemen di XML maupun hash seed Python. |
| FR-D13 | Perubahan hanya pada DI, urutan elemen di XML, atau urutan flow tidak dianggap perubahan. |
| FR-D14 | Hasil langsung `json.dumps`-able dan memuat `schema_version`. |
| FR-D15 | `warnings` dari kedua model disertakan dengan penanda `side` (`old`/`new`). |
| FR-D16 | **Penjaga file tak berkaitan:** bila kedua model punya node tetapi **tidak ada ID node yang sama**, tambahkan warning `NO_OVERLAPPING_IDS` (diff tetap dihasilkan). |
| FR-D17 | `summary.possible_renames` (opsional): pasangan removed dan added dengan `type`, `name`, dan `lane` sama. Hanya petunjuk, tidak mengubah daftar utama. |
| FR-D18 | Mode `strict` diteruskan ke parser; warning dari diff sendiri (`NO_OVERLAPPING_IDS`) juga menjadi error di mode ini. |
| FR-D19 | **Opsional, prioritas rendah:** `diff_dirs(old_dir, new_dir)` memasangkan file berdasarkan nama; file yang hanya ada di satu sisi dilaporkan sebagai `files.added`/`files.removed`. |

### 6.5 ID berganti
Jika ID berganti (misalnya `PUR-PR-001` menjadi `PUR-PR-010`), diff melaporkan satu `removed` dan satu `added`; tidak ada penebakan. Bentuk `possible_renames` ada di 7.2. Boleh ditunda bila waktu mepet.

### 6.6 Apa yang dibandingkan dan apa yang diabaikan

| Dibandingkan | Diabaikan |
|---|---|
| ID, jenis, nama, lane (via `lane_id`), parent, dokumentasi | Posisi, ukuran, warna, bentuk gambar (DI) |
| Sumber, tujuan, nama, kondisi flow | Urutan elemen di file XML |
| Jenis event, arah gateway, loop, `calledElement`, `attachedToRef`, `cancelActivity` | Anak `incoming`/`outgoing` pada node |
| Nama dan induk lane; nama proses | Ekstensi vendor (Camunda, Bizagi) dan atributnya |
| | Perbedaan whitespace dan baris baru pada teks |

### 6.7 Unit perbandingan
Unit perbandingan adalah **sepasang file**. Elemen yang pindah dari satu file BPMN ke file lain muncul sebagai `removed` di satu pasangan dan `added` di pasangan lain; tidak dilacak lintas-file (keterbatasan yang diketahui). File yang ditambah atau dihapus seluruhnya hanya terlihat lewat `diff_dirs` (FR-D19).

## 7. Model data

### 7.1 Model hasil parser

```json
{
  "schema_version": "1.0",
  "source_file": "docs/bpmn/purchasing.bpmn",
  "processes": [{"id": "P2P", "name": "Procure to Pay"}],
  "participants": [],
  "lanes": {
    "L1": {"id": "L1", "name": "Staff Purchasing", "parent_lane": "", "process": "P2P"}
  },
  "nodes": {
    "PUR-PR-001": {
      "id": "PUR-PR-001", "type": "task", "name": "Buat Purchase Request",
      "lane": "Staff Purchasing", "lane_id": "L1", "lane_path": ["Staff Purchasing"],
      "parent": "P2P", "process": "P2P", "documentation": "",
      "default_flow": "", "gateway_direction": "", "event_definition": "",
      "loop": "", "called_element": "", "attached_to": "", "cancel_activity": ""
    }
  },
  "flows": {
    "FLOW-P2P-008A": {
      "id": "FLOW-P2P-008A", "type": "sequence",
      "source": "PUR-PR-001", "target": "PUR-PR-002",
      "name": "", "condition": "", "parent": "P2P", "process": "P2P"
    }
  },
  "warnings": [{"code": "UNKNOWN_ELEMENT", "message": "...", "element_id": "X1"}]
}
```

### 7.2 Hasil diff

```json
{
  "schema_version": "1.0",
  "old_file": "...", "new_file": "...",
  "summary": {
    "identical": false,
    "nodes": {"added": 1, "removed": 0, "changed": 1},
    "flows": {"added": 1, "removed": 0, "changed": 1},
    "lanes": {"added": 1, "removed": 0, "changed": 0},
    "processes": {"added": 0, "removed": 0, "changed": 0},
    "possible_renames": [{"removed": "A-1", "added": "A-2", "basis": ["type", "name", "lane"]}]
  },
  "nodes": {
    "added":   [{"node": {}, "context": {"incoming": [{"flow": "F2", "node": "PUR-PR-001", "name": "...", "type": "task"}], "outgoing": []}}],
    "removed": [{"node": {}, "context": {}}],
    "changed": [{
      "id": "PUR-PR-001", "kinds": ["retyped"],
      "fields": {"type": {"old": "subProcess", "new": "task"}},
      "context": {"incoming": [], "outgoing": []}
    }]
  },
  "flows": {
    "added": [{"flow": {}, "endpoints": {"source": {}, "target": {}}}],
    "removed": [],
    "changed": [{
      "id": "F2", "kinds": ["rewired_target"],
      "fields": {"target": {"old": "END", "new": "PUR-PR-002"}},
      "endpoints": {"source": {}, "target": {}},
      "endpoints_old": {"source": {}, "target": {}}
    }]
  },
  "lanes":     {"added": [], "removed": [], "changed": []},
  "processes": {"added": [], "removed": [], "changed": []},
  "warnings": [{"side": "new", "code": "DANGLING_REF", "message": "...", "element_id": "F9"}]
}
```

### 7.3 Label `kinds`

| Objek | Field berubah | Label |
|---|---|---|
| Node | `type` | `retyped` |
| Node | `name` | `renamed` |
| Node | `lane_id` | `lane_moved` |
| Node | `parent` | `reparented` |
| Node | `documentation` | `documentation_changed` |
| Node | `default_flow` | `default_flow_changed` |
| Node | `gateway_direction` | `gateway_direction_changed` |
| Node | `event_definition` | `event_definition_changed` |
| Node | `loop` | `loop_changed` |
| Node | `called_element` | `called_element_changed` |
| Node | `attached_to` | `attached_to_changed` |
| Node | `cancel_activity` | `cancel_activity_changed` |
| Flow | `type` | `retyped` |
| Flow | `source` | `rewired_source` |
| Flow | `target` | `rewired_target` |
| Flow | `name` | `renamed` |
| Flow | `condition` | `condition_changed` |
| Flow | `parent` | `reparented` |
| Lane | `name` | `renamed` |
| Lane | `parent_lane` | `reparented` |
| Proses | `name` | `renamed` |

Satu elemen boleh punya beberapa label. `kinds` diurutkan alfabetis.

### 7.4 Arti field khusus

| Field | Nilai |
|---|---|
| `gateway_direction` | Nilai atribut `gatewayDirection` (`Converging`, `Diverging`, `Mixed`, `Unspecified`); kosong bila tidak ada |
| `event_definition` | Nama definisi event tanpa akhiran `EventDefinition`: `message`, `timer`, `error`, `signal`, `terminate`, `escalation`, `conditional`, `link`, `compensation`, `cancel`; `multiple` bila lebih dari satu; kosong bila event polos |
| `loop` | `""`, `standard`, `multi_instance_parallel`, `multi_instance_sequential` |
| `called_element` | Nilai `calledElement` pada `callActivity` |
| `attached_to` | Nilai `attachedToRef` pada `boundaryEvent` |
| `cancel_activity` | `"true"`/`"false"` pada `boundaryEvent`; kosong bila tidak berlaku |
| `lane_path` | Daftar nama lane dari terluar ke terdalam |

## 8. Antarmuka

### 8.1 API Python (kontrak publik)

```python
# core/bpmn_parser.py
def parse_bpmn(path: str | Path, strict: bool = False) -> dict: ...        # 7.1
def parse_bpmn_string(xml_text: str, strict: bool = False) -> dict: ...
class BpmnParseError(Exception): ...

# core/bpmn_diff.py
def diff_models(old: dict, new: dict, strict: bool = False) -> dict: ...   # 7.2
def diff_files(old_path, new_path, strict: bool = False) -> dict: ...
def get_element(model: dict, element_id: str) -> dict | None: ...
def get_context(model: dict, element_id: str) -> dict: ...                 # incoming/outgoing
def diff_dirs(old_dir, new_dir) -> dict: ...                               # opsional (FR-D19)
```

Semua fungsi **murni**: tanpa efek samping, tanpa state global, tanpa membaca environment variable.

### 8.2 CLI

```
python -m core.bpmn_diff OLD.bpmn NEW.bpmn                 # JSON ke stdout
python -m core.bpmn_diff OLD.bpmn NEW.bpmn --md            # ringkasan Markdown
python -m core.bpmn_diff OLD.bpmn NEW.bpmn --strict --out hasil.json
python -m core.bpmn_parser FILE.bpmn [FILE2.bpmn ...]      # ringkasan tiap file (boleh banyak file)
```

- Keluaran selalu UTF-8 (stdout dipaksa UTF-8, JSON dengan `ensure_ascii=False`), agar tidak rusak di konsol Windows.
- Kode keluar: **0** sukses, **2** file tidak bisa dibaca/di-parse (atau pelanggaran `--strict`), **1** error lain.

## 9. Penanganan error dan kasus tepi

### 9.1 Berkas dan struktur

| # | Kasus | Perilaku |
|---|---|---|
| E1 | File tidak ada/tidak terbaca | `BpmnParseError` (path dan sebab) |
| E2 | XML rusak | `BpmnParseError` + nomor baris bila ada |
| E3 | Root bukan `definitions` BPMN | `BpmnParseError` |
| E4 | Node tanpa `id` | Dilewati, warning `MISSING_ID` |
| E5 | ID duplikat (di antara semua elemen berID) | `BpmnParseError` |
| E6 | Node tanpa `name` | `name` = `""` |
| E7 | Node tidak ada di lane mana pun | `lane` = `""`, `lane_id` = `""` |
| E8 | Node terdaftar di dua lane | Warning `MULTI_LANE`; dipakai lane pertama menurut urutan dokumen |
| E9 | Referensi menggantung (flow ke node yang tak ada, `default` ke flow yang tak ada, boundary ke node yang tak ada) | Warning `DANGLING_REF`; elemen tetap dibaca |
| E10 | Flow tanpa `sourceRef`/`targetRef` | Dilewati, warning `MISSING_ENDPOINT` |
| E11 | Namespace/prefix berbeda | Tetap terbaca (FR-P3) |
| E12 | Dua `process` dalam satu file | Dibaca semua (FR-P9) |
| E13 | `subProcess` bersarang | Dibaca rekursif (FR-P8) |
| E14 | Lane bersarang | Lane terdalam dipakai; `lane_path` terisi (FR-P7) |
| E15 | Elemen tak dikenal berID | Warning `UNKNOWN_ELEMENT` |
| E16 | Ekstensi vendor | Diabaikan (FR-P13) |
| E17 | Anak `incoming`/`outgoing` tidak cocok dengan daftar flow | Diabaikan; flow adalah sumber kebenaran |
| E18 | Path Windows (backslash), path berspasi, objek `Path` | Terbaca |
| E19 | BOM, UTF-16, deklarasi encoding lain | Terbaca (FR-P19) |
| E20 | Karakter non-ASCII (Bahasa Indonesia, tanda baca) | Terbaca benar |
| E21 | File lebih dari 20 MB | Ditolak dengan pesan jelas |
| E22 | DTD/entitas eksternal; entity-expansion (billion laughs) | Tidak diikuti/ditolak; tidak ada akses file atau jaringan |
| E23 | Input berupa string XML, bukan file | `parse_bpmn_string` (FR-P2) |

### 9.2 Perbandingan

| # | Kasus | Perilaku |
|---|---|---|
| E24 | File lama sama dengan file baru | `identical: true` |
| E25 | Perubahan hanya di DI | `identical: true` |
| E26 | Urutan elemen di XML berbeda, isi sama | `identical: true` |
| E27 | Beda spasi/baris baru pada nama atau kondisi | Dinormalisasi, bukan perubahan |
| E28 | Beda kapitalisasi pada nama | Dianggap perubahan (`renamed`) |
| E29 | ID beda hanya kapitalisasi | Dianggap ID berbeda (hapus + tambah) |
| E30 | Semua node dihapus | `removed` berisi semuanya, tidak error |
| E31 | Dua file tak berkaitan (tanpa ID node yang sama) | Warning `NO_OVERLAPPING_IDS` |
| E32 | Elemen berubah lane dan tipe sekaligus | Satu entri `changed`, dua label |
| E33 | Elemen pindah `parent` (masuk/keluar subProcess, atau antar proses) | `reparented` |
| E34 | Lane diganti nama, anggotanya sama | Hanya `lanes.changed` (`renamed`); node tidak berubah |
| E35 | Lane baru ditambah, node dipindahkan ke sana | `lanes.added` + `lane_moved` pada node |
| E36 | Lane dihapus | `lanes.removed`; node yang ada di dalamnya muncul `lane_moved` bila masih ada di lane lain |
| E37 | Jenis event berubah (mis. polos menjadi timer) | `event_definition_changed` |
| E38 | Arah gateway berubah | `gateway_direction_changed` |
| E39 | Loop/multi-instance ditambah atau dihapus | `loop_changed` |
| E40 | Boundary event dipindah ke aktivitas lain | `attached_to_changed` |
| E41 | Flow berubah jenis (sequence ke message) dengan ID sama | `retyped` pada flow |
| E42 | Elemen berpindah antar-file | `removed` di satu pasangan, `added` di pasangan lain; tidak dilacak (6.7) |
| E43 | Mode `--strict` bertemu warning | Error, kode keluar 2 |

## 10. Persyaratan non-fungsional

- **Deterministik:** input sama menghasilkan keluaran persis sama, byte per byte (JSON kunci terurut), tidak bergantung urutan XML maupun `PYTHONHASHSEED`.
- **Tanpa jaringan dan tanpa LLM.**
- **Dependensi:** pustaka standar Python + `defusedxml` (keamanan XML). Untuk pengujian: `pytest`.
- **Versi Python:** 3.10 ke atas **[ASUMSI]**, konfirmasi dengan kelompok.
- **Lintas-platform:** berjalan di Windows, Linux, macOS (path via `pathlib`, keluaran UTF-8).
- **Kinerja:** satu pasang file Simple-ERP selesai di bawah 1 detik di laptop biasa; file sintetis berukuran besar (lihat T17) selesai di bawah 5 detik.
- **Keterbacaan:** type hints, docstring pada fungsi publik, tanpa state global.
- **Versi skema:** `schema_version` naik bila bentuk keluaran berubah; perubahan bentuk harus disepakati kelompok.

## 11. Rencana pengujian

`pytest`; berkas uji di `tests/`, fixture kecil di `tests/fixtures/` (pasangan `*_old.bpmn` dan `*_new.bpmn` ditulis tangan, hasil harapan ditentukan **sebelum** menjalankan kode).

| # | Uji | Memverifikasi |
|---|---|---|
| T1 | Satu fixture per label di 7.3 (termasuk lane, proses, event, gateway, loop, attached_to, flow retyped) | FR-D3 sampai FR-D8 |
| T2 | Tambah dan hapus node serta flow; periksa `context` dan `endpoints` | FR-D9 |
| T3 | File identik; perbedaan hanya di DI; urutan elemen XML diacak | FR-D11, FR-D13 (E24 sampai E26) |
| T4 | Prefix namespace berbeda untuk isi yang sama | FR-P3 (E11) |
| T5 | **Uji asap** pada 6 file asli Simple-ERP: parse tanpa error; catat jumlah elemen dan semua warning | T1 tujuan; menjawab [TERBUKA] di bagian 4 |
| T6 | **Skenario S00** (commit `f5a556b`): diff harus memuat `retyped` untuk elemen tersebut. *Butuh clone Simple-ERP; file lama diambil dari commit induk dan file baru dari `f5a556b` dengan `git show`.* | Validasi pada perubahan nyata |
| T7 | Determinisme: dua kali jalan, urutan XML diacak, `PYTHONHASHSEED` berbeda; hasil identik | FR-D12 |
| T8 | Kasus tepi berkas dan struktur (E1 sampai E23 yang berlaku, termasuk ID duplikat lintas jenis elemen) | FR-P14, FR-P15 |
| T9 | Whitespace/baris baru/NFC berbeda; kapitalisasi berbeda | FR-P16 (E27, E28, E29) |
| T10 | Serialisasi JSON dan kembali, hasil sama; `schema_version` ada | FR-D14 |
| T11 | Dua file tak berkaitan | FR-D16 (E31) |
| T12 | Mode `--strict` pada file dengan warning | FR-P17, FR-D18 (E43) |
| T13 | Keamanan: fixture XXE dan billion laughs; tidak ada akses file/jaringan, tidak habis memori | FR-P20 (E22) |
| T14 | Encoding: BOM, UTF-16, deklarasi ISO-8859-1, path berspasi; keluaran UTF-8 | FR-P19 (E18 sampai E20) |
| T15 | `parse_bpmn_string` memberi hasil sama dengan `parse_bpmn` untuk isi yang sama | FR-P2 (E23) |
| T16 | Lane bersarang; lane diganti nama; lane ditambah/dihapus | FR-P7, FR-D4, FR-D6 (E14, E34 sampai E36) |
| T17 | Kinerja: file sintetis sekitar 5.000 node | Bagian 10 |
| T18 | CLI: kode keluar 0/1/2, mode `--md`, `--out`, banyak file | Bagian 8.2 |
| T19 | File lebih dari 20 MB ditolak | FR-P19 (E21) |
| T20 | `possible_renames` pada pasangan hapus + tambah yang mirip (bila fitur dikerjakan) | FR-D17 |

## 12. Kriteria penerimaan (Definition of Done)

- [ ] Parser membaca 6 file BPMN asli tanpa error; jumlah node, flow, lane cocok dengan hitungan manual untuk minimal satu file.
- [ ] Semua label di 7.3 terdeteksi benar pada fixture (T1).
- [ ] S00 menghasilkan diff yang sesuai perubahan commit `f5a556b` (T6).
- [ ] Keluaran deterministik (T7).
- [ ] Seluruh unit test lulus dengan satu perintah `pytest`.
- [ ] CLI berjalan sesuai 8.2, termasuk kode keluar dan keluaran UTF-8.
- [ ] Format keluaran (7.1 dan 7.2) disetujui kelompok dan didokumentasikan (README singkat di `core/`).
- [ ] Contoh keluaran diff untuk S00 disimpan sebagai berkas contoh bagi anggota lain.
- [ ] Setiap kasus E1 sampai E43 punya perilaku terdokumentasi; yang berlaku punya test.
- [ ] Jawaban atas pertanyaan [TERBUKA] nomor 1 dicatat dari hasil uji asap.

## 13. Tahapan pengerjaan

| Tahap | Isi | Hasil |
|---|---|---|
| 1 | Sepakati format keluaran (7.1, 7.2) dan nama field dengan kelompok | Kontrak disetujui |
| 2 | Parser dasar + fixture dasar + uji asap 6 file asli | `bpmn_parser.py`, daftar isi file asli |
| 3 | Diff node, flow, lane, proses + label `kinds` + konteks | `bpmn_diff.py` |
| 4 | Kasus tepi, error, keamanan, encoding | Test T8 sampai T16, T19 |
| 5 | CLI, uji S00, kinerja, contoh keluaran, README | Siap dipakai anggota lain |
| 6 | Fitur opsional: `possible_renames`, `diff_dirs` | Bila waktu tersisa |
| 7 | (Tahap berikutnya) bungkus MCP/function calling | Di luar PRD ini |

## 14. Risiko

| Risiko | Dampak | Mitigasi |
|---|---|---|
| File asli memuat elemen tak terduga (boundary event, message flow, ekstensi vendor) | Elemen terlewat | Uji asap lebih awal; `UNKNOWN_ELEMENT` menampung yang belum didukung |
| ID tidak stabil antar versi BPMN buatan | Diff penuh `added`/`removed` palsu | Konvensi ID dijaga di pembuat skenario; `possible_renames`; penjaga `NO_OVERLAPPING_IDS` |
| Anggota lain sudah membuat parser sendiri | Duplikasi dan format berbeda | Umumkan bahwa `core/` dipegang Hisyam sebelum mulai |
| Format keluaran berubah di tengah jalan | Setup lain harus diubah | Kunci format di tahap 1; perubahan lewat kesepakatan dan naikkan `schema_version` |
| Encoding konsol Windows merusak keluaran | Karakter terbaca salah | stdout dipaksa UTF-8; uji T14 |
| Hubungan lintas-file di Simple-ERP ternyata penting | Perpindahan elemen antar-file tidak terlihat | Periksa saat uji asap; perluas 6.7 bila perlu |
| `defusedxml` tidak terpasang di komputer anggota | Parser gagal jalan | Tercantum di `requirements.txt`; pesan error jelas bila tidak ada |

## 15. Pertanyaan terbuka

1. **[TERBUKA]** Elemen BPMN apa yang benar-benar ada di 6 file asli (bagian 4)? Dijawab oleh T5.
2. **[TERBUKA]** Apakah format keluaran 7.1 dan 7.2 sudah cukup untuk setup lain, atau ada field yang mereka butuhkan?
3. **[TERBUKA]** Perlu mendukung multi-pool/`messageFlow`, atau cukup satu proses per file?
4. **[TERBUKA]** Perlu `--md` untuk dibaca manusia, selain JSON?
5. **[TERBUKA]** Apakah ada hubungan lintas-file yang perlu dilacak (bagian 4 dan 6.7)?
6. **[TERBUKA]** Siapa yang membuat BPMN "baru" untuk skenario sintetis dan bagaimana dibuat (otomatis dari patch)? Mempengaruhi fixture bersama.
7. **[TERBUKA]** Apakah `diff_dirs` (FR-D19) dibutuhkan, atau cukup diff satu pasang file?
8. **[ASUMSI]** Python 3.10+, dependensi hanya `defusedxml` dan `pytest`.
9. **[ASUMSI]** Anggota kelompok memakai campuran Windows dan Linux/macOS, sehingga uji lintas-platform diperlukan.
