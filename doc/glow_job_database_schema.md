# Glow-Job Database Schema Documentation

## 1. Overview

เอกสารนี้อธิบายโครงสร้างฐานข้อมูลของ **Glow-Job** จาก schema ล่าสุดที่ขยายมาจาก `glow_job_data_pipeline` เดิม ให้รองรับทั้ง:

- Job Market Data
- User / Application Data
- RAG / Skill Knowledge
- Skill Dependency Graph
- Personalized Roadmap
- User Progress
- Re-planning
- Operational Metadata

ระบบแนะนำให้ใช้ **PostgreSQL / Amazon RDS เพียง 1 database instance** ก่อน แล้วแบ่งข้อมูลออกเป็น logical schema ตาม domain เพื่อให้ทีมสามารถแยก ownership และพัฒนาแบบขนานกันได้ง่าย

```text
PostgreSQL / Amazon RDS
│
├── core
│   ├── companies
│   ├── careers
│   ├── career_profiles
│   ├── skills
│   └── skill_aliases
│
├── market
│   ├── job_postings
│   ├── job_skills
│   └── career_skill_stats
│
├── knowledge
│   ├── knowledge_sources
│   ├── knowledge_chunks
│   ├── skill_dependencies
│   └── learning_modules
│
├── app
│   ├── users
│   ├── user_profiles
│   ├── resumes
│   ├── user_experiences
│   ├── user_skills
│   ├── roadmaps
│   ├── roadmap_items
│   ├── roadmap_tasks
│   ├── user_progress
│   ├── user_task_progress
│   ├── applications
│   └── application_feedback
│
└── system
    ├── ingestion_runs
    └── ai_runs
```

---

# 2. การแบ่ง Domain ของ Database

## 2.1 `core`

### หน้าที่

`core` คือข้อมูลกลางที่ทั้งฝั่ง Market, App, RAG และ AI Agent ใช้ร่วมกัน

ถือเป็น **Shared Canonical Data**

ตัวอย่างเช่น Skill `Apache Airflow` ควรมี `skill_id` เดียวกันทั้งระบบ

```text
core.skills

skill_id = 42
skill_name = Apache Airflow
```

จากนั้น:

```text
market.job_skills.skill_id = 42
app.user_skills.skill_id = 42
knowledge.skill_dependencies.target_skill_id = 42
app.roadmap_items.skill_id = 42
```

ข้อดีคือไม่เกิดปัญหา:

```text
Market -> "Apache Airflow"
App    -> "Airflow"
RAG    -> "apache-airflow"
```

แล้วต้องมา map กันภายหลัง

### ใช้โดย

- Market
- App
- RAG
- AI Agent
- Roadmap Engine

---

## 2.2 `market`

### หน้าที่

เก็บข้อมูลเกี่ยวกับ **ตลาดแรงงาน**

ตอบคำถาม เช่น:

- ตอนนี้ Data Engineer ต้องการ Skill อะไร
- Skill ไหนพบใน JD เยอะ
- Skill ไหน Required / Preferred
- ตลาดส่วนใหญ่คาดหวังระดับ Skill แค่ไหน
- Skill ไหนควรเป็น Core / Important / Optional

ข้อมูลส่วนนี้มาจาก pipeline เช่น:

```text
JSearch API
    ↓
Raw Job Data
    ↓
Clean
    ↓
Normalize
    ↓
Skill Extraction
    ↓
Aggregate
    ↓
market.*
```

### ใช้โดย

- Data Pipeline
- Market Intelligence
- AI Agent
- Skill Gap Engine
- Roadmap Engine

---

## 2.3 `knowledge`

### หน้าที่

เก็บข้อมูลสำหรับ **RAG และ Skill Knowledge**

ตอบคำถาม เช่น:

- Apache Airflow คืออะไร
- ก่อน Airflow ควรรู้อะไร
- Skill A ควรเรียนก่อน Skill B หรือไม่
- ระดับ Beginner ของ Airflow มีหัวข้ออะไร
- ระดับ Intermediate ต้องทำอะไรได้
- Agent ควร retrieve เอกสารไหนมาใช้เป็น context

ส่วนนี้ไม่เหมือน `market`

```text
market
= ตลาดต้องการอะไร

knowledge
= Skill คืออะไร และควรเรียนอย่างไร
```

### ใช้โดย

- RAG Engineer
- Vector Retrieval
- Skill Dependency Graph
- AI Agent
- Roadmap Engine

---

## 2.4 `app`

### หน้าที่

เก็บข้อมูลของ **ผู้ใช้และ Product**

ตอบคำถาม เช่น:

