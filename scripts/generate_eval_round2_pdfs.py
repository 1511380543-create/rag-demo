#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「构建高质量测评集第二轮」必加的 4 份虚拟 PDF。

1. 机动车排放监管综合技术手册（虚拟长文）——长文切块压测
2. 道路运政数据交换与报表规范（虚拟技术手册）——大表/续表/嵌套列表
3. 老旧柴油车淘汰更新指导意见（虚拟政策文档）——原则篇
4. 老旧柴油车淘汰更新实施细则（2026修订版）（虚拟政策文档）——细则/现行版

依赖本机中文字体：/System/Library/Fonts/Supplemental/Arial Unicode.ttf
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
FONT_PATH = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")


def _register_font() -> str:
    if not FONT_PATH.exists():
        raise FileNotFoundError(f"缺少中文字体: {FONT_PATH}")
    pdfmetrics.registerFont(TTFont("CN", str(FONT_PATH)))
    return "CN"


def _styles(font_name: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "r2_title",
            parent=base["Title"],
            fontName=font_name,
            fontSize=16,
            leading=22,
            spaceAfter=10,
        ),
        "h1": ParagraphStyle(
            "r2_h1",
            parent=base["Heading1"],
            fontName=font_name,
            fontSize=13,
            leading=18,
            spaceBefore=12,
            spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "r2_h2",
            parent=base["Heading2"],
            fontName=font_name,
            fontSize=11,
            leading=16,
            spaceBefore=8,
            spaceAfter=4,
        ),
        "h3": ParagraphStyle(
            "r2_h3",
            parent=base["Heading3"],
            fontName=font_name,
            fontSize=10.5,
            leading=15,
            spaceBefore=6,
            spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "r2_body",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=10.5,
            leading=16,
            spaceAfter=4,
        ),
        "meta": ParagraphStyle(
            "r2_meta",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=10,
            leading=15,
            spaceAfter=2,
        ),
        "cell": ParagraphStyle(
            "r2_cell",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=8.5,
            leading=11,
        ),
        "note": ParagraphStyle(
            "r2_note",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=9,
            leading=13,
            textColor=colors.grey,
            spaceAfter=4,
        ),
    }


def _p(styles: dict, key: str, text: str) -> Paragraph:
    return Paragraph(text.replace("\n", "<br/>"), styles[key])


def _build(path: Path, flowables: list) -> None:
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=path.stem,
    )
    doc.build(flowables)
    print(f"wrote {path.name} ({path.stat().st_size} bytes)")


