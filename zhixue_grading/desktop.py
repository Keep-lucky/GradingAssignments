"""答题卡 AI 辅助评分桌面程序。"""

from io import BytesIO
import base64
from dataclasses import replace
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.request import urlopen

from PIL import Image, ImageTk

from .api import MarkingExamClient
from .card_fetcher import AnswerCard, MarkingTopic
from .config import GradingConfig, load_grading_config
from .models import MarkingExam
from .prompt_templates import get_template, template_labels
from .provider_settings import DEFAULT_BASE_URLS, list_models
from .vision_grader import AnswerRecognition, VisionGrader


class GradingDesktopApp:
    """在界面中显示答题卡、AI 建议和人工确认分数。"""

    CURRENT_PROMPT_OPTION = "当前 Prompt（config.json）"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("智学网答题卡 AI 辅助评分")
        self.root.geometry("1200x780")
        self.client: MarkingExamClient | None = None
        self.grader = VisionGrader(load_grading_config())
        self.exams: list[MarkingExam] = []
        self.topic_mapping: dict[str, str] = {}
        self.topic_counts: dict[str, tuple[int, int]] = {}
        self.current_topic_display: str | None = None
        self.reviewed_count = 0
        self._submission_in_progress = False
        self._submitted_card_id: str | None = None
        self.selected_exam: MarkingExam | None = None
        self.current_card: AnswerCard | None = None
        self.prefetched_card: AnswerCard | None = None
        self.prefetched_image: Image.Image | None = None
        self.prefetched_recognition: AnswerRecognition | None = None
        self.prefetched_score: int | None = None
        self.current_recognition: AnswerRecognition | None = None
        self._score_from_edited_transcription = False
        self.manual_review_var: tk.BooleanVar | None = None
        self.ai_latency: float | None = None
        self.image_ref: ImageTk.PhotoImage | None = None
        self._login_pending = False
        self._build_login_ui()

    def _login(self, cookie: str, on_workbench, on_error=None) -> None:
        """使用当前输入的 Cookie 加载考试，并将结果交给工作台回调。"""
        cookie = cookie.strip()
        if not cookie:
            messagebox.showerror("Cookie 无效", "请输入 Cookie")
            return
        self.client = MarkingExamClient(cookie)
        self._run(self.client.list_marking_exams, on_workbench, on_error)

    def _build_login_ui(self) -> None:
        self.login_frame = ttk.Frame(self.root, padding=32)
        self.login_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(self.login_frame, text="智学网答题卡 AI 辅助评分", font=("Microsoft YaHei UI", 20)).pack(anchor=tk.W, pady=(0, 16))
        ttk.Label(
            self.login_frame,
            text="请粘贴当前浏览器会话的 Cookie。验证成功后将加载待阅考试；Cookie 仅在本次运行的内存中使用。",
            wraplength=800,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 16))
        ttk.Label(self.login_frame, text="Cookie").pack(anchor=tk.W)
        self.cookie_input = tk.Text(self.login_frame, height=10, wrap=tk.WORD)
        self.cookie_input.pack(fill=tk.X, pady=(6, 16))
        self.cookie_input.bind("<Control-Return>", self._submit_login)
        self.login_button = ttk.Button(self.login_frame, text="登录并加载考试（Ctrl+Enter）", command=self._submit_login)
        self.login_button.pack(anchor=tk.W)
        self.cookie_input.focus_set()

    def _submit_login(self, _event=None) -> str | None:
        if self._login_pending:
            return "break"
        cookie = self.cookie_input.get("1.0", "end-1c")
        if not cookie.strip():
            self._login(cookie, self._on_login_success, self._on_login_error)
            return "break"
        self._login_pending = True
        self.cookie_input.configure(state="disabled")
        self.login_button.configure(state="disabled")
        self._login(cookie, self._on_login_success, self._on_login_error)
        return "break"

    def _on_login_error(self, message: str) -> None:
        self._login_pending = False
        self.cookie_input.configure(state="normal")
        self.login_button.configure(state="normal")
        messagebox.showerror("操作失败", message)

    def _on_login_success(self, exams: list[MarkingExam]) -> None:
        self.cookie_input.configure(state="normal")
        self.cookie_input.delete("1.0", tk.END)
        self.login_frame.destroy()
        self._build_ui()
        self._on_exams_loaded(exams)
        self._run(self.grader.check_connection, self._on_health_checked)

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.X)
        ttk.Label(top, text="考试：").pack(side=tk.LEFT)
        self.exam_box = ttk.Combobox(top, state="readonly", width=55)
        self.exam_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.exam_box.bind("<<ComboboxSelected>>", self._on_exam_selected)
        self.grading_mode = tk.StringVar(value="manual")
        ttk.Label(top, text="模式：").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Radiobutton(top, text="手动确认", variable=self.grading_mode, value="manual").pack(side=tk.LEFT)
        ttk.Radiobutton(top, text="自动接受 AI", variable=self.grading_mode, value="automatic").pack(side=tk.LEFT)
        ttk.Button(top, text="编辑 Prompt", command=self._open_prompt_editor).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(top, text="AI 设置", command=self._open_ai_settings).pack(side=tk.LEFT, padx=(8, 0))
        self.reviewed_count_var = tk.StringVar(value="已阅题数：0")
        ttk.Label(top, textvariable=self.reviewed_count_var).pack(side=tk.LEFT, padx=(12, 0))

        status_row = ttk.Frame(self.root, padding=(10, 0, 10, 6))
        status_row.pack(fill=tk.X)
        self.status_var = tk.StringVar(value="正在初始化……")
        ttk.Label(status_row, textvariable=self.status_var).pack(anchor=tk.W)

        body = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        left = ttk.Frame(body, padding=6)
        right = ttk.Frame(body, padding=6)
        body.add(left, weight=1)
        body.add(right, weight=3)

        ttk.Label(left, text="题目阅卷概览").pack(anchor=tk.W)
        self.topic_tree = ttk.Treeview(
            left, columns=("topic", "pending", "marked"), show="headings", height=22
        )
        for column, title, width in (("topic", "题号", 70), ("pending", "待阅", 70), ("marked", "已阅", 70)):
            self.topic_tree.heading(column, text=title)
            self.topic_tree.column(column, width=width, anchor=tk.CENTER)
        self.topic_tree.pack(fill=tk.BOTH, expand=True)
        self.topic_tree.bind("<<TreeviewSelect>>", self._on_topic_selected)

        self.image_label = ttk.Label(right, text="选择题号后显示答题卡", anchor=tk.CENTER)
        self.image_label.pack(fill=tk.BOTH, expand=True)
        transcription_frame = ttk.LabelFrame(right, text="AI 识别的最终作答（可修改后重新评分）", padding=6)
        transcription_frame.pack(fill=tk.X)
        self.transcription_input = tk.Text(transcription_frame, height=5, wrap=tk.WORD)
        self.transcription_input.pack(fill=tk.X)
        self.recognition_var = tk.StringVar(value="识别状态：等待答题卡")
        ttk.Label(transcription_frame, textvariable=self.recognition_var).pack(anchor=tk.W, pady=(4, 0))
        ttk.Button(
            transcription_frame, text="按当前文本重新评分", command=self._rescore_transcription
        ).pack(anchor=tk.E, pady=(4, 0))
        bottom = ttk.Frame(right, padding=(0, 8, 0, 0))
        bottom.pack(fill=tk.X)
        self.info_var = tk.StringVar(value="题号：-    满分：-    AI 建议：等待中")
        ttk.Label(bottom, textvariable=self.info_var).pack(side=tk.LEFT)
        ttk.Label(bottom, text="最终分数：").pack(side=tk.LEFT, padx=(18, 0))
        self.score_var = tk.StringVar()
        self.score_entry = ttk.Entry(bottom, textvariable=self.score_var, width=8)
        self.score_entry.pack(side=tk.LEFT)
        self.score_entry.bind("<Return>", self._submit_score)
        self.manual_review_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            bottom,
            text="风险答卷人工复核（仅自动模式）",
            variable=self.manual_review_var,
        ).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(bottom, text="提交（Enter）", command=self._submit_score).pack(side=tk.LEFT, padx=6)

    def _open_prompt_editor(self) -> None:
        """打开当前评分 Prompt 的运行时编辑窗口。"""
        self.prompt_window = tk.Toplevel(self.root)
        self.prompt_window.title("编辑评分 Prompt")
        self.prompt_window.geometry("760x760")
        self.prompt_window.transient(self.root)

        container = ttk.Frame(self.prompt_window, padding=14)
        container.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            container,
            text="选择题型预设后，填写题目和参考答案即可由 AI 生成批改 Prompt；生成结果仍可手动修改。应用后仅影响本次运行。",
            wraplength=700,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 8))
        template_row = ttk.Frame(container, padding=(0, 0, 0, 8))
        template_row.pack(fill=tk.X)
        ttk.Label(template_row, text="题型预设：").pack(side=tk.LEFT)
        self.prompt_template_var = tk.StringVar(value=self.CURRENT_PROMPT_OPTION)
        self.prompt_template_box = ttk.Combobox(
            template_row,
            textvariable=self.prompt_template_var,
            values=(self.CURRENT_PROMPT_OPTION, *template_labels()),
            state="readonly",
            width=34,
        )
        self.prompt_template_box.pack(side=tk.LEFT)
        self.prompt_template_box.bind("<<ComboboxSelected>>", self._on_prompt_template_selected)
        generation_inputs = ttk.Frame(container)
        generation_inputs.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(generation_inputs, text="题目：").pack(anchor=tk.W)
        self.prompt_question_input = tk.Text(generation_inputs, wrap=tk.WORD, height=4)
        self.prompt_question_input.pack(fill=tk.X, pady=(2, 6))
        ttk.Label(generation_inputs, text="参考答案：").pack(anchor=tk.W)
        self.prompt_answer_input = tk.Text(generation_inputs, wrap=tk.WORD, height=4)
        self.prompt_answer_input.pack(fill=tk.X, pady=(2, 6))
        self.generate_prompt_button = ttk.Button(
            generation_inputs, text="AI 生成批改 Prompt", command=self._generate_prompt
        )
        self.generate_prompt_button.pack(anchor=tk.E)
        ttk.Label(container, text="生成的批改 Prompt（可继续编辑）：").pack(anchor=tk.W)
        self.prompt_input = tk.Text(container, wrap=tk.WORD, height=14)
        self.prompt_input.pack(fill=tk.BOTH, expand=True)
        self._prompt_editor_default = self.grader.prompt
        self.prompt_input.insert("1.0", self._prompt_editor_default)
        actions = ttk.Frame(container, padding=(0, 10, 0, 0))
        actions.pack(fill=tk.X)
        ttk.Button(actions, text="取消", command=self.prompt_window.destroy).pack(side=tk.RIGHT)
        ttk.Button(actions, text="应用", command=self._save_prompt).pack(side=tk.RIGHT, padx=(0, 8))
        self.prompt_input.focus_set()

    def _open_ai_settings(self) -> None:
        """打开本次运行使用的 AI 服务设置，不将密钥写入磁盘。"""
        config = self.grader._config
        self.ai_settings_window = tk.Toplevel(self.root)
        self.ai_settings_window.title("AI 设置")
        self.ai_settings_window.geometry("640x300")
        self.ai_settings_window.transient(self.root)
        form = ttk.Frame(self.ai_settings_window, padding=16)
        form.pack(fill=tk.BOTH, expand=True)
        ttk.Label(form, text="接口类型").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.ai_provider_var = tk.StringVar(value=config.provider)
        provider_box = ttk.Combobox(form, textvariable=self.ai_provider_var, values=("openai", "anthropic"), state="readonly", width=18)
        provider_box.grid(row=0, column=1, sticky=tk.EW, pady=4)
        provider_box.bind("<<ComboboxSelected>>", self._on_ai_provider_changed)
        ttk.Label(form, text="请求地址").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.ai_base_url_var = tk.StringVar(value=config.base_url)
        ttk.Entry(form, textvariable=self.ai_base_url_var, width=56).grid(row=1, column=1, sticky=tk.EW, pady=4)
        ttk.Label(form, text="API Key").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.ai_api_key_var = tk.StringVar(value=config.api_key)
        ttk.Entry(form, textvariable=self.ai_api_key_var, show="*", width=56).grid(row=2, column=1, sticky=tk.EW, pady=4)
        ttk.Label(form, text="模型").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.ai_model_var = tk.StringVar(value=config.model)
        self.ai_model_box = ttk.Combobox(form, textvariable=self.ai_model_var, state="normal", width=42)
        self.ai_model_box.grid(row=3, column=1, sticky=tk.EW, pady=4)
        self.fetch_models_button = ttk.Button(form, text="获取模型", command=self._fetch_models)
        self.fetch_models_button.grid(row=3, column=2, padx=(8, 0))
        actions = ttk.Frame(form)
        actions.grid(row=4, column=1, sticky=tk.E, pady=(14, 0))
        ttk.Button(actions, text="取消", command=self.ai_settings_window.destroy).pack(side=tk.RIGHT)
        ttk.Button(actions, text="应用", command=self._apply_ai_settings).pack(side=tk.RIGHT, padx=(0, 8))
        form.columnconfigure(1, weight=1)

    def _on_ai_provider_changed(self, _event=None) -> None:
        self.ai_base_url_var.set(DEFAULT_BASE_URLS[self.ai_provider_var.get()])
        self.ai_model_box["values"] = ()

    def _fetch_models(self) -> None:
        self.fetch_models_button.configure(state="disabled")
        self.status_var.set("正在获取可用模型……")
        self._run(
            lambda: list_models(self.ai_provider_var.get(), self.ai_base_url_var.get(), self.ai_api_key_var.get()),
            self._on_models_loaded,
            self._on_models_load_error,
        )

    def _on_models_loaded(self, models: list[str]) -> None:
        self.ai_model_box["values"] = models
        if self.ai_model_var.get() not in models:
            self.ai_model_var.set(models[0])
        self.fetch_models_button.configure(state="normal")
        self.status_var.set(f"已获取 {len(models)} 个可用模型。")

    def _on_models_load_error(self, message: str) -> None:
        self.fetch_models_button.configure(state="normal")
        self.status_var.set("获取模型失败")
        messagebox.showerror("获取模型失败", message)

    def _apply_ai_settings(self) -> None:
        provider = self.ai_provider_var.get()
        base_url = self.ai_base_url_var.get().strip().rstrip("/")
        api_key = self.ai_api_key_var.get().strip()
        model = self.ai_model_var.get().strip()
        if not base_url or not api_key or not model:
            messagebox.showwarning("设置不完整", "请填写请求地址、API Key 并选择模型。")
            return
        old = self.grader._config
        self.grader = VisionGrader(GradingConfig(base_url, api_key, model, old.prompt, old.timeout_seconds, provider))
        self.ai_settings_window.destroy()
        self.status_var.set("AI 设置已应用到本次运行。")

    def _on_prompt_template_selected(self, _event=None) -> None:
        """将只读预设复制进编辑框，保留编辑框的后续可修改性。"""
        selected_name = self.prompt_template_var.get()
        if selected_name == self.CURRENT_PROMPT_OPTION:
            prompt = self._prompt_editor_default
        else:
            prompt = get_template(selected_name).prompt
        self.prompt_input.delete("1.0", tk.END)
        self.prompt_input.insert("1.0", prompt)

    def _generate_prompt(self) -> None:
        """使用所选预设和教师输入生成评分 Prompt。"""
        selected_name = self.prompt_template_var.get()
        question = self.prompt_question_input.get("1.0", "end-1c").strip()
        reference_answer = self.prompt_answer_input.get("1.0", "end-1c").strip()
        if selected_name == self.CURRENT_PROMPT_OPTION:
            messagebox.showwarning("请选择题型", "请先选择一个题型预设，再生成批改 Prompt。")
            return
        if not question or not reference_answer:
            messagebox.showwarning("信息不完整", "请填写题目和参考答案。")
            return
        template = get_template(selected_name).prompt
        self.generate_prompt_button.configure(state="disabled")
        self.status_var.set("正在根据题目和参考答案生成批改 Prompt……")
        self._run(
            lambda: self.grader.generate_grading_prompt(template, question, reference_answer),
            self._on_prompt_generated,
            self._on_prompt_generation_error,
        )

    def _on_prompt_generated(self, prompt: str) -> None:
        self.prompt_input.delete("1.0", tk.END)
        self.prompt_input.insert("1.0", prompt)
        self.generate_prompt_button.configure(state="normal")
        self.status_var.set("批改 Prompt 已生成，请确认或编辑后点击“应用”。")

    def _on_prompt_generation_error(self, message: str) -> None:
        self.generate_prompt_button.configure(state="normal")
        self.status_var.set("批改 Prompt 生成失败")
        messagebox.showerror("生成失败", message)

    def _save_prompt(self) -> None:
        prompt = self.prompt_input.get("1.0", "end-1c").strip()
        if not prompt:
            messagebox.showwarning("Prompt 不能为空", "请输入评分 Prompt。")
            return
        try:
            self.grader.set_prompt(prompt)
        except ValueError as error:
            messagebox.showwarning("Prompt 无效", str(error))
            return
        self.prompt_window.destroy()
        self.status_var.set("评分 Prompt 已更新，将用于后续 AI 评分。")

    def _run(self, function, on_success, on_error=None) -> None:
        def worker() -> None:
            try:
                result = function()
            except Exception as error:  # 在 UI 中呈现后台失败原因
                error_message = str(error)
                error_handler = on_error or self._show_error
                self.root.after(0, lambda message=error_message: error_handler(message))
                return
            self.root.after(0, lambda: on_success(result))
        threading.Thread(target=worker, daemon=True).start()

    def _on_exams_loaded(self, exams: list[MarkingExam]) -> None:
        self.exams = exams
        self.exam_box["values"] = [exam.exam_name for exam in self.exams]
        self.status_var.set("请选择考试")

    def _on_health_checked(self, latency: float) -> None:
        self.ai_latency = latency
        if self.selected_exam is None:
            self.status_var.set(f"AI 接口正常（轻量请求 {latency:.1f} 秒）")

    def _on_exam_selected(self, _event=None) -> None:
        self.selected_exam = self.exams[self.exam_box.current()]
        self.status_var.set("正在读取题目概览……")
        self._run(lambda: self.client.fetch_current_answer_card(self.selected_exam), self._on_overview_loaded)

    def _on_overview_loaded(self, card: AnswerCard) -> None:
        self.topic_mapping = {topic.display_topic: topic.topic_num_str for topic in card.topics}
        self.topic_counts = {
            topic.display_topic: (topic.pending_count or 0, topic.marked_count or 0)
            for topic in card.topics
        }
        self.topic_tree.delete(*self.topic_tree.get_children())
        for topic in card.topics:
            self.topic_tree.insert("", tk.END, iid=topic.display_topic, values=(topic.display_topic, topic.pending_count or 0, topic.marked_count or 0))
        self._set_reviewed_count(sum(marked for _pending, marked in self.topic_counts.values()))
        self.status_var.set("请选择左侧题号")

    def _on_topic_selected(self, _event=None) -> None:
        selected = self.topic_tree.selection()
        if not selected or self.selected_exam is None:
            return
        self.current_topic_display = selected[0]
        topic_num_str = self.topic_mapping[selected[0]]
        self.status_var.set("正在获取答题卡……")
        self._run(lambda: self.client.fetch_current_answer_card(self.selected_exam, topic_num_str=topic_num_str), self._on_card_loaded)

    def _on_card_loaded(self, card: AnswerCard) -> None:
        self.current_card = card
        self.current_recognition = None
        self._score_from_edited_transcription = False
        self.score_var.set("")
        self.transcription_input.delete("1.0", tk.END)
        self.recognition_var.set("识别状态：正在识别手写作答……")
        self.info_var.set(f"题号：{card.topic_num_str}    满分：{card.standard_score}    AI 建议：评分中")
        self.status_var.set("正在下载答题卡并启动 AI 评分……")
        # 图片下载完成后复用同一个内存对象来显示和评分，避免同一答卷下载两次。
        self._run(
            lambda: self._load_image(card),
            lambda image: self._on_current_image_loaded(card, image),
        )
        self._start_preload(card)

    def _on_current_image_loaded(self, card: AnswerCard, image: Image.Image) -> None:
        if self.current_card and self.current_card.scan_record_id == card.scan_record_id:
            self._show_card_image(image)
            self._run(
                lambda: self._recognize_from_image(card, image),
                lambda recognition: self._on_current_recognition(card, recognition),
            )

    def _on_current_recognition(self, card: AnswerCard, recognition: AnswerRecognition) -> None:
        if self.current_card and self.current_card.scan_record_id == card.scan_record_id:
            self.current_recognition = recognition
            self._display_recognition(recognition)
            self._run(
                lambda: self.grader.grade_transcription(card, recognition.transcription),
                lambda score: self._on_current_score(card, score),
            )

    def _on_current_score(self, card: AnswerCard, score: int) -> None:
        if self.current_card and self.current_card.scan_record_id == card.scan_record_id:
            self._on_grade_ready(score)

    def _start_preload(self, card: AnswerCard) -> None:
        """后台预加载下一张答卷、图片与 AI 建议分。"""
        if self.selected_exam is None:
            return
        exam = self.selected_exam
        self.prefetched_card = None
        self.prefetched_image = None
        self.prefetched_recognition = None
        self.prefetched_score = None
        self._run(
            lambda: self.client.preload_next_answer_card(
                exam, topic_num_str=card.topic_num_str, standard_score=card.standard_score
            ),
            self._on_prefetched_card,
        )

    def _on_prefetched_card(self, card: AnswerCard | None) -> None:
        if card is None:
            return
        self.prefetched_card = card
        self._run(
            lambda: self._load_image(card),
            lambda image: self._on_prefetched_image_loaded(card, image),
        )

    def _on_prefetched_image_loaded(self, card: AnswerCard, image: Image.Image) -> None:
        if self.prefetched_card and self.prefetched_card.scan_record_id == card.scan_record_id:
            self.prefetched_image = image
            self._run(
                lambda: self._recognize_from_image(card, image),
                lambda recognition: self._on_prefetched_recognition(card, recognition),
            )
        if self.current_card and self.current_card.scan_record_id == card.scan_record_id:
            self._show_card_image(image)

    def _on_prefetched_recognition(
        self, card: AnswerCard, recognition: AnswerRecognition
    ) -> None:
        is_prefetched = bool(
            self.prefetched_card
            and self.prefetched_card.scan_record_id == card.scan_record_id
        )
        is_current = bool(
            self.current_card and self.current_card.scan_record_id == card.scan_record_id
        )
        if is_prefetched:
            self.prefetched_recognition = recognition
        if is_current:
            self.current_recognition = recognition
            self._display_recognition(recognition)
        if is_prefetched or is_current:
            self._run(
                lambda: self.grader.grade_transcription(card, recognition.transcription),
                lambda score: self._on_prefetched_score(card, score),
            )

    def _on_prefetched_score(self, card: AnswerCard, score: int) -> None:
        if self.prefetched_card and self.prefetched_card.scan_record_id == card.scan_record_id:
            self.prefetched_score = score
        if self.current_card and self.current_card.scan_record_id == card.scan_record_id:
            self._on_grade_ready(score)

    @staticmethod
    def _load_image(card: AnswerCard) -> Image.Image:
        with urlopen(card.image_urls[0], timeout=30) as response:
            image = Image.open(BytesIO(response.read()))
            image.load()
        return image

    @staticmethod
    def _image_to_data_url(image: Image.Image) -> str:
        """将已在本地取得的答题卡编码给 AI，避免模型访问智学网链接。"""
        buffer = BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def _recognize_from_image(self, card: AnswerCard, image: Image.Image) -> AnswerRecognition:
        """使用已下载的内存图像识别作答，不再发起第二次图片下载。"""
        local_card = replace(card, image_urls=(self._image_to_data_url(image),))
        return self.grader.recognize(local_card)

    def _display_recognition(self, recognition: AnswerRecognition) -> None:
        self.transcription_input.delete("1.0", tk.END)
        self.transcription_input.insert("1.0", recognition.transcription)
        if recognition.needs_review:
            issues = list(recognition.uncertain_spans)
            if recognition.crossed_out_text:
                issues.append("存在划除或删改内容")
            if not recognition.final_answer_clear:
                issues.append("最终作答不明确")
            issue_text = "；".join(issues) or "模型要求复核"
            self.recognition_var.set(f"识别状态：发现风险（{issue_text}）。{recognition.reason}")
        else:
            self.recognition_var.set("识别状态：文字清晰，可核对后评分。")

    def _rescore_transcription(self) -> None:
        if self.current_card is None:
            return
        transcription = self.transcription_input.get("1.0", "end-1c").strip()
        self._score_from_edited_transcription = True
        self.score_var.set("")
        self.status_var.set("正在按当前转录文本重新评分……")
        card = self.current_card
        self._run(
            lambda: self.grader.grade_transcription(card, transcription),
            lambda score: self._on_current_score(card, score),
        )

    def _manual_review_selected(self) -> bool:
        """仅在自动模式且教师开启风险复核时阻止自动提交。"""
        manual_review_var = getattr(self, "manual_review_var", None)
        recognition = getattr(self, "current_recognition", None)
        return bool(
            self.grading_mode.get() == "automatic"
            and manual_review_var is not None
            and manual_review_var.get()
            and recognition
            and recognition.needs_review
        )

    def _show_card_image(self, image: Image.Image) -> None:
        # 给模型保留原始分辨率；界面预览使用副本，避免影响后续识别。
        preview = image.copy()
        preview.thumbnail((820, 620))
        self.image_ref = ImageTk.PhotoImage(preview)
        self.image_label.configure(image=self.image_ref, text="")
        self.status_var.set("答题卡已加载，正在等待 AI 建议分……")

    def _on_grade_ready(self, score: int) -> None:
        if self.current_card is None:
            return
        self.score_var.set(str(score))
        self.info_var.set(f"题号：{self.current_card.topic_num_str}    满分：{self.current_card.standard_score}    AI 建议：{score} 分")
        if (
            self.grading_mode.get() == "automatic"
            and self.current_recognition is not None
            and not self._manual_review_selected()
            and not self._score_from_edited_transcription
        ):
            self.status_var.set("自动模式：正在接受 AI 建议并提交……")
            self._submit_score()
            return
        if self._manual_review_selected():
            self.status_var.set("风险答卷已进入人工复核，请核对转录文本和分数后手动提交。")
            self.score_entry.focus_set()
            self.score_entry.select_range(0, tk.END)
            return
        self.status_var.set("请核对分数，按 Enter 提交或直接修改")
        self.score_entry.focus_set()
        self.score_entry.select_range(0, tk.END)

    def _submit_score(self, _event=None) -> None:
        if self._submission_in_progress:
            return
        if self.current_card is None or self.selected_exam is None:
            return
        try:
            score = int(self.score_var.get())
            if not 0 <= score <= self.current_card.standard_score:
                raise ValueError
        except (TypeError, ValueError):
            messagebox.showwarning("分数无效", "请输入满分范围内的整数。")
            return
        card = self.current_card
        exam = self.selected_exam
        self._submission_in_progress = True
        self._submitted_card_id = card.scan_record_id
        self.status_var.set("正在提交分数……")
        self._run(
            lambda: self._submit_and_get_next(exam, card, score),
            self._on_next_card,
            self._on_submit_error,
        )

    def _on_submit_error(self, message: str) -> None:
        self._submission_in_progress = False
        self._submitted_card_id = None
        self._show_error(message)

    def _submit_and_get_next(self, exam: MarkingExam, card: AnswerCard, score: int) -> AnswerCard:
        self.client.submit_confirmed_score(exam, card, score)
        return self.client.fetch_current_answer_card(exam, topic_num_str=card.topic_num_str)

    def _on_next_card(self, card: AnswerCard) -> None:
        if self.current_card and card.scan_record_id == self.current_card.scan_record_id:
            self._submission_in_progress = False
            self._submitted_card_id = None
            self.status_var.set("平台尚未切换答卷，已停止以避免重复提交。")
            return
        if self._submission_in_progress and self._submitted_card_id:
            self._record_successful_submission()
        self._submission_in_progress = False
        self._submitted_card_id = None
        if self.prefetched_card and card.scan_record_id == self.prefetched_card.scan_record_id:
            self._promote_prefetched_card(card)
            return
        self._on_card_loaded(card)

    def _set_reviewed_count(self, count: int) -> None:
        self.reviewed_count = count
        if hasattr(self, "reviewed_count_var"):
            self.reviewed_count_var.set(f"已阅题数：{count}")

    def _record_successful_submission(self) -> None:
        """仅在平台返回不同答卷后更新本地已阅数量。"""
        self._set_reviewed_count(self.reviewed_count + 1)
        if self.current_topic_display is None:
            return
        pending, marked = self.topic_counts.get(self.current_topic_display, (0, 0))
        marked += 1
        self.topic_counts[self.current_topic_display] = (pending, marked)
        self.topic_tree.item(
            self.current_topic_display,
            values=(self.current_topic_display, pending, marked),
        )

    def _promote_prefetched_card(self, card: AnswerCard) -> None:
        """平台确认切换后，将已预加载的图片和建议分提升为当前答卷。"""
        self.current_card = card
        self.current_recognition = self.prefetched_recognition
        self._score_from_edited_transcription = False
        self.score_var.set("")
        self.info_var.set(f"题号：{card.topic_num_str}    满分：{card.standard_score}    AI 建议：评分中")
        if self.prefetched_image is not None:
            self._show_card_image(self.prefetched_image)
        else:
            self.image_label.configure(image="", text="下一张答题卡图片加载中……")
        if self.current_recognition is not None:
            self._display_recognition(self.current_recognition)
        else:
            self.transcription_input.delete("1.0", tk.END)
            self.recognition_var.set("识别状态：正在识别手写作答……")
        if self.prefetched_score is not None:
            self._on_grade_ready(self.prefetched_score)
        else:
            self.status_var.set("已切换下一张，正在等待已启动的 AI 评分……")
        self._start_preload(card)

    def _show_error(self, message: str) -> None:
        self.status_var.set("操作失败")
        messagebox.showerror("操作失败", message)


def main() -> None:
    root = tk.Tk()
    GradingDesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