- User คือใคร
- User มี Skill อะไร
- User อยากเป็นอะไร
- User มีเวลาเรียนเท่าไร
- Roadmap ปัจจุบันคืออะไร
- User ทำ Roadmap ไปถึงไหนแล้ว
- Skill ไหน Completed แล้ว
- ต้อง Re-plan หรือไม่

### ใช้โดย

- Backend
- Frontend
- AI Agent
- Roadmap Engine
- Progress Tracking

---

## 2.5 `system`

### หน้าที่

เก็บข้อมูลเชิง operational

เช่น:

- Data Pipeline รอบล่าสุดสำเร็จหรือไม่
- ดึง Job มาเท่าไร
- AI operation ไหน fail
- ใช้ model ไหน
- Re-plan เกิดเมื่อไร

ไม่ได้เป็นข้อมูลหลักของ Product แต่มีประโยชน์ต่อ:

- Monitoring
- Debugging
- Pipeline Tracking
- AI Operation Tracking

---

# 3. Enum ที่ใช้ร่วมกัน

## 3.1 `requirement_type`

ใช้บอกว่า Skill ใน JD มีความสำคัญแบบใด

| Value | ความหมาย |
|---|---|
| `required` | บริษัทต้องการ Skill นี้โดยตรง |
| `preferred` | มีจะได้เปรียบ แต่ไม่จำเป็น |
| `optional` | เป็น Skill เสริม |
| `unknown` | ไม่สามารถระบุได้ |

---

## 3.2 `proficiency_level`

ใช้เป็นระดับมาตรฐานเดียวกันของทั้ง Market และ User

| Value | ความหมาย |
|---|---|
| `beginner` | เข้าใจพื้นฐาน / ใช้งานเบื้องต้น |
| `intermediate` | ใช้งานจริงได้ |
| `advanced` | ใช้งานในสถานการณ์ซับซ้อนได้ |
| `expert` | ระดับเชี่ยวชาญ |
| `unknown` | ไม่สามารถระบุได้ |

---

## 3.3 `importance_tier`

ใช้จัด Skill ใน Career Baseline

| Value | ความหมาย |
|---|---|
| `core` | Skill หลักของอาชีพ |
| `important` | สำคัญ แต่ไม่จำเป็นในทุกตำแหน่ง |
| `optional` | Skill เสริมหรือ specialization |
| `unknown` | ยังระบุไม่ได้ |

---

## 3.4 `dependency_type`

ใช้ใน Skill Graph

| Value | ความหมาย |
|---|---|
| `prerequisite` | ต้องรู้ก่อน |
| `recommended_before` | แนะนำให้รู้ก่อน |
| `related` | Skill ที่เกี่ยวข้อง |

---

## 3.5 `dependency_strength`

ใช้บอกความแรงของ dependency

| Value | ความหมาย |
|---|---|
| `required` | ควรถือเป็น prerequisite จริง |
| `strong` | ความสัมพันธ์สูง |
| `recommended` | แนะนำ |
| `weak` | ความสัมพันธ์อ่อน |

---

## 3.6 `user_skill_source`

บอกว่า Skill ของ User มาจากไหน

- `resume`
- `self_report`
- `assessment`
- `project`
- `application_feedback`
- `system_inferred`

---

## 3.7 `verification_type`

บอกระดับหลักฐานของ Skill

- `self_report`
- `assessment`
- `project_evidence`
- `real_world_outcome`
- `unverified`

---

## 3.8 `roadmap_status`

- `active`
- `completed`
- `replaced`
- `archived`

---

## 3.9 `progress_status`

- `not_started`
- `in_progress`
- `completed`
- `skipped`

---

# 4. CORE Schema

---

# 4.1 `core.companies`

## หน้าที่

เก็บข้อมูลบริษัทแบบ canonical

ใช้ทั้ง Market และ App

ตัวอย่าง:

```text
Company ID = 10
Company Name = Agoda
```

แล้ว:

```text
market.job_postings.company_id = 10
app.applications.company_id = 10
```

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `company_id` | bigint | Primary Key ของบริษัท |
| `company_name` | text | ชื่อบริษัทที่ใช้แสดงผล |
| `normalized_name` | text | ชื่อที่ normalize แล้ว เช่น lowercase / ตัด suffix เพื่อใช้ deduplicate |
| `company_website` | text | เว็บไซต์ของบริษัท |
| `created_at` | timestamptz | เวลาที่สร้าง record |
| `updated_at` | timestamptz | เวลาแก้ไขล่าสุด |

### เหตุผลที่มี `normalized_name`

ข้อมูลจากหลาย source อาจเขียนบริษัทต่างกัน เช่น:

```text
Agoda
Agoda Company Pte. Ltd.
AGODA
```

สามารถ normalize ให้เทียบกันได้ง่ายขึ้น

---

# 4.2 `core.careers`

## หน้าที่

เก็บ Career หลัก

ตัวอย่าง:

```text
Data Engineer
Data Analyst
Backend Engineer
```

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `career_id` | bigint | Primary Key |
| `slug` | text | Stable key เช่น `data_engineer` |
| `career_name` | text | ชื่ออาชีพที่แสดง |
| `description` | text | คำอธิบายอาชีพ |
| `is_active` | boolean | เปิด/ปิด Career ในระบบ |
| `created_at` | timestamptz | เวลาสร้าง |
| `updated_at` | timestamptz | เวลาอัปเดต |

---

# 4.3 `core.career_profiles`

## หน้าที่

เก็บ Career + Seniority

แยกจาก `careers` เพราะ:

```text
Junior Data Engineer
Data Engineer
Senior Data Engineer
```

ต้องการ Skill level ไม่เท่ากัน

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `career_profile_id` | bigint | Primary Key |
| `career_id` | bigint | FK ไป `core.careers` |
| `slug` | text | เช่น `junior_data_engineer` |
| `profile_name` | text | ชื่อ Profile |
| `seniority_level` | text | junior / mid / senior / general |
| `description` | text | รายละเอียด Profile |
| `is_active` | boolean | ใช้งานอยู่หรือไม่ |
| `created_at` | timestamptz | เวลาสร้าง |
| `updated_at` | timestamptz | เวลาอัปเดต |

### ความสัมพันธ์

```text
Data Engineer
│
├── Junior Data Engineer
├── General Data Engineer
└── Senior Data Engineer
```

---

# 4.4 `core.skills`

## หน้าที่

เป็น Skill Master กลางของทั้งระบบ

ถือเป็น table สำคัญที่สุดตัวหนึ่ง

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `skill_id` | bigint | Primary Key |
| `skill_name` | text | ชื่อ canonical เช่น `Apache Airflow` |
| `skill_category` | text | เช่น Programming, Database, Cloud, Data Orchestration |
| `description` | text | คำอธิบาย Skill |
| `created_at` | timestamptz | เวลาสร้าง |
| `updated_at` | timestamptz | เวลาอัปเดต |

---

# 4.5 `core.skill_aliases`

## หน้าที่

ใช้ normalize ชื่อ Skill ที่แตกต่างกัน

ตัวอย่าง:

```text
Canonical:
PostgreSQL

Aliases:
Postgres
Postgre SQL
postgresql
```

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `alias_id` | bigint | Primary Key |
| `skill_id` | bigint | Skill canonical |
| `alias` | text | ชื่ออื่นของ Skill |
| `created_at` | timestamptz | เวลาสร้าง |

---

# 5. MARKET Schema

---

# 5.1 `market.job_postings`

## หน้าที่

เก็บ Job Description แต่ละตำแหน่งจาก Job Provider

เป็นข้อมูลระดับ Raw/Structured Job Posting

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `job_id` | bigint | Internal Primary Key |
| `provider_job_id` | text | Job ID จาก provider เช่น JSearch |
| `company_id` | bigint | บริษัท |
| `career_profile_id` | bigint | Career/Profile ที่ job ถูก map เข้า |
| `job_title` | text | Job title ต้นฉบับ |
| `normalized_job_title` | text | Job title หลัง normalize |
| `job_description` | text | JD เต็ม |
| `location` | text | location ต้นฉบับ |
| `city` | text | เมือง |
| `state` | text | รัฐ/จังหวัด |
| `country` | char(2) | Country code |
| `employment_type` | text | Full-time / Contract / Internship |
| `provider` | text | Provider ที่ดึงข้อมูล เช่น JSearch |
| `publisher` | text | Source ที่ provider อ้าง เช่น LinkedIn |
| `source_url` | text | URL ต้นทาง |
| `posted_at` | timestamptz | วันที่ประกาศ |
| `collected_at` | timestamptz | วันที่ Pipeline เก็บ |
| `search_query` | text | Query ที่ใช้ดึง |
| `created_at` | timestamptz | เวลาสร้าง |
| `updated_at` | timestamptz | เวลาอัปเดต |

### Provider vs Publisher

```text
provider = JSearch
publisher = LinkedIn
```

ไม่ควรรวมกันเพราะมีความหมายต่างกัน

---

# 5.2 `market.job_skills`

## หน้าที่

เก็บ Skill ที่ extract ได้จาก JD แต่ละงาน

