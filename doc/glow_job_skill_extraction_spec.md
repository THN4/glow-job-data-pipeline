# Glow-Job Skill Extraction Specification

## 1. Purpose

เอกสารนี้กำหนดรูปแบบและ logic สำหรับ **Skill Extraction จาก Job Description (JD)** ในระบบ Glow-Job

เป้าหมายคือไม่ extract เพียงว่าใน JD มี Skill อะไรบ้าง แต่ต้องเก็บ **บริบทของ Skill แต่ละตัว** ด้วย เพื่อให้ระบบสามารถตอบได้ว่า:

- Skill นี้ถูกกล่าวถึงจริงหรือไม่
- Skill นี้เป็น `required`, `preferred`, `optional` หรือไม่ชัดเจน
- บริษัทคาดหวังระดับความสามารถประมาณไหน
- Skill นี้สำคัญต่อ JD นี้มากแค่ไหน
- ระบบมั่นใจแค่ไหนว่า extraction ถูกต้อง
- ข้อความส่วนไหนของ JD เป็นหลักฐาน
- เมื่อ aggregate หลาย JD แล้ว Skill นี้สำคัญต่อ Career โดยรวมแค่ไหน

---

## 2. Overall Flow

```text
Job Description
      ↓
Text Preparation
      ↓
LLM / NLP Context-Aware Extraction
      ↓
Raw Skill Extraction
      ↓
Skill Normalization
      ↓
Rule-Based Scoring
      │
      ├── importance_weight
      └── confidence scores
      ↓
market.job_skills
      ↓
Aggregate Many Job Postings
      ↓
market.career_skill_stats
```

หลักสำคัญคือ:

> LLM มีหน้าที่อ่าน Context และ Extract ข้อมูลเชิงความหมาย  
> ส่วนคะแนนเชิงตัวเลขควรคำนวณด้วย deterministic logic เพื่อให้ผล consistent และ testable

---

## 3. What the LLM Should Extract

LLM ไม่ควรสร้าง `importance_weight` หรือ confidence แบบสุ่มเองโดยตรง

LLM ควร extract ข้อมูลพื้นฐานต่อไปนี้:

```json
{
  "skill": "Python",
  "requirement_type": "required",
  "proficiency_level": "advanced",
  "evidence_text": "Strong Python skills are required."
}
```

| Field | หน้าที่ |
|---|---|
| `skill` | Skill ที่ตรวจพบ |
| `requirement_type` | Skill นี้จำเป็นต่อ Job แค่ไหน |
| `proficiency_level` | บริษัทต้องการให้เก่งระดับไหน |
| `evidence_text` | ประโยคหรือข้อความที่รองรับ extraction |

จากนั้นระบบจะทำ Skill Normalization และ Scoring ต่อ

---

## 4. Requirement Type

`requirement_type` ตอบคำถามว่า:

> บริษัทให้ความสำคัญกับการ “มี Skill นี้” แค่ไหน

ค่าที่ใช้:

```text
required
preferred
optional
unknown
```

| Value | ความหมาย |
|---|---|
| `required` | ผู้สมัครต้องมี Skill นี้ |
| `preferred` | มีจะได้เปรียบ แต่ไม่ใช่ข้อบังคับ |
| `optional` | เป็น Skill เสริมหรือ Nice-to-have |
| `unknown` | JD ไม่ได้ระบุชัดเจน |

ตัวอย่าง:

```text
Python experience is required.
Basic Kafka knowledge is preferred.
```

```json
[
  {
    "skill": "Python",
    "requirement_type": "required"
  },
  {
    "skill": "Apache Kafka",
    "requirement_type": "preferred"
  }
]
```

---

## 5. Proficiency Level

`proficiency_level` ตอบคำถามว่า:

> บริษัทคาดหวังให้ผู้สมัครมี Skill นี้ในระดับไหน

ค่าที่ใช้:

```text
beginner
intermediate
advanced
expert
unknown
```

| Value | ความหมาย |
|---|---|
| `beginner` | รู้พื้นฐานหรือใช้งานเบื้องต้น |
| `intermediate` | สามารถใช้งานจริงได้ |
| `advanced` | ใช้งานในงานซับซ้อนได้ |
| `expert` | เชี่ยวชาญหรือเป็น specialist |
| `unknown` | JD ไม่ได้ระบุระดับชัดเจน |

