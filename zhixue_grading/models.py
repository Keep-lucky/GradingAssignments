"""阅卷考试领域模型。"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MarkingExam:
    """一份可显示、可选择的阅卷考试。"""

    task_id: str
    exam_id: str
    paper_id: str
    answer_sheet_id: str
    exam_name: str
    grade_name: str
    subject_name: str
    status: str
    can_marking: bool

    @classmethod
    def from_api_item(cls, item: dict[str, Any]) -> "MarkingExam":
        """转换接口 paperList 中的一项。"""
        paper = item["markingPaper"]
        return cls(
            task_id=str(paper["id"]),
            exam_id=str(paper["examId"]),
            paper_id=str(paper["paperId"]),
            answer_sheet_id=str(paper["answerSheetId"]),
            exam_name=str(paper["examName"]),
            grade_name=str(paper["gradeName"]),
            subject_name=str(paper["subjectName"]),
            status=str(paper["status"]),
            can_marking=bool(item["canMarking"]),
        )
