"""教师确认后的智学网分数回填。"""

import json
from typing import Any

from .card_fetcher import AnswerCard
from .models import MarkingExam


COMMIT_TOPIC_URL = "https://pt-ali-bj.zhixue.com/marking/marking/commitTopic/"


class ScoreSubmitter:
    """仅提交已由教师确认的单题整数分数。"""

    def __init__(self, session: Any) -> None:
        self._session = session

    def submit_confirmed_score(
        self, exam: MarkingExam, answer_card: AnswerCard, score: int
    ) -> None:
        """提交一张答题卡的已确认分数，并验证接口成功响应。"""
        self._validate_score(answer_card, score)
        response = self._session.post(
            COMMIT_TOPIC_URL,
            data={
                "markingPaperId": exam.task_id,
                "id": json.dumps(list(answer_card.marking_item_ids)),
                "markingScores": json.dumps({answer_card.topic_num_str: score}),
                "isBack": "false",
                "keep": "false",
                "superiority": "normal0",
                "markContent": "[]",
                "isArbitration": "false",
                "exceptionType": "0",
                "preScores": "",
            },
        )
        response.raise_for_status()
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as error:
            raise RuntimeError("提交分数失败：接口没有返回 JSON。") from error
        if payload.get("result") != "success":
            raise RuntimeError("提交分数失败：接口未返回 success。")

    @staticmethod
    def _validate_score(answer_card: AnswerCard, score: int) -> None:
        if isinstance(score, bool) or not isinstance(score, int):
            raise ValueError("分数必须是整数。")
        if answer_card.standard_score is None:
            raise ValueError("当前题目缺少满分信息，不能安全提交。")
        if not 0 <= score <= answer_card.standard_score:
            raise ValueError(f"分数必须在 0 到 {answer_card.standard_score} 之间。")
