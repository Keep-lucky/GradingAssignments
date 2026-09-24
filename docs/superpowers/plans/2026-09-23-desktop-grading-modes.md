# Desktop Grading Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the reviewed-question count and provide manual confirmation and automatic AI-accept grading modes in the desktop workbench.

**Architecture:** Keep mode and reviewed-count state on `GradingDesktopApp`. Manual mode continues to wait for the existing submit action; automatic mode submits the validated AI suggestion when it becomes available, then reuses the existing submit-and-next-card flow. Update the selected topic's displayed marked count only after a successful platform submission.

**Tech Stack:** Python 3.11, Tkinter/ttk, unittest, Pillow.

---

### Task 1: Specify grading-mode UI state

**Files:**
- Modify: `tests/test_desktop.py`
- Modify: `zhixue_grading/desktop.py`

- [x] **Step 1: Write failing tests for the mode selector and initial count state**

```python
def test_workbench_exposes_manual_and_automatic_grading_modes(self) -> None:
    self.app._build_ui()
    self.assertEqual(self.app.grading_mode.get(), "manual")

def test_overview_sets_reviewed_count_from_marked_topics(self) -> None:
    self.app._on_overview_loaded(card)
    self.assertEqual(self.app.reviewed_count, 5)
```

- [x] **Step 2: Run the desktop test module to verify the new tests fail**

Run: `python -m unittest tests.test_desktop -v`

Expected: FAIL because `grading_mode` and `reviewed_count` do not exist.

- [x] **Step 3: Add the minimal workbench state and controls**

```python
self.grading_mode = tk.StringVar(value="manual")
self.reviewed_count = 0
ttk.Radiobutton(top, text="手动", variable=self.grading_mode, value="manual").pack(side=tk.LEFT)
ttk.Radiobutton(top, text="自动", variable=self.grading_mode, value="automatic").pack(side=tk.LEFT)
```

Set `reviewed_count` from the selected topic's initial `marked_count`, and render it in the workbench header.

- [x] **Step 4: Run the desktop test module to verify the tests pass**

Run: `python -m unittest tests.test_desktop -v`

Expected: PASS for the new tests; pre-existing import failure remains an environment blocker until `zhixuewang` is installed.

### Task 2: Specify automatic AI acceptance and count updates

**Files:**
- Modify: `tests/test_desktop.py`
- Modify: `zhixue_grading/desktop.py`

- [x] **Step 1: Write failing tests for automatic submission and successful reviewed-count update**

```python
def test_grade_ready_submits_ai_score_in_automatic_mode(self) -> None:
    self.app.grading_mode = FakeVar("automatic")
    self.app._on_grade_ready(4)
    self.app._submit_score.assert_called_once()

def test_successful_submission_increments_selected_topic_reviewed_count(self) -> None:
    self.app._on_next_card(next_card)
    self.assertEqual(self.app.reviewed_count, 3)
```

- [x] **Step 2: Run the affected tests to verify they fail**

Run: `python -m unittest tests.test_desktop -v`

Expected: FAIL because automatic mode does not submit and no reviewed count is changed.

- [x] **Step 3: Implement the smallest safe behavior**

```python
if self.grading_mode.get() == "automatic":
    self._submit_score()
    return
```

Track the card ID pending submission. On a successful transition to a different card, increment the currently selected topic's marked count and refresh that Treeview row. Do not update the count when the platform returns the same card or submission fails.

- [x] **Step 4: Run the affected tests to verify they pass**

Run: `python -m unittest tests.test_desktop -v`

Expected: PASS for the new tests; pre-existing import failure remains an environment blocker until `zhixuewang` is installed.

### Task 3: Document the user-visible behavior

**Files:**
- Modify: `CONTINUOUS_GRADING.md`

- [x] **Step 1: Add concise desktop workflow documentation**

```markdown
工作台顶部会显示当前题号的已阅数量。选择“手动”后，AI 建议分仅填入输入框，教师确认提交；选择“自动”后，AI 建议分会立即按同样的校验与提交流程写回，并跳至下一张。计数仅在平台确认提交并切换到新答卷后增加。
```

- [x] **Step 2: Run the full test suite**

Run: `python -m unittest discover -s tests -v`

Expected: Existing suite imports successfully only when the local `zhixuewang` dependency is installed; otherwise report the existing `ModuleNotFoundError` exactly and separately from feature-test evidence.