def _make_table(styles: dict, header: list[str], rows: list[list[str]], col_widths: list[float]) -> Table:
    data = [[Paragraph(h, styles["cell"]) for h in header]]
    for row in rows:
        data.append([Paragraph(c, styles["cell"]) for c in row])
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.85, 0.88, 0.92)),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def doc_long_manual(styles: dict) -> list:
    """长文：多章多节，制造需要软上限切开的长节。"""
    parts: list = [
        _p(styles, "title", "机动车排放监管综合技术手册（虚拟长文）"),
        _p(styles, "meta", "文档编号：YQ-PF-LONG-2026-V1"),
        _p(styles, "meta", "编制单位：省级机动车排放监管技术支撑中心（虚拟）"),
        _p(styles, "meta", "实施日期：2026年06月01日"),
        _p(
            styles,
            "meta",
            "效力说明：本文档为虚拟长文技术手册，专用于 RAG 切块压测与测评，非官方法定文本。",
        ),
        Spacer(1, 6),
        _p(styles, "h1", "第一章 总则与适用范围"),
        _p(
            styles,
            "body",
            "第一条 为统筹柴油车、汽油车与新能源汽车的排放监管技术要求，统一远程监控、现场抽检、"
            "数据质量与应急处置流程，制定本手册。本手册适用于省级及以下生态环境、交通运输协同监管场景。",
        ),
        _p(
            styles,
            "body",
            "第二条 本手册所称「综合监管」是指以车载终端数据为主、路检路查与遥感监测为辅的闭环监管模式。"
            "关键术语锚点：综合监管闭环周期为90个自然日。",
        ),
        _p(styles, "h1", "第二章 监管对象分类"),
        _p(styles, "h2", "2.1 柴油车监管对象"),
        _p(
            styles,
            "body",
            "柴油车监管覆盖国三及以后排放阶段的营运与非营运货车、客车及专项作业车。"
            "柴油车入网核验时限不超过5个工作日。",
        ),
        _p(styles, "h2", "2.2 汽油车监管对象"),
        _p(
            styles,
            "body",
            "汽油车以轻型车年检排放检测为主，不强制接入重型柴油车远程平台。"
            "汽油车抽检比例原则上不低于在用车保有量的3%。",
        ),
        _p(styles, "h2", "2.3 新能源汽车监管对象"),
        _p(
            styles,
            "body",
            "新能源汽车须接入省级远程监控平台，终端证书有效期最长12个月。"
            "新能源车离线补传窗口不超过72小时。",
        ),
    ]

    # 第三章 deliberately long to exceed section_soft_max (~1000)
    long_paras = [
        "第三章为长节压测专章，正文连续叙述远程监控数据质量、传输有效率、断联处置、补传规则、"
        "异常告警分级、现场核查触发条件以及与路检路查的衔接要求，便于验证章节软上限切开后每块仍带章标题。",
        "远程监控数据质量以完整性、及时性、一致性三项核心指标评价。完整性指关键字段缺失率；"
        "及时性指采集到平台入库时延；一致性指同车多源数据在允许误差内相互校验通过。"
        "省级平台应将三项指标按车辆、企业、区县三维汇总，形成周报与月报。",
        "传输有效率统计口径为：检验周期内实际上传有效报文条数除以应上传报文条数。"
        "关键锚点：长文手册有效率警戒线95%。低于警戒线的车辆应进入黄色预警名单，"
        "连续两个周期低于警戒线的，应转入重点核查名单并安排现场抽查。",
        "断联处置遵循「先自愈、后告警、再核查」原则。终端短暂断联且在补传窗口内完成补传的，"
        "记台账不升级处罚；超过补传窗口仍未恢复的，平台自动生成断联工单，推送至属地监管账号。"
        "断联工单响应时限为24小时内签收，72小时内反馈处置结果。",
        "补传规则要求按时间顺序补齐缺失区间，禁止只补最新点而跳过中间空洞。"
        "补传报文须携带原始采集时间戳与补传标记位，平台入库时不得覆盖已存在的同时间戳有效记录。"
        "同一车辆单日补传量异常高于日常均值三倍的，应触发数据真实性复核。",
        "异常告警分为一级（超标排放或数据造假嫌疑）、二级（长期断联或有效率不达标）、"
        "三级（轻微抖动或短时异常）。一级告警须在2小时内启动应急核查；二级告警在1个工作日内分派；"
        "三级告警纳入周例会通报。告警闭环完成后须回写处置结论与证据编号。",
        "现场核查触发条件包括但不限于：一级告警未按时闭环、遥感监测连续两次超标、"
        "路检发现OBD接口异常、企业自查报告与平台数据严重不符。"
        "现场核查应双人执法并留存影像，核查结论须在5个工作日内录入综合监管平台。",
        "与路检路查的衔接方面，远程监控提供候选车辆清单，路检队伍按风险分值优先拦查。"
        "拦查结果应在当日回传平台，形成「线索—拦查—处罚—整改—复测」闭环。"
        "本手册约定路检结果回传字段最小集为：号牌、拦查时间、检测项目、是否超标、处置措施。",
        "数据留存与审计方面，平台原始报文至少保存180天，汇总指标至少保存3年，"
        "涉嫌违法案件相关数据延长保存至结案后两年。审计日志应记录查询、导出、修改配置等敏感操作。",
        "本章附关键合成句用于检索锚点定位：长文手册第三章软上限压测锚点句-PF-SOFTMAX-2026。"
        "该锚点句仅出现于本章，用于验证切开后的续块是否仍可通过标题前缀或邻近上下文被检索到。",
    ]
    parts.append(_p(styles, "h1", "第三章 远程监控数据质量与闭环（长节）"))
    for para in long_paras:
        parts.append(_p(styles, "body", para))

    for chapter, title, bullets in [
        (
            "第四章",
            "现场抽检与遥感监测",
            [
                "遥感监测点位应避开急弯与长上坡，校准周期不超过30个自然日。",
                "关键锚点：遥感筛查阳性复核时限为48小时。",
                "抽检不合格车辆须在复检合格前限制核发相关环保凭证。",
            ],
        ),
        (
            "第五章",
            "企业主体责任与台账",
            [
                "运输企业须建立排放合规台账，台账保存不少于2年。",
                "关键锚点：企业月度自查覆盖率应达到100%。",
                "弄虚作假骗取监管便利的，依法撤销相关资格并通报。",
            ],
        ),
        (
            "第六章",
            "应急与重污染天气应对",
            [
                "重污染天气橙色及以上预警期间，高排放柴油车执行临时管控清单。",
                "关键锚点：应急管控清单更新频率不低于每日一次。",
                "应急期间断联车辆优先安排现场核查。",
            ],
        ),
        (
            "第七章",
            "系统对接与安全",
            [
                "综合监管平台与运政、公安交管系统对接应采用专线或等效安全通道。",
                "关键锚点：跨系统接口调用须携带时效不超过2小时的访问令牌。",
                "禁止将原始报文明文落盘到非受控终端。",
            ],
        ),
        (
            "第八章",
            "附则",
            [
                "本手册由省级机动车排放监管技术支撑中心解释。",
                "关键锚点：本手册自2026年06月01日起施行。",
                "与专项细则冲突时，专项细则对特定车型另有规定的从其规定，但不得低于本手册底线。",
            ],
        ),
    ]:
        parts.append(_p(styles, "h1", f"{chapter} {title}"))
        for b in bullets:
            parts.append(_p(styles, "body", b))

    # 强制分页扩展篇幅，目标约 8～15 页，服务长文切块压测
    for i in range(1, 9):
        parts.append(PageBreak())
        parts.append(_p(styles, "h1", f"附录{i} 场景说明与培训要点"))
        parts.append(
            _p(
                styles,
                "body",
                f"附录{i}用于扩展手册篇幅与章节层次，内容覆盖培训讲解、常见误区、案例拆解与检查表。"
                f"附录{i}不改变正文强制性条款，仅作为实施参考。附录{i}检索锚点：LONG-APPENDIX-{i}-ANCHOR。",
            )
        )
        for j in range(1, 5):
            parts.append(_p(styles, "h2", f"附录{i}.{j} 讲解单元"))
            parts.append(
                _p(
                    styles,
                    "body",
                    "培训时应强调：远程数据不能替代现场执法；抽检与遥感结论须可追溯；"
                    "企业台账应与平台数据相互印证；应急期间优先保障高风险车辆核查。"
                    "检查表建议包含终端状态、有效率、告警闭环、现场核查与处罚回传五项。"
                    f"本单元补充说明编号 A{i}-{j}：监管人员应能复述告警分级、补传窗口、工单时限与留存要求，"
                    "并在演练中完成一次从线索生成到闭环回写的全流程操作记录。",
                )
            )
            parts.append(
                _p(
                    styles,
                    "body",
                    "常见误区包括：把短暂断联直接等同于造假；忽略补传标记导致重复计量；"
                    "只看日均有效率而忽视连续空洞区间；现场核查缺少双人留痕；跨系统回传字段不完整。"
                    "纠正措施应写入企业整改台账，并在下一周期复核时作为必查项。"
                    f"附录{i}单元{j}结束标记：LONG-UNIT-{i}-{j}-END。",
                )
            )
    return parts


