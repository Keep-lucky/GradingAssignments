"""当前阅卷答题卡的只读获取。"""

from dataclasses import dataclass
import json
from typing import Any

from .models import MarkingExam


SCAN_RECORD_DETAIL_URL = (
    "https://pt-ali-bj.zhixue.com/marking/marking/personal/scanrecorddetail/"
)
PRELOAD_SCAN_RECORD_DETAIL_URL = (
    "https://pt-ali-bj.zhixue.com/marking/marking/personal/preLoadScanrecorddetail/"
)
REQUEST_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class MarkingTopic:
    """一名教师在当前阅卷任务中可处理的题目统计。"""

    topic_num_str: str
    display_topic: str
    pending_count: int | None
    marked_count: int | None
    total_marked_count: int | None
    is_arbitration: bool

    @classmethod
    def from_api_item(cls, item: dict[str, Any]) -> "MarkingTopic":
        """从接口 teacherTopic 中的一项解析统计信息。"""
        return cls(
            topic_num_str=str(item["topicNumStr"]),
            display_topic=str(item.get("dispTopic") or item["topicNumStr"]),
            pending_count=_optional_int(item.get("teacherTodo")),
            marked_count=_optional_int(item.get("teacherMarked")),
            total_marked_count=_optional_int(item.get("topicMarked")),
            is_arbitration=bool(item.get("isArbitration")),
        )


def _optional_int(value: Any) -> int | None:
    """将接口中可能为空的计数字段转换为整数。"""
    return int(value) if value is not None else None


@dataclass(frozen=True)
class AnswerCard:
    """当前待阅卷答题卡中评分所需的最小信息。

    ``image_urls`` 仅在内存中保留，命令行不会输出，避免泄露学生作答图片链接。
    """

    scan_record_id: str
    marking_item_ids: tuple[str, ...]
    topic_num_str: str
    image_urls: tuple[str, ...]
    standard_score: float | None
    has_previous: bool
    has_next: bool
    topics: tuple[MarkingTopic, ...]

    @classmethod
    def from_api_data(cls, data: dict[str, Any]) -> "AnswerCard":
        """从 scanrecorddetail 接口的 data 字段解析答题卡。"""
        try:
            topics = tuple(
                MarkingTopic.from_api_item(item)
                for item in data.get("teacherTopic") or []
            )
            return cls.from_topic_info(
                data["topicInfo"],
                topic_num_str=str(data["topicNum"]),
                standard_scores=data["topicInfo"].get("standardScores"),
                marking_item_ids=_parse_marking_item_ids(data["topicInfo"]["item"]),
                has_previous=bool(data.get("hasPrev")),
                has_next=bool(data.get("hasNext")),
                topics=topics,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("答题卡响应格式不符合预期。") from error

    @classmethod
    def from_topic_info(
        cls,
        topic_info: dict[str, Any],
        *,
        topic_num_str: str,
        standard_scores: list[dict[str, Any]] | None = None,
        fallback_standard_score: float | None = None,
        marking_item_ids: tuple[str, ...] = (),
        has_previous: bool = False,
        has_next: bool = False,
        topics: tuple[MarkingTopic, ...] = (),
    ) -> "AnswerCard":
        """解析当前答题卡或预加载答题卡中的 topicInfo。"""
        try:
            detail = topic_info["detail"]
            image_urls = tuple(str(url) for url in detail.get("topicImageIds", []))
            score = standard_scores[0].get("standardScore") if standard_scores else fallback_standard_score
            return cls(
                scan_record_id=str(detail["scanRecordId"]),
                marking_item_ids=marking_item_ids,
                topic_num_str=topic_num_str,
                image_urls=image_urls,
                standard_score=float(score) if score is not None else None,
                has_previous=has_previous,
                has_next=has_next,
                topics=topics,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("答题卡响应格式不符合预期。") from error


def _parse_marking_item_ids(item: dict[str, Any]) -> tuple[str, ...]:
    """解析提交分数所需的 topicInfo.item.id JSON 数组。"""
    try:
        raw_ids = item["id"]
        ids = json.loads(raw_ids) if isinstance(raw_ids, str) else raw_ids
        if not isinstance(ids, list) or not ids:
            raise ValueError
        return tuple(str(item_id) for item_id in ids)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("答题卡缺少提交分数所需的阅卷记录 ID。") from error


class AnswerCardFetcher:
    """复用已登录会话读取当前待阅卷答题卡。"""

    def __init__(self, session: Any) -> None:
        self._session = session

    def fetch_current(self, exam: MarkingExam, *, topic_num_str: str = "") -> AnswerCard:
        """读取选中任务指定题号（或当前题）的答题卡，不修改阅卷状态或分数。"""
        response = self._session.post(
            SCAN_RECORD_DETAIL_URL,
            data={
                "markingPaperId": exam.task_id,
                "isSpecify": "true" if topic_num_str else "false",
                "topicNumStr": topic_num_str,
                "isArbitration": "false",
                "isContinueMarkButton": "false",
                "withOutPreLoad": "true",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as error:
            raise RuntimeError("获取答题卡失败：接口没有返回 JSON。") from error

        if payload.get("code") != 200:
            message = payload.get("msg", "未知错误")
            raise RuntimeError(f"获取答题卡失败：{message}")
        return AnswerCard.from_api_data(payload["data"])

    def preload_next(
        self, exam: MarkingExam, *, topic_num_str: str, standard_score: float | None = None
    ) -> AnswerCard | None:
        """只读预加载指定题号的下一张答题卡；没有下一张时返回 None。"""
        response = self._session.post(
            PRELOAD_SCAN_RECORD_DETAIL_URL,
            data={
                "markingPaperId": exam.task_id,
                "isSpecify": "true",
                "topicNumStr": topic_num_str,
                "isArbitration": "false",
                "entranceType": "0",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as error:
            raise RuntimeError("预加载答题卡失败：接口没有返回 JSON。") from error

        if payload.get("code") != 200:
            message = payload.get("msg", "未知错误")
            raise RuntimeError(f"预加载答题卡失败：{message}")
        data = payload.get("data") or {}
        next_topic_info = data.get("nextTopicInfo")
        if next_topic_info is None:
            return None
        return AnswerCard.from_topic_info(
            next_topic_info,
            topic_num_str=str(next_topic_info.get("topicNumStr", topic_num_str)),
            standard_scores=next_topic_info.get("standardScores"),
            fallback_standard_score=standard_score,
            marking_item_ids=_parse_marking_item_ids(next_topic_info["item"]),
        )
