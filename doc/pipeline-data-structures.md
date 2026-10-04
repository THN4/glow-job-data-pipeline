# โครงสร้างข้อมูลในแต่ละขั้นของ Pipeline

เอกสารนี้อธิบายว่าข้อมูลประกาศงานเปลี่ยนรูปร่างอย่างไรตั้งแต่รับจาก JSearch จนถึงจุดเตรียมบันทึกลงฐานข้อมูล พร้อมเหตุผลว่าทำไมแต่ละขั้นจึงเพิ่ม แปลง หรือเก็บข้อมูลบางส่วนไว้

แนวคิดหลักคือ **ข้อมูลประกาศงาน (`job`)** กับ **ข้อมูลที่มาว่าพบงานนี้จากไหน (`metadata` / `matches`)** เป็นคนละส่วนกัน เราเก็บทั้งคู่เพื่อใช้ประมวลผลและย้อนดูที่มาได้

## ภาพรวม

```text
JSearch response
      ↓
ไฟล์ raw JSON หนึ่งไฟล์ต่อหนึ่ง query
      ↓
load หรือ replay ไฟล์ raw
      ↓
validation: แยกงานที่ใช้ได้ / ใช้ไม่ได้
      ↓
cleaning: ทำความสะอาด field และวันที่
      ↓
deduplication: รวมผลซ้ำจาก ID หรือ URL พร้อมเก็บ matches
      ↓
company normalization: เพิ่มชื่อเทียบมาตรฐานและ candidate
      ↓
career mapping: ขั้นถัดไป ยังไม่ได้ implement
      ↓
database load: แปลงเป็น column และ foreign key ของ PostgreSQL
```

ตัวอย่างด้านล่างย่อ field ที่ไม่เกี่ยวออกเพื่อให้อ่านง่าย ของจริงมี field จาก JSearch มากกว่านี้

## 1. ผลจาก JSearch API

`extract_single_query()` คืน JSON response ของ API ตามที่ได้รับ โดยไม่ได้แปลงเป็น class หรือเปลี่ยนเป็นรูปแบบตารางก่อน

รูปแบบที่พบใน raw run ปัจจุบันมี `data.jobs` เป็นรายการประกาศ และอาจมี `cursor` สำหรับ pagination:

```json
{
  "status": "OK",
  "parameters": {
    "query": "Data Engineer",
    "country": "th"
  },
  "data": {
    "jobs": [
      {
        "job_id": "provider-job-123",
        "job_title": "Senior Data Engineer",
        "employer_name": "Example Co., Ltd.",
        "job_country": "",
        "job_location": "ประเทศไทย • ผ่าน LinkedIn",
        "job_posted_at": "10 วันที่ผ่านมา",
        "job_description": "...",
        "job_publisher": "LinkedIn",
        "job_apply_link": "https://example.com/jobs/123",
        "apply_options": [
          {
            "publisher": "LinkedIn",
            "apply_link": "https://example.com/jobs/123",
            "is_direct": false
          }
        ]
      }
    ],
    "cursor": "..."
  }
}
```

API response ยังเก็บข้อมูลระดับ response เช่น `status`, `parameters`, `cursor` ไว้ด้วย ไม่ใช่มีเฉพาะ job รายการเดียว

Validator รองรับทั้งรูปแบบปัจจุบัน `response.data.jobs` และรูปแบบเดิมที่ `response.data` เป็น list โดยตรง

## 2. เพิ่ม metadata และบันทึก raw JSON

`extract_jobs()` ครอบ API response ด้วย metadata ของ query ที่ใช้ดึง:

```python
{
    "run_id": "20260927T172453146903Z",
    "query_number": 1,
    "collected_at": "2026-09-27T17:24:53+00:00",
    "career_slug": "data_engineer",
    "career_name": "Data Engineer",
    "query": "Data Engineer",
    "response": { ... API response เต็ม ... }
}
```

เหตุผลของ metadata:

- `run_id` บอกว่ามาจากการรัน pipeline รอบไหน
- `query_number` บอกลำดับ query ใน run และใช้เช็กว่า raw run มีไฟล์ครบ
- `collected_at` บอกเวลาที่เราเก็บข้อมูล ใช้ช่วยคำนวณวันที่ของประกาศที่ API ให้มาเป็นข้อความสัมพัทธ์
- `career_slug`, `career_name`, `query` บอกบริบทการค้นหา
- `response` เก็บข้อมูลต้นฉบับทั้งหมดเพื่อ replay และตรวจสอบย้อนหลัง

ไฟล์ถูกจัดตามวันที่และ run เช่น:

```text
data/raw/2026/09/27/<run_id>/001_data_engineer.json
```

หนึ่งไฟล์เก็บผลของหนึ่ง query ส่วน `load_raw_result()` อ่านไฟล์ทั้ง run เรียงตาม `query_number` และคืน list ของ query results โดยคง metadata และ response ไว้

```python
[
    {"run_id": "...", "query_number": 1, "query": "Data Engineer", "response": {...}},
    {"run_id": "...", "query_number": 2, "query": "Junior Data Engineer", "response": {...}},
]
```

Replay จึงไม่ต้องยิง API ซ้ำ และ raw JSON ยังคงเป็นต้นฉบับ ไม่ถูก validation หรือ cleaning เขียนทับ

## 3. Validation: แยก job ที่ใช้ได้และใช้ไม่ได้

Validator เปิด `response.data.jobs` (หรือ list รูปแบบเดิม) แล้วตรวจ **job ทีละรายการ** ไม่ได้ตรวจทั้ง response เป็น job เดียว

รูปแบบผลลัพธ์ของ job ที่ผ่าน:

```python
{
    "job": {
        "job_id": "provider-job-123",
        "job_title": "Senior Data Engineer",
        "employer_name": "Example Co., Ltd.",
        "job_location": "ประเทศไทย • ผ่าน LinkedIn",
        "job_posted_at": "10 วันที่ผ่านมา",
        "job_description": "...",
        "apply_options": [...]
    },
    "metadata": {
        "run_id": "...",
        "query_number": 1,
        "collected_at": "...",
        "career_slug": "data_engineer",
        "career_name": "Data Engineer",
        "query": "Data Engineer"
    }
}
```

`job` คือข้อมูลจากประกาศ ส่วน `metadata` คือข้อมูลของ query ที่พบประกาศนั้น การแยกแบบนี้ทำให้ตรวจ job ได้โดยยังรู้ที่มา

Validator ตรวจ field ที่จำเป็น เช่นชื่อตำแหน่ง รายละเอียด ประเทศ ตัวระบุงาน และวันที่ประกาศ รายการที่ไม่ผ่านจะอยู่ใน `invalid_jobs` พร้อม `errors`:

```python
{
    "job": {...},
    "metadata": {...},
    "errors": ["missing posted date"]
}
```

งานที่ไม่มีวันประกาศทั้ง `job_posted_at_datetime_utc`, `job_posted_at_timestamp` และ `job_posted_at` จะไม่สามารถคำนวณวันประกาศได้ จึงถูกปฏิเสธตามกฎปัจจุบัน การปฏิเสธนี้ไม่ได้ลบ raw file; หมายถึงไม่นำ record นั้นไปขั้นถัดไป

กรณี JSearch ไม่มี `job_country` แต่ `job_location` ระบุ `Thailand`, `ประเทศไทย` หรือ `TH` ชัดเจน ระบบอนุมานประเทศเป็น `TH` ได้ ถ้ามีแค่ชื่อเมือง เช่นกรุงเทพฯ จะไม่เดาประเทศให้

## 4. Cleaning: ทำสำเนา job แล้วปรับค่าที่ใช้ต่อ

`clean_jobs()` ไม่แก้ dict ต้นทาง แต่สร้างสำเนา entry และสำเนา `job` ก่อนทำความสะอาด เช่น:

- ตัดช่องว่างส่วนเกินและ HTML จาก text
- ล้าง URL ว่างหรือช่องว่างหัวท้าย
- ทำรหัสประเทศให้เป็นรูปแบบเดียว เช่น `Thailand` → `TH`
- แปลงวันประกาศเป็น `posted_at` แบบ Python `datetime`
- เพิ่ม `posted_at_is_estimated` เพื่อบอกว่าวันที่คำนวณจากข้อความ เช่น “10 วันที่ผ่านมา” หรือไม่

ตัวอย่างบางส่วนหลัง clean:

```python
{
    "job": {
        "job_title": "Senior Data Engineer",
        "job_country": "TH",
        "job_location": "ประเทศไทย • ผ่าน LinkedIn",
        "job_posted_at": "10 วันที่ผ่านมา",
        "posted_at": datetime(..., tzinfo=timezone.utc),
        "posted_at_is_estimated": True,
        "job_description": "ข้อความที่เอา HTML ออกแล้ว"
    },
    "metadata": {...}
}
```

ค่า `job_posted_at` ต้นทางยังเก็บไว้ ส่วน `posted_at` เป็นค่าที่ pipeline ใช้เรียงและกรองวันที่ ถ้า clean แล้วพบว่าข้อมูลใช้ไม่ได้ จะอยู่ใน `cleaning_rejections` และไม่ส่งต่อ

