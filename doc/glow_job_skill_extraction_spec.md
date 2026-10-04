# Glow-Job Skill Extraction Specification

## 1. Purpose and scope

เอกสารนี้กำหนดผลลัพธ์และกติกาของการดึง skill จาก Job Description (JD) หนึ่งประกาศ โดยต้องเก็บบริบทที่บอกว่า skill นั้นจำเป็นแค่ไหน ระดับที่ประกาศระบุ หลักฐานจากข้อความ และความมั่นใจของระบบ

งานนี้จบที่ข้อมูล skill ระดับประกาศ (`market.job_skills`) การรวมสถิติหลายประกาศ (`market.career_skill_stats`) เป็นขั้นต่อไป ไม่ใช่ผลลัพธ์ที่ LLM สร้างจาก JD รายการเดียว

ภาพรวม:

```text
Clean Job Description
        ↓
NLP text preparation / candidate detection
        ↓
LLM context extraction
        ↓
Validate evidence and output
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
| NLP/text preparation | แบ่งข้อความเป็นประโยคและส่วนย่อย เตรียมข้อความสะอาด และช่วยหา candidate skill |
| LLM | อ่านบริบทและส่ง `raw_skill_name`, `requirement_type`, `proficiency_level` และ `evidence_text` ตามรูปแบบที่กำหนด |
| Skill normalization | map ชื่อที่พบไปยัง canonical skill และ `skill_id` จาก `core.skills` / `core.skill_aliases` |
| Rule engine | ตรวจผล คำนวณ `importance_weight` และ confidence ด้วยกฎที่กำหนด ไม่รับตัวเลขคะแนนที่ LLM คิดเอง |
| Aggregation | สรุปผลจากหลาย job ใน career และช่วงเวลาที่ระบุ |

NLP และ LLM เป็นแนวทางของระบบ แต่ยังไม่ผูกกับ library หรือผู้ให้บริการ LLM รายใด การเลือกเครื่องมือและค่าใช้บริการเป็นการตั้งค่าของ implementation แยกต่างหาก

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
      "overall_confidence": 0.97,
      "evidence_text": "Experience using Postgres in production is required.",
      "extraction_method": "hybrid"
    }
  ]
}
```

`skill_id` มาจากการค้น canonical skill ในฐานข้อมูล ไม่ให้ LLM สร้าง ID เอง `skill_name` เป็นชื่อ canonical ที่ join จาก `core.skills`; `raw_skill_name` เก็บรูปคำที่พบใน JD

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
| `strong`, `solid`, `proficient` | `advanced` | 0.80 |
| ระบุระดับตรง ๆ ว่า `expert` | `expert` | 0.98 |
| `deep expertise`, `specialist` | `expert` | 0.90 |
| ไม่มี cue ระดับที่ชัดเจน | `unknown` | 0.95 |

ถ้า JD ระบุชื่อระดับตรง ๆ เช่น `advanced Python skills` จะได้ confidence สูงกว่าการอนุมานจากคำกว้าง ๆ เช่น `strong Python skills` ตารางนี้เป็น heuristic เริ่มต้น ไม่ใช่มาตรฐานสากล จึงต้องเก็บ evidence และทบทวนตัวอย่างจริงก่อนใช้ตัดสินอัตโนมัติ จำนวนปีประสบการณ์เพียงอย่างเดียวไม่แปลเป็นระดับแบบตายตัว เช่น `3 years` ไม่ได้แปลว่า `advanced` เสมอไป

### `evidence_text`

เก็บข้อความจริงจาก JD ที่รองรับการระบุ skill และ context ห้ามให้ LLM เขียนประโยคหลักฐานขึ้นใหม่ หากหา span จากต้นฉบับไม่พบ ให้ผลตรวจไม่ผ่านหรือส่ง review

### `extraction_method`

ใช้ค่ามาตรฐานชุดเดียว:

```text
llm | rule | hybrid | manual
```

ใช้ `hybrid` เมื่อมีทั้ง LLM และกฎ deterministic ใน record นั้น ไม่ใช้ `llm_rule_hybrid` เป็นอีกค่าหนึ่ง เพื่อป้องกันค่า method หลายชื่อที่มีความหมายเดียวกัน

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