ตอบคำถามว่า:

> งานนี้ต้องการ Skill อะไร และต้องการในระดับไหน

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `job_id` | bigint | Job ที่ Skill นี้มาจาก |
| `skill_id` | bigint | Skill canonical |
| `requirement_type` | enum | required / preferred / optional |
| `proficiency_level` | enum | beginner / intermediate / advanced |
| `importance_weight` | numeric | น้ำหนักความสำคัญ 0-1 |
| `confidence` | numeric | ความมั่นใจของ extraction |
| `evidence_text` | text | ข้อความใน JD ที่ใช้เป็นหลักฐาน |
| `extraction_method` | text | เช่น `llm`, `rule`, `hybrid` |
| `created_at` | timestamptz | เวลาสร้าง |

### ตัวอย่าง

JD:

```text
Strong Airflow experience is required.
Basic Kafka knowledge is preferred.
```

ผล:

```text
Airflow
requirement = required
level = advanced
importance = 1.0

Kafka
requirement = preferred
level = beginner
importance = 0.4
```

---

# 5.3 `market.career_skill_stats`

## หน้าที่

เป็น Market Baseline ของ Career/Profile

เป็นผล aggregate จาก `job_skills`

ตัวอย่าง:

```text
Junior Data Engineer

SQL       85%  intermediate  core
Python    78%  intermediate  core
Airflow   46%  beginner      important
Kafka     22%  beginner      optional
```

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `career_profile_id` | bigint | Career/Profile |
| `skill_id` | bigint | Skill |
| `analysis_start_date` | date | วันเริ่มช่วงข้อมูล |
| `analysis_end_date` | date | วันสิ้นสุดช่วงข้อมูล |
| `demand_count` | integer | จำนวน Job ที่พบ Skill |
| `total_jobs` | integer | จำนวน Job ทั้งหมดใน analysis |
| `demand_percentage` | numeric | % ที่พบ Skill |
| `required_count` | integer | จำนวนครั้งที่เป็น required |
| `preferred_count` | integer | จำนวนครั้งที่เป็น preferred |
| `optional_count` | integer | จำนวนครั้งที่เป็น optional |
| `weighted_demand_score` | numeric | คะแนน Demand หลังคำนึงถึง requirement |
| `target_level` | enum | ระดับที่ตลาดโดยรวมคาดหวัง |
| `target_level_confidence` | numeric | ความมั่นใจของ target level |
| `level_observation_count` | integer | จำนวน JD ที่ระบุระดับจนใช้สรุปได้ |
| `importance_tier` | enum | core / important / optional |
| `last_updated` | timestamptz | เวลา aggregate ล่าสุด |

### เหตุผลที่ต้องมี `level_observation_count`

เพราะหลาย JD อาจบอกว่า:

```text
Airflow required
```

แต่ไม่ได้บอกว่า:

```text
beginner / intermediate / advanced
```

ดังนั้นควรรู้ว่าข้อสรุป target level มาจากข้อมูลจำนวนเท่าไร

---

# 6. KNOWLEDGE / RAG Schema

---

# 6.1 `knowledge.knowledge_sources`

## หน้าที่

เก็บ metadata ของ Knowledge Source ที่ RAG ใช้

ไฟล์จริงควรอยู่ S3

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `source_id` | bigint | Primary Key |
| `skill_id` | bigint | ถ้า Source เกี่ยวกับ Skill เฉพาะ |
| `source_type` | text | official_docs / course / article / learning_path |
| `title` | text | ชื่อ Source |
| `source_url` | text | URL ต้นทาง |
| `storage_key` | text | S3 path |
| `publisher` | text | ผู้จัดทำ |
| `is_active` | boolean | ยังใช้งาน Source นี้หรือไม่ |
| `collected_at` | timestamptz | เวลาเก็บ |
| `updated_at` | timestamptz | เวลาอัปเดต |

---

# 6.2 `knowledge.knowledge_chunks`

## หน้าที่

เก็บข้อความที่ผ่าน Chunking แล้วสำหรับ RAG

flow:

```text
Document
   ↓
Clean
   ↓
Chunk
   ↓
Embedding
   ↓
knowledge_chunks
```

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `chunk_id` | bigint | Primary Key |
| `source_id` | bigint | Source ต้นทาง |
| `skill_id` | bigint | Skill ที่เกี่ยวข้อง |
| `topic` | text | เช่น prerequisite / concept / learning_outcome |
| `chunk_index` | integer | ลำดับ Chunk |
| `content` | text | ข้อความของ Chunk |
| `metadata` | jsonb | Metadata เพิ่มเติม |
| `embedding_model` | text | Model ที่ใช้สร้าง embedding |
| `embedding` | vector | Vector สำหรับ semantic search |
| `created_at` | timestamptz | เวลาสร้าง |

