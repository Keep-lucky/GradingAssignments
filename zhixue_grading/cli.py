"""命令行交互与应用编排。"""

from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor

# 正常情况下通过 ``python -m zhixue_grading`` 启动，使用相对导入。
# 兼容 IDE 直接运行本文件的场景，此时需要将项目根目录加入模块搜索路径。
if __package__ in (None, ""):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from zhixue_grading.api import MarkingExamClient
    from zhixue_grading.card_fetcher import AnswerCard, MarkingTopic
    from zhixue_grading.config import load_cookie
    from zhixue_grading.config import load_grading_config
    from zhixue_grading.models import MarkingExam
    from zhixue_grading.vision_grader import VisionGrader
else:
    from .api import MarkingExamClient
    from .card_fetcher import AnswerCard, MarkingTopic
    from .config import load_cookie
    from .config import load_grading_config
    from .models import MarkingExam
    from .vision_grader import VisionGrader


def print_exam_list(exams: Sequence[MarkingExam]) -> None:
    """显示可选考试。"""
    print(f"\n共找到 {len(exams)} 场阅卷考试：\n")
    for index, exam in enumerate(exams, start=1):
        print("=" * 80)
        print(f"[{index}] {exam.exam_name}")
        print("阅卷任务ID：", exam.task_id)
        print("考试ID：", exam.exam_id)
        print("试卷ID：", exam.paper_id)
        print("答题卡ID：", exam.answer_sheet_id)
        print("年级：", exam.grade_name)
        print("科目：", exam.subject_name)
        print("状态：", exam.status)
        print("允许阅卷：", exam.can_marking)


def select_exam(exams: Sequence[MarkingExam], input_func: Callable[[str], str] = input) -> MarkingExam | None:
    """按序号选择考试；输入 q 时返回 None。"""
    if not exams:
        print("没有可选择的阅卷考试。")
        return None
    while True:
        choice = input_func(f"\n请输入要选择的考试序号（1-{len(exams)}，输入 q 退出）：").strip()
        if choice.lower() == "q":
            return None
        try:
            index = int(choice) - 1
            if not 0 <= index < len(exams):
                raise ValueError
        except ValueError:
            print("输入无效，请输入列表中的考试序号。")
            continue
        return exams[index]


def print_selected_exam(exam: MarkingExam) -> None:
    """显示选中的考试。"""
    print("\n已选择考试：", exam.exam_name)
    print("阅卷任务ID：", exam.task_id)
    print("考试ID：", exam.exam_id)
    print("试卷ID：", exam.paper_id)
    print("答题卡ID：", exam.answer_sheet_id)


def print_answer_card_summary(answer_card: AnswerCard) -> None:
    """显示答题卡读取结果，不显示学生信息或图片链接。"""
    print("\n已获取当前答题卡：")
    print("题号：", answer_card.topic_num_str)
    print("答题图片数量：", len(answer_card.image_urls))
    print("本题满分：", answer_card.standard_score)
    print("可切换上一张：", answer_card.has_previous)
    print("可切换下一张：", answer_card.has_next)


def print_preload_summary(answer_card: AnswerCard | None) -> None:
    """显示下一张答题卡的预加载状态，不显示其图片链接。"""
    if answer_card is None:
        print("下一张答题卡：当前没有可预加载的答卷。")
        return
    print(
        "下一张答题卡已预加载："
        f"题号 {answer_card.topic_num_str}，图片数量 {len(answer_card.image_urls)}"
    )


def print_topic_list(topics: Sequence[MarkingTopic]) -> None:
    """显示当前教师在该阅卷任务中的全部题目统计。"""
    if not topics:
        print("\n接口未返回可阅题目列表。")
        return
    print("\n题目阅卷概览（待阅、已阅为当前教师统计）：")
    print("题号\t接口题号\t待阅\t已阅\t全体已阅\t仲裁")
    for topic in topics:
        pending = topic.pending_count if topic.pending_count is not None else "-"
        marked = topic.marked_count if topic.marked_count is not None else "-"
        total_marked = (
            topic.total_marked_count if topic.total_marked_count is not None else "-"
        )
        arbitration = "是" if topic.is_arbitration else "否"
        print(
            f"{topic.display_topic}\t{topic.topic_num_str}\t{pending}\t{marked}\t"
            f"{total_marked}\t{arbitration}"
        )


def input_topic_num(
    topics: Sequence[MarkingTopic], input_func: Callable[[str], str] = input
) -> str | None:
    """按页面显示题号选择，并转换为接口所需的 topicNumStr。"""
    topic_mapping = {topic.display_topic: topic.topic_num_str for topic in topics}
    while True:
        topic_num = input_func(
            "请输入题号（按概览左侧题号，如 9；直接回车读取当前题；输入 q 取消）："
        ).strip()
        if not topic_num:
            return ""
        if topic_num.lower() == "q":
            return None
        if topic_num in topic_mapping:
            return topic_mapping[topic_num]
        print("题号不存在于当前阅卷概览，请输入左侧“题号”列中的值。")


