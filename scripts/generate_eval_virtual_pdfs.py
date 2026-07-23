#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成测评扩容用的 7 份虚拟 PDF（中文）。

依赖本机中文字体：/System/Library/Fonts/Supplemental/Arial Unicode.ttf
输出目录：docs/
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

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
            "title_cn",
            parent=base["Title"],
            fontName=font_name,
            fontSize=16,
            leading=22,
            spaceAfter=10,
        ),
        "h1": ParagraphStyle(
            "h1_cn",
            parent=base["Heading1"],
            fontName=font_name,
            fontSize=13,
            leading=18,
            spaceBefore=12,
            spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "h2_cn",
            parent=base["Heading2"],
            fontName=font_name,
            fontSize=11,
            leading=16,
            spaceBefore=8,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body_cn",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=10.5,
            leading=16,
            spaceAfter=4,
        ),
        "meta": ParagraphStyle(
            "meta_cn",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=10,
            leading=15,
            spaceAfter=2,
        ),
    }


def _build(path: Path, flowables: list) -> None:
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=path.stem,
    )
    doc.build(flowables)
    print(f"wrote {path.name} ({path.stat().st_size} bytes)")


def _p(styles: dict, key: str, text: str) -> Paragraph:
    return Paragraph(text.replace("\n", "<br/>"), styles[key])


def doc_guosi(styles: dict) -> list:
    return [
        _p(styles, "title", "国四排放标准柴油货车淘汰补贴实施细则（虚拟政策文档）"),
        _p(styles, "meta", "发文机关：生态环境部、财政部、交通运输部"),
        _p(styles, "meta", "发文文号：环发〔2026〕58号"),
        _p(styles, "meta", "施行日期：2026年09月15日"),
        _p(
            styles,
            "meta",
            "效力说明：本文档为虚拟政策文档，仅用于 RAG 测评与培训演示，非官方法定文件。",
        ),
        Spacer(1, 6),
        _p(styles, "h1", "第一章 总则"),
        _p(
            styles,
            "body",
            "第一条 为加快国四排放标准柴油货车（以下简称“国四柴油货车”）淘汰更新，规范补贴申领与审核，"
            "制定本细则。",
        ),
        _p(
            styles,
            "body",
            "第二条 本细则适用于全国范围内登记注册的国四柴油货车，不含汽油车、天然气车及新能源车辆。",
        ),
        _p(styles, "h1", "第二章 淘汰条件"),
        _p(
            styles,
            "body",
            "第三条 国四中重型营运柴油货车使用年限满10年的，应当启动淘汰程序，可申请本细则规定的补贴。",
        ),
        _p(
            styles,
            "body",
            "第四条 轻型国四柴油车累计行驶里程达到80万公里的，应当强制淘汰并注销登记。",
        ),
        _p(
            styles,
            "body",
            "第五条 国四与国三政策不得混用：本细则补贴标准独立核算，不得与环发〔2026〕32号重复申领。",
        ),
        _p(styles, "h1", "第三章 补贴标准"),
        _p(
            styles,
            "body",
            "第六条 国四中重型营运柴油货车提前淘汰的单车补贴标准为：单车补贴8000-15000元，"
            "具体档位由省级生态环境部门按车龄与排放一致性检查结果确定。",
        ),
        _p(
            styles,
            "body",
            "第七条 轻型国四柴油货车提前淘汰的单车补贴上限为6000元，不设下限。",
        ),
        _p(styles, "h1", "第四章 申请与审核"),
        _p(
            styles,
            "body",
            "第八条 车主应在车辆注销前通过省级补贴服务平台提交申请，材料包括登记证书、报废证明、银行账户信息。",
        ),
        _p(
            styles,
            "body",
            "第九条 审核时限为材料齐全后15个工作日，逾期未办结须书面说明原因。",
        ),
        _p(styles, "h1", "第五章 附则"),
        _p(
            styles,
            "body",
            "第十条 本细则自2026年09月15日起施行，有效期至2028年12月31日。",
        ),
    ]