### `metadata`

สามารถเก็บข้อมูล flexible เช่น:

```json
{
  "section": "Prerequisites",
  "language": "en",
  "version": "3.0"
}
```

---

# 6.3 `knowledge.skill_dependencies`

## หน้าที่

เก็บ Skill Dependency Graph

ตอบคำถาม:

> Skill ไหนควรเรียนก่อน Skill ไหน

ตัวอย่าง:

```text
Python
  ↓
ETL Concepts
  ↓
Apache Airflow
```

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `dependency_id` | bigint | Primary Key |
| `prerequisite_skill_id` | bigint | Skill ที่ควรมาก่อน |
| `target_skill_id` | bigint | Skill เป้าหมาย |
| `dependency_type` | enum | prerequisite / recommended_before / related |
| `strength` | enum | ความสำคัญของ dependency |
| `confidence` | numeric | ความมั่นใจ |
| `source_id` | bigint | Source ที่สนับสนุน relation |
| `evidence_text` | text | Evidence |
| `is_verified` | boolean | ผ่าน validation แล้วหรือไม่ |
| `created_at` | timestamptz | เวลาสร้าง |
| `updated_at` | timestamptz | เวลาอัปเดต |

### เหตุผลที่มี `is_verified`

LLM สามารถช่วย extract relation ได้ แต่ไม่ควรถือว่าเป็น source of truth ทันที

---

# 6.4 `knowledge.learning_modules`

## หน้าที่

กำหนด scope การเรียนของแต่ละ Skill

ตัวอย่าง:

```text
Apache Airflow

Beginner
├── DAG Concepts
├── Basic Tasks
├── Operators
└── Scheduling

Intermediate
├── Task Dependencies
├── Connections
├── Retry Handling
└── ETL Pipeline
```

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `module_id` | bigint | Primary Key |
| `skill_id` | bigint | Skill |
| `level` | enum | Level ของ Module |
| `title` | text | หัวข้อ |
| `description` | text | รายละเอียด |
| `learning_outcome` | text | เมื่อเรียนจบควรทำอะไรได้ |
| `sequence_order` | integer | ลำดับ |
| `estimated_hours` | numeric | เวลาประมาณการ |
| `is_active` | boolean | ใช้งานอยู่หรือไม่ |
| `created_at` | timestamptz | เวลาสร้าง |
| `updated_at` | timestamptz | เวลาอัปเดต |

---

# 7. APP Schema

---

# 7.1 `app.users`

## หน้าที่

เก็บ Account Identity

ไม่ควรเก็บ password plaintext

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `user_id` | bigint | Primary Key |
| `email` | text | Email |
| `auth_provider` | text | เช่น Cognito / Google |
| `auth_subject` | text | User ID จาก Auth Provider |
| `is_active` | boolean | Account active หรือไม่ |
| `created_at` | timestamptz | เวลาสร้าง |
| `updated_at` | timestamptz | เวลาอัปเดต |

---

# 7.2 `app.user_profiles`

## หน้าที่

เก็บ User Background ที่ Agent ใช้ Personalize Roadmap

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `user_id` | bigint | User |
| `target_career_profile_id` | bigint | Career เป้าหมาย |
| `current_status` | text | student / employed / career_switcher |
| `education_level` | text | ระดับการศึกษา |
| `field_of_study` | text | สาขา |
| `current_role` | text | Role ปัจจุบัน |
| `experience_years` | numeric | ประสบการณ์ |
| `target_duration_months` | integer | ระยะเวลาที่อยากไปถึงเป้าหมาย |
| `available_hours_per_week` | numeric | เวลาที่มีต่อสัปดาห์ |
| `preferred_learning_style` | text | รูปแบบการเรียน |
| `background_text` | text | Background แบบ free text |
| `created_at` | timestamptz | เวลาสร้าง |
| `updated_at` | timestamptz | เวลาอัปเดต |

---

# 7.3 `app.resumes`

## หน้าที่

เก็บ metadata ของ Resume

File จริงอยู่ S3

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `resume_id` | bigint | Primary Key |
| `user_id` | bigint | เจ้าของ Resume |
| `file_name` | text | ชื่อไฟล์ |
| `storage_key` | text | S3 Key |
| `extraction_status` | text | pending / completed / failed |
| `extracted_text` | text | Text หลัง extract ถ้าต้องการ |
| `uploaded_at` | timestamptz | เวลา upload |
| `processed_at` | timestamptz | เวลาประมวลผล |

