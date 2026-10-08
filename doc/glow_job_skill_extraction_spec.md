# Glow-Job Skill Extraction Specification

## 1. Purpose and scope

เอกสารนี้เป็น **spec หลักฉบับเดียว** สำหรับการดึง skill จาก Job Description (JD) หนึ่งประกาศ โดยเก็บบริบทที่บอกว่า skill นั้นจำเป็นแค่ไหน ระดับที่ประกาศระบุ หลักฐานจากข้อความ และความมั่นใจของระบบ กฎคะแนนในเอกสารเป็น heuristic เริ่มต้นของโปรเจกต์ ไม่ใช่ความน่าจะเป็นที่ผ่านการ calibrate แล้ว

งานนี้จบที่ข้อมูล skill ระดับประกาศ (`market.job_skills`) การรวมสถิติหลายประกาศ (`market.career_skill_stats`) เป็นขั้นต่อไป ไม่ใช่ผลลัพธ์ที่ LLM สร้างจาก JD รายการเดียว

ภาพรวม:

```text
Clean Job Description
        ↓
LLM context extraction
        ↓
Validate evidence and output
        ↓
Find canonical skill candidates from skills/aliases
        ↓
Normalize raw skill to canonical skill
        ↓
Rule-based scoring
        ↓
Job-level skill records
        ↓
Career-level aggregation (later stage)
```

## 2. Responsibilities

| Component | Responsibility |
|---|---|
| Job cleaning | เตรียม JD ให้อ่านได้ก่อนส่งให้ LLM; ไม่ต้องหา candidate skill ล่วงหน้า |
| LLM | อ่านบริบทและส่ง `raw_skill_name`, `requirement_type`, `proficiency_level` และ `evidence_text` ตามรูปแบบที่กำหนด |
| Skill normalization | ใช้ `raw_skill_name` ค้น canonical candidates จาก `core.skills` / `core.skill_aliases` แล้วจึงยืนยันการจับคู่และกำหนด `skill_id` |
| Rule engine | ตรวจผล คำนวณ `importance_weight` และ confidence ด้วยกฎที่กำหนด ไม่รับตัวเลขคะแนนที่ LLM คิดเอง |
| Aggregation | สรุปผลจากหลาย job ใน career และช่วงเวลาที่ระบุ |

MVP ส่ง JD ที่ผ่าน cleaning ให้ LLM อ่านโดยตรง คำว่า candidate ในเอกสารนี้หมายถึงชื่อ canonical ที่อาจตรงกับ `raw_skill_name` หลัง extraction ไม่ใช่รายชื่อที่หาใน JD ก่อนเรียก LLM

## 3. Per-job extraction contract

ก่อนบันทึกลงฐานข้อมูล ผลจากการวิเคราะห์หนึ่งประกาศควรมีรูปแบบประมาณนี้:

```json
{
  "job_ref": "jsearch:provider-job-123",
  "extraction_status": "completed",
  "skills": [
    {
      "raw_skill_name": "Postgres",
      "requirement_type": "required",
      "proficiency_level": "unknown",
      "evidence_text": "Experience using Postgres in production is required."
    }
  ]
}
```

`job_ref` ใช้ผูกผลกับประกาศก่อนมี database-generated `job_id` เมื่อมี `job_id` แล้วจึง resolve ความสัมพันธ์ตอน load

ผลหลัง normalize และเตรียมบันทึกอาจแสดงเป็น:

```json
{
  "job_id": 101,
  "skills": [
    {
      "skill_id": 12,
      "skill_name": "PostgreSQL",
      "raw_skill_name": "Postgres",
      "requirement_type": "required",
      "proficiency_level": "unknown",
      "importance_weight": 0.88,
      "skill_confidence": 0.95,
      "requirement_confidence": 1.0,
      "proficiency_confidence": 0.95,
      "overall_confidence": 0.968,
      "evidence_text": "Experience using Postgres in production is required.",
      "extraction_method": "hybrid"
    }
  ]
}
```

`skill_id` มาจากการค้น canonical skill ในฐานข้อมูล ไม่ให้ LLM สร้าง ID เอง `skill_name` เป็นชื่อ canonical ที่ join จาก `core.skills`; `raw_skill_name` เก็บรูปคำที่พบใน JD

ตัวอย่าง `job_id` และ `skill_id` เป็นเลขสมมติ `overall_confidence = 0.968` มาจาก `0.40(0.95) + 0.35(1.00) + 0.25(0.95) = 0.9675` แล้วปัดเป็นทศนิยมสามตำแหน่ง