def doc_exchange_spec(styles: dict) -> list:
    """结构多样性：大表 + 续表 + 嵌套列表。"""
    parts: list = [
        _p(styles, "title", "道路运政数据交换与报表规范（虚拟技术手册）"),
        _p(styles, "meta", "文档编号：JT-DATA-XCH-2026"),
        _p(styles, "meta", "编制单位：省级交通运输数据中心（虚拟）"),
        _p(styles, "meta", "实施日期：2026年05月20日"),
        _p(
            styles,
            "meta",
            "效力说明：本文档为虚拟技术规范，用于大表/续表/嵌套列表切块测评，非官方标准。",
        ),
        Spacer(1, 6),
        _p(styles, "h1", "1 范围与引用"),
        _p(
            styles,
            "body",
            "本规范约定道路运政业务系统与上级监管平台之间的数据交换报文、报表字段及传输约束。"
            "关键锚点：运政交换规范主版本号为XCH-2026.05。",
        ),
        _p(styles, "h1", "2 嵌套列表：交换原则"),
        _p(styles, "body", "交换原则分层如下："),
        _p(styles, "body", "1. 安全原则"),
        _p(styles, "body", "1.1 传输通道须加密；"),
        _p(styles, "body", "1.2 密钥轮换周期不超过90天；"),
        _p(styles, "body", "1.3 访问令牌有效期不超过2小时。"),
        _p(styles, "body", "2. 可靠原则"),
        _p(styles, "body", "2.1 支持断点续传；"),
        _p(styles, "body", "2.2 关键锚点：单次批量上报上限为500条；"),
        _p(styles, "body", "2.3 失败重试退避基数为3秒，最多重试5次。"),
        _p(styles, "body", "3. 可审计原则"),
        _p(styles, "body", "3.1 保留交换日志不少于180天；"),
        _p(styles, "body", "3.2 导出操作须双人审批。"),
        _p(styles, "h1", "3 主表：车辆运行日报字段"),
        _p(styles, "body", "表3-1 车辆运行日报主字段（第1部分）"),
    ]

    header = ["字段编码", "字段名称", "类型", "必填", "说明"]
    rows_part1 = [
        ["VRD_001", "号牌号码", "string", "是", "含颜色代码"],
        ["VRD_002", "车辆识别代号", "string", "是", "VIN，17位"],
        ["VRD_003", "业户名称", "string", "是", "道路运输经营者"],
        ["VRD_004", "统计日期", "date", "是", "YYYY-MM-DD"],
        ["VRD_005", "行驶里程", "number", "是", "单位公里，保留1位小数"],
        ["VRD_006", "在线时长", "number", "是", "单位小时"],
        ["VRD_007", "报警次数", "int", "是", "含超速与疲劳"],
        ["VRD_008", "数据完整率", "number", "是", "百分比"],
        ["VRD_009", "终端型号", "string", "否", "厂家型号"],
        ["VRD_010", "备注", "string", "否", "自由文本"],
    ]
    parts.append(_make_table(styles, header, rows_part1, [22 * mm, 28 * mm, 18 * mm, 12 * mm, 70 * mm]))
    parts.append(_p(styles, "note", "（续表见下页表3-1续）"))
    parts.append(PageBreak())
    parts.append(_p(styles, "body", "表3-1续 车辆运行日报主字段（第2部分）"))
    rows_part2 = [
        ["VRD_011", "所属区县", "string", "是", "行政区划代码"],
        ["VRD_012", "燃料类型", "string", "是", "柴油/汽油/新能源"],
        ["VRD_013", "排放阶段", "string", "否", "国三/国四/国五/国六"],
        ["VRD_014", "营运状态", "string", "是", "营运/停运/注销"],
        ["VRD_015", "平台接收时间", "datetime", "是", "ISO-8601"],
        ["VRD_016", "校验状态", "string", "是", "通过/失败"],
        ["VRD_017", "失败原因码", "string", "否", "失败时必填"],
        ["VRD_018", "补传标记", "bool", "是", "true表示补传"],
        ["VRD_019", "原始报文哈希", "string", "是", "SHA-256"],
        ["VRD_020", "扩展JSON", "string", "否", "厂商扩展"],
    ]
    parts.append(_make_table(styles, header, rows_part2, [22 * mm, 28 * mm, 18 * mm, 12 * mm, 70 * mm]))
    parts.append(_p(styles, "body", "关键锚点：表3-1续含字段编码VRD_019原始报文哈希。"))

    parts.extend(
        [
            _p(styles, "h1", "4 报表：企业周汇总"),
            _p(styles, "body", "表4-1 企业周汇总指标"),
        ]
    )
    week_header = ["指标编码", "指标名称", "统计周期", "阈值阈值", "处置动作"]
    week_rows = [
        ["WK_01", "车辆在线率", "自然周", "低于92%", "黄色预警"],
        ["WK_02", "数据完整率", "自然周", "低于95%", "限期整改"],
        ["WK_03", "超速报警闭环率", "自然周", "低于98%", "约谈业户"],
        ["WK_04", "疲劳驾驶报警数", "自然周", "环比上升30%", "重点巡查"],
        ["WK_05", "补传占比", "自然周", "高于15%", "真实性核查"],
        ["WK_06", "接口失败率", "自然周", "高于2%", "技术联调"],
    ]
    parts.append(_make_table(styles, week_header, week_rows, [22 * mm, 35 * mm, 22 * mm, 30 * mm, 40 * mm]))
    parts.append(_p(styles, "body", "关键锚点：企业周汇总超速报警闭环率阈值阈值为低于98%。"))

    parts.extend(
        [
            _p(styles, "h1", "5 接口路径与编码"),
            _p(styles, "body", "日报交换接口路径为 /v1/transport/daily-report/sync。"),
            _p(styles, "body", "关键锚点：运政日报同步接口路径为/v1/transport/daily-report/sync。"),
            _p(styles, "body", "报文编码采用UTF-8，Content-Type为application/json。"),
            _p(styles, "h1", "6 附则"),
            _p(styles, "body", "本规范自2026年05月20日起施行，由省级交通运输数据中心解释。"),
        ]
    )
    return parts


