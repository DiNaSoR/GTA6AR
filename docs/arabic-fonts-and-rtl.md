# الخطوط العربية المرخّصة، دعم RTL، ومعايير الربط والأرقام — Licensed Arabic Fonts, RTL & Shaping Specification

تُوثّق هذه الوثيقة الخطوط العربية مفتوحة المصدر المختارة لمشروع **GTA6AR** (`#12`)، وآلية دعم الاتجاه من اليمين إلى اليسار (RTL) والمعاينة ثنائية الاتجاه (`#13`)، وقواعد اختبار ربط الحروف والتشكيل والأرقام (`#14`).

> **تنبيه قانوني:** جميع الخطوط المختارة هنا مرخّصة تحت رخصة **SIL Open Font License 1.1 (OFL-1.1)** المتوافقة تمامًا مع المشاريع مفتوحة المصدر وإعادة التوزيع الحر ضمن الترقيعات، وجميع النصوص التدريبية والاختبارية هي نصوص وهمية لا علاقة لها بملفات اللعبة الأصلية.

---

## 1. الخطوط العربية المرخّصة المعتمدة (Issue #12)

بعد المفاضلة بين الخطوط العربية الحرة من حيث وضوح القراءة على الشاشات (HUD / Subtitles)، وتعدد الأوزان، وتناسق الأرقام اللاتينية (`0-9`) مع الحروف العربية، اعتُمدت الخطوط الثلاثة التالية:

| الاستخدام داخل اللعبة | اسم الخط | الأوزان المعتمدة | الرخصة | المصدر الرسمي |
|---|---|---|---|---|
| **القوائم، الواجهة، والترجمات الفرعية (UI & Subtitles Primary)** | **IBM Plex Sans Arabic** | Regular (400), Medium (500), SemiBold (600), Bold (700) | SIL OFL 1.1 | [github.com/IBM/plex](https://github.com/IBM/plex) / [Google Fonts](https://fonts.google.com/specimen/IBM+Plex+Sans+Arabic) |
| **العناوين، اللافتات، وشاشات المهمات (Display & Headers)** | **Cairo** | SemiBold (600), Bold (700), ExtraBold (800) | SIL OFL 1.1 | [github.com/Gue3bara/Cairo](https://github.com/Gue3bara/Cairo) / [Google Fonts](https://fonts.google.com/specimen/Cairo) |
| **الحوارات الطويلة، الرسائل، والسرد النصي (Body & Fallbacks)** | **Noto Sans Arabic** | Regular (400), Medium (500), Bold (700) | SIL OFL 1.1 | [github.com/notofonts/arabic](https://github.com/notofonts/arabic) / [Google Fonts](https://fonts.google.com/noto/specimen/Noto+Sans+Arabic) |

### مسوّغات الاختيار التقنية:
1. **وضوح فائق في الأحجام الصغيرة (`14px–18px`):** يتميز خط **IBM Plex Sans Arabic** بارتفاع سطر متوازن وتباعد واضح للنقاط والهمزات، مما يمنع تداخل الحروف على شاشات اللعب السريعة أو دقة العرض المتفاوتة.
2. **توافق الرخصة (SIL OFL 1.1):** تسمح الرخصة بتضمين الخطوط وتعديلها أو تحويلها إلى صيغ خطوط محركات الألعاب وتوزيعها مجانًا ضمن حزم الترقيع (`patches`)، بشرط الإبقاء على إشعار حقوق الخط وعدم بيع ملف الخط منفردًا.
3. **اتساق الأرقام والرموز:** تدعم الخطوط الثلاثة الأرقام القياسية (`0-9`) وعلامات الترقيم العربية (« »، `،`، `؛`، `؟`) والرموز اللاتينية المدمجة بسلاسة.

---

## 2. دعم الاتجاه من اليمين إلى اليسار (RTL) والمعاينة (Issue #13)

تواجه محركات الألعاب وأدوات سطر الأوامر تحديين رئيسيين عند عرض العربية:
1. **النصوص المختلطة (BiDi):** وجود رموز برمجية لاتينية (مثل `~INPUT_ACCEPT~` أو `{0}` أو `V-Sync`) أو أرقام (`$1,500`، `120 كم/س`) وسط سطر عربي قد يؤدي إلى انعكاس ترتيب الجملة أو انفصال الأقواس إذا لم يُضبط اتجاه الفقرة الأساسي.
2. **محركات العرض التي لا تدعم الربط أو الـ BiDi تلقائيًا:** بعض واجهات العرض تحتاج إلى حروف مربوطة مسبقًا (Presentation Forms-B) أو علامات عزلة اتجاهية (Unicode BiDi Isolates).

### الحل المعتمد في أدوات المشروع (`tools/rtl_shaper.py` و `tools/text_tool.py`):
- **العزل الاتجاهي القياسي (Unicode BiDi Isolates):**
  - إحاطة السطر العربي بعلامة العزل من اليمين إلى اليسار `U+2067` (`RLI`) وإغلاقها بـ `U+2069` (`PDI`).
  - إحاطة المتغيرات البرمجية اللاتينية (`{0}`, `%s`, `~INPUT_...~`) بعلامة العزل من اليسار إلى اليمين `U+2066` (`LRI`) وإغلاقها بـ `U+2069` (`PDI`) لمنع بعثرة علامات الترقيم المجاورة.
- **نحت الحروف العربية (Contextual Letter Shaping) والترتيب البصري (`--shape` / `--visual-order`):**
  - توفّر وحدة `tools/rtl_shaper.py` محرك ربط قياسيًا خاليًا من التبعيات الخارجية يحوّل الحروف العربية القياسية (`U+0600..U+06FF`) إلى أشكالها السياقية الأربعة (مفرد `Isolated`، بداية `Initial`، وسط `Medial`، نهاية `Final`) في نطاق `U+FE70..U+FEFC`، مع دعم تام لتراكيب **اللّام ألف** (`لا`، `لأ`، `لإ`، `لآ`).
  - يعمل الخيار `--shape` بالترتيب المنطقي (`Logical Order`) للمحركات التي تدعم اتجاه RTL لكنها تفتقر لربط الحروف، بينما يوفّر الخيار الإضافي `--visual-order` (`visual_reorder_line`) عكس السطر بصريًا مع الإبقاء على مقاطع الـ LTR والمتغيرات والأرقام سليمة للمحركات القديمة التي لا تدعم خوارزمية Unicode BiDi إطلاقًا.
- **المعاينة البصرية للمراجعين (`preview` CLI):**
  - يُولّد الأمر `python tools/text_tool.py preview` صفحة معاينة HTML مستقلة (`dir="rtl" lang="ar"`) تستدعي خطوط `IBM Plex Sans Arabic` و`Cairo` و`Noto Sans Arabic` وتعرض كل سلسلة نصية بثلاثة أحجام (`14px`، `20px`، `28px`) لمراجعة الترقيم والأقواس والنصوص المختلطة بصريًا قبل الدمج.

---

## 3. سياسة الربط، التشكيل، الكشيدة، والأرقام (Issue #14)

### أ. سياسة الأرقام (Numerals Policy)
- **تُعتمد الأرقام العربية الغربية/الدولية (`0123456789`)** في جميع نصوص الواجهة، العدادات، المبالغ المالية، المسافات، والترجمات الفرعية.
- **تُمنع الأرقام الهندية الشرقية (`٠١٢٣٤٥٦٧٨٩`)** في ملفات الترقيع تفاديًا لعدم تطابقها مع عدادات المحرك الرقمية؛ وتتضمن أداة `tools/rtl_shaper.py` دالة تحويل وتحقق آلي (`normalize_numerals` و`has_eastern_arabic_Indic_numerals`).

### ب. سياسة التشكيل (Diacritics / Tashkeel Policy)
- **القاعدة العامة:** النصوص غير مشكولة بالكامل حفاظًا على نظافة القراءة السريعة في الترجمات الفرعية (`subtitles`) وعناصر الواجهة (`ui`).
- **متى يُستخدم التشكيل؟**
  1. **التنوين بالفتح على الألف** (مثل: «شكرًا»، «فورًا»، «معًا»، «قريبًا»).
  2. **الشّدّة والضبط لمنع اللبس الدلالي** (مثل: «حفظ التقدّم»، «مُلاحَقة»، «عَلِمَ» مقابل «عَلَّمَ»).
- **سلوك محرك الربط مع التشكيل:** يتعامل محرك الربط (`shape_arabic_text`) مع الحركات (`U+064B..U+0652`، `U+0670`) كعلامات غير فاصلة (Transparent Non-Spacing Marks)، فلا تقطع اتصال الحرف بما قبله أو بعده.

### ج. سياسة الكشيدة / التطويل (`ـ` `U+0640`)
- يُمنع استخدام الكشيدة (`ـ`) في ملفات الترقيع النصية لأنها تستهلك ميزانية الأحرف (`max_chars`) وتُربك حساب سرعة القراءة في الترجمات الفرعية.

---

## 4. كيف تعاين النصوص وتختبرها محليًا؟

```bash
# 1. تشغيل اختبارات الربط والتشكيل والأرقام والاستخراج والحقن
python -m unittest discover -s tools/tests -v

# 2. توليد صفحة معاينة RTL بالخطوط العربية المرخّصة من ملف ترقيع وهمي
python tools/text_tool.py preview \
  --patch text/samples/dummy_patch_rtl.json \
  --output preview_rtl.html
```

---

## English Summary

This specification covers Milestone 4 (`#12`, `#13`, `#14`):
- **Licensed Arabic Fonts (`#12`):** Selects **IBM Plex Sans Arabic** (UI/subtitles), **Cairo** (headers/HUD display), and **Noto Sans Arabic** (long-form body/fallback), all under **SIL Open Font License 1.1 (OFL-1.1)**.
- **RTL & BiDi Tooling (`#13`):** Implements Unicode BiDi isolation (`RLI`/`LRI`/`PDI`) for mixed Arabic/Latin placeholders and numbers, plus an HTML RTL preview generator in `tools/text_tool.py`.
- **Shaping, Diacritics & Numerals (`#14`):** Implements zero-dependency contextual Arabic shaping (including Lam-Alef ligatures and transparent tashkeel handling) and enforces standard `0-9` numerals in `tools/rtl_shaper.py`, verified by automated unit tests on dummy strings.