`extraction_status` ต้องแยก `completed` ที่ไม่พบ skill (`skills: []`) ออกจาก `failed` ที่วิเคราะห์ไม่สำเร็จ งานที่ failed ห้ามถูกนับภายหลังว่าเป็นประกาศที่ไม่มี skill

## 4. Fields and allowed values

### `raw_skill_name`

ข้อความชื่อ skill ที่พบใน JD เช่น `Postgres` หรือ `Amazon Web Services` เก็บตามต้นฉบับเท่าที่ทำได้ เพื่อ audit และช่วยตรวจ normalization

### `requirement_type`

ตอบว่า JD ต้องการ skill นี้ในระดับใด:

| Value | ความหมายและ cue เบื้องต้น |
|---|---|
| `required` | ต้องมี เช่น `required`, `must have`, `mandatory` |
| `preferred` | เป็นข้อได้เปรียบ เช่น `preferred`, `plus`, `bonus`, `nice to have`, `desirable` |
| `optional` | JD ระบุชัดว่าเป็นทางเลือกหรือเสริม แต่ไม่ได้ใช้เป็นเงื่อนไขคัดเลือก |
| `unknown` | พบ skill แต่ไม่มีข้อมูลพอจะจัดประเภท |

สำหรับ MVP ให้จัด `plus`, `bonus` และ `nice to have` เป็น `preferred` เพื่อให้กฎไม่ซ้อนกัน ส่วนคำว่า `optional` ใช้เมื่อประกาศระบุชัด หรือบริบทบอกว่าเป็นทักษะเสริมที่ไม่ใช่ข้อได้เปรียบในการคัดเลือก หากไม่มี cue ให้ใช้ `unknown`

`requirement_type` ตอบว่า *จำเป็นต้องมี skill หรือไม่* ส่วน `proficiency_level` ตอบว่า *หากมี ต้องเก่งระดับใด* จึงเกิดกรณี `required + beginner` หรือ `preferred + advanced` ได้ ทั้งสอง field และคะแนน confidence ของแต่ละ field ต้องแยกกัน

ถ้าข้อความปฏิเสธการใช้ skill เช่น `we do not use Java` ให้ไม่นับเป็น skill ที่ต้องการ ถ้าเขียนว่า `Java is not required` แต่ยังไม่ได้ระบุว่าเป็นข้อได้เปรียบ ให้จัดเป็น `optional` เฉพาะเมื่อบริบทสนับสนุน มิฉะนั้นใช้ `unknown`

### `proficiency_level`

ตอบระดับที่ JD คาดหวัง ไม่ใช่การประเมินความสามารถของผู้สมัคร:

```text
beginner | intermediate | advanced | expert | unknown
```

กฎเริ่มต้น:

| Cue ใน JD | Level เบื้องต้น | Confidence เริ่มต้น |
|---|---|---:|
| ระบุระดับตรง ๆ ว่า `beginner` | `beginner` | 0.95 |
| `basic`, `fundamental` | `beginner` | 0.90 |
| ระบุระดับตรง ๆ ว่า `intermediate` | `intermediate` | 0.95 |
| `working knowledge`, `practical experience` | `intermediate` | 0.85 |
| ระบุระดับตรง ๆ ว่า `advanced` | `advanced` | 0.95 |
| `strong`, `solid` ที่ขยายชื่อ skill โดยตรง | `advanced` | 0.80 |
| ระบุระดับตรง ๆ ว่า `expert` | `expert` | 0.98 |
| `deep expertise`, `specialist` | `expert` | 0.90 |
| ไม่มี cue ระดับที่ชัดเจน | `unknown` | 0.95 |

`proficient` เพียงคำเดียว, `highly proficient` และ `solid experience` อาจใช้ต่างความหมายตามบริบท MVP จึงไม่ให้คะแนนระดับอัตโนมัติจากคำเหล่านี้จนกว่าจะมีตัวอย่างที่คนตรวจแล้ว ถ้า JD ระบุชื่อระดับตรง ๆ เช่น `advanced Python skills` จะได้ confidence สูงกว่าการอนุมานจาก `strong Python skills` ต้องเก็บ evidence และทบทวนตัวอย่างจริงก่อนใช้ตัดสินอัตโนมัติ จำนวนปีประสบการณ์เพียงอย่างเดียวไม่แปลเป็นระดับแบบตายตัว เช่น `3 years` ไม่ได้แปลว่า `advanced` เสมอไป

