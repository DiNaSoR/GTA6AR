# هيكل المستودع، معايير التسمية، وتصميم خط الإنتاج الشامل — Repository Structure, Naming & End-to-End Pipeline

تُوثّق هذه الوثيقة الهيكل المعتمد لمجلدات مستودع **GTA6AR** وقواعد تسمية الفروع والملفات ومخرجات الذكاء الاصطناعي (`#1`)، وتصميم خط الإنتاج الشامل من الاستخراج المحلي حتى بناء الترقيع (`#2`)، وإعداد بيئة التشغيل المحلية للأدوات (`#3`).

> **قاعدة أساسية:** يعمل هذا المشروع بنظام **الترقيعات والأدوات فقط (Patch-only)**. يلزم اللاعب امتلاك نسخة أصلية قانونية من اللعبة، ويُحظر تمامًا رفع أو إرفاق أي ملفات أو أصول مستخرجة من اللعبة (`*.rpf`, `*.iso`, `*.bin`, `*.pak`, `*.wem`, `*.ytd`, `*.dds`, `*.exe`) أو مفاتيح API السرية (`.env`).

---

## 1. هيكل المجلدات في المستودع (Issue #1)

```text
GTA6AR/
├── .github/                  # قوالب القضايا وطلبات الدمج وسكربتات التحديث الآلي
├── assets/                   # شعارات وصور ترويسة المستودع العامة
├── audio/                    # ملفات ومواصفات ومخرجات الدبلجة الصوتية بالذكاء الاصطناعي (ElevenLabs v4+)
│   ├── profiles/             # بطاقات مواصفات أصوات الشخصيات (بدون أصول اللعبة)
│   ├── manifests/            # سجلات المقاطع الصوتية ومواءمة التوقيت (.voice.json)
│   └── samples/              # عينات وهمية لاختبار خط أنابيب الدبلجة
├── docs/                     # التوثيق الهندسي، معايير الجودة، وموقع متابعة التقدّم
├── images/                   # ملفات ومواصفات ومخرجات تعريب الصور والرسوم (OpenAI Sunburn+)
│   ├── catalog/              # جرد الفئات البصرية ومعايير النص العربي داخل الصور
│   ├── manifests/            # سجلات الصور المولّدة وبيانات النموذج (.image.json)
│   └── samples/              # عينات وهمية لاختبار خط أنابيب الصور
├── text/                     # ملفات الترقيع النصي والمسرد العربي الفصيح (Gemini 3.8 Flash+)
│   ├── glossary.json         # المسرد الموحد للمصطلحات المعتمدة
│   ├── schema/               # مخطط JSON القياسي لملفات الترقيع النصي
│   ├── patches/              # ملفات الترقيع النصي مقسّمة حسب المجال (ui / subtitles / missions)
│   └── samples/              # عينات نصية وهمية للاختبارات الآلية
├── tools/                    # أدوات سطر الأوامر وخطوط الإنتاج والاختبارات الآلية (Python 3.10+)
│   └── tests/                # اختبارات الوحدة الشاملة على بيانات وهمية
├── .env.example              # قالب متغيرات البيئة المحلي الخالي من الأسرار
├── .gitignore                # قائمة حظر ملفات اللعبة والأسرار والملفات المؤقتة
├── CONTRIBUTING.md           # دليل المساهمة وقواعد النماذج المعتمدة
└── README.md                 # واجهة المشروع وجدول التقدّم الحي
```

---

## 2. معايير تسمية الفروع والملفات ومخرجات الذكاء الاصطناعي (Issue #1)

### أ. تسمية الفروع (Git Branches)
- `feat/<area>-<short-slug>`: لإضافة أداة أو خط أنابيب أو دفعة تعريب جديدة (مثل: `feat/translation-foundation`، `feat/voice-pipeline`).
- `fix/<area>-<short-slug>`: لإصلاح خلل في أداة أو تصحيح مصطلح في ترقيع.
- `docs/<short-slug>`: لتحديث التوثيق أو أدلة الاستخدام.

### ب. تسمية ملفات المخرجات والترقيعات (AI Outputs & Patches)
تُسمّى جميع المخرجات بنمط موحّد يوضّح **المجال**، **الفئة الفرعية**، **رقم الدفعة**، و**نوع المخرج**:
- **ترقيعات النصوص (`text/patches/<domain>/`):**
  `<domain>-<category>-<batch_num>.patch.json`
  *(مثال: `ui-settings-001.patch.json`، `subtitles-ch01-scene02.patch.json`)*
- **سجلات ومخرجات الدبلجة (`audio/manifests/`):**
  `voice-<scene_or_batch>-<model_tag>.voice.json`
  *(مثال: `voice-scene01-elevenlabs-v4.voice.json`)*