ตัวอย่าง:

```text
Strong Python programming skills are required.
Basic SQL knowledge is preferred.
```

```json
[
  {
    "skill": "Python",
    "requirement_type": "required",
    "proficiency_level": "advanced"
  },
  {
    "skill": "SQL",
    "requirement_type": "preferred",
    "proficiency_level": "beginner"
  }
]
```

---

## 6. Requirement Type vs Proficiency Level

สอง Field นี้ตอบคนละคำถาม:

```text
requirement_type
= จำเป็นต้องมีไหม

proficiency_level
= ถ้ามีแล้ว ต้องเก่งแค่ไหน
```

ตัวอย่าง:

```text
required + beginner
= ต้องมี แต่แค่พื้นฐานก็พอ

required + advanced
= ต้องมี และต้องเก่ง

preferred + beginner
= มีก็ดี และแค่พื้นฐานก็พอ

preferred + advanced
= ไม่บังคับ แต่ถ้ามีคาดหวังระดับสูง
```

เพราะฉะนั้นต้องเก็บทั้งสอง Field แยกกัน

---

## 7. Skill Normalization

หลัง LLM Extract Skill แล้ว ห้ามนำชื่อ Raw ไปใช้โดยตรงทันที

ตัวอย่าง:

```text
Postgres
Postgre SQL
PostgreSQL
```

ควร map ไปยัง Canonical Skill เดียว:

```text
skill_id = 12
skill_name = PostgreSQL
```

ใช้:

```text
core.skills
core.skill_aliases
```

Output หลัง Normalize ควรมีทั้งชื่อ Raw และ Canonical:

```json
{
  "skill_id": 12,
  "skill_name": "PostgreSQL",
  "raw_skill_name": "Postgres"
}
```

---

## 8. Importance Weight

`importance_weight` ตอบคำถามว่า:

> Skill นี้สำคัญต่อ Job Posting นี้มากแค่ไหน

ช่วงคะแนน:

```text
0.0 - 1.0
```

ไม่ควรให้ LLM Generate คะแนนนี้โดยตรง

ควรคำนวณจาก:

```text
requirement_type
+
proficiency_level
```

### Requirement Score

```text
required   = 1.00
preferred  = 0.60
optional   = 0.30
unknown    = 0.40
```

### Proficiency Score

```text
expert        = 1.00
advanced      = 0.90
intermediate  = 0.70
beginner      = 0.50
unknown       = 0.60
```

### Formula

```text
importance_weight
=
0.7 × requirement_score
+
0.3 × proficiency_score
```

เหตุผลที่ Requirement มี Weight สูงกว่า:

> `importance_weight` ต้องสะท้อนว่า Skill นี้จำเป็นต่อ Job มากแค่ไหน ไม่ใช่เพียงว่าต้องเก่งระดับไหน

### Example A

```text
Python
required
advanced
```

```text
0.7(1.00) + 0.3(0.90)
= 0.97
```

### Example B

```text
SQL
preferred
beginner
```

```text
0.7(0.60) + 0.3(0.50)
= 0.57
```

### Example C

```text
Linux
required
beginner
```

```text
0.7(1.00) + 0.3(0.50)
= 0.85
```

ถึงแม้บริษัทต้องการเพียง Beginner แต่ Skill ยังมีความสำคัญสูง เพราะเป็น Requirement

---

## 9. Confidence

Confidence ใช้ตอบคำถามว่า:

> ระบบมั่นใจแค่ไหนว่า Skill Extraction ในแต่ละ field ถูกต้อง

Confidence **ไม่ใช่** ค่าความสำคัญของ Skill ต่อ Job

ตัวอย่าง:

```text
importance_weight = 0.95
overall_confidence = 0.50
```

หมายถึง:

> ถ้า extraction นี้ถูก Skill นี้สำคัญมากต่อ Job แต่ระบบยังไม่มั่นใจว่า extraction ถูกจริง

