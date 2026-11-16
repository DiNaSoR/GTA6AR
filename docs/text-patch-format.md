# صيغة الترقيع النصي وخطة دفعات التعريب — Text Patch Format & Batching Plan

تُعرّف هذه الوثيقة الصيغة القياسية لملفات الترقيع النصي (`.patch.json`) في مشروع **GTA6AR**، بالإضافة إلى خطة تقسيم العمل (الواجهة، الترجمات الفرعية، والمهمات) ومعايير التحقق الآلي قبل الدمج.

> **قاعدة صارمة:** صيغة الترقيع النصي مصممة لتكون **مستقلة تمامًا عن ملفات اللعبة الأصلية**. لا يُخزّن النص الإنجليزي الأصلي للعبة داخل المستودع، بل يُربط كل نص معرّب بمعرّف السلسلة (`id`) أو بصمتها (`source_hash`) لتطبيقه محليًا على نسخة اللاعب الأصلية.

---

## 1. هيكل ملف الترقيع النصي (`.patch.json`)

يُحفظ كل ملف ترقيع بصيغة JSON مرمّزة بـ `UTF-8`، ويتبع المخطط القياسي في `text/schema/text_patch.schema.json`.

### الحقول العليا (Top-level Metadata):
| الحقل | النوع | الوصف |
|---|---|---|
| `schema_version` | `string` | إصدار مخطط الترقيع (حاليًا `"1.0.0"`). |
| `domain` | `string` | المجال الرئيسي: `"ui"` (واجهة وقوائم)، `"subtitles"` (ترجمات فرعية وحوار)، أو `"missions"` (مهمات وقصص). |
| `batch_id` | `string` | معرّف الدفعة (مثل: `"ui-core-menus-001"`، `"sub-scene-001"`، `"mis-prologue-001"`). |
| `generated_at` | `string` | طابع زمني بصيغة ISO-8601 UTC لتاريخ التوليد (مثل: `"2026-11-16T18:00:00Z"`). |
| `generator` | `object` | بيانات نموذج الذكاء الاصطناعي والبيئة التي أنتجت الدفعة. |
| `entries` | `array` | قائمة السلاسل العربية المعرّبة. |

### حقول `generator`:
- `model_name`: اسم النموذج المعتمد (يجب أن يكون `Gemini 3.8 Flash` أو أقوى، مثل `gemini-3.8-flash` أو `gemini-3.8-pro` أو `gemini-4-argon`).
- `model_version`: رقم إصدار النموذج (مثل `"3.8"` أو `"4.0"`).
- `pipeline_version`: إصدار أداة خط الإنتاج في المستودع (`"1.0.0"`).
- `glossary_version`: إصدار مسرد المصطلحات المستخدم أثناء التوليد (`"1.0.0"`).

### حقول كل مدخل في `entries`:
- `id` *(إلزامي)*: معرّف السلسلة النصية الفريد (مثل `"UI_MENU_SETTINGS"`).
- `source_hash` *(اختياري)*: بصمة `SHA-256` للنص الأصلي للتحقق من تطابق النسخة عند الحقن دون تخزين النص الأصلي.
- `ar` *(إلزامي)*: النص العربي الفصيح المولّد بالذكاء الاصطناعي.
- `context_category` *(اختياري)*: التصنيف الفرعي (`"menu"`, `"hud"`, `"settings"`, `"dialogue"`, `"objective"`, إلخ).
- `max_chars` *(اختياري)*: الحد الأقصى المسموح به لعدد الأحرف في هذا الموضع.
- `max_lines` *(اختياري)*: الحد الأقصى لعدد الأسطر.
- `timing_ms` *(اختياري — للترجمات الفرعية)*: كائن `{ "start": 0, "end": 3200 }` يحدّد نافذة الظهور بالملي ثانية لمواءمة طول السطر والدبلجة الصوتية.
- `placeholders` *(اختياري)*: قائمة المتغيرات البرمجية المتوقعة في السلسلة (مثل `["{0}", "~INPUT_ACCEPT~"]`) للتحقق الآلي من وجودها في النص العربي.
- `glossary_terms` *(اختياري)*: قائمة معرّفات المصطلحات من `text/glossary.json` المرتبطة بهذه السلسلة، ليتم التحقق من التزام الترجمة بها آليًا عبر `tools/check_glossary.py`.

---

## 2. مثال لملف ترقيع نصي (بيانات وهمية للتوضيح فقط)

```json
{
  "schema_version": "1.0.0",
  "domain": "ui",
  "batch_id": "sample-ui-menus-001",
  "generated_at": "2026-11-16T18:00:00Z",
  "generator": {
    "model_name": "gemini-3.8-flash",
    "model_version": "3.8",
    "pipeline_version": "1.0.0",
    "glossary_version": "1.0.0"
  },
  "entries": [
    {
      "id": "DUMMY_UI_MAIN_START",
      "source_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "ar": "بدء اللعبة",
      "context_category": "menu",
      "max_chars": 20,
      "max_lines": 1,
      "placeholders": [],
      "glossary_terms": ["term.start_game"]
    },
    {
      "id": "DUMMY_UI_PROMPT_SAVE",
      "source_hash": "8f434346648f6b96df89dda901c5176b10a6d83961dd3c1ac88b59b2dc327aa4",
      "ar": "اضغط على ~INPUT_ACCEPT~ لحفظ التقدّم في الفتحة {0}.",
      "context_category": "hud",
      "max_chars": 60,
      "max_lines": 2,
      "placeholders": ["~INPUT_ACCEPT~", "{0}"],
      "glossary_terms": ["term.save_progress"]
    }
  ]
}
```