- **سجلات ومخرجات الصور (`images/manifests/`):**
  `img-<category>-<batch_num>-<model_tag>.image.json`
  *(مثال: `img-roadsigns-001-sunburn-v1.image.json`)*

> **إلزامية توثيق النموذج:** يجب أن يتضمن كل ملف مخرجات حقل `generator` يوثّق `model_name` و `model_version` وتاريخ التوليد `generated_at`.

---

## 3. تصميم خط الإنتاج الشامل من الاستخراج إلى الترقيع (Issue #2)

```text
[نسخة اللاعب الأصلية (محليًا فقط — خارج المستودع)]
       │
       ▼ (1. الاستخراج المحلي وبصمات SHA-256 عبر tools/text_tool.py)
[ملف مدخلات وسيط بمعرّفات السلاسل والـ Metadata]
       │
       ▼ (2. التوليد بالذكاء الاصطناعي بالحد الأدنى المعتمد فقط)
       ├─ النصوص: Gemini 3.8 Flash أو أقوى + المسرد الفصيح
       ├─ الصوت:  ElevenLabs v4 أو أقوى + مواصفات الصوت ومواءمة التوقيت
       └─ الصور:  OpenAI Sunburn أو أفضل + معايير وضوح الخط العربي وRTL
       │
       ▼ (3. بوابة الفحص والمراجعة الآلية قبل الدمج)
       ├─ فحص المسرد والـ Placeholders والطول (tools/check_glossary.py)
       ├─ فحص التوقيت الصوتي ومعايير النطق الفصيح
       └─ فحص نظافة المستودع من ملفات اللعبة والأسرار (tools/verify_repo_cleanliness.py)
       │
       ▼ (4. بناء وحقن الترقيع النهائي على جهاز اللاعب)
[تطبيق الترقيع محليًا على النسخة الأصلية بدون تداول ملفات اللعبة]
```

### النماذج المعتمدة في كل مرحلة:
| المسار | الحد الأدنى للنموذج | أداة التحقق الآلي | صيغة المخرج في المستودع |
|---|---|---|---|
| **الترجمة والنصوص** | `Gemini 3.8 Flash` (`>= 3.8`) | `tools/translate_pipeline.py` + `tools/check_glossary.py` | `*.patch.json` |
| **الدبلجة الصوتية** | `ElevenLabs v4` (`>= 4.0`) | `tools/voice_pipeline.py` | `*.voice.json` + مخرجات AI الصافية |
| **الصور والرسوم** | `OpenAI Sunburn` (`>= 1.0`) | `tools/image_pipeline.py` | `*.image.json` + مخرجات AI الصافية |

---

## 4. إعداد بيئة التشغيل المحلية للأدوات (Issue #3)

صُمّمت جميع أدوات المشروع في `tools/` بلغة **Python 3.10+** بالاعتماد الكامل على **المكتبة القياسية (Python Standard Library)** دون الحاجة لتثبيت حزم خارجية ثقيلة، مما يضمن سهولة التشغيل على أنظمة Windows و macOS و Linux.

### خطوات الإعداد والتشغيل المحلي:
1. **استنساخ المستودع:**
   ```bash
   git clone https://github.com/DiNaSoR/GTA6AR.git
   cd GTA6AR
   ```
2. **إعداد متغيرات البيئة المحلية (بدون رفعها):**
   انسخ ملف المثال `.env.example` إلى `.env` محليًا (الملف `.env` مستبعد تلقائيًا في `.gitignore`):
   ```bash
   cp .env.example .env
   ```
   ثم أضف مفاتيحك المحلية عند تشغيل خطوط التوليد الحية (`GEMINI_API_KEY`، `ELEVENLABS_API_KEY`، `OPENAI_API_KEY`).
3. **تشغيل الاختبارات والفحوصات المحلية (بدون الحاجة لمفاتيح API عبر وضع `--dry-run`):**
   ```bash
   # تشغيل جميع اختبارات الوحدة
   python -m unittest discover -s tools/tests -v

   # فحص نظافة المستودع من ملفات اللعبة المحظورة والأسرار
   python tools/verify_repo_cleanliness.py
   ```

---

## English Summary

This document covers Milestone 1 (`#1`, `#2`, `#3`):
- **Repository Structure & Naming (`#1`):** Defines folder roles (`text`, `audio`, `images`, `tools`, `docs`), branch conventions, and standardized file naming including model metadata.
- **End-to-End Pipeline Architecture (`#2`):** Details the 4-stage workflow (Local Extraction → Approved AI Generation → Automated QA Gates → Local Patch Injection) without storing game assets.
- **Local Tooling Environment (`#3`):** Zero-dependency Python 3.10+ standard-library CLI suite with a secrets-free `.env.example` template and `.gitignore` protections.
