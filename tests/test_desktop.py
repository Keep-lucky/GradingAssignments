"""桌面端后台任务调度的回归测试。"""

import sys
import threading
import unittest
from unittest.mock import Mock, patch

if "zhixuewang.account" not in sys.modules:
    zhixuewang = Mock()
    sys.modules["zhixuewang"] = zhixuewang
    sys.modules["zhixuewang.account"] = zhixuewang.account

from PIL import Image

from zhixue_grading.card_fetcher import AnswerCard, MarkingTopic
from zhixue_grading.config import GradingConfig
from zhixue_grading.desktop import GradingDesktopApp
from zhixue_grading.prompt_templates import get_template, template_labels
from zhixue_grading.vision_grader import VisionGrader


class ImmediateRoot:
    """暂存 Tk 回调，模拟后台线程结束后才由主线程执行。"""

    def __init__(self) -> None:
        self.callbacks = []
        self.scheduled = threading.Event()

    def after(self, _delay: int, callback) -> None:
        self.callbacks.append(callback)
        self.scheduled.set()

    def run_pending(self) -> list[Exception]:
        errors = []
        for callback in self.callbacks:
            try:
                callback()
            except Exception as error:
                errors.append(error)
        return errors


class ValueHolder:
    def __init__(self, value="") -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class FakeTopicTree:
    def __init__(self) -> None:
        self.rows = {}

    def delete(self, *item_ids) -> None:
        for item_id in item_ids:
            self.rows.pop(item_id, None)

    def get_children(self):
        return tuple(self.rows)

    def insert(self, _parent, _index, *, iid, values) -> None:
        self.rows[iid] = values

    def item(self, item_id, *, values) -> None:
        self.rows[item_id] = values


def make_card(scan_record_id: str, *, topic_num_str: str = "2") -> AnswerCard:
    return AnswerCard(
        scan_record_id=scan_record_id,
        marking_item_ids=("item-1",),
        topic_num_str=topic_num_str,
        image_urls=("https://example.test/card.png",),
        standard_score=5,
        has_previous=False,
        has_next=True,
        topics=(),
    )


class DesktopBackgroundTaskTests(unittest.TestCase):
    def test_image_is_encoded_as_data_url_for_ai_request(self) -> None:
        image = Image.new("RGB", (1, 1), "white")

        data_url = GradingDesktopApp._image_to_data_url(image)

        self.assertTrue(data_url.startswith("data:image/png;base64,"))
        self.assertNotIn("zhixue", data_url)

    def test_run_displays_background_exception_message(self) -> None:
        app = GradingDesktopApp.__new__(GradingDesktopApp)
        root = ImmediateRoot()
        app.root = root
        finished = threading.Event()
        messages: list[str] = []

        def show_error(message: str) -> None:
            messages.append(message)
            finished.set()

        app._show_error = show_error

        def fail() -> None:
            raise RuntimeError("连接失败")

        app._run(fail, lambda _result: self.fail("不应调用成功回调"))

        self.assertTrue(root.scheduled.wait(1), "异常回调未被调度")
        self.assertEqual(root.run_pending(), [])
        self.assertTrue(finished.is_set(), "异常信息未被显示")
        self.assertEqual(messages, ["连接失败"])

    def test_current_card_download_is_reused_for_display_and_grading(self) -> None:
        """同一答卷只下载一次，显示和 AI 评分共享该内存图像。"""
        app = GradingDesktopApp.__new__(GradingDesktopApp)
        card = make_card("card-1")
        image = Image.new("RGB", (2, 2), "white")
        app.score_var = ValueHolder()
        app.info_var = ValueHolder()
        app.status_var = ValueHolder()
        app._load_image = Mock(return_value=image)
        app._show_card_image = Mock()
        app._grade_from_image = Mock(return_value=4)
        app._on_current_score = Mock()
        app._start_preload = Mock()

        def run_immediately(function, on_success, _on_error=None):
            on_success(function())

        app._run = run_immediately

        app._on_card_loaded(card)

        app._load_image.assert_called_once_with(card)
        app._show_card_image.assert_called_once_with(image)
        app._grade_from_image.assert_called_once()
        graded_card, graded_image = app._grade_from_image.call_args.args
        self.assertIs(graded_card, card)
        self.assertIs(graded_image, image)


class DesktopCookieLoginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = GradingDesktopApp.__new__(GradingDesktopApp)
        self.app.root = ImmediateRoot()
        self.app._login_pending = False

    def test_login_trims_cookie_fetches_exams_and_calls_workbench(self) -> None:
        exams = [object()]
        client = Mock()
        client.list_marking_exams.return_value = exams
        workbench = Mock()

        with patch("zhixue_grading.desktop.MarkingExamClient", return_value=client) as make_client:
            self.app._login("  session=secret  ", workbench)

        make_client.assert_called_once_with("session=secret")
        client.list_marking_exams.assert_called_once_with()
        self.assertTrue(self.app.root.scheduled.wait(1), "考试结果回调未被调度")
        self.assertEqual(self.app.root.run_pending(), [])
        workbench.assert_called_once_with(exams)

    def test_login_with_blank_cookie_does_not_start_background_work(self) -> None:
        with (
            patch("zhixue_grading.desktop.MarkingExamClient") as make_client,
            patch("zhixue_grading.desktop.threading.Thread") as make_thread,
            patch("zhixue_grading.desktop.messagebox.showerror") as show_error,
        ):
            self.app._login(" \t\n ", Mock())

        make_client.assert_not_called()
        make_thread.assert_not_called()
        show_error.assert_called_once_with("Cookie 无效", "请输入 Cookie")

    def test_startup_shows_login_before_workbench(self) -> None:
        root = Mock()
        with (
            patch("zhixue_grading.desktop.load_grading_config"),
            patch("zhixue_grading.desktop.VisionGrader"),
            patch.object(GradingDesktopApp, "_build_login_ui") as build_login,
            patch.object(GradingDesktopApp, "_build_ui") as build_workbench,
        ):
            GradingDesktopApp(root)
        build_login.assert_called_once_with()
        build_workbench.assert_not_called()

    def test_login_view_has_cookie_field_and_ctrl_enter_shortcut(self) -> None:
        with (
            patch("zhixue_grading.desktop.ttk.Frame") as frame,
            patch("zhixue_grading.desktop.ttk.Label") as label,
            patch("zhixue_grading.desktop.tk.Text") as text_field,
            patch("zhixue_grading.desktop.ttk.Button") as button,
        ):
            self.app._build_login_ui()
        self.assertTrue(any("Cookie" in call.kwargs.get("text", "") for call in label.call_args_list))
        text_field.return_value.bind.assert_called_once_with("<Control-Return>", self.app._submit_login)
        button.assert_called_once()
        self.assertEqual(button.call_args.kwargs["command"], self.app._submit_login)

    def test_submit_disables_controls_until_exam_validation_finishes(self) -> None:
        self.app.cookie_input = Mock()
        self.app.cookie_input.get.return_value = " session=secret "
        self.app.login_button = Mock()
        with patch.object(self.app, "_login") as login:
            self.app._submit_login()
        self.app.cookie_input.configure.assert_called_once_with(state="disabled")
        self.app.login_button.configure.assert_called_once_with(state="disabled")
        login.assert_called_once_with(" session=secret ", self.app._on_login_success, self.app._on_login_error)

    def test_submit_ignores_repeated_shortcut_during_validation(self) -> None:
        self.app.cookie_input = Mock()
        self.app.cookie_input.get.return_value = "session=secret"
        self.app.login_button = Mock()
        self.app._login_pending = False
        with patch.object(self.app, "_login") as login:
            self.app._submit_login()
            self.app._submit_login()
        login.assert_called_once()

    def test_login_error_restores_controls_and_reports_failure(self) -> None:
        self.app.cookie_input = Mock()
        self.app.login_button = Mock()
        with patch("zhixue_grading.desktop.messagebox.showerror") as show_error:
            self.app._on_login_error("Cookie 已失效")
        self.app.cookie_input.configure.assert_called_once_with(state="normal")
        self.app.login_button.configure.assert_called_once_with(state="normal")
        show_error.assert_called_once_with("操作失败", "Cookie 已失效")

    def test_failed_exam_validation_restores_login_controls(self) -> None:
        self.app.cookie_input = Mock()
        self.app.login_button = Mock()
        client = Mock()
        client.list_marking_exams.side_effect = RuntimeError("Cookie 已失效")
        with (
            patch("zhixue_grading.desktop.MarkingExamClient", return_value=client),
            patch("zhixue_grading.desktop.messagebox.showerror") as show_error,
        ):
            self.app._login("session=secret", self.app._on_login_success, self.app._on_login_error)
            self.assertTrue(self.app.root.scheduled.wait(1))
            self.assertEqual(self.app.root.run_pending(), [])
        self.app.cookie_input.configure.assert_called_once_with(state="normal")
        self.app.login_button.configure.assert_called_once_with(state="normal")
        show_error.assert_called_once_with("操作失败", "Cookie 已失效")

    def test_success_replaces_login_with_fetched_exams_and_starts_health_check(self) -> None:
        exams = [Mock(exam_name="期中考试")]
        self.app.cookie_input = Mock()
        self.app.login_frame = Mock()
        self.app.grader = Mock()
        self.app.exam_box = {"values": []}
        self.app.status_var = Mock()
        self.app.selected_exam = None
        with (
            patch.object(self.app, "_build_ui"),
            patch.object(self.app, "_run") as run,
        ):
            self.app._on_login_success(exams)
        self.app.cookie_input.delete.assert_called_once_with("1.0", "end")
        self.app.login_frame.destroy.assert_called_once_with()
        self.assertEqual(self.app.exams, exams)
        self.assertEqual(self.app.exam_box["values"], ["期中考试"])
        run.assert_called_once_with(self.app.grader.check_connection, self.app._on_health_checked)


class DesktopGradingModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = GradingDesktopApp.__new__(GradingDesktopApp)

    def test_overview_initializes_reviewed_count_from_marked_topics(self) -> None:
        card = make_card("card-1")
        card = AnswerCard(
            **{**card.__dict__, "topics": (
                MarkingTopic("2", "2", 10, 3, 8, False),
                MarkingTopic("3", "3", 8, 2, 7, False),
            )}
        )
        self.app.topic_tree = FakeTopicTree()
        self.app.status_var = ValueHolder()
        self.app.reviewed_count_var = ValueHolder()

        self.app._on_overview_loaded(card)

        self.assertEqual(self.app.reviewed_count, 5)
        self.assertEqual(self.app.reviewed_count_var.get(), "已阅题数：5")

    def test_manual_mode_keeps_ai_score_for_teacher_confirmation(self) -> None:
        self.app.current_card = make_card("card-1")
        self.app.grading_mode = ValueHolder("manual")
        self.app.score_var = ValueHolder()
        self.app.info_var = ValueHolder()
        self.app.status_var = ValueHolder()
        self.app.score_entry = Mock()
        self.app._submit_score = Mock()

        self.app._on_grade_ready(4)

        self.assertEqual(self.app.score_var.get(), "4")
        self.app._submit_score.assert_not_called()

    def test_automatic_mode_submits_ai_score_without_manual_confirmation(self) -> None:
        self.app.current_card = make_card("card-1")
        self.app.grading_mode = ValueHolder("automatic")
        self.app.score_var = ValueHolder()
        self.app.info_var = ValueHolder()
        self.app.status_var = ValueHolder()
        self.app.score_entry = Mock()
        self.app._submit_score = Mock()

        self.app._on_grade_ready(4)

        self.assertEqual(self.app.score_var.get(), "4")
        self.app._submit_score.assert_called_once_with()

    def test_successful_card_transition_updates_reviewed_count_and_topic_row(self) -> None:
        self.app.current_card = make_card("card-1")
        self.app.prefetched_card = None
        self.app._submission_in_progress = True
        self.app._submitted_card_id = "card-1"
        self.app.current_topic_display = "2"
        self.app.reviewed_count = 3
        self.app.reviewed_count_var = ValueHolder()
        self.app.topic_counts = {"2": (10, 3)}
        self.app.topic_tree = FakeTopicTree()
        self.app.topic_tree.rows["2"] = ("2", 10, 3)
        self.app._on_card_loaded = Mock()

        self.app._on_next_card(make_card("card-2"))

        self.assertEqual(self.app.reviewed_count, 4)
        self.assertEqual(self.app.reviewed_count_var.get(), "已阅题数：4")
        self.assertEqual(self.app.topic_tree.rows["2"], ("2", 10, 4))
        self.app._on_card_loaded.assert_called_once()

    def test_same_card_response_does_not_update_reviewed_count(self) -> None:
        self.app.current_card = make_card("card-1")
        self.app._submission_in_progress = True
        self.app._submitted_card_id = "card-1"
        self.app.reviewed_count = 3
        self.app.status_var = ValueHolder()

        self.app._on_next_card(make_card("card-1"))

        self.assertEqual(self.app.reviewed_count, 3)


