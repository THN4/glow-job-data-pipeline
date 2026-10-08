# Learning Graph: Document-to-Skill Flow

## เป้าหมายและขอบเขต

เอกสารนี้อธิบายงานฝั่ง **knowledge** ที่จะทำหลัง market pipeline ใช้งานได้ โดยใช้ชื่อทักษะมาตรฐานจาก `core.skills` เป็นจุดเชื่อม งานฝั่ง market ตอบว่า *ตลาดต้องการทักษะใด* ส่วน learning graph ตอบว่า *ทักษะใดควรเรียนก่อนทักษะใด และอ้างอิงจากแหล่งใด* จำนวนงานที่ระบุ Python และ Apache Airflow พร้อมกันไม่ได้พิสูจน์ว่า Python เป็น prerequisite ของ Airflow

งาน knowledge ยัง **ไม่ได้ implement ใน repo นี้** ตาราง `knowledge.*` มีเฉพาะใน [DBML รวม](schemas/glow-job.dbml) และ [คำอธิบาย schema](glow_job_database_schema.md) ยังไม่มี migration หรือ pipeline สำหรับดึงเอกสาร รายละเอียดในไฟล์นี้เป็นแผนการทำงาน ไม่ใช่สถานะของระบบปัจจุบัน

```text
Market: JSearch → job skills → career skill demand
                          │
                          └── เลือก skill ที่จะทำเนื้อหาก่อน
                                      ↓
Knowledge: เอกสารต้นทาง → เก็บ source/ไฟล์ → แปลงข้อความ → แบ่ง chunk
                                                        ├──→ ค้นเนื้อหา/RAG (ภายหลัง)
                                                        └──→ เสนอความสัมพันธ์ของ skill
                                                                      ↓
                                                           ตรวจหลักฐานและชื่อ skill
                                                                      ↓
                                                           คนยืนยันความสัมพันธ์
                                                                      ↓
                                                        learning graph ที่ใช้ได้จริง
```

## ลำดับการทำงาน

### 1. เลือก skill และแหล่งข้อมูล

เริ่มจาก skill ที่มีชื่อมาตรฐานแล้วใน `core.skills` และมีประโยชน์ต่อเป้าหมายของ product อาจใช้ `market.career_skill_stats` ช่วยจัดลำดับความสำคัญเมื่อมีข้อมูลเพียงพอ เริ่มทดลองกับ 3–5 skills และเอกสารทางการจำนวนเล็กน้อยก่อนขยายการดึงข้อมูล

สำหรับแต่ละแหล่ง เก็บชื่อเรื่อง, URL, publisher, ประเภทแหล่ง, วันเก็บ และตำแหน่งไฟล์ต้นฉบับใน `knowledge.knowledge_sources` ระบุเวอร์ชันเอกสารหรือวันที่เผยแพร่ถ้ามี ตรวจเงื่อนไขการเข้าถึงและการเก็บสำเนาของแหล่งนั้นก่อนดาวน์โหลด ไฟล์ต้นฉบับควรอยู่ใน object storage; ตารางเก็บ metadata กับ `storage_key` เพื่อย้อนกลับไปดูต้นทางได้

### 2. แปลงเอกสารเป็นข้อความที่อ้างอิงกลับได้

อ่าน HTML, Markdown หรือ PDF แล้วเอาส่วนที่ไม่ใช่เนื้อหาออก โดยพยายามคงหัวข้อ, ลำดับ, URL ของหน้า และตำแหน่งในเอกสาร จากนั้นแบ่งข้อความเป็น chunks ตามหัวข้อหรือย่อหน้า แต่ละ chunk ผูกกับ `source_id`, `chunk_index` และ metadata เช่น section, language, version

`knowledge.knowledge_chunks` มีไว้เก็บข้อความที่ใช้ค้นและนำมาเป็นหลักฐาน การสร้าง embedding และค้นแบบ vector เป็น **ทางเลือกของงาน RAG ภายหลัง** ไม่ใช่เงื่อนไขก่อนสร้าง graph ถ้าจะเก็บ `embedding vector` ใน PostgreSQL ต้องเลือกและติดตั้ง vector extension ก่อนออก migration จริง

### 3. เสนอความสัมพันธ์ระหว่าง skill

ใช้ข้อความในเอกสารเป็นหลักฐานให้กฎหรือ LLM เสนอความสัมพันธ์ เช่น `prerequisite`, `recommended_before` หรือ `related` ผลที่เสนอควรระบุชื่อ skill ต้นทางและปลายทาง, ประเภทความสัมพันธ์, ข้อความหลักฐาน และแหล่งที่มา

ตัวอย่างสมมติ: เอกสารบทเรียนเขียนว่า “Learners should know Python before writing Airflow DAGs.” ระบบอาจเสนอ `Python → Apache Airflow` แบบ `prerequisite` โดยแนบประโยคนั้นและ `source_id` แต่ถ้าเอกสารเพียงกล่าวถึง Python และ Airflow ในหน้าเดียวกัน **ยังไม่พอ** ที่จะสร้างขอบ prerequisite