def doc_guidance(styles: dict) -> list:
    """原则篇：口径偏宽，与细则冲突处写清楚。"""
    return [
        _p(styles, "title", "老旧柴油车淘汰更新指导意见（虚拟政策文档）"),
        _p(styles, "meta", "发文机关：生态环境部、财政部、交通运输部（虚拟）"),
        _p(styles, "meta", "发文文号：环发〔2025〕19号"),
        _p(styles, "meta", "施行日期：2025年10月01日"),
        _p(
            styles,
            "meta",
            "效力说明：本文档为虚拟原则性指导意见；具体标准以后续修订实施细则为准。用于层级/效力测评。",
        ),
        Spacer(1, 6),
        _p(styles, "h1", "一、总体要求"),
        _p(
            styles,
            "body",
            "各地应加快老旧柴油车淘汰更新，坚持「淘汰与更新并重、约束与激励并行」。"
            "本意见提出方向性要求，不替代地方实施细则的量化标准。",
        ),
        _p(styles, "h1", "二、淘汰导向（原则口径）"),
        _p(
            styles,
            "body",
            "原则上，使用年限较长、排放稳定性差的老旧柴油货车应优先淘汰。"
            "原则锚点：指导意见建议中重型营运柴油货车使用年限满12年启动淘汰评估。"
            "（注：该年限为原则建议，可被修订细则收紧。）",
        ),
        _p(
            styles,
            "body",
            "原则锚点：指导意见提出提前淘汰中央财政补贴可按单车最高不超过10000元掌握。"
            "各地可在此导向下制定分档，但不得突破本意见公布的原则上限口径，除非另有专项细则修订。",
        ),
        _p(styles, "h1", "三、更新导向"),
        _p(
            styles,
            "body",
            "鼓励更新为新能源或更高排放阶段车辆。原则锚点：指导意见鼓励更新车辆排放阶段不低于国六。",
        ),
        _p(styles, "h1", "四、工作机制"),
        _p(
            styles,
            "body",
            "建立部门协同、信息共享与年度评估机制。原则锚点：指导意见要求各省每年报送一次淘汰更新进展。",
        ),
        _p(styles, "h1", "五、效力说明"),
        _p(
            styles,
            "body",
            "本意见为原则性文件。若与后续发布的实施细则不一致，涉及量化年限、补贴标准、强制时限等事项，"
            "以实施细则为准。关键锚点：指导意见量化冲突时从细则。",
        ),
    ]