### `evidence_text`

เก็บข้อความจริงจาก JD ที่รองรับการระบุ skill และ context ห้ามให้ LLM เขียนประโยคหลักฐานขึ้นใหม่ หากหา span จากต้นฉบับไม่พบ ให้ผลตรวจไม่ผ่านหรือส่ง review การใช้ section header หรือข้อความอีกตำแหน่งเป็นหลักฐานต้องย้อนหาได้จาก JD เต็ม; `evidence_text` หนึ่งช่วงอาจไม่พอสำหรับกรณี conflict จึงไม่ควรอ้างคะแนนสูงจากช่วงเดียว

### `extraction_method`

ใช้ค่ามาตรฐานชุดเดียว:

```text
llm | rule | hybrid | manual
```

ใช้ `hybrid` เมื่อมีทั้ง LLM และกฎ deterministic ใน record นั้น ไม่ใช้ `llm_rule_hybrid` เป็นอีกค่าหนึ่ง เพื่อป้องกันค่า method หลายชื่อที่มีความหมายเดียวกัน โค้ดปัจจุบันยังเก็บ `llm` สำหรับผล extract แล้ว normalize; หากเปลี่ยนเป็น `hybrid` ต้องอัปเดตตัวโหลดและทดสอบให้ตรงกัน

## 5. LLM output and validation

LLM ส่งเฉพาะข้อมูลเชิงความหมายต่อ skill:

```json
{
  "raw_skill_name": "Python",
  "requirement_type": "required",
  "proficiency_level": "advanced",
  "evidence_text": "Strong Python skills are required."
}
```

LLM ไม่ส่ง `skill_id`, `importance_weight` หรือ confidence scores ให้ระบบเชื่อโดยตรง Rule engine ต้องตรวจว่า:

- ค่า enum อยู่ในชุดที่อนุญาต
- `evidence_text` มีอยู่จริงใน JD ที่ส่งเข้าไป
- skill ไม่ได้ถูกกล่าวถึงในบริบทปฏิเสธหรือไม่เกี่ยวกับความต้องการของงาน
- ชื่อซ้ำใน JD เดียวกันถูกรวมเป็นหนึ่ง record ต่อ canonical skill

ถ้า LLM ส่ง JSON ผิดรูปแบบหรือ evidence ใช้ไม่ได้ ให้ retry ได้ตามจำนวนที่ตั้งไว้ หากยังไม่สำเร็จให้ทำเครื่องหมาย `failed` พร้อม log สาเหตุ; อย่าแปลงความล้มเหลวเป็น `skills: []` แบบ completed

## 6. Duplicate mentions and conflicting context

ฐานข้อมูลมีหนึ่ง record ต่อคู่ `(job_id, skill_id)` ดังนั้นให้รวมการกล่าวถึง canonical skill เดียวกันใน JD เดียวเป็นหนึ่ง record:

- เก็บ `evidence_text` ที่ชัดที่สุดและรองรับผลที่เลือก
- เลือก requirement ที่มีน้ำหนักชัดที่สุดตามลำดับ `required` > `preferred` > `optional` > `unknown` เมื่อมีหลักฐานตรงกัน
- เลือก proficiency จากหลักฐานระดับที่ชัดที่สุด ไม่ใช้จำนวนปีหรือชื่อตำแหน่งเดาแทน
- ถ้าบริบทขัดแย้งจนเลือกผลไม่ได้ ให้ลด confidence และใช้ `unknown` ใน field ที่ขัดแย้ง

MVP เก็บ evidence หนึ่งช่วงต่อ skill หากภายหลังต้องตรวจหลายบริบทพร้อมกัน ค่อยพิจารณาเก็บ evidence หลายรายการแยกตาราง/JSON

## 7. Skill normalization

Normalize หลัง LLM ระบุ `raw_skill_name`:

```text
Postgres | Postgre SQL | PostgreSQL
                 ↓
        PostgreSQL (canonical)
```

ลำดับ MVP:

1. exact canonical match ใน `core.skills`
2. exact alias match ใน `core.skill_aliases`
3. ถ้ายังไม่พบ ให้เก็บเป็น unmatched/review candidate ไม่สร้าง `skill_id` โดยเดา