เพื่อให้สามารถอธิบายและ debug ได้ชัดเจน Glow-Job จะแยก Confidence ออกเป็น 4 ค่า:

```text
skill_confidence
requirement_confidence
proficiency_confidence
overall_confidence
```

---

### 9.1 `skill_confidence`

ตอบคำถามว่า:

> ระบบมั่นใจแค่ไหนว่า Skill ที่ extract ออกมาคือ Skill ที่ JD กล่าวถึงจริง

แนวทางการให้คะแนน:

| กรณี | ตัวอย่าง | Score แนะนำ |
|---|---|---:|
| Exact canonical match | `Python` → `Python` | `1.00` |
| Exact alias match | `Postgres` → `PostgreSQL` | `0.95` |
| High fuzzy match | typo หรือชื่อใกล้เคียงมาก | `0.85` |
| Strong semantic / embedding match | ความหมายใกล้กันมาก | `0.75` |
| LLM inference from context | ไม่ได้พูดชื่อ Skill ตรง ๆ | `0.60` |
| Weak inference | ต้องเดาจากบริบทมาก | `0.40` |

ตัวอย่าง:

```text
JD:
"Experience with Postgres is required."

Raw:
Postgres

Canonical:
PostgreSQL
```

สามารถให้:

```text
skill_confidence = 0.95
```

อีกตัวอย่าง:

```text
JD:
"Experience with relational database systems."
```

ถ้าระบบ infer เป็น `SQL`:

```text
skill_confidence ≈ 0.60
```

เพราะ JD ไม่ได้ mention SQL โดยตรง

หาก `skill_confidence` ต่ำมาก เช่นต่ำกว่า `0.50` ควรพิจารณา:

```text
ไม่บันทึกอัตโนมัติ
หรือ
ส่งเข้า review
```

---

### 9.2 `requirement_confidence`

ตอบคำถามว่า:

> ระบบมั่นใจแค่ไหนว่า `required / preferred / optional / unknown` ที่ classify ถูกต้อง

แนวทาง:

| Context | Classification | Confidence |
|---|---|---:|
| `must`, `required`, `mandatory` | `required` | `1.00` |
| `should have`, `expected to have` | `required` | `0.85` |
| `preferred`, `desirable`, `advantageous` | `preferred` | `1.00` |
| `nice to have`, `plus`, `bonus` | `preferred` หรือ `optional` | `0.85–0.90` |
| Mention Skill แต่ไม่มี requirement cue | `unknown` | `≈0.90` |
| ต้อง infer จากบริบทหลายประโยค | ตามผลที่ classify | `0.60–0.75` |

ตัวอย่าง:

```text
"Python is required."
```

ได้:

```text
requirement_type = required
requirement_confidence = 1.00
```

ตัวอย่าง:

```text
"Kafka knowledge would be a plus."
```

อาจได้:

```text
requirement_type = preferred
requirement_confidence = 0.90
```

สิ่งสำคัญคือค่าต่อไปนี้ **ถูกต้องได้**:

```json
{
  "requirement_type": "unknown",
  "requirement_confidence": 0.95
}
```

ความหมายคือ:

> ระบบมั่นใจสูงว่า JD ไม่ได้ให้ข้อมูลเพียงพอที่จะระบุว่า Skill นี้ required, preferred หรือ optional

ไม่ได้หมายความว่าระบบไม่มั่นใจ

---

### 9.3 `proficiency_confidence`

ตอบคำถามว่า:

> ระบบมั่นใจแค่ไหนว่า `beginner / intermediate / advanced / expert / unknown` ที่ classify ถูกต้อง

แนวทาง:

| Context | Level | Confidence |
|---|---|---:|
| `basic`, `fundamental`, `introductory` | `beginner` | `1.00` |
| `working knowledge`, `practical experience` | `intermediate` | `≈0.90` |
| `proficient`, `solid experience` | `intermediate` | `≈0.80` |
| `strong`, `highly proficient` | `advanced` | `≈0.85` |
| `expert`, `deep expertise`, `specialist` | `expert` | `≈0.95` |
| ไม่มีการพูดถึงระดับ | `unknown` | `≈0.95` |
| infer จาก years of experience | inferred level | `0.60–0.75` |