---

# 7.4 `app.user_experiences`

## หน้าที่

เก็บ Experience ของ User

เช่น:

- Work
- Internship
- Project
- Education
- Competition
- Course

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `experience_id` | bigint | Primary Key |
| `user_id` | bigint | User |
| `experience_type` | enum | ประเภท Experience |
| `title` | text | ชื่อ |
| `organization` | text | บริษัท/มหาวิทยาลัย/องค์กร |
| `description` | text | รายละเอียด |
| `start_date` | date | วันเริ่ม |
| `end_date` | date | วันจบ |
| `source` | text | resume / self_report |
| `created_at` | timestamptz | เวลาสร้าง |
| `updated_at` | timestamptz | เวลาอัปเดต |

---

# 7.5 `app.user_skills`

## หน้าที่

เก็บ Current Skill State ของ User

เป็น table ที่ใช้เทียบกับ `market.career_skill_stats`

```text
Market Baseline
      -
User Skills
      =
Skill Gap
```

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `user_id` | bigint | User |
| `skill_id` | bigint | Skill |
| `proficiency_level` | enum | ระดับของ User |
| `source` | enum | Skill มาจากไหน |
| `confidence` | numeric | ความมั่นใจ |
| `verification_type` | enum | วิธี verify |
| `evidence_reference` | text | หลักฐาน |
| `verified_at` | timestamptz | เวลา verify |
| `created_at` | timestamptz | เวลาสร้าง |
| `updated_at` | timestamptz | เวลาอัปเดต |

---

# 8. ROADMAP Schema

---

# 8.1 `app.roadmaps`

## หน้าที่

เก็บ Roadmap ของ User แบบ Versioned

ไม่ควร overwrite Roadmap เดิม

ตัวอย่าง:

```text
V1 = Initial
V2 = Progress Update
V3 = Market Update
V4 = Application Feedback
```

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `roadmap_id` | bigint | Primary Key |
| `user_id` | bigint | เจ้าของ Roadmap |
| `target_career_profile_id` | bigint | Career Target |
| `version` | integer | Version |
| `status` | enum | active / completed / replaced |
| `generation_reason` | text | ทำไม Roadmap นี้ถูกสร้าง |
| `market_analysis_start_date` | date | Market Window เริ่มต้น |
| `market_analysis_end_date` | date | Market Window สิ้นสุด |
| `generated_at` | timestamptz | เวลาที่ Agent สร้าง |

---

# 8.2 `app.roadmap_items`

## หน้าที่

เก็บ Step หลักของ Roadmap

ตัวอย่าง:

```text
1. ETL Concepts
2. Apache Airflow
3. AWS
```

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `roadmap_item_id` | bigint | Primary Key |
| `roadmap_id` | bigint | Roadmap |
| `skill_id` | bigint | Skill |
| `module_id` | bigint | Learning Module ถ้ามี |
| `sequence_order` | integer | ลำดับ |
| `title` | text | ชื่อ Step |
| `target_level` | enum | ระดับเป้าหมาย |
| `reason` | text | เหตุผลที่ Agent เลือก |
| `estimated_hours` | numeric | เวลาที่คาด |
| `is_required` | boolean | จำเป็นหรือ optional |
| `created_at` | timestamptz | เวลาสร้าง |

---

# 8.3 `app.roadmap_tasks`

## หน้าที่

Checklist ย่อยในแต่ละ Roadmap Item

ตัวอย่าง:

```text
Apache Airflow

[x] Understand DAG
[x] Build Basic DAG
[ ] Connections
[ ] Retry Handling
[ ] Build ETL Pipeline
```

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `task_id` | bigint | Primary Key |
| `roadmap_item_id` | bigint | Item ที่ Task อยู่ใต้ |
| `title` | text | Task |
| `description` | text | รายละเอียด |
| `sequence_order` | integer | ลำดับ |
| `is_required` | boolean | จำเป็นหรือไม่ |
| `created_at` | timestamptz | เวลาสร้าง |

---

# 8.4 `app.user_progress`

## หน้าที่

เก็บ Progress ระดับ Roadmap Item

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `progress_id` | bigint | Primary Key |
| `user_id` | bigint | User |
| `roadmap_item_id` | bigint | Roadmap Item |
| `status` | enum | not_started / in_progress / completed / skipped |
| `progress_percentage` | numeric | 0-100 |
| `user_note` | text | Note จาก User |
| `started_at` | timestamptz | เวลาเริ่ม |
| `completed_at` | timestamptz | เวลาจบ |
| `updated_at` | timestamptz | เวลาอัปเดต |