Fuzzy matching, RapidFuzz และ embedding เป็นทางเลือกสำหรับระยะถัดไป ไม่ใช่เงื่อนไขจำเป็นของ MVP การเพิ่ม alias ที่ยืนยันแล้วเป็นวิธีแก้รายการ unmatched ในช่วงแรก

## 8. Importance weight

`importance_weight` คือคะแนนความสำคัญของ skill ต่อประกาศนั้น อยู่ในช่วง `0.0–1.0` คำนวณด้วยกฎ ไม่ให้ LLM กำหนด:

```text
importance_weight
= 0.7 × requirement_score + 0.3 × proficiency_score
```

Requirement score:

```text
required = 1.00 | preferred = 0.60 | optional = 0.30 | unknown = 0.40
```

Proficiency score:

```text
expert = 1.00 | advanced = 0.90 | intermediate = 0.70
beginner = 0.50 | unknown = 0.60
```

ตัวอย่าง `required + advanced` ได้ `0.7(1.00) + 0.3(0.90) = 0.97` ส่วน `preferred + beginner` ได้ `0.57` ค่าเหล่านี้เป็นนโยบายเริ่มต้นของโปรเจกต์ ควรเก็บเป็น versioned rule และทบทวนหลังเห็นผลกับข้อมูลจริง

## 9. Confidence scoring

Confidence เป็น heuristic ว่า **การระบุค่าแต่ละ field มีหลักฐานชัดแค่ไหน** ไม่ใช่ความน่าจะเป็นที่รับประกันความถูกต้อง และไม่ใช่ `importance_weight` (ความสำคัญของ skill ต่องาน) งานหนึ่งอาจมี `importance_weight` สูง แต่ classification ยังไม่แน่นอน ต้องเก็บ confidence ทั้งสี่ค่าแยกกัน:

| Field | ตรวจอะไร |
|---|---|
| `skill_confidence` | ชื่อ canonical ที่จับคู่ตรงกับ skill ที่ JD กล่าวถึงจริงแค่ไหน |
| `requirement_confidence` | จัด `required/preferred/optional/unknown` ชัดแค่ไหน |
| `proficiency_confidence` | จัด `beginner/intermediate/advanced/expert/unknown` ชัดแค่ไหน |
| `overall_confidence` | สรุปจากสามค่าข้างบนเมื่อมีครบ |

### 9.1 Skill confidence

MVP ใช้ชื่อ canonical/alias ที่ยืนยันแล้วเท่านั้น หลังตรวจว่า `raw_skill_name` หรือรูปคำที่ยืนยันแล้วปรากฏใน evidence ที่อ้างกลับ JD ได้:

| วิธีจับคู่ | `skill_confidence` |
|---|---:|
| exact canonical | 1.00 |
| exact alias | 0.95 |

คะแนนนี้สะท้อนความชัดของ **การจับคู่ชื่อ** ไม่ใช่หลักฐานว่าการตีความ JD ทั้งหมดถูกต้อง ถ้า Gemini คืน `SQL` ทั้งที่ evidence พูดเพียง “relational database systems” การจับชื่อกับ catalog ได้ไม่ทำให้เป็น exact mention ใน JD ให้ส่ง review และอย่ายืนยัน `skill_id` จากการอนุมานนั้นโดยอัตโนมัติ Fuzzy, embedding และ semantic inference เป็นแนวทางต่อยอด ไม่ได้เปิดใช้ใน MVP

### 9.2 Requirement confidence

สำหรับ cue ที่อยู่ในช่วงข้อความหลักฐานเดียวกับ skill และไม่ถูกปฏิเสธ ให้ใช้ `cue_strength` ต่อไปนี้ ค่า `requirement_type` ต้องตรงกับคอลัมน์ classification:

| Cue ที่ชัดใน evidence | Classification | `cue_strength` |
|---|---|---:|
| `required`, `must have`, `mandatory`, `minimum requirement` | `required` | 1.00 |
| `essential`, `need to have` | `required` | 0.95 |
| `preferred`, `preferred qualification` | `preferred` | 1.00 |
| `desirable` | `preferred` | 0.95 |
| `advantageous`, `plus`, `bonus`, `nice to have` | `preferred` | 0.90 |
| `would be beneficial`, `good to have` | `preferred` | 0.85 |
| ระบุว่า `optional` ชัดเจน | `optional` | 1.00 |