def doc_rules_2026(styles: dict) -> list:
    """细则/现行版：收紧原则篇口径，制造效力冲突。"""
    return [
        _p(styles, "title", "老旧柴油车淘汰更新实施细则（2026修订版）（虚拟政策文档）"),
        _p(styles, "meta", "发文机关：生态环境部、财政部、交通运输部（虚拟）"),
        _p(styles, "meta", "发文文号：环发〔2026〕41号"),
        _p(styles, "meta", "施行日期：2026年08月01日"),
        _p(styles, "meta", "废止说明：本细则施行后，环发〔2025〕19号中与本细则冲突的量化条款不再执行。"),
        _p(
            styles,
            "meta",
            "效力说明：本文档为虚拟修订实施细则，用于「现行标准/细则优先」测评，非官方法定文本。",
        ),
        Spacer(1, 6),
        _p(styles, "h1", "第一章 总则"),
        _p(
            styles,
            "body",
            "第一条 为细化老旧柴油车淘汰更新标准，依据指导意见并结合同期监管实践，制定本细则（2026修订版）。",
        ),
        _p(
            styles,
            "body",
            "第二条 本细则为现行有效量化标准。关键锚点：现行淘汰更新量化标准以环发〔2026〕41号为准。",
        ),
        _p(styles, "h1", "第二章 强制淘汰年限（收紧）"),
        _p(
            styles,
            "body",
            "第三条 中重型营运柴油货车使用年限满10年的，应当启动强制淘汰程序。"
            "细则锚点：2026修订版中重型营运柴油货车强制淘汰年限为满10年。"
            "该标准严于指导意见建议的满12年评估口径。",
        ),
        _p(
            styles,
            "body",
            "第四条 轻型营运柴油货车使用年限满12年的，应当强制淘汰。",
        ),
        _p(styles, "h1", "第三章 补贴标准（调整）"),
        _p(
            styles,
            "body",
            "第五条 中重型营运柴油货车提前淘汰的单车补贴标准为8000-16000元。"
            "细则锚点：2026修订版中重型营运柴油货车单车补贴为8000-16000元。"
            "不再适用指导意见「最高不超过10000元」的原则上限表述。",
        ),
        _p(styles, "h1", "第四章 更新要求"),
        _p(
            styles,
            "body",
            "第六条 领取本细则补贴的更新车辆，排放阶段须达到国六或新能源。"
            "细则锚点：2026修订版更新车辆排放阶段须达到国六或新能源。",
        ),
        _p(styles, "h1", "第五章 施行与废止"),
        _p(
            styles,
            "body",
            "第七条 本细则自2026年08月01日起施行。关键锚点：2026修订版自2026年08月01日起施行。",
        ),
        _p(
            styles,
            "body",
            "第八条 本细则与环发〔2025〕19号指导意见不一致的，以本细则为准。",
        ),
    ]


def main() -> None:
    font_name = _register_font()
    styles = _styles(font_name)
    DOCS.mkdir(parents=True, exist_ok=True)
    jobs = [
        ("机动车排放监管综合技术手册（虚拟长文）.pdf", doc_long_manual),
        ("道路运政数据交换与报表规范（虚拟技术手册）.pdf", doc_exchange_spec),
        ("老旧柴油车淘汰更新指导意见（虚拟政策文档）.pdf", doc_guidance),
        ("老旧柴油车淘汰更新实施细则（2026修订版）（虚拟政策文档）.pdf", doc_rules_2026),
    ]
    for name, builder in jobs:
        _build(DOCS / name, builder(styles))


if __name__ == "__main__":
    main()