### Progress สามารถคำนวณจาก Task

```text
3 completed / 5 total
= 60%
```

---

# 8.5 `app.user_task_progress`

## หน้าที่

เก็บ progress ระดับ Task

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `user_id` | bigint | User |
| `task_id` | bigint | Task |
| `status` | enum | progress status |
| `completed_at` | timestamptz | เวลาที่เสร็จ |
| `updated_at` | timestamptz | เวลาอัปเดต |

---

# 9. Application Tracking

ส่วนนี้สามารถถือเป็น Phase 2 ของ MVP

---

# 9.1 `app.applications`

## หน้าที่

เก็บ Job Application ของ User

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `application_id` | bigint | Primary Key |
| `user_id` | bigint | User |
| `job_id` | bigint | Job จาก Market ถ้ามี |
| `company_id` | bigint | บริษัท |
| `job_title` | text | Job title |
| `status` | enum | applied / interview / rejected / offer |
| `applied_at` | timestamptz | วันที่สมัคร |
| `created_at` | timestamptz | เวลาสร้าง |
| `updated_at` | timestamptz | เวลาอัปเดต |

---

# 9.2 `app.application_feedback`

## หน้าที่

เก็บ Feedback จากการสมัครงาน

ใช้เป็น input สำหรับ Re-planning

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `feedback_id` | bigint | Primary Key |
| `application_id` | bigint | Application |
| `feedback_type` | text | ประเภท Feedback |
| `feedback_text` | text | Feedback ต้นฉบับ |
| `extracted_reason` | text | Reason ที่ AI extract |
| `created_at` | timestamptz | เวลาสร้าง |

---

# 10. SYSTEM Schema

---

# 10.1 `system.ingestion_runs`

## หน้าที่

ติดตาม Data Pipeline แต่ละรอบ

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `run_id` | bigint | Primary Key |
| `source` | text | Data Source |
| `career_profile_id` | bigint | Career ที่ดึง |
| `started_at` | timestamptz | เวลาเริ่ม |
| `finished_at` | timestamptz | เวลาจบ |
| `jobs_fetched` | integer | ดึงมาเท่าไร |
| `jobs_inserted` | integer | Insert เท่าไร |
| `jobs_updated` | integer | Update เท่าไร |
| `jobs_failed` | integer | Fail เท่าไร |
| `status` | enum | pending/running/completed/failed |
| `error_message` | text | Error ถ้ามี |
| `created_at` | timestamptz | เวลาสร้าง |

---

# 10.2 `system.ai_runs`

## หน้าที่

ติดตาม AI Operations

ตัวอย่าง:

```text
resume_extraction
roadmap_generation
replanning
skill_gap_analysis
```

## Columns

| Column | Type | หน้าที่ |
|---|---|---|
| `ai_run_id` | bigint | Primary Key |
| `user_id` | bigint | User ที่เกี่ยวข้อง |
| `operation_type` | text | AI operation |
| `model_provider` | text | Provider |
| `model_name` | text | Model |
| `status` | enum | Status |
| `started_at` | timestamptz | เวลาเริ่ม |
| `finished_at` | timestamptz | เวลาจบ |
| `error_message` | text | Error |

---

# 11. ความสัมพันธ์หลักระหว่าง Market และ App

ส่วนสำคัญที่สุดของ architecture คือ:

```text
                 core.skills
                     │
          ┌──────────┴───────────┐
          │                      │
          ▼                      ▼
market.career_skill_stats    app.user_skills
          │                      │
          └──────────┬───────────┘
                     ▼
                 Skill Gap
                     │
                     ▼
          knowledge.skill_dependencies
                     │
                     ▼
          knowledge.learning_modules
                     │
                     ▼
                  AI Agent
                     │
                     ▼
                app.roadmaps
```

ตัวอย่าง:

```text
Market

Airflow
target_level = intermediate
importance = important
demand = 46%

User

Airflow
level = beginner
```

ระบบจึงรู้ว่า:

```text
Skill Gap:
Airflow beginner → intermediate
```

จากนั้นดู:

```text
knowledge.skill_dependencies

ETL Concepts
→ Airflow
```

Agent จึงสามารถจัด Roadmap:

```text
1. ETL Concepts
2. Airflow Intermediate
```

---

# 12. Data Flow ทั้งระบบ