def doc_gasoline(styles: dict) -> list:
    return [
        _p(styles, "title", "轻型汽油车年检排放检测方法操作规程（虚拟技术手册）"),
        _p(styles, "meta", "文档编号：YQ-QC-JY-2026-03"),
        _p(styles, "meta", "发布单位：省级机动车排放检验技术指导中心（虚拟）"),
        _p(styles, "meta", "实施日期：2026年03月01日"),
        _p(
            styles,
            "meta",
            "效力说明：本文档为虚拟技术手册，仅用于检测方法培训与 RAG 测评，非官方检测标准文本。",
        ),
        Spacer(1, 6),
        _p(styles, "h1", "1 适用范围"),
        _p(
            styles,
            "body",
            "本规程适用于总质量不超过3500千克的轻型汽油车在用车排放年度检验，不含柴油车、新能源汽车。",
        ),
        _p(styles, "h1", "2 检测方法"),
        _p(styles, "h2", "2.1 怠速法"),
        _p(
            styles,
            "body",
            "采用怠速法时，怠速法检测时长不少于90秒；采样开始前应确认发动机水温达到正常工作温度。",
        ),
        _p(styles, "h2", "2.2 双怠速法"),
        _p(
            styles,
            "body",
            "双怠速法高怠速转速范围2500±200转/分，低怠速按车辆制造商规定执行；转速超限应中止本次检测。",
        ),
        _p(styles, "h1", "3 设备与校准"),
        _p(
            styles,
            "body",
            "检验机构使用的气体分析仪设备校准周期不超过30个自然日，超期未校准不得出具检验报告。",
        ),
        _p(
            styles,
            "body",
            "校准气体应在有效期内，并保留校准记录至少24个月备查。",
        ),
        _p(styles, "h1", "4 复检规则"),
        _p(
            styles,
            "body",
            "首次检验不合格的，不合格复检间隔不少于24小时；同一检验周期内复检不得超过2次。",
        ),
        _p(styles, "h1", "5 结果判定"),
        _p(
            styles,
            "body",
            "一氧化碳、碳氢化合物任一项超过限值即判定不合格；结果应即时写入机动车排放检验信息系统。",
        ),
    ]


def doc_nev(styles: dict) -> list:
    return [
        _p(styles, "title", "新能源汽车远程监控平台接入技术规范（虚拟技术手册）"),
        _p(styles, "meta", "文档编号：NEV-RM-2026-V1"),
        _p(styles, "meta", "主管单位：省级工业和信息化主管部门（虚拟）"),
        _p(styles, "meta", "实施日期：2026年04月01日"),
        _p(
            styles,
            "meta",
            "效力说明：本文档为虚拟技术规范，仅用于平台接入培训与 RAG 测评，不替代真实国标或地标。",
        ),
        Spacer(1, 6),
        _p(styles, "h1", "1 总则"),
        _p(
            styles,
            "body",
            "本规范规定新能源汽车车载终端接入省级远程监控平台的通信、报文与安全要求，"
            "不适用于传统燃油车 OBD 监管链路。",
        ),
        _p(styles, "h1", "2 通信要求"),
        _p(
            styles,
            "body",
            "车载终端与平台之间数据传输协议仅支持MQTT over TLS，禁止明文 MQTT 与自定义私有明文协议。",
        ),
        _p(
            styles,
            "body",
            "平台接入端口9443；测试环境可使用9444，但正式上线必须切换至9443。",
        ),
        _p(
            styles,
            "body",
            "终端心跳周期为60秒，心跳超时未恢复的，平台应在3个周期后标记终端离线。",
        ),
        _p(styles, "h1", "3 报文与指令"),
        _p(
            styles,
            "body",
            "车辆实时工况数据上报对应的报文指令 ID 为0xA101；平台下发参数更新指令 ID 为0xA201。",
        ),
        _p(
            styles,
            "body",
            "报文正文采用 UTF-8 编码的 JSON，字段命名遵循 camelCase。",
        ),
        _p(styles, "h1", "4 本地缓存"),
        _p(
            styles,
            "body",
            "终端离线时本地缓存不少于5000条工况记录，恢复在线后应按时间顺序补传，补传完成前不得丢弃。",
        ),
        _p(styles, "h1", "5 安全"),
        _p(
            styles,
            "body",
            "终端证书有效期最长12个月，过期证书不得建立 TLS 会话。",
        ),
    ]