class DesktopLayoutTests(unittest.TestCase):
    def test_status_uses_its_own_row_so_exam_box_width_does_not_follow_status_text(self) -> None:
        app = GradingDesktopApp.__new__(GradingDesktopApp)
        app.root = Mock()
        toolbar = Mock()
        status_row = Mock()
        body = Mock()
        left = Mock()
        right = Mock()
        bottom = Mock()
        string_vars = [ValueHolder(), ValueHolder(), ValueHolder(), ValueHolder(), ValueHolder()]

        with (
            patch("zhixue_grading.desktop.ttk.Frame", side_effect=[toolbar, status_row, left, right, bottom]),
            patch("zhixue_grading.desktop.ttk.PanedWindow", return_value=body),
            patch("zhixue_grading.desktop.ttk.Label") as label,
            patch("zhixue_grading.desktop.ttk.Combobox"),
            patch("zhixue_grading.desktop.ttk.Radiobutton"),
            patch("zhixue_grading.desktop.ttk.Treeview"),
            patch("zhixue_grading.desktop.ttk.Entry"),
            patch("zhixue_grading.desktop.ttk.Button"),
            patch("zhixue_grading.desktop.tk.StringVar", side_effect=string_vars),
        ):
            app._build_ui()

        status_label = next(
            call for call in label.call_args_list
            if call.kwargs.get("textvariable") is app.status_var
        )
        self.assertIs(status_label.args[0], status_row)


class DesktopPromptEditorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = GradingDesktopApp.__new__(GradingDesktopApp)
        self.app.root = Mock()
        self.app.grader = Mock()
        self.app.status_var = ValueHolder()

    def test_open_prompt_editor_populates_text_with_config_loaded_prompt(self) -> None:
        self.app.grader.prompt = "config prompt"
        prompt_window = Mock()
        prompt_inputs = [Mock(), Mock(), Mock()]

        with (
            patch("zhixue_grading.desktop.tk.Toplevel", return_value=prompt_window),
            patch("zhixue_grading.desktop.tk.Text", side_effect=prompt_inputs),
            patch("zhixue_grading.desktop.ttk.Frame"),
            patch("zhixue_grading.desktop.ttk.Label"),
            patch("zhixue_grading.desktop.ttk.Button"),
            patch("zhixue_grading.desktop.ttk.Combobox"),
            patch("zhixue_grading.desktop.tk.StringVar", return_value=ValueHolder()),
        ):
            self.app._open_prompt_editor()

        prompt_inputs[2].insert.assert_called_once_with("1.0", "config prompt")

    def test_save_prompt_applies_trimmed_value_without_writing_config(self) -> None:
        self.app.prompt_input = Mock()
        self.app.prompt_input.get.return_value = "  revised prompt  "
        self.app.prompt_window = Mock()

        self.app._save_prompt()

        self.app.grader.set_prompt.assert_called_once_with("revised prompt")
        self.app.prompt_window.destroy.assert_called_once_with()
        self.assertEqual(self.app.status_var.get(), "评分 Prompt 已更新，将用于后续 AI 评分。")

    def test_save_prompt_rejects_blank_value(self) -> None:
        self.app.prompt_input = Mock()
        self.app.prompt_input.get.return_value = " \n "
        self.app.prompt_window = Mock()

        with patch("zhixue_grading.desktop.messagebox.showwarning") as show_warning:
            self.app._save_prompt()

        self.app.grader.set_prompt.assert_not_called()
        self.app.prompt_window.destroy.assert_not_called()
        show_warning.assert_called_once_with("Prompt 不能为空", "请输入评分 Prompt。")