ตัวอย่าง:

```text
"Basic Kafka knowledge"
```

ได้:

```text
proficiency_level = beginner
proficiency_confidence = 1.00
```

ตัวอย่าง:

```text
"Strong Python programming skills"
```

อาจได้:

```text
proficiency_level = advanced
proficiency_confidence = 0.85
```

### Important Rule

ไม่ควร map จำนวนปีเป็น proficiency แบบตายตัว เช่น:

```text
3 years of Python
≠
advanced เสมอไป
```

หากจะใช้จำนวนปีเป็น signal ต้องถือว่าเป็น inference และลด confidence ลง

---

### 9.4 `overall_confidence`

ใช้เป็นคะแนนสรุปว่า:

> Skill record นี้โดยรวมเชื่อถือได้แค่ไหน

สำหรับ MVP แนะนำสูตร:

```text
overall_confidence
=
0.40 × skill_confidence
+
0.35 × requirement_confidence
+
0.25 × proficiency_confidence
```

เหตุผลของ Weight:

```text
skill_confidence
```

มีน้ำหนักสูงที่สุด เพราะถ้า identify Skill ผิด ค่า requirement และ proficiency ที่เหลือจะไม่มีความหมาย

รองลงมา:

```text
requirement_confidence
```

เพราะ requirement มีผลโดยตรงต่อ:

```text
importance_weight
Market Priority
```

และสุดท้าย:

```text
proficiency_confidence
```

เพราะหลาย JD ไม่ระบุระดับอย่างชัดเจนเป็นเรื่องปกติ

ตัวอย่าง:

```text
skill_confidence       = 1.00
requirement_confidence = 1.00
proficiency_confidence = 0.85
```

คำนวณ:

```text
overall_confidence
=
0.40(1.00)
+
0.35(1.00)
+
0.25(0.85)

= 0.9625
```

สามารถเก็บ:

```text
overall_confidence = 0.963
```

---

## 10. Confidence Threshold

สามารถใช้ `overall_confidence` เพื่อกำหนดพฤติกรรมของ Pipeline

ค่าเริ่มต้นสำหรับ MVP:

| Overall Confidence | Action |
|---|---|
| `>= 0.85` | Auto Accept |
| `0.65 – 0.84` | Accept แต่ mark เป็น uncertain |
| `0.50 – 0.64` | Low confidence / Review |
| `< 0.50` | Reject หรือไม่บันทึกอัตโนมัติ |

Threshold นี้เป็น **ค่าเริ่มต้น** และควรปรับหลังจากทดสอบกับ JD จริง

ไม่ควรถือว่าเป็นค่าตายตัวตั้งแต่แรก

---

## 11. Relationship Between Confidence and Importance

ต้องแยกสองแนวคิดนี้อย่างชัดเจน:

```text
importance_weight
= Skill นี้สำคัญต่อ Job แค่ไหน

confidence
= เรามั่นใจแค่ไหนว่า Extraction ถูก
```

จึงสามารถเกิดกรณี:

```text
importance_weight = 0.97
overall_confidence = 0.55
```

ความหมาย:

> ถ้าการตีความนี้ถูก Skill นี้สำคัญมาก แต่ระบบยังไม่มั่นใจในการ extraction

หรือ:

```text
importance_weight = 0.30
overall_confidence = 0.99
```

ความหมาย:

> ระบบมั่นใจมากว่า Skill นี้เป็น Skill เสริมและมีความสำคัญต่ำ

### Final Confidence Flow

```text
JD
 ↓
LLM Extraction
 ↓
skill
requirement_type
proficiency_level
evidence_text
 ↓
Skill Normalization
 ↓
Rule Engine
 ├── skill_confidence
 ├── requirement_confidence
 ├── proficiency_confidence
 ├── overall_confidence
 └── importance_weight
 ↓
market.job_skills
```

หลักสำคัญ:

> LLM ใช้เพื่อเข้าใจภาษาและ Context  
> ส่วน Confidence และ Importance ใช้ Rule ที่ทีมกำหนด เพื่อให้ผลสม่ำเสมอ ทดสอบได้ และอธิบายได้

