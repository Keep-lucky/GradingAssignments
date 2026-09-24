"""智学网阅卷考试列表接口的访问封装。"""

import json
from typing import Any

from zhixuewang.account import login_cookie

from .card_fetcher import AnswerCard, AnswerCardFetcher
from .models import MarkingExam
from .score_submitter import ScoreSubmitter


PAPER_LIST_URL = "https://www.zhixue.com/exam/marking/index/paperList/"


class MarkingExamClient:
    """使用已有登录 Cookie 查询阅卷考试。"""

    def __init__(self, cookie: str) -> None:
        self._session = login_cookie(cookie).get_session()

    def fetch_current_answer_card(
        self, exam: MarkingExam, *, topic_num_str: str = ""
    ) -> AnswerCard:
        """读取所选阅卷任务指定题号（或当前分配题）的答题卡。"""
        return AnswerCardFetcher(self._session).fetch_current(
            exam, topic_num_str=topic_num_str
        )

    def preload_next_answer_card(
        self, exam: MarkingExam, *, topic_num_str: str, standard_score: float | None = None
    ) -> AnswerCard | None:
        """预加载指定题号的下一张答题卡。"""
        return AnswerCardFetcher(self._session).preload_next(
            exam, topic_num_str=topic_num_str, standard_score=standard_score
        )

    def submit_confirmed_score(
        self, exam: MarkingExam, answer_card: AnswerCard, score: int
    ) -> None:
        """回填教师已确认的当前题整数分数。"""
        ScoreSubmitter(self._session).submit_confirmed_score(exam, answer_card, score)

    def list_marking_exams(
        self, *, page_index: int = 1, page_size: int = 10
    ) -> list[MarkingExam]:
        """获取指定页的进行中阅卷考试。"""
        if page_index < 1 or page_size < 1:
            raise ValueError("page_index 和 page_size 必须是正整数。")
        response = self._session.post(
            PAPER_LIST_URL,
            data={"pageIndex": page_index, "pageSize": page_size, "paperStatus": "marking"},
        )
        response.raise_for_status()
        outer_data: dict[str, Any] = response.json()
        if not outer_data.get("result"):
            raise RuntimeError("查询阅卷考试失败：接口未返回成功状态。")
        try:
            data = json.loads(outer_data["message"])
            return [MarkingExam.from_api_item(item) for item in data["paperList"]]
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError("查询阅卷考试失败：接口响应格式不符合预期。") from error