## 9. Confidence

Confidence เป็นคะแนน heuristic ที่บอกความชัดเจนของการจัดประเภท ไม่ใช่ความน่าจะเป็นที่รับประกันความถูกต้อง และไม่ใช่ความสำคัญของ skill

แยกเป็น:

| Field | ตรวจอะไร |
|---|---|
| `skill_confidence` | ระบุ skill จากข้อความได้ตรงแค่ไหน |
| `requirement_confidence` | จัด required/preferred/optional/unknown ได้ชัดแค่ไหน |
| `proficiency_confidence` | จัดระดับ proficiency ได้ชัดแค่ไหน รวมถึงมั่นใจว่าเป็น `unknown` |
| `overall_confidence` | คะแนนสรุปจากสาม field |

คะแนนเริ่มต้นสำหรับ skill match:

| วิธีพบ skill | Score เบื้องต้น |
|---|---:|
| exact canonical | 1.00 |
| exact alias | 0.95 |
| LLM inference ที่มีหลักฐานบริบทชัด | 0.60 |

Fuzzy/embedding scores ยังไม่อยู่ใน MVP เพราะ fuzzy/embedding matching ถูกเลื่อนไประยะถัดไป คะแนนตารางทั้งหมดเป็นค่าเริ่มต้นที่ต้องเทียบกับตัวอย่างซึ่งคนตรวจแล้ว ไม่ใช่ค่าที่ calibrate แล้ว

คำนวณ:

```text
overall_confidence
= 0.40 × skill_confidence
 + 0.35 × requirement_confidence
 + 0.25 × proficiency_confidence
```

การได้ `proficiency_level = unknown` พร้อม confidence สูง หมายถึงระบบมั่นใจว่าข้อความไม่ระบุระดับ ไม่ได้หมายถึงระบบรู้ระดับของ skill นั้น

Threshold ต่อไปนี้ใช้เป็น **คำแนะนำสำหรับ review เท่านั้น** ใน MVP ห้าม reject record อัตโนมัติจาก threshold ก่อนตรวจผลกับ JD จริง:

| Overall confidence | แนวทาง |
|---|---|
| `>= 0.85` | รับอัตโนมัติได้หลังผ่านหลักฐานและ schema validation |
| `0.65–0.84` | เก็บผลและติดสถานะ uncertain |
| `0.50–0.64` | ส่ง review |
| `< 0.50` | ส่ง review; ยังเก็บ raw/extraction result ไว้ |

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

ณ ตอนเขียน spec นี้ DBML ยังมี `confidence` ค่าเดียวและไม่มี `raw_skill_name` หรือ confidence แยกสี่ค่า ดังนั้นรายการด้านบนเป็น **target contract** ไม่ใช่คำกล่าวว่า schema/migration ปัจจุบันรองรับครบแล้ว ต้องปรับ DBML และสร้าง migration ก่อน load ฟิลด์ที่ยังไม่มี ค่า `proficiency_level` ใน DBML ต้องจำกัดให้ตรงกับ `beginner`, `intermediate`, `advanced`, `expert`, `unknown`

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

สำหรับ `target_level` ให้พิจารณาเฉพาะ job-skill ที่มี proficiency ไม่ใช่ `unknown`; เลือกระดับที่พบบ่อยที่สุด และคำนวณ `target_level_confidence` เป็นสัดส่วนของระดับนั้นใน observations ที่ใช้ได้ `level_observation_count` คือจำนวน observations ดังกล่าว กรณีเสมอกันให้เป็น `unknown` จนกว่าจะมีกฎเพิ่ม

ค่า threshold สำหรับ `importance_tier` (`core`, `important`, `optional`, `unknown`) ยังไม่กำหนดใน spec นี้ เพราะต้องดู distribution ของตลาดจริงก่อน จึงไม่ควรสร้าง tier อัตโนมัติจนกว่าจะตกลง threshold

## 12. MVP and later work

MVP ของ skill extraction:

- รับ JD ที่ผ่าน cleaning แล้ว และ extract ทีละ job
- ใช้ NLP เตรียมข้อความ/หา candidates ร่วมกับ LLM วิเคราะห์ context
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