## 5. Deduplication: รวมผลประกาศซ้ำ แต่เก็บประวัติ query

`deduplicate_jobs()` ใช้ `job_id` จาก provider ก่อน และใช้ URL ของประกาศ/ช่องทางสมัครเป็นทางเลือก โดย URL key ผูกกับ publisher ด้วย กรณีนี้คือการหาผลซ้ำจากข้อมูลที่มี ID หรือลิงก์เดียวกัน ไม่ได้สรุปว่าสองประกาศต่าง publisher เป็นงานเดียวกันเพียงเพราะชื่อตำแหน่งคล้าย

เมื่อเจอรายการซ้ำ:

- เก็บ `job` ของรายการแรกเป็นข้อมูลหลัก
- เก็บ `metadata` ของรายการแรกไว้เป็นที่มาหลักเดิม
- รวม metadata ของทุก query ที่พบไว้ใน `matches`
- รวม `apply_options` ที่มีลิงก์ไม่ซ้ำ
- เก็บรายการที่ถูกพับรวมในผล `duplicates` พร้อม `duplicate_of` และ `dedupe_reason` (ปัจจุบัน `main` ใช้จำนวนสำหรับ log)

ตัวอย่างหลัง dedup:

```python
{
    "job": {...},
    "metadata": {"query_number": 1, "query": "Data Engineer", ...},
    "matches": [
        {"query_number": 1, "query": "Data Engineer", ...},
        {"query_number": 2, "query": "Junior Data Engineer", ...}
    ]
}
```

`matches` มี metadata หนึ่งชุดต่อแหล่งการค้นหาที่พบงาน ไม่ใช่สำเนา job ทั้งก้อน และไม่ใช่ publisher links

## 6. Company normalization: เพิ่มผลเทียบชื่อ โดยไม่เขียนทับชื่อเดิม

ขั้นนี้คง `employer_name` จากประกาศไว้ และเพิ่ม `company_normalization` ใน `job`:

```python
{
    "job": {
        "employer_name": "Siam Commercial Ban",
        "company_normalization": {
            "normalized_name": "siam commercial ban",
            "canonical_name": None,
            "match_method": "candidate_review",
            "candidates": [
                {
                    "canonical_name": "Siam Commercial Bank",
                    "matched_alias": "siam commercial bank",
                    "score": 95.0,
                    "candidate_source": "configured_alias"
                }
            ]
        }
    },
    "metadata": {...},
    "matches": [...]
}
```

ความหมายของผล:

- `normalized_name`: key สำหรับเปรียบเทียบหลังปรับรูปแบบชื่อ
- `canonical_name`: ชื่อมาตรฐานที่ตรงกับ alias ซึ่งยืนยันไว้แล้ว; ถ้าไม่ตรงจะเป็น `None`
- `match_method`: วิธีหรือสถานะ เช่น `confirmed_alias`, `candidate_review`, `unmatched`, `missing`
- `candidates`: รายชื่อใกล้เคียงสำหรับตรวจ ไม่ได้แปลว่าระบบยืนยันว่าเป็นบริษัทเดียวกัน
- `candidate_source`: candidate มาจาก alias config หรือชื่ออื่นที่พบใน batch เดียวกัน

RapidFuzz ช่วยหา candidate จากชื่อที่มีอยู่ใน registry หรือ batch ปัจจุบัน แต่ไม่ได้เพิ่ม alias ลง config/DB และไม่ได้รวมบริษัทให้อัตโนมัติ ชื่อที่ยืนยันแล้วจึงค่อยเพิ่มใน `config/company_aliases.yaml` เพื่อให้รอบต่อไประบุได้ตรง

รายงาน CSV ต่อ run อยู่ที่:

```text
data/processed/company_match_candidates/<run_id>.csv
```

หนึ่งแถวคือหนึ่งคู่ job–candidate และมีชื่อประกาศ publisher ลิงก์ต้นทาง คะแนน และ query number ประกอบ ถ้าไม่มี candidate จะมีเฉพาะ header

## 7. Career mapping: เพิ่มชื่อมาตรฐานและหมวดอาชีพ

เป้าหมายคือคง `job_title` เดิม แล้วเพิ่มข้อมูลหมวดอาชีพ เช่น:

```python
{
    "job_title": "Senior Data Engineer",
    "normalized_job_title": "Data Engineer",
    "career_slug": "data_engineer",
    "career_name": "Data Engineer",
    "career_profile_slug": "data_engineer_general",
    "career_mapping_status": "mapped",
    "career_mapping_method": "title_alias",
    "career_candidates": []
}
```