```text
                         JOB MARKET

JSearch
   ↓
Raw JSON (S3)
   ↓
Pipeline
   ↓
market.job_postings
   ↓
Skill Extraction
   ↓
market.job_skills
   ↓
Aggregation
   ↓
market.career_skill_stats


                         KNOWLEDGE

Official Docs
Courses
Learning Resources
   ↓
S3
   ↓
Chunking
   ↓
Embedding
   ↓
knowledge.knowledge_chunks
   ↓
RAG Retrieval

และ

Knowledge Sources
   ↓
LLM Extraction
   ↓
knowledge.skill_dependencies
knowledge.learning_modules


                           USER

User / Resume
   ↓
app.user_profiles
app.user_experiences
app.user_skills
   ↓
Skill Gap
   ↓
Agent
   ↓
app.roadmaps
   ↓
app.roadmap_items
   ↓
app.roadmap_tasks
   ↓
app.user_progress
   ↓
Re-plan
```

---

# 13. สิ่งที่เก็บใน RDS กับ S3

## Amazon RDS / PostgreSQL

เหมาะกับ:

- Structured Data
- Relations
- Market Statistics
- User Data
- Skills
- Roadmaps
- Progress
- Metadata
- Skill Graph

## Amazon S3

เหมาะกับ:

- Raw JSearch JSON
- Resume PDF
- HTML / PDF จาก Knowledge Sources
- Raw RAG documents
- Large unstructured files

ตัวอย่าง:

```text
s3://glow-job/

raw-jobs/
resumes/
knowledge/
```

---

# 14. MVP Priority

ถ้าเวลามีประมาณ 23 วัน ไม่จำเป็นต้อง implement ทุก table พร้อมกัน

## Core MVP

ควรทำก่อน:

```text
core.skills
core.skill_aliases
core.careers
core.career_profiles
core.companies

market.job_postings
market.job_skills
market.career_skill_stats

knowledge.knowledge_sources
knowledge.knowledge_chunks
knowledge.skill_dependencies
knowledge.learning_modules

app.users
app.user_profiles
app.resumes
app.user_experiences
app.user_skills

app.roadmaps
app.roadmap_items
app.roadmap_tasks
app.user_progress
app.user_task_progress

system.ingestion_runs
```

## Phase 2

สามารถเพิ่มทีหลัง:

```text
app.applications
app.application_feedback
system.ai_runs
```

---

# 15. Ownership ที่แนะนำสำหรับทีม

## Data / RAG Engineer

รับผิดชอบหลัก:

```text
core.skills
core.skill_aliases

market.*
knowledge.*
system.ingestion_runs
```

โดยเฉพาะ:

- Job Market Pipeline
- Skill normalization
- Career Skill Aggregation
- Knowledge ingestion
- Chunking
- Embedding
- RAG retrieval
- Skill Dependency

---

## Backend Engineer

รับผิดชอบหลัก:

```text
app.users
app.user_profiles
app.resumes
app.user_experiences
app.user_skills

app.roadmaps
app.roadmap_items
app.roadmap_tasks
app.user_progress
app.user_task_progress
```

---

## AI Engineer

ไม่จำเป็นต้องเป็น owner ของ schema หลัก แต่ใช้ข้อมูลจาก:

```text
market.career_skill_stats
app.user_skills
knowledge.skill_dependencies
knowledge.learning_modules
app.user_progress
```

เพื่อทำ:

```text
Skill Gap
Priority
Best Next Action
Roadmap
Re-planning
```

---

# 16. Summary

Glow-Job Database ถูกแบ่งเป็น 5 domain หลัก:

```text
CORE
= ข้อมูลกลาง

MARKET
= ตลาดต้องการอะไร

KNOWLEDGE
= Skill คืออะไร / เรียนอย่างไร / อะไรมาก่อนอะไร

APP
= User คือใคร / มีอะไร / ทำถึงไหนแล้ว

SYSTEM
= ระบบทำงานเป็นอย่างไร
```

หัวใจของการเชื่อมระบบคือ:

```text
core.skills
```

เพราะเชื่อม:

```text
Market
↕
User
↕
RAG
↕
Skill Graph
↕
Roadmap
```

และ core logic ของ Glow-Job สามารถมองเป็น:

```text
Market Career Baseline
          -
User Current Skills
          +
Skill Dependencies
          +
Learning Modules
          +
User Constraints
          =
Personalized Roadmap
```

เมื่อ User Progress เปลี่ยน:

```text
User Progress
      ↓
Update User State
      ↓
Recalculate Skill Gap
      ↓
Re-evaluate Next Action
      ↓
Re-plan if necessary
```

โครงสร้างนี้จึงรองรับทั้ง MVP ปัจจุบันและการขยาย Glow-Job ในอนาคต โดยยังรักษา separation ระหว่าง Data Pipeline, RAG, AI, Backend และ Frontend ให้ชัดเจน