def doc_danger(styles: dict) -> list:
    return [
        _p(styles, "title", "危险品道路运输车辆动态监控管理规定（虚拟政策文档）"),
        _p(styles, "meta", "发文机关：交通运输部、公安部（虚拟联签）"),
        _p(styles, "meta", "发文文号：交运规〔2026〕11号"),
        _p(styles, "meta", "施行日期：2026年05月01日"),
        _p(
            styles,
            "meta",
            "效力说明：本文档为虚拟政策规定，仅用于监管培训与 RAG 测评，非官方法定文本。",
        ),
        Spacer(1, 6),
        _p(styles, "h1", "第一章 总则"),
        _p(
            styles,
            "body",
            "第一条 为加强危险品道路运输车辆动态监控，预防重特大事故，制定本规定。",
        ),
        _p(styles, "h1", "第二章 监控要求"),
        _p(
            styles,
            "body",
            "第二条 危险品道路运输车辆轨迹回传间隔不超过30秒，隧道等弱信号路段允许短时缓存后补传。",
        ),
        _p(
            styles,
            "body",
            "第三条 监控平台应保存轨迹数据不少于180天，涉嫌事故的应延长保存至结案后两年。",
        ),
        _p(
            styles,
            "body",
            "第四条 超速报警阈值阈值为同一路段连续3次超速；达到阈值的，企业安全员须在15分钟内处置并留痕。",
        ),
        _p(styles, "h1", "第三章 车辆退出"),
        _p(
            styles,
            "body",
            "第五条 危险品运输车辆强制报废使用年限满8年，达到年限的不得继续从事危险货物道路运输。",
        ),
        _p(
            styles,
            "body",
            "第六条 本规定所称危险品运输车辆年限计算，与国三柴油车报废标准相互独立，不得直接套用环发〔2026〕32号年限。",
        ),
        _p(styles, "h1", "第四章 附则"),
        _p(
            styles,
            "body",
            "第七条 本规定自2026年05月01日起施行。",
        ),
    ]


def doc_health(styles: dict) -> list:
    return [
        _p(styles, "title", "机动车维修电子健康档案数据交换规范（虚拟技术手册）"),
        _p(styles, "meta", "文档编号：VX-HEALTH-XCH-2026"),
        _p(styles, "meta", "编制单位：省级交通运输数据中心（虚拟）"),
        _p(styles, "meta", "实施日期：2026年02月20日"),
        _p(
            styles,
            "meta",
            "效力说明：本文档为虚拟数据交换规范，仅用于接口联调培训与 RAG 测评。",
        ),
        Spacer(1, 6),
        _p(styles, "h1", "1 范围"),
        _p(
            styles,
            "body",
            "本规范约定机动车维修电子健康档案在维修企业、监管平台之间的数据交换格式与接口行为，"
            "不覆盖 JT/T 809 道路运政监管链路。",
        ),
        _p(styles, "h1", "2 编码与格式"),
        _p(
            styles,
            "body",
            "数据交换报文编码采用UTF-8；日期时间统一使用 ISO-8601，时区固定为东八区。",
        ),
        _p(
            styles,
            "body",
            "报文类型使用 application/json，禁止以 HTML 表格作为交换正文。",
        ),
        _p(styles, "h1", "3 接口约定"),
        _p(
            styles,
            "body",
            "健康档案同步接口路径为 /v1/vehicle-health/sync，HTTP 方法为 POST。",
        ),
        _p(
            styles,
            "body",
            "单次批量上传上限200条；超过上限应拆分为多次请求，服务端可返回 413。",
        ),
        _p(styles, "h1", "4 可靠性"),
        _p(
            styles,
            "body",
            "网络失败时重试退避基数为5秒，采用指数退避，最多重试4次。",
        ),
        _p(
            styles,
            "body",
            "档案保留期限不少于6年；超期归档数据应可审计追溯。",
        ),
        _p(styles, "h1", "5 安全"),
        _p(
            styles,
            "body",
            "接口调用须携带平台颁发的 accessToken，令牌有效期不超过2小时。",
        ),
    ]