## 12. Final Skill Extraction Output

หลังผ่าน:

```text
LLM Extraction
+
Normalization
+
Scoring
```

Final Output:

```json
{
  "job_id": 101,
  "skills": [
    {
      "skill_id": 1,
      "skill_name": "Python",
      "raw_skill_name": "Python",

      "requirement_type": "required",
      "proficiency_level": "advanced",

      "importance_weight": 0.97,

      "skill_confidence": 0.99,
      "requirement_confidence": 0.99,
      "proficiency_confidence": 0.95,
      "overall_confidence": 0.98,

      "evidence_text": "Strong Python skills are required.",

      "extraction_method": "llm_rule_hybrid"
    },
    {
      "skill_id": 2,
      "skill_name": "SQL",
      "raw_skill_name": "SQL",

      "requirement_type": "preferred",
      "proficiency_level": "beginner",

      "importance_weight": 0.57,

      "skill_confidence": 0.99,
      "requirement_confidence": 0.95,
      "proficiency_confidence": 0.95,
      "overall_confidence": 0.96,

      "evidence_text": "Basic SQL knowledge is preferred.",

      "extraction_method": "llm_rule_hybrid"
    }
  ]
}
```

---

## 13. Recommended `market.job_skills` Schema

ควรใช้ประมาณ:

```text
market.job_skills

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

---

## 14. Why Evidence Text Is Important

`evidence_text` ช่วย:

1. Debug Extraction
2. Explain Result
3. Human Validation
4. Improve Prompt
5. Review Wrong Classification

ตัวอย่าง:

```json
{
  "skill": "Kafka",
  "requirement_type": "preferred",
  "proficiency_level": "beginner",
  "evidence_text": "Basic Kafka knowledge would be a plus."
}
```

---

## 15. Extraction Method

ค่าที่แนะนำ:

```text
llm
rule
hybrid
manual
```

สำหรับ Glow-Job เหมาะกับ:

```text
llm_rule_hybrid
```

เพราะ:

```text
LLM
→ Context Understanding

Rule
→ Standardization / Scoring

Skill Master
→ Normalization
```

---

## 16. Market Aggregation

เมื่อมี `market.job_skills` จากหลาย Job แล้ว จึง aggregate เป็น:

```text
market.career_skill_stats
```

ตัวอย่าง:

```text
200 Data Engineer Jobs

Python found = 170

required = 140
preferred = 25
optional = 5
```

ได้:

```text
demand_count = 170
total_jobs = 200
demand_percentage = 85%
```

---

## 17. Weighted Market Demand

เพื่อไม่ให้ Skill ที่ Optional เยอะมีน้ำหนักเท่ากับ Skill ที่ Required เยอะ

แนะนำ:

```text
weighted_demand_score
=
SUM(job_skill.importance_weight)
/
total_jobs
```

ดังนั้น Skill ที่มีทั้ง frequency สูงและ importance สูงจะเด่นขึ้น

---

## 18. Market Target Level

ใช้ `proficiency_level` ของหลาย Job เพื่อหา `target_level`

ตัวอย่าง Airflow:

```text
beginner      10
intermediate  45
advanced      20
unknown       15
```

ไม่ใช้ `unknown` ในการเลือกระดับเป้าหมาย

```text
level_observation_count = 75
```

แล้วสามารถสรุป:

```text
target_level = intermediate
```

ในอนาคตสามารถเพิ่ม weighting ให้ Required JD มีน้ำหนักมากกว่า Preferred JD ได้

---

## 19. `career_skill_stats` Example

```json
{
  "career": "Data Engineer",
  "skill_id": 3,
  "skill_name": "Apache Airflow",

  "demand_count": 110,
  "total_jobs": 240,
  "demand_percentage": 45.83,

  "required_count": 70,
  "preferred_count": 32,
  "optional_count": 8,

  "weighted_demand_score": 0.39,

  "target_level": "intermediate",
  "target_level_confidence": 0.72,
  "level_observation_count": 66,

  "importance_tier": "important"
}
```

---

## 20. Full Processing Example

Input JD:

```text
We are looking for a Data Engineer with strong Python skills.
Advanced Python programming is required.