สำหรับ MVP ถ้า evidence ที่ครอบคลุมข้อความเกี่ยวกับ skill นั้นไม่มี cue และไม่มี section/ข้อความอื่นที่เปลี่ยนความหมาย ให้ `requirement_type=unknown` กับ `requirement_confidence=0.95` หมายถึงมั่นใจว่า **ไม่มีข้อมูลพอให้จัดประเภท** ไม่ได้หมายถึงมั่นใจน้อย ถ้า LLM ระบุ classification ไม่ตรงกับ cue หรือไม่มีหลักฐานรองรับ ให้ส่ง review และปล่อย confidence เป็น `NULL` จนกว่าจะตัดสินได้

กฎคือ `requirement_confidence = cue_strength × context_consistency` สำหรับกรณีชัดเจนใน evidence เดียว MVP ให้ `context_consistency=1.00` เท่านั้น จึงได้ `Python is required → 1.00` และ `Kafka would be a plus → 0.90` กรณี ambiguity หรือข้อความขัดกันยังไม่มีวิธีให้ตัวคูณต่ำกว่า 1 ที่ตรวจซ้ำได้ จึง **ไม่เดาค่ากลางช่วง** ให้ใช้ `unknown` หรือส่ง review พร้อม `NULL` ตามหลักฐาน

ตรวจ negation ก่อนจับ cue: `Kafka is not required` ไม่ใช่ `required`; `we do not use Java` ไม่ใช่ skill ที่ต้องการ เงื่อนไขเฉพาะกลุ่ม เช่น “required for the streaming team” ก็ไม่ใช่ global required โดยอัตโนมัติ หัวข้อ `Required Skills`/`Preferred Qualifications` อาจเป็นหลักฐานได้ แต่คะแนนจากหัวข้อใช้ต่อเมื่อระบบระบุตำแหน่ง skill และหัวข้อที่ครอบอยู่ได้จริง; ถ้าข้อความอยู่คนละส่วนหรือเกิด conflict ให้เก็บข้อเสนอเพื่อ review ไม่ใช้คะแนนจาก evidence ช่วงเดียวตัดสินแทนทั้ง JD

### 9.3 Proficiency confidence

ใช้ตาราง cue ในข้อ 4 เป็นค่าเริ่มต้นเมื่อ cue ขยาย skill นั้นโดยตรงและ level ที่ LLM คืนมาตรงกับกฎ เช่น `advanced Python → advanced, 0.95`, `strong Python skills → advanced, 0.80`, `basic SQL → beginner, 0.90` ถ้าไม่มี cue ระดับ และตรวจแล้วว่าไม่มีบริบทอื่นที่ระบุระดับ ให้ `unknown, 0.95` ได้ ความมั่นใจสูงใน `unknown` หมายถึงมั่นใจว่า JD **ไม่ได้ระบุระดับ** ไม่ได้หมายถึงรู้ระดับจริง

ถ้า cue ไม่รองรับ level ที่คืนมา มีหลาย cue ขัดกัน หรืออ้างจากจำนวนปี/ชื่อตำแหน่งเพียงอย่างเดียว ให้ส่ง review และปล่อย confidence เป็น `NULL` แทนการเลือกคะแนนจากช่วงโดยเดา ตารางในข้อ 4 เป็น policy เดียวสำหรับ MVP; การให้คะแนนคำกำกวมอื่นต้องประเมินกับตัวอย่างที่คนตรวจแล้วก่อนเพิ่มกฎ

### 9.4 Overall confidence and review policy

เมื่อสามค่าข้างบนมีครบ คำนวณและปัดเป็นทศนิยมสามตำแหน่ง:

```text
overall_confidence
= 0.40 × skill_confidence
  + 0.35 × requirement_confidence
  + 0.25 × proficiency_confidence
```

ตัวอย่าง `Postgres` เป็น required โดยไม่มี cue ระดับ: `0.40(0.95) + 0.35(1.00) + 0.25(0.95) = 0.9675 → 0.968` หากค่าใดเป็น `NULL` ให้ `overall_confidence=NULL` อย่าแทนด้วยศูนย์หรือ renormalize น้ำหนัก

ตัวอย่างอีกสองกรณีช่วยแยกความสำคัญออกจากความมั่นใจ:

| Evidence | ผล | `importance_weight` | Confidence ที่มีหลักฐานชัด → `overall_confidence` |
|---|---|---:|---|
| `Strong Python skills are required.` | Python, required, advanced | 0.970 | canonical 1.00, required 1.00, strong 0.80 → **0.950** |
| `Basic SQL knowledge is preferred.` | SQL, preferred, beginner | 0.570 | canonical 1.00, preferred 1.00, basic 0.90 → **0.975** |