def doc_security(styles: dict) -> list:
    return [
        _p(styles, "title", "企业内部信息安全分级保护管理手册（虚拟制度文档）"),
        _p(styles, "meta", "文档编号：AQ-NB-2026-007"),
        _p(styles, "meta", "发布部门：公司信息安全委员会（虚拟企业）"),
        _p(styles, "meta", "生效日期：2026年01月10日"),
        _p(
            styles,
            "meta",
            "效力说明：本文档为虚拟企业内部制度，仅用于异域噪声语料与 RAG 测评，与机动车监管业务无关。",
        ),
        Spacer(1, 6),
        _p(styles, "h1", "1 目的"),
        _p(
            styles,
            "body",
            "为规范公司信息系统与电子文档的分级保护，降低信息泄露与越权访问风险，制定本手册。",
        ),
        _p(styles, "h1", "2 分级与审批"),
        _p(
            styles,
            "body",
            "机密级文档外发须经信息安全委员会双人审批；绝密级文档禁止通过公共即时通讯工具传输。",
        ),
        _p(styles, "h1", "3 账号与口令"),
        _p(
            styles,
            "body",
            "业务系统登录密码最短长度不少于12位，须同时包含大小写字母、数字与特殊字符。",
        ),
        _p(
            styles,
            "body",
            "特权账号应启用多因素认证，会话空闲超过30分钟自动锁定。",
        ),
        _p(styles, "h1", "4 事件响应"),
        _p(
            styles,
            "body",
            "安全事件上报时限为发现后2小时内，重大事件须同步通知值班总监。",
        ),
        _p(
            styles,
            "body",
            "等保自查周期每半年一次，自查报告应在结束后10个工作日内归档。",
        ),
        _p(styles, "h1", "5 附则"),
        _p(
            styles,
            "body",
            "本手册由信息安全委员会解释，修订须发布新版本号。",
        ),
    ]


def doc_park(styles: dict) -> list:
    return [
        _p(styles, "title", "智慧园区访客预约与门禁通行管理规范（虚拟制度文档）"),
        _p(styles, "meta", "文档编号：YQ-MJ-202604"),
        _p(styles, "meta", "发布单位：园区运营中心（虚拟）"),
        _p(styles, "meta", "生效日期：2026年04月08日"),
        _p(
            styles,
            "meta",
            "效力说明：本文档为虚拟园区制度，仅用于异域噪声语料与 RAG 测评，与机动车排放监管无关。",
        ),
        Spacer(1, 6),
        _p(styles, "h1", "1 总则"),
        _p(
            styles,
            "body",
            "为规范智慧园区访客预约、门禁通行与园区交通秩序，制定本规范。",
        ),
        _p(styles, "h1", "2 访客预约"),
        _p(
            styles,
            "body",
            "访客须提前至少4小时在线预约，预约成功后方可申领临时通行码。",
        ),
        _p(
            styles,
            "body",
            "临时通行码有效期为当日24时前，过期自动失效，不得跨日复用。",
        ),
        _p(styles, "h1", "3 门禁通行"),
        _p(
            styles,
            "body",
            "门禁刷卡失败连续5次锁定，锁定后须由前台人工核验身份后方可解锁。",
        ),
        _p(
            styles,
            "body",
            "货车装卸通道与访客人行通道物理隔离，访客不得进入装卸作业区。",
        ),
        _p(styles, "h1", "4 园区交通"),
        _p(
            styles,
            "body",
            "园区主干道限速20公里/小时；违反限速规定的，当月累计3次取消预约权限30天。",
        ),
        _p(styles, "h1", "5 附则"),
        _p(
            styles,
            "body",
            "本规范由园区运营中心负责解释，自生效日期起执行。",
        ),
    ]


def main() -> None:
    font_name = _register_font()
    styles = _styles(font_name)
    DOCS.mkdir(parents=True, exist_ok=True)

    jobs = [
        ("国四排放标准柴油货车淘汰补贴实施细则（虚拟政策文档）.pdf", doc_guosi),
        ("轻型汽油车年检排放检测方法操作规程（虚拟技术手册）.pdf", doc_gasoline),
        ("新能源汽车远程监控平台接入技术规范（虚拟技术手册）.pdf", doc_nev),
        ("危险品道路运输车辆动态监控管理规定（虚拟政策文档）.pdf", doc_danger),
        ("机动车维修电子健康档案数据交换规范（虚拟技术手册）.pdf", doc_health),
        ("企业内部信息安全分级保护管理手册（虚拟制度文档）.pdf", doc_security),
        ("智慧园区访客预约与门禁通行管理规范（虚拟制度文档）.pdf", doc_park),
    ]
    for name, builder in jobs:
        _build(DOCS / name, builder(styles))


if __name__ == "__main__":
    main()