class VisionGraderPromptTests(unittest.TestCase):
    def test_set_prompt_replaces_active_prompt_and_strips_surrounding_whitespace(self) -> None:
        grader = VisionGrader.__new__(VisionGrader)
        grader._config = GradingConfig("https://example.test", "key", "model", "config prompt")

        grader.set_prompt("  revised prompt  ")

        self.assertEqual(grader.prompt, "revised prompt")


class PromptTemplateTests(unittest.TestCase):
    def test_template_catalog_labels_each_supported_question_type(self) -> None:
        labels = template_labels()

        self.assertIn("文言文翻译", labels)
        self.assertIn("文言文阅读：内容理解与表达效果", labels)
        self.assertIn("古诗文默写填空", labels)
        self.assertIn("现代文阅读：句意理解与主题探究", labels)
        self.assertIn("古诗鉴赏：表现手法", labels)
        self.assertIn("综合材料：填空与关系分析", labels)
        self.assertEqual(get_template("文言文翻译").name, "文言文翻译")


class EditablePromptInput:
    def __init__(self, content: str = "") -> None:
        self.content = content

    def delete(self, _start: str, _end: str) -> None:
        self.content = ""

    def insert(self, _index: str, content: str) -> None:
        self.content += content

    def get(self, _start: str, _end: str) -> str:
        return self.content


class DesktopPromptTemplateTests(unittest.TestCase):
    def test_selecting_template_replaces_editor_text_with_an_editable_copy(self) -> None:
        app = GradingDesktopApp.__new__(GradingDesktopApp)
        app.prompt_template_var = ValueHolder("文言文翻译")
        app.prompt_input = EditablePromptInput("current prompt")

        app._on_prompt_template_selected()

        app.prompt_input.insert("end", "\n教师补充要求")
        self.assertEqual(
            app.prompt_input.get("1.0", "end-1c"),
            get_template("文言文翻译").prompt + "\n教师补充要求",
        )
        self.assertNotIn("教师补充要求", get_template("文言文翻译").prompt)


class DesktopPromptGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = GradingDesktopApp.__new__(GradingDesktopApp)
        self.app.grader = Mock()
        self.app.status_var = ValueHolder()
        self.app.prompt_template_var = ValueHolder("文言文翻译")
        self.app.prompt_question_input = EditablePromptInput("翻译下面句子")
        self.app.prompt_answer_input = EditablePromptInput("把句子翻译成现代汉语")
        self.app.generate_prompt_button = Mock()

    def test_generate_prompt_uses_selected_template_question_and_reference_answer(self) -> None:
        captured = {}

        def run(function, on_success, on_error):
            captured["result"] = function()
            captured["success"] = on_success
            captured["error"] = on_error

        self.app._run = run
        self.app._generate_prompt()

        self.app.grader.generate_grading_prompt.assert_called_once_with(
            get_template("文言文翻译").prompt, "翻译下面句子", "把句子翻译成现代汉语"
        )
        self.assertEqual(self.app.status_var.get(), "正在根据题目和参考答案生成批改 Prompt……")

    def test_generate_prompt_requires_question_and_reference_answer(self) -> None:
        self.app.prompt_question_input = EditablePromptInput()

        with patch("zhixue_grading.desktop.messagebox.showwarning") as show_warning:
            self.app._generate_prompt()

        self.app.grader.generate_grading_prompt.assert_not_called()
        show_warning.assert_called_once_with("信息不完整", "请填写题目和参考答案。")


if __name__ == "__main__":
    unittest.main()