ชื่อที่พบในเอกสารต้องจับคู่กับ `core.skills` และ `core.skill_aliases` ก่อนสร้างขอบที่อ้างอิง `skill_id` ชื่อที่ไม่ตรงหรือกำกวมให้ส่ง review; อย่าสร้าง skill หรือความสัมพันธ์โดยเดา

### 4. ตรวจและเผยแพร่ graph

ตรวจว่า evidence ปรากฏใน source จริง, `source_id` ยังใช้งานได้, skill ทั้งสองมีตัวตน, ไม่มีขอบจาก skill ไปหาตัวเอง และความสัมพันธ์ไม่ได้ขัดแย้งกับขอบที่ยืนยันไว้ สำหรับ `prerequisite` ให้ตรวจวงจรที่อาจทำให้ลำดับการเรียนใช้ไม่ได้ ความมั่นใจของ LLM เป็นเพียงข้อมูลช่วย review ไม่ใช่หลักฐานรับรอง

เก็บข้อเสนอพร้อม `evidence_text`, `source_id` และ `is_verified=false` ใน `knowledge.skill_dependencies` หรือพื้นที่ review ที่ออกแบบภายหลัง เฉพาะขอบที่คนตรวจและยืนยันแล้วจึงตั้ง `is_verified=true` และนำไปใช้สร้างลำดับการเรียน

`knowledge.learning_modules` ใช้กำหนดหัวข้อและ learning outcome ของแต่ละ skill/level โดยอ้างอิงเอกสารและ graph ที่ยืนยันแล้ว ไม่ควรสร้าง roadmap ส่วนบุคคลจากเอกสารดิบโดยตรง เพราะ roadmap เป็นงานฝั่ง app ที่ต้องใช้ข้อมูลผู้ใช้เพิ่ม

## ตารางที่เกี่ยวข้อง

| ตารางใน DBML รวม | บทบาท |
|---|---|
| `core.skills`, `core.skill_aliases` | ชื่อ skill มาตรฐานและชื่อเรียกอื่นที่ยืนยันแล้ว ใช้เชื่อมข้อมูล market กับ knowledge |
| `knowledge.knowledge_sources` | metadata และตำแหน่งไฟล์เอกสารต้นทาง |
| `knowledge.knowledge_chunks` | ข้อความแยกส่วนสำหรับค้นและอ้างอิง; embedding เป็นทางเลือก |
| `knowledge.skill_dependencies` | ขอบ graph พร้อมชนิดความสัมพันธ์ หลักฐาน และสถานะตรวจสอบ |
| `knowledge.learning_modules` | หัวข้อและผลลัพธ์การเรียนต่อ skill/level |
| `market.career_skill_stats` | ข้อมูลตลาดสำหรับจัดลำดับว่าควรทำเนื้อหา skill ใดก่อน ไม่ใช่แหล่งพิสูจน์ prerequisite |

## MVP ที่แนะนำและจุดต้องตัดสินก่อนสร้าง schema จริง

1. เลือก 3–5 skills และแหล่งทางการไม่กี่แห่ง เก็บ source, ข้อความ และที่มาที่ตรวจกลับได้
2. สกัดขอบ `prerequisite` เฉพาะข้อความที่มีหลักฐานชัด ส่งคนตรวจ แล้วทดลองใช้ graph ที่ยืนยันแล้ว
3. เพิ่ม `recommended_before`/`related`, learning modules, การค้นด้วย embedding และการดึงเอกสารจำนวนมากเมื่อผลทดลองบอกว่าจำเป็น

ก่อนสร้าง migration ของฝั่ง knowledge ต้องทบทวนว่าเอกสารหนึ่งฉบับเกี่ยวกับหลาย skill ได้หรือไม่: DBML ปัจจุบันมี `knowledge_sources.skill_id` และ `knowledge_chunks.skill_id` อย่างละค่าเดียว หากต้องรองรับหลาย skill ให้พิจารณาตารางเชื่อมแทน อย่าทำสำเนาเอกสารเพียงเพื่อเปลี่ยน `skill_id` นอกจากนี้ควรตกลงวิธีระบุเวอร์ชัน/ตำแหน่งหลักฐานในเอกสาร และวิธีเก็บไฟล์เมื่อเปลี่ยน repo หรือ storage

DBML ปัจจุบันให้ `knowledge.skill_dependencies` เก็บ `source_id` กับ `evidence_text` ได้อย่างละหนึ่งค่าต่อขอบที่ไม่ซ้ำกัน ถ้าต้องการเก็บหลักฐานจากหลายเอกสารสำหรับความสัมพันธ์เดียวกัน ควรแยกตารางหลักฐานและสถานะการ review ก่อนทำ migration

หาก market และ knowledge อยู่คนละฐานข้อมูล อย่าสมมติว่าเลข `skill_id` จะตรงกันเอง ให้ใช้ชื่อหรือ key ที่เสถียรในการแลกข้อมูล และ resolve เป็น `skill_id` ของฐานข้อมูลปลายทาง