Candidates should have experience with SQL and relational databases.

Basic Kafka knowledge would be a plus.
```

### Step 1 — LLM Extraction

```json
[
  {
    "skill": "Python",
    "requirement_type": "required",
    "proficiency_level": "advanced",
    "evidence_text": "Advanced Python programming is required."
  },
  {
    "skill": "SQL",
    "requirement_type": "required",
    "proficiency_level": "unknown",
    "evidence_text": "Candidates should have experience with SQL and relational databases."
  },
  {
    "skill": "Kafka",
    "requirement_type": "preferred",
    "proficiency_level": "beginner",
    "evidence_text": "Basic Kafka knowledge would be a plus."
  }
]
```

### Step 2 — Normalization

```text
Python → Python
SQL → SQL
Kafka → Apache Kafka
```

### Step 3 — Importance

```text
Python
required + advanced
→ 0.97

SQL
required + unknown
→ 0.88

Kafka
preferred + beginner
→ 0.57
```

### Step 4 — Confidence

ประเมินจาก explicit evidence ของแต่ละ Field

### Step 5 — Save

```text
market.job_skills
```

---

## 21. Responsibilities

### LLM / NLP

รับผิดชอบ:

```text
Skill Detection
Requirement Classification
Proficiency Classification
Evidence Extraction
Context Understanding
```

### Rule Engine

รับผิดชอบ:

```text
Importance Calculation
Confidence Calculation
Threshold
Validation Rules
```

### Skill Normalization

รับผิดชอบ:

```text
raw skill
→ core.skills.skill_id
```

ใช้:

```text
Exact Match
Alias
RapidFuzz
Embedding fallback
```

### Market Aggregation

รับผิดชอบ:

```text
market.job_skills
→ market.career_skill_stats
```

---

## 22. Recommended Final Architecture

```text
                    Job Description
                           │
                           ▼
                    Text Preparation
                           │
                           ▼
                     LLM Extraction
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
       Skill         Requirement         Proficiency
         │                 │                 │
         └─────────────────┼─────────────────┘
                           │
                           ▼
                    Evidence Text
                           │
                           ▼
                  Skill Normalization
                           │
                           ▼
                      Rule Engine
                    /             \
                   /               \
         Importance Weight       Confidence
                   \               /
                    \             /
                           ▼
                   market.job_skills
                           │
                           ▼
                  Market Aggregation
                           │
                           ▼
               market.career_skill_stats
                           │
                           ▼
                   Career Baseline
                           │
                           ▼
                       AI Agent
```

---

## 23. Key Design Decisions

ทีมควรยึดหลัก:

1. **LLM อ่าน Context แต่ไม่ควรสร้างคะแนน arbitrary**
2. `requirement_type` และ `proficiency_level` เป็นคนละมิติ
3. `importance_weight` ต้อง deterministic
4. Confidence ต้องสะท้อนความชัดเจนของ Evidence
5. ควรแยก Confidence ต่อ Field
6. `evidence_text` ต้องเก็บเพื่อ Debug และ Explain
7. Skill ต้อง Normalize ก่อนลง Market Analytics
8. Job-level data อยู่ใน `market.job_skills`
9. Career-level summary อยู่ใน `market.career_skill_stats`
10. AI Agent ควรใช้ Market Summary ไม่ควรต้องอ่าน JD ทั้งหมดทุกครั้ง

---

## 24. Summary

Final Skill Extraction ของ Glow-Job ไม่ใช่เพียง:

```json
["Python", "SQL", "Airflow"]
```

แต่เป็น:

```text
Skill
+
Requirement
+
Required Proficiency
+
Importance
+
Confidence
+
Evidence
```

สิ่งนี้ทำให้ระบบสามารถเปลี่ยน:

```text
Raw Job Descriptions
```

ให้กลายเป็น:

```text
Structured Job Market Intelligence
```

และสุดท้าย Agent สามารถตอบได้ว่า:

```text
ตลาดต้องการ Skill อะไร
Skill ไหนสำคัญ
ต้องเก่งระดับไหน
User ยังขาดอะไร
และควรพัฒนาอะไรต่อ
```
