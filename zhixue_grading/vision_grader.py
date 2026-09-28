"""OpenAI 兼容视觉评分客户端。"""

import json
import re
from dataclasses import replace
from dataclasses import dataclass
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError

from .card_fetcher import AnswerCard
from .config import GradingConfig


@dataclass(frozen=True)
class AnswerRecognition:
    """模型对答题文字及其可判定性的识别结果。"""

    transcription: str
    uncertain_spans: tuple[str, ...]
    crossed_out_text: tuple[str, ...]
    final_answer_clear: bool
    needs_review: bool
    reason: str


class VisionGrader:
    """将答题图片发送到 OpenAI Chat Completions 兼容接口。"""

    def __init__(self, config: GradingConfig) -> None:
        self._config = config
        self._client = (
            OpenAI(base_url=config.base_url, api_key=config.api_key, timeout=config.timeout_seconds, max_retries=2)
            if config.provider == "openai" else None
        )

    @property
    def prompt(self) -> str:
        """返回当前运行中用于评分的 Prompt。"""
        return self._config.prompt

    def set_prompt(self, prompt: str) -> None:
        """更新本次运行的评分 Prompt，不写入本地配置文件。"""
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("评分 Prompt 不能为空。")
        self._config = replace(self._config, prompt=prompt)

    def _complete(self, content, *, max_tokens: int, json_mode: bool = False) -> str:
        """以当前选择的 OpenAI 或 Anthropic 协议完成一次非流式请求。"""
        if self._config.provider == "openai":
            response = self._client.chat.completions.create(
                model=self._config.model, messages=[{"role": "user", "content": content}],
                temperature=0, max_tokens=max_tokens,
                response_format={"type": "json_object"} if json_mode else None,
                extra_body={"thinking": {"type": "disabled"}},
            )
            return response.choices[0].message.content or ""
        parts = [{"type": "text", "text": content}] if isinstance(content, str) else []
        if not isinstance(content, str):
            for item in content:
                if item["type"] == "text":
                    parts.append({"type": "text", "text": item["text"]})
                else:
                    data_url = item["image_url"]["url"]
                    header, encoded = data_url.split(",", 1)
                    media_type = header.split(";")[0].split(":", 1)[1]
                    parts.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}})
        body = {"model": self._config.model, "max_tokens": max_tokens, "temperature": 0, "messages": [{"role": "user", "content": parts}]}
        request = Request(
            f"{self._config.base_url.rstrip('/')}/v1/messages",
            data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"content-type": "application/json", "x-api-key": self._config.api_key, "anthropic-version": "2023-06-01"},
        )
        try:
            with urlopen(request, timeout=self._config.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return str(payload["content"][0]["text"])
        except (HTTPError, URLError, TimeoutError, KeyError, TypeError, ValueError) as error:
            raise RuntimeError("Anthropic API 请求失败。") from error

    def generate_grading_prompt(self, template: str, question: str, reference_answer: str) -> str:
        """根据题型预设、题目和参考答案生成可直接用于评分的 Prompt。"""
        template = template.strip()
        question = question.strip()
        reference_answer = reference_answer.strip()
        if not template or not question or not reference_answer:
            raise ValueError("题型预设、题目和参考答案均不能为空。")

        request = f"""你是一名专业的初中语文阅卷规则设计助手。
请严格参考下方的题型评分 Prompt 模板，并结合题目和参考答案，生成一份可直接交给视觉评分模型使用的完整评分 Prompt。

生成要求：
1. 保留模板的角色、评分原则和“只输出 JSON：{{\"score\": 整数}}”等安全输出约束。
2. 将模板中的 {{题目}} 和 {{参考答案}} 替换为给定内容；根据题目和答案补充具体、可执行的评分细则与得分点。
3. 满分会由评分程序在实际阅卷时附加，因此不要保留 {{满分}} 或 {{评分细则}} 等未替换的占位符；若题目未明确每个得分点的分值，不要虚构固定分值，使用“按满分比例合理分配”等可执行表述。
4. 只输出生成后的评分 Prompt 正文，不要解释生成过程，不要使用 Markdown 代码块。

【题型预设】
{template}

【题目】
{question}

【参考答案】
{reference_answer}
"""
        try:
            prompt = self._complete(request, max_tokens=1600).strip()
        except (APIConnectionError, APITimeoutError, RateLimitError, APIError, AttributeError, IndexError, KeyError, TypeError, ValueError) as error:
            raise RuntimeError("AI 生成批改 Prompt 失败。") from error
        if not prompt:
            raise RuntimeError("AI 未返回批改 Prompt。")
        return prompt

    def recognize(self, answer_card: AnswerCard) -> AnswerRecognition:
        """从答题图片转录最终作答，并明确暴露不确定性与涂改。"""
        if not answer_card.image_urls or answer_card.standard_score is None:
            raise RuntimeError("答题卡图片或满分缺失，无法识别作答。")
        prompt = (
            "你是手写答题卡转录助手，只负责读取本次消息附带的答题图片，不评分。"
            "准确转录学生最终保留的作答；完整划除、涂黑或明确删除的文字不要纳入 transcription，"
            "但应列入 crossed_out_text。若字迹模糊、涂改后最终答案不明确、或关键文字无法确定，"
            "必须将相关片段列入 uncertain_spans，并将 needs_review 设为 true。"
            "不要猜测或擅自纠正疑似错别字；看不清就标记不确定。"
            "只返回 JSON：{\"transcription\": 字符串, \"uncertain_spans\": 字符串数组, "
            "\"crossed_out_text\": 字符串数组, \"final_answer_clear\": 布尔值, "
            "\"needs_review\": 布尔值, \"reason\": 字符串}。"
        )
        content = [{"type": "text", "text": prompt}]
        content.extend(
            {"type": "image_url", "image_url": {"url": url, "detail": "high"}}
            for url in answer_card.image_urls
        )
        try:
            content_text = self._complete(content, max_tokens=1200, json_mode=True)
            recognition = self._parse_recognition(content_text)
        except (APIConnectionError, APITimeoutError, RateLimitError, APIError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("AI 作答识别失败或返回格式无效。") from error
        return recognition

    def grade_transcription(self, answer_card: AnswerCard, transcription: str) -> int:
        """仅依据可见、可编辑的转录文本生成建议分，不再次解读图片。"""
        if answer_card.standard_score is None:
            raise RuntimeError("答题卡满分缺失，无法进行 AI 评分。")
        prompt = (
            f"{self._config.prompt}\n\n"
            f"当前平台记录的满分是 {answer_card.standard_score} 分。"
            "以下是从答题卡转录、且可能已由教师修订的学生最终作答。"
            "只依据这段转录文本和评分规则评分；不得猜测、补全或纠正其中的文字。"
            f"\n\n【学生最终作答】\n{transcription}\n\n"
            "不要输出推理过程、分析、解释或 Markdown。"
            "回复必须且只能是 JSON 对象：{\"score\": 整数}。"
        )
        try:
            score = self._parse_score(self._complete(prompt, max_tokens=16, json_mode=True))
        except (APIConnectionError, APITimeoutError, RateLimitError, APIError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("AI 评分失败或返回格式无效。") from error
        if isinstance(score, bool) or not isinstance(score, int):
            raise RuntimeError("AI 未返回整数建议分。")
        if not 0 <= score <= answer_card.standard_score:
            raise RuntimeError("AI 建议分超出满分范围。")
        return score

    @staticmethod
    def _parse_recognition(content: str) -> AnswerRecognition:
        try:
            payload = json.loads(content)
            transcription = payload["transcription"]
            uncertain_spans = payload["uncertain_spans"]
            crossed_out_text = payload["crossed_out_text"]
            final_answer_clear = payload["final_answer_clear"]
            needs_review = payload["needs_review"]
            reason = payload["reason"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise RuntimeError("AI 未按约定返回作答识别结果。") from error
        if (
            not isinstance(transcription, str)
            or not isinstance(uncertain_spans, list)
            or not isinstance(crossed_out_text, list)
            or isinstance(final_answer_clear, bool) is False
            or isinstance(needs_review, bool) is False
            or not isinstance(reason, str)
            or not all(isinstance(item, str) for item in uncertain_spans + crossed_out_text)
        ):
            raise RuntimeError("AI 作答识别结果字段类型无效。")
        # 自动提交只允许“文字明确且没有删改痕迹”的答卷；任何划除内容都交由教师确认。
        needs_review = (
            needs_review
            or bool(uncertain_spans)
            or bool(crossed_out_text)
            or not final_answer_clear
        )
        return AnswerRecognition(
            transcription=transcription,
            uncertain_spans=tuple(uncertain_spans),
            crossed_out_text=tuple(crossed_out_text),
            final_answer_clear=final_answer_clear,
            needs_review=needs_review,
            reason=reason,
        )

    def check_connection(self) -> float:
        """发送无学生数据的轻量请求，返回服务端往返耗时（秒）。"""
        started_at = perf_counter()
        try:
            if not self._complete("Reply with OK.", max_tokens=4):
                raise RuntimeError("接口未返回 choices。")
        except (APIConnectionError, APITimeoutError, RateLimitError, APIError, KeyError, TypeError, ValueError) as error:
            raise RuntimeError("AI 接口连接或模型配置不可用。") from error
        return perf_counter() - started_at

    @staticmethod
    def _parse_score(content: str) -> int:
        """兼容 JSON 或“【得分：X分】”的严格评分输出。"""
        try:
            score = json.loads(content)["score"]
        except (json.JSONDecodeError, KeyError, TypeError):
            match = re.fullmatch(r"\s*【得分：(\d+)分】\s*", content)
            if not match:
                raise RuntimeError("AI 未按约定格式返回评分。")
            score = int(match.group(1))
        return score
