# Cookie Login Desktop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the desktop grader a dedicated Cookie login page that validates a pasted Cookie before revealing the grading workbench.

**Architecture:** The app starts without a Zhixue client and shows a login frame. A successful background `MarkingExamClient(cookie).list_marking_exams()` call creates an in-memory session, then replaces the login frame with the existing workbench. The Cookie is not persisted or displayed.

**Tech Stack:** Python 3, Tkinter/ttk, existing Zhixue session client, `unittest`.

---

### Task 1: Add tests for Cookie login behavior

**Files:**
- Modify: `tests/test_desktop.py`
- Test: `tests/test_desktop.py`

- [ ] **Step 1: Write the failing test**

```python
def test_login_uses_trimmed_cookie_and_loads_exams(self) -> None:
    app = GradingDesktopApp.__new__(GradingDesktopApp)
    app.cookie_var = FakeVariable("  session=value  ")
    app.status_var = FakeVariable()
    app._run = lambda function, success: success(function())
    app._show_workbench = lambda exams: loaded.append(exams)
    with patch("zhixue_grading.desktop.MarkingExamClient", return_value=client):
        app._login()
    client.assert_called_once_with("session=value")
    self.assertEqual(loaded, [[exam]])
```

- [ ] **Step 2: Verify red**

Run: `F:\Development\Tools\miniconda3\envs\GradingExam\python.exe -m unittest tests.test_desktop -v`

Expected: FAIL because `_login` does not exist.

- [ ] **Step 3: Implement minimally**

Add `_login` to validate nonblank input, create `MarkingExamClient(cookie)`, fetch exams through `_run`, and pass the result to `_show_workbench`. Add a second test for blank input asserting it does not invoke `_run` and sets `请输入 Cookie`.

- [ ] **Step 4: Verify green**

Run: `F:\Development\Tools\miniconda3\envs\GradingExam\python.exe -m unittest tests.test_desktop -v`

Expected: PASS.

### Task 2: Build the login-to-workbench transition

**Files:**
- Modify: `zhixue_grading/desktop.py`
- Test: `tests/test_desktop.py`

- [ ] **Step 1: Write the failing test**

Add a test that successful login removes the login frame, assigns the fetched exams, and invokes the workbench builder once.

- [ ] **Step 2: Verify red**

Run: `F:\Development\Tools\miniconda3\envs\GradingExam\python.exe -m unittest tests.test_desktop -v`

Expected: FAIL because no transition exists.

- [ ] **Step 3: Implement minimally**

Add `_build_login_ui()` with a long-form Cookie input, explanatory privacy copy, `验证并进入` button, and `Ctrl+Enter` binding. Change the existing `_build_ui()` to `_build_workbench_ui()`. `_show_workbench()` destroys the login frame, stores the exams, builds the workbench, and starts the AI health check. Disable login controls during validation and restore them when an error is shown.

- [ ] **Step 4: Verify green**

Run: `F:\Development\Tools\miniconda3\envs\GradingExam\python.exe -m unittest tests.test_desktop -v`

Expected: PASS.

### Task 3: Remove file-based Cookie startup and document the behavior

**Files:**
- Modify: `zhixue_grading/desktop.py`
- Modify: `CONTINUOUS_GRADING.md`
- Test: `tests/test_desktop.py`

- [ ] **Step 1: Write the failing test**

Test that app initialization does not call `load_cookie` and begins with `client is None`.

- [ ] **Step 2: Verify red**

Run: `F:\Development\Tools\miniconda3\envs\GradingExam\python.exe -m unittest tests.test_desktop -v`

Expected: FAIL because startup calls `load_cookie()`.

- [ ] **Step 3: Implement minimally**

Initialize `self.client` as `None`, keep AI configuration loading, remove the `load_cookie` import, and guard workbench-only calls after successful login. Document that desktop Cookie input remains in memory only and is not saved in `config.json`.

- [ ] **Step 4: Verify full behavior**

Run: `F:\Development\Tools\miniconda3\envs\GradingExam\python.exe -m unittest tests.test_desktop -v`

Run: `F:\Development\Tools\miniconda3\envs\GradingExam\python.exe -m py_compile zhixue_grading\desktop.py`

Expected: all tests pass and compilation exits 0.