ชื่อมาตรฐานและ slug มาจาก `config/careers.yaml` ส่วน `title_aliases` ใน career แต่ละอันเป็นกฎจับคู่ชื่อตำแหน่ง `queries` ยังมีไว้ค้นหาจาก API แยกจากกฎ map

ระบบพยายามจับจากชื่อตำแหน่งก่อน หากชื่อชี้ไป career เดียว จะใช้ career นั้น ถ้าชื่อไม่ชัดจึงใช้ `matches` เป็นบริบทสำรองเมื่อพบจาก career เดียวเท่านั้น ถ้าพบหลักฐานขัดกันจะใส่ `career_mapping_status = "ambiguous"`; ถ้าไม่พบหลักฐานจะเป็น `"unmapped"` โดยยังเก็บประกาศไว้

`career_profile_id` เป็นเลข ID ที่ฐานข้อมูลสร้าง การประมวลผลก่อน load จึงควรใช้ slug ที่คงที่ก่อน แล้วค่อย lookup ID ตอนบันทึกลง DB

## 8. Database load: จาก dict เป็น column ของตาราง

Database ไม่ได้บันทึก Python dict ทั้งก้อนลง `market.job_postings` โดยตรง `JobPostingRepository` รับค่าทีละ argument แล้วเขียนลง column เช่น:

```text
job_title               → market.job_postings.job_title
normalized_job_title    → market.job_postings.normalized_job_title
career_profile_id      → market.job_postings.career_profile_id
company_id              → market.job_postings.company_id
provider_job_id         → market.job_postings.provider_job_id
publisher               → market.job_postings.publisher
source_url              → market.job_postings.source_url
posted_at               → market.job_postings.posted_at
```

PostgreSQL สร้าง `job_id` ภายในของระบบ ส่วน `provider_job_id` คือ ID ที่ JSearch ให้มา ทั้งสอง ID คนละความหมาย

Query provenance ถูกบันทึกแยกใน `market.job_search_matches` ผ่าน `record_search_match()` โดยเชื่อม job, ingestion run, career profile และ search query เข้าด้วยกัน

ใน schema/repository ปัจจุบันยังไม่มีการเขียน `apply_options` เป็นตารางแยก ดังนั้น raw JSON ยังคงเป็นแหล่งเก็บ response เต็มและหลาย application links จนกว่าจะกำหนดวิธี load field นี้เพิ่มเติม

## สรุปสิ่งที่เปลี่ยนรูปร่างและสิ่งที่คงเดิม

| ขั้น | รูปร่างหลัก | สิ่งที่เปลี่ยน | เหตุผล |
|---|---|---|---|
| Extract | response เต็มจาก API | เพิ่ม run/query metadata ครอบ response | trace และ replay ได้ |
| Raw storage | JSON หนึ่งไฟล์ต่อ query | ไม่มีการ clean หรือทิ้ง field | เก็บต้นฉบับไว้ตรวจสอบ |
| Validation | `job` + `metadata` แยก valid/invalid | แยกเป็น record ต่อ job พร้อม errors ถ้าไม่ผ่าน | กันข้อมูลใช้ไม่ได้เข้าสู่ transform |
| Cleaning | `job` สำเนาที่ normalize แล้ว + metadata | เพิ่ม `posted_at`, `posted_at_is_estimated` | ใช้รูปแบบสม่ำเสมอในขั้นต่อไป |
| Dedup | หนึ่ง job ต่อ identity พร้อม `matches` | รวม query provenance และ apply links ที่ไม่ซ้ำ | ไม่ทำสถิติซ้ำจากหลาย query |
| Company normalization | job + `company_normalization` | เพิ่มชื่อเทียบและ candidate | ช่วยจัดบริษัทโดยยังเก็บชื่อเดิม |
| Career mapping | job พร้อม `job_title` และ query provenance | เพิ่ม `normalized_job_title`, career/profile slug และสถานะการ map | จัดกลุ่มข้อมูลเพื่อการวิเคราะห์ โดยยังเก็บชื่อตำแหน่งเดิม |
| Database load | columns และ foreign keys | แปลงค่าจาก dict เป็น argument/column | ให้ query และ join ข้อมูลได้ |

จำง่าย ๆ: `job` บอกว่า **ประกาศมีข้อมูลอะไร**, `metadata`/`matches` บอกว่า **เราเจอประกาศนี้จากการค้นหาไหน**, และ `company_normalization` เป็น **ผลช่วยจัดมาตรฐาน** ที่แนบเพิ่มโดยไม่ลบชื่อจากต้นทาง