---

## 3. تنظيم التخزين وتقسيم الدفعات (Batching Strategy)

تُقسّم ملفات الترقيع داخل مجلد `text/patches/` إلى ثلاثة مجالات رئيسية، بحيث يسهل توزيع المهام ومراجعتها في طلبات الدمج:

```text
text/
├── glossary.json                     # المسرد الموحد للمصطلحات المعتمدة
├── schema/
│   └── text_patch.schema.json        # مخطط JSON القياسي لملفات الترقيع
├── samples/                          # أمثلة وهمية للاختبارات الآلية فقط
│   ├── dummy_input_batch.json
│   ├── dummy_patch_valid.json
│   └── dummy_patch_invalid.json
└── patches/
    ├── ui/                           # دفعات الواجهة والقوائم (UI & Menus)
    ├── subtitles/                    # دفعات الترجمات الفرعية والحوار (Subtitles & Dialogue)
    └── missions/                     # دفعات نصوص المهمات والقصص (Missions & Story)
```

### أ. خطة دفعات واجهة المستخدم والقوائم (`text/patches/ui/` — Issue #8)
- **التقسيم:**
  1. `ui-main-menu-*`: القائمة الرئيسة، شاشات التوقف، وتحميل الملفات.
  2. `ui-settings-*`: إعدادات الرسوميات، الصوت، عناصر التحكم، واللغة.
  3. `ui-hud-prompts-*`: تنبيهات الشاشة، أزرار التفاعل، والرادار/الخريطة.
  4. `ui-inventory-phone-*`: واجهات الهاتف، المتاجر، والقوائم الفرعية.
- **حجم الدفعة:** 100 إلى 250 سلسلة نصية لكل ملف ترقيع.
- **قيود الطول:** تُضبط `max_chars` لكل فئة (18–25 حرفًا للأزرار، 55 حرفًا للتنبيهات)، وتُرفض أي سلسلة تتجاوز الحد في فحص ما قبل الدمج.

### ب. خطة دفعات الترجمات الفرعية والحوار (`text/patches/subtitles/` — Issue #9)
- **التقسيم:** تُقسّم حسب المشهد أو الفصل (`sub-ch01-scene01.patch.json`) ليبقى السياق الحواري متماسكًا أثناء تمريره لنموذج Gemini.
- **حجم الدفعة:** 50 إلى 150 سطرًا حواريًا في الطلب الواحد لضمان ثبات نبرة المتحدثين.
- **ضوابط التوقيت والأسطر:**
  - الحد الأقصى لعدد الأسطر `max_lines: 2`، والحد الأقصى للسطر الواحد `48` حرفًا.
  - سرعة القراءة المستهدفة لا تتجاوز `16–18` حرفًا في الثانية بناءً على حقل `timing_ms`، مما يضمن توافق السطر مع خط أنابيب الدبلجة الصوتية (ElevenLabs v4+).

### ج. خطة دفعات المهمات والقصص (`text/patches/missions/` — Issue #10)
- **التقسيم:** دفعة مستقلة لكل مهمة أو سلسلة مهمات مرتبطة (`mis-main-001.patch.json`، `mis-side-001.patch.json`).
- **اتساق الأسماء والمصطلحات:** تُربط كل مهمة بقائمة الأعلام والمصطلحات في `text/glossary.json` عبر الحقل `glossary_terms`، ويُتحقق منها آليًا قبل الدمج.

---

## 4. كيف يُطبّق الترقيع على نسخة اللاعب الأصلية؟

1. يمتلك اللاعب نسخته الأصلية القانونية من اللعبة على جهازه.
2. تُشغّل أداة الاستخراج والحقن المحلية على جهاز اللاعب لقراءة المعرّفات وتطبيق النصوص العربية من ملفات `text/patches/**/*.patch.json` مع التحقق من `source_hash` عند توفره.
3. لا يحتاج المستودع في أي مرحلة إلى استضافة ملفات اللعبة (`*.rpf`, `*.dat`, `*.pak`) أو نصوصها الإنجليزية الأصلية.

---

## 5. بوابة التحقق والمراجعة قبل الدمج (Pre-Merge QA Checklist)

قبل قبول أي طلب دمج (Pull Request) يضيف أو يعدّل ملفات في `text/patches/`:
1. **التحقق من النموذج المعتمد:** التأكد من أن `generator.model_name` هو `Gemini 3.8 Flash` أو أقوى.
2. **سلامة المتغيرات البرمجية:** تطابق جميع عناصر `placeholders` في النص العربي `ar`.
3. **اتساق المسرد:** نجاح تشغيل `python tools/check_glossary.py` بدون أي مخالفات للمصطلحات المعتمدة أو الممنوعة أو تجاوز لحدود الطول (`max_chars` / `max_lines`).
4. **خلو التعديل من النصوص الأصلية:** التأكد من عدم تضمين نصوص اللعبة الأصلية أو ملفاتها.

---

## English Summary

This specification covers the **GTA6AR** text patch format (`#4`) and the translation batching plans for UI/menus (`#8`), subtitles/dialogue (`#9`), and missions/story (`#10`):
- **Patch Schema (`text/schema/text_patch.schema.json`):** Maps string IDs (`id`) and optional `SHA-256` hashes (`source_hash`) to Arabic AI translations (`ar`), recording `model_name`, `model_version`, `timing_ms`, `placeholders`, and `glossary_terms` — with zero original game text stored in the repo.
- **Batching:** Organized under `text/patches/{ui,subtitles,missions}/` with strict character/line limits and reading-speed budgets aligned with the voice dubbing pipeline.