def input_confirmed_score(
    answer_card: AnswerCard, suggested_score: int, input_func: Callable[[str], str] = input
) -> int | None:
    """显示 AI 建议分，由教师确认或修改最终整数分数。"""
    if answer_card.standard_score is None:
        print("该题未返回满分，已禁止提交分数。")
        return None
    maximum = answer_card.standard_score
    while True:
        raw_score = input_func(f"AI 建议 {suggested_score} 分。回车确认，输入 0-{maximum} 修改，q 跳过： ").strip()
        if not raw_score:
            return suggested_score
        if raw_score.lower() == "q":
            return None
        try:
            score = int(raw_score)
            if not 0 <= score <= maximum:
                raise ValueError
        except ValueError:
            print("分数无效，请输入满分范围内的整数。")
            continue
        return score


def grade_topic_continuously(
    client: MarkingExamClient, exam: MarkingExam, current_answer_card: AnswerCard, grader: VisionGrader
) -> None:
    """循环处理同一题，且只在平台切换到新答卷后继续。"""
    with ThreadPoolExecutor(max_workers=2) as executor:
        current_future: Future[int] = executor.submit(grader.grade, current_answer_card)
        while True:
            print_answer_card_summary(current_answer_card)
            print("正在预加载下一张答题卡……")
            next_answer_card = client.preload_next_answer_card(
                exam,
                topic_num_str=current_answer_card.topic_num_str,
                standard_score=current_answer_card.standard_score,
            )
            next_future = executor.submit(grader.grade, next_answer_card) if next_answer_card else None
            print_preload_summary(next_answer_card)
            try:
                print("AI 正在评分当前答题卡……")
                suggested_score = current_future.result()
            except RuntimeError as error:
                print(f"AI 评分不可用：{error}。本张未提交。")
                return
            confirmed_score = input_confirmed_score(current_answer_card, suggested_score)
            if confirmed_score is None:
                print("已停止连续批改；当前答题卡未提交分数。")
                return

            client.submit_confirmed_score(exam, current_answer_card, confirmed_score)
            print("分数已提交成功。正在读取下一张答题卡……")

            updated_answer_card = client.fetch_current_answer_card(exam, topic_num_str=current_answer_card.topic_num_str)
            if updated_answer_card.scan_record_id == current_answer_card.scan_record_id:
                print("平台尚未切换到下一张答题卡，已停止以避免重复提交。")
                return
            if next_answer_card and updated_answer_card.scan_record_id == next_answer_card.scan_record_id:
                current_future = next_future
            else:
                current_future = executor.submit(grader.grade, updated_answer_card)
            current_answer_card = updated_answer_card


def main() -> None:
    """执行查询并选择考试的流程。"""
    client = MarkingExamClient(load_cookie())
    grader = VisionGrader(load_grading_config())
    print("正在加载考试列表，AI 接口测试在后台进行……")
    startup_executor = ThreadPoolExecutor(max_workers=1)
    health_future: Future[float] = startup_executor.submit(grader.check_connection)
    exams = client.list_marking_exams()
    print_exam_list(exams)
    selected_exam = select_exam(exams)
    if selected_exam is None:
        startup_executor.shutdown(wait=False, cancel_futures=True)
        print("已取消选择考试。")
        return
    print("正在确认 AI 接口状态……")
    try:
        latency_seconds = health_future.result()
    except RuntimeError as error:
        print(f"AI 接口不可用：{error}")
        return
    finally:
        startup_executor.shutdown(wait=False)
    print(f"AI 接口连接正常，轻量请求耗时 {latency_seconds:.2f} 秒。")
    print_selected_exam(selected_exam)
    print("正在读取题目概览和当前答题卡……")
    current_answer_card = client.fetch_current_answer_card(selected_exam)
    print_topic_list(current_answer_card.topics)
    topic_num_str = input_topic_num(current_answer_card.topics)
    if topic_num_str is None:
        print("已取消获取答题卡。")
        return
    answer_card = (
        current_answer_card
        if not topic_num_str
        else _fetch_selected_topic(client, selected_exam, topic_num_str)
    )
    grade_topic_continuously(client, selected_exam, answer_card, grader)


def _fetch_selected_topic(
    client: MarkingExamClient, exam: MarkingExam, topic_num_str: str
) -> AnswerCard:
    """显示进度后读取用户选择的题目。"""
    print(f"正在获取所选题目的答题卡（接口题号：{topic_num_str}）……")
    return client.fetch_current_answer_card(exam, topic_num_str=topic_num_str)


if __name__ == "__main__":
    main()
