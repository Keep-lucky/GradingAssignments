# Prompt Template Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide subject-specific Chinese-language grading Prompt templates in the desktop editor, while allowing per-session edits without changing the source templates.

**Architecture:** Add a module containing immutable named templates distilled from the supplied draft: classical-Chinese translation, classical reading, ancient-poetry dictation, modern reading, poetry appreciation, and integrated material questions. The editor adds a readonly selector; choosing a template copies its text into the existing editable Text widget. The existing config-loaded Prompt remains the default “当前 Prompt（config.json）” option.

**Tech Stack:** Python 3.11, Tkinter/ttk, unittest, frozen dataclasses.

---

### Task 1: Add immutable prompt templates

**Files:**
- Create: `zhixue_grading/prompt_templates.py`
- Modify: `tests/test_desktop.py`

- [x] **Step 1: Write failing tests for the named template catalog**

```python
def test_template_catalog_labels_each_supported_question_type(self) -> None:
    labels = template_labels()
    self.assertIn("文言文翻译", labels)
    self.assertIn("现代文阅读：句意理解与主题探究", labels)
    self.assertEqual(get_template("文言文翻译").name, "文言文翻译")
```

- [x] **Step 2: Run the test and verify it fails**

Run: `python -m unittest tests.test_desktop.PromptTemplateTests -v`

Expected: FAIL because `prompt_templates` does not exist.

- [x] **Step 3: Implement the catalog**

```python
@dataclass(frozen=True)
class PromptTemplate:
    name: str
    prompt: str

PROMPT_TEMPLATES = (...)
```

Each prompt keeps the draft's scoring structure but replaces specific questions and answers with `{题目}`、`{参考答案}`、`{评分细则}` and `{满分}` placeholders.

- [x] **Step 4: Run the test and verify it passes**

Run: `python -m unittest tests.test_desktop.PromptTemplateTests -v`

Expected: PASS.

### Task 2: Select and edit a copied template in the desktop editor

**Files:**
- Modify: `zhixue_grading/desktop.py`
- Modify: `tests/test_desktop.py`

- [x] **Step 1: Write failing tests for selection and non-mutating copy behavior**

```python
def test_selecting_template_replaces_editor_text_with_a_copy(self) -> None:
    self.app.prompt_template_var.set("文言文翻译")
    self.app._on_prompt_template_selected()
    self.assertEqual(self.app.prompt_input.get("1.0", "end-1c"), get_template("文言文翻译").prompt)
```

- [x] **Step 2: Run the test and verify it fails**

Run: `python -m unittest tests.test_desktop.DesktopPromptTemplateTests -v`

Expected: FAIL because the selector and callback do not exist.

- [x] **Step 3: Implement the selector and copy operation**

```python
self.prompt_template_var = tk.StringVar(value="当前 Prompt（config.json）")
self.prompt_template_box = ttk.Combobox(..., state="readonly")
self.prompt_template_box.bind("<<ComboboxSelected>>", self._on_prompt_template_selected)
```

The callback deletes editor text and inserts the selected immutable template. It does not call `grader.set_prompt`; that still happens only when the teacher clicks “应用”.

- [x] **Step 4: Run the test and verify it passes**

Run: `python -m unittest tests.test_desktop.DesktopPromptTemplateTests -v`

Expected: PASS.

### Task 3: Document templates and runtime scope

**Files:**
- Modify: `CONTINUOUS_GRADING.md`

- [x] **Step 1: Document the available question-type templates**

```markdown
预设包括文言文翻译、文言文阅读、古诗文默写填空、现代文阅读、古诗鉴赏和综合材料题；选择预设会复制模板到编辑框，教师可再修改，原始预设保持不变。
```

- [x] **Step 2: Run full verification**

Run: `python -m unittest discover -s tests -v && python -m py_compile zhixue_grading/prompt_templates.py zhixue_grading/desktop.py`

Expected: PASS.
