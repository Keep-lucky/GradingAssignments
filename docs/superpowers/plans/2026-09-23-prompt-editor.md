# Prompt Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let teachers view and change the AI grading prompt in the desktop app, initially populated from `config.json`.

**Architecture:** `load_grading_config()` already loads `grading.prompt` at startup. Expose that prompt and a validated in-memory update method on `VisionGrader`; a Tkinter modal editor reads the exposed value, then applies edits to the same grader instance without writing local configuration.

**Tech Stack:** Python 3.11, Tkinter/ttk, unittest, dataclasses.

---

### Task 1: Make the active prompt readable and replaceable

**Files:**
- Modify: `tests/test_desktop.py`
- Modify: `zhixue_grading/vision_grader.py`

- [x] **Step 1: Write the failing test**

```python
def test_save_prompt_updates_the_current_grader_without_writing_config(self) -> None:
    self.app.prompt_input.get.return_value = "  revised prompt  "
    self.app._save_prompt()
    self.app.grader.set_prompt.assert_called_once_with("revised prompt")
```

- [x] **Step 2: Run the test and verify it fails**

Run: `python -m unittest tests.test_desktop.DesktopPromptEditorTests -v`

Expected: FAIL because `GradingDesktopApp._save_prompt` does not exist.

- [x] **Step 3: Implement the minimal runtime prompt update**

```python
@property
def prompt(self) -> str:
    return self._config.prompt

def set_prompt(self, prompt: str) -> None:
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("评分 Prompt 不能为空。")
    self._config = replace(self._config, prompt=prompt)
```

- [x] **Step 4: Run the test and verify it passes**

Run: `python -m unittest tests.test_desktop.DesktopPromptEditorTests -v`

Expected: PASS.

### Task 2: Add the desktop prompt editor

**Files:**
- Modify: `tests/test_desktop.py`
- Modify: `zhixue_grading/desktop.py`

- [x] **Step 1: Write a failing test that opening the editor loads the grader prompt**

```python
def test_open_prompt_editor_populates_text_with_config_loaded_prompt(self) -> None:
    self.app.grader.prompt = "config prompt"
    self.app._open_prompt_editor()
    self.app.prompt_input.insert.assert_called_once_with("1.0", "config prompt")
```

- [x] **Step 2: Run the test and verify it fails**

Run: `python -m unittest tests.test_desktop.DesktopPromptEditorTests -v`

Expected: FAIL because `_open_prompt_editor` does not exist.

- [x] **Step 3: Implement the editor**

```python
self.prompt_window = tk.Toplevel(self.root)
self.prompt_input = tk.Text(self.prompt_window, wrap=tk.WORD)
self.prompt_input.insert("1.0", self.grader.prompt)
ttk.Button(actions, text="应用", command=self._save_prompt).pack(side=tk.RIGHT)
```

The save handler trims input, rejects blank values with a warning, applies it through `grader.set_prompt`, closes the window, and updates the status label.

- [x] **Step 4: Run the test and verify it passes**

Run: `python -m unittest tests.test_desktop.DesktopPromptEditorTests -v`

Expected: PASS.

### Task 3: Document the runtime-only behavior

**Files:**
- Modify: `CONTINUOUS_GRADING.md`

- [x] **Step 1: Add the user-facing note**

```markdown
点击“编辑 Prompt”会显示启动时从 `config.json` 读取的评分 Prompt；应用后仅影响本次运行中后续发起的 AI 评分，不改写配置文件。
```

- [x] **Step 2: Run the full test suite**

Run: `python -m unittest discover -s tests -v`

Expected: PASS.