คะแนนข้างบนเป็นตัวอย่างตามกฎเมื่อข้อความทั้งประโยคเป็นหลักฐานตรงของ skill นั้น ไม่ใช่คะแนนที่ยืนยันความถูกต้องของ LLM กับทุก JD

Threshold ใช้จัดลำดับ **review เท่านั้น** ระหว่างที่คะแนนยังไม่ calibrate กับ JD ที่คนตรวจแล้ว ไม่ reject หรือซ่อน record อัตโนมัติจาก threshold:

| Overall confidence | แนวทางเริ่มต้น |
|---|---|
| `>= 0.85` | หลักฐานค่อนข้างชัด; ยังต้องผ่าน validation |
| `0.65–<0.85` | เก็บผลและติดสถานะ uncertain |
| `<0.65` | ส่ง review และเก็บ raw/extraction result ไว้ |
| `NULL` | กฎยังตัดสินไม่ได้; ส่ง review |

ยังไม่ใช้การ `reject เมื่อ <0.50` ใน MVP เพราะคะแนนเป็น heuristic และอาจตัด skill จริงทิ้ง ต้องทบทวน threshold กับชุด JD ที่คนตรวจแล้วก่อนเปิดการตัดสินอัตโนมัติ

## 10. Storage target and schema alignment

ผลต่อประกาศมีข้อมูลระดับ `market.job_skills` ดังนี้:

```text
job_id
skill_id
raw_skill_name
requirement_type
proficiency_level
importance_weight
skill_confidence
requirement_confidence
proficiency_confidence
overall_confidence
evidence_text
extraction_method
created_at
```

ตัวอย่าง JSON ที่แสดง `skill_name` เป็น convenience representation; ใน relational schema ชื่อ canonical มาจาก `core.skills` ผ่าน `skill_id` ส่วน `raw_skill_name` ต้องเก็บบน job-skill record หากต้องการตรวจคำต้นฉบับย้อนหลัง

DBML และ migration `003_create_job_skills.sql` รองรับ field เป้าหมายเหล่านี้แล้ว โดย loader คำนวณคะแนนจากหลักฐานที่ตรวจได้และบันทึก `NULL` เมื่อกฎยังตัดสินไม่ได้:

| ส่วน | สถานะโค้ดปัจจุบัน |
|---|---|
| LLM extraction และตรวจว่าข้อความ evidence อยู่ใน JD | มีแล้ว |
| exact canonical/alias normalization และเก็บ unmatched | มีแล้ว; loader ตรวจว่าชื่อ skill ปรากฏใน evidence ก่อนยืนยัน `skill_id` |
| `importance_weight` | คำนวณแล้วตามข้อ 8 |
| `skill_confidence` | คำนวณจาก exact canonical/alias เมื่อชื่อ raw skill ปรากฏใน evidence ที่อ้างกลับ JD ได้; semantic inference ยังไม่รองรับ |
| `requirement_confidence`, `proficiency_confidence`, `overall_confidence` | คำนวณตาม cue ที่ชัดใน evidence หรือหัวข้อที่ระบุได้; ค่าใดไม่ชัดเก็บเป็น `NULL` เพื่อ review |
| การจัดการ conflict หลายตำแหน่ง, section และ conditional requirement | ตรวจหัวข้อที่รู้จักและบางรูปแบบของ negation; หากชื่อ skill ปรากฏหลายจุดใน JD จะไม่ให้ requirement/proficiency confidence อัตโนมัติ ต้อง review บริบททั้งหมด |

ตัวอย่างการไหลของข้อมูลหนึ่ง job: LLM คืน `Postgres` + `required` + `unknown` + evidence จาก JD → alias map เป็น `PostgreSQL` → rule คำนวณ `importance_weight=0.88` → บันทึกหนึ่งแถวต่อ `(job_id, skill_id)` เมื่อมี job ในฐานข้อมูล ส่วนชื่อที่ไม่พบใน catalog อยู่ใน checkpoint เพื่อ review ไม่สร้าง `skill_id` โดยเดา

## 11. Aggregation contract (later stage)

Aggregate จาก job-skill records หลัง normalize แล้ว แยกตาม career profile และช่วงวันที่ที่ระบุ:

```text
demand_count = จำนวน job ที่มี canonical skill นี้ (นับ job ไม่ใช่จำนวน mention)
total_jobs = จำนวน job ในกลุ่มที่ extraction_status = completed และมี JD ใช้ได้
demand_percentage = demand_count / total_jobs × 100
required_count / preferred_count / optional_count = จำนวน job ต่อ requirement type
weighted_demand_score = SUM(importance_weight) / total_jobs
```

งานที่ extraction ล้มเหลวหรือไม่มี JD ใช้ได้ไม่รวมใน `total_jobs`; งานที่สำเร็จแต่ไม่พบ skill รวมอยู่ใน denominator และมี skills ว่าง การกำหนดกลุ่ม career, date window และจำนวนตัวอย่างต้องแนบกับ aggregate result

ดังนั้นขั้น aggregation ต้องเข้าถึง `extraction_status` ของทุก job ที่อยู่ในช่วง ไม่สามารถใช้เฉพาะแถวใน `market.job_skills` นับ denominator ได้ เพราะ job ที่ extraction สำเร็จแต่ได้ `skills: []` ไม่มีแถวในตารางนี้ ปัจจุบันสถานะยังอยู่ใน checkpoint; ก่อนทำ aggregation ต้องกำหนดที่เก็บสถานะในฐานข้อมูลหรือวิธีอ่าน checkpoint ที่เชื่อถือได้

สำหรับ `target_level` ให้พิจารณาเฉพาะ job-skill ที่มี proficiency ไม่ใช่ `unknown`; เลือกระดับที่พบบ่อยที่สุด และคำนวณ `target_level_confidence` เป็นสัดส่วนของระดับนั้นใน observations ที่ใช้ได้ `level_observation_count` คือจำนวน observations ดังกล่าว กรณีเสมอกันให้เป็น `unknown` จนกว่าจะมีกฎเพิ่ม

ค่า threshold สำหรับ `importance_tier` (`core`, `important`, `optional`, `unknown`) ยังไม่กำหนดใน spec นี้ เพราะต้องดู distribution ของตลาดจริงก่อน จึงไม่ควรสร้าง tier อัตโนมัติจนกว่าจะตกลง threshold

## 12. MVP and later work

MVP ของ skill extraction:

- รับ JD ที่ผ่าน cleaning แล้ว และ extract ทีละ job
- ใช้ LLM วิเคราะห์บริบทจาก JD ที่ผ่าน cleaning แล้วโดยตรง
- คืน raw skill, requirement type, proficiency เมื่อมีหลักฐาน และ evidence
- ตรวจ schema/evidence, normalize ด้วย canonical/alias match และคำนวณ weight/confidence ด้วย rule
- เก็บสถานะ completed/failed และไม่ทิ้งผลที่ confidence ต่ำโดยอัตโนมัติ
- ทดสอบกับชุด JD ที่คนตรวจผลคาดหวังไว้

งานต่อยอด:

- fuzzy/embedding matching และ review UI
- ปรับ confidence/threshold จากผลประเมินจริง
- เลือก LLM provider/model และตั้ง cost, timeout, retry, rate limit
- สรุป importance tier หลังดู distribution
- เพิ่มการเก็บหลาย evidence ต่อ skill หากมี use case ชัดเจน

ก่อนเชื่อมผู้ให้บริการ LLM ต้องกำหนดว่าจะส่ง JD ส่วนใดออกไป และห้ามบันทึก API key หรือข้อมูลลับลง log

## 13. Acceptance checks

ก่อนถือว่า MVP ใช้งานได้ ต้องตรวจว่า:

1. skill ที่ระบบคืนมีหลักฐานอยู่ใน JD จริง
2. แยก required, preferred, optional และ unknown ตาม cue ที่ตกลงไว้
3. ไม่ extract skill จากบริบทปฏิเสธว่าไม่ใช้
4. ไม่เดา proficiency เมื่อไม่มีข้อความรองรับ
5. รวม alias ให้ canonical skill เดียวและคง raw name ไว้
6. job หนึ่งรายการไม่มี skill ซ้ำหลัง normalize
7. ผล completed ที่ไม่มี skill แยกจาก extraction failure
8. importance/confidence คำนวณซ้ำแล้วได้ผลเดิม และตรวจย้อนสูตรได้
9. aggregation ใช้เฉพาะ job ที่ extraction สำเร็จเป็น denominator
