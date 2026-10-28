"""Human-readable final physics coverage, keyed by source unit across genders."""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
import re

MARKER_PREFIX = "SWAY_REPORT_V1 "
REPORT_FILENAME = "动态骨骼诊断报告.txt"
SUMMARY_FILENAME = "sway_summary.json"
GENDERS = {"female": "女性", "male": "男性"}
SAFETY_STATES = {"gate_transform", "gate_axiom", "gate_weight_collision", "systemic_disable"}
STATUS_LABELS = {
    "active": "已独立分配节点", "capacity_overflow": "未获独立节点",
    "unsupported_limit": "特殊约束未自动启用", "no_weighted_chain": "无权重骨链",
    "disabled": "设置中关闭", "gate_transform": "静止姿态不匹配",
    "source_disabled": "源组件已关闭",
    "gate_axiom": "支点位置安全检查未通过", "gate_weight_collision": "骨骼权重冲突",
    "systemic_disable": "整体动态已安全停用", "allocation_unassignable": "无法分配物理节点",
    "unassigned": "未分配", "unknown": "未记录",
    "nested_follow_parent": "随父级动态（兼容模式）",
    "nested_parent_unavailable": "父级动态未启用",
}
ADVICE = {
    "active": "该部件已写入物理节点；幅度仍需在游戏中确认，可在动态参数中调节后重新转换。",
    "capacity_overflow": "该部件未在初始容量分配中获得独立节点，未启用模拟；自动模式会在初始配线前补用嵌套合并空出的节点，传统模式不补位。后续安全剔除不会再启用尚未配线的部件。可在动态详细设置中调整选择，保留头发、尾巴或衣服后重新转换。",
    "unsupported_limit": "源方向限制不能直接等价转换，默认不模拟该部件；确需摆动可在详细设置中手动启用有限角度兼容近似，但不能完整复刻碰撞器或平面限制。",
    "no_weighted_chain": "此骨链未直接驱动有权重的网格，未占用动态槽位；这不是转换错误。若它应驱动衣服，请检查 Unity 中网格权重及骨骼关系。",
    "disabled": "按设置保留为静态，不是转换错误；需要摆动时勾选该部件并重新转换。",
    "source_disabled": "源 PhysBone 或所属对象在 Unity 中已关闭，转换设置不会重新启用它；如需此动态，请在 Unity 中启用后重新导出。",
    "gate_transform": "该部件不会继续模拟，保留静态外观以避免骨骼扭曲；请保留源导出和本报告用于修复静止姿态，不建议直接放宽安全阈值。",
    "gate_axiom": "该部件不会继续模拟；需检查绑定支点和父级位置，调大摆动幅度无法修复此问题。",
    "gate_weight_collision": "该部件不会继续模拟；存在供体骨骼权重竞争，请提供源导出和本报告排查。",
    "systemic_disable": "本次动态整体停用以完成模型转换；请保留转换日志和源导出，修复后重新转换。",
    "allocation_unassignable": "该部件没有可用的物理节点或锚点；请结合原始原因检查骨链及选择数量。",
    "unassigned": "没有最终生效的物理节点；请结合原始原因及转换日志检查。",
    "unknown": "诊断记录不完整或格式无效，无法确认最终状态；重新完整转换可获得明细。",
    "nested_follow_parent": "该部件随父级动态，保留父组件对整条骨链的模拟；子组件的独立参数未移植，使用父组件参数，不额外占用物理节点。",
    "nested_parent_unavailable": "父级动态未通过后续检查，因此该子部件也不能随父模拟；请检查父组件原因。关闭父组件后可重新选择子组件独立转换。",
}
POSTURE_RE = re.compile(
    r"(?P<bone>.+?): posture mismatch \(dev#1625\): donor '(?P<donor>[^']+)' "
    r"direction differs by (?P<angle>[\d.]+) deg \(exceeds cull threshold (?P<threshold>[\d.]+) deg\)")


def _unit_key(row):
    value = row.get("unit_key")
    if isinstance(value, str) and value:
        return value
    # Compatibility with older reports; anchors alone cannot identify separate
    # components, so preserve the source and available bone/chain identity.
    return json.dumps([row.get("source", "unknown"), row.get("anchor", "unknown"),
                       row.get("bones"), row.get("source_chains")], ensure_ascii=False, sort_keys=True)


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _validated_rows(data, key, gender, warnings):
    rows = data.get(key) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        warnings.append(f"{gender}/{key}: invalid component list")
        return [], False
    result, valid, seen = [], True, set()
    for index, row in enumerate(rows):
        status_key = "stage" if key == "excluded" else "status"
        if not isinstance(row, dict):
            row = {"unit_key": f"unknown:{key}:{index}", "anchor": f"unknown_{index}"}
        row = dict(row)
        status = row.get(status_key)
        checks = row.get("placement_checks", [])
        damaged = not isinstance(status, str) or not status or not isinstance(checks, list)
        if isinstance(checks, list):
            damaged |= any(not isinstance(c, dict) or not isinstance(c.get("reason", ""), str)
                           for c in checks)
        damaged |= any(field in row and not isinstance(row[field], str)
                       for field in ("unit_key", "anchor", "source", "reason"))
        if damaged:
            valid = False
            warnings.append(f"{gender}/{key}[{index}]: invalid component fields; status unknown")
            row["status"] = "unknown"
            row["placement_checks"] = []
            row["reason"] = "Invalid diagnostic component fields; final state is unknown"
            for field in ("unit_key", "anchor", "source"):
                if field in row and not isinstance(row[field], str):
                    row[field] = f"unknown:{key}:{index}:{field}"
        else:
            row["status"] = status
        identity = _unit_key(row)
        if key == "components" and identity in seen:
            valid = False
            warnings.append(f"{gender}/{key}[{index}]: duplicate source unit; coverage unknown")
            row["status"] = "unknown"
            row["reason"] = "Duplicate source component identity in diagnostic data"
        seen.add(identity)
        result.append(row)
    return result, valid


def summarize(coverage_by_gender, exclusions_by_gender, requested_genders=None):
    genders = sorted({str(g).lower() for g in (requested_genders or
                     set(coverage_by_gender) | set(exclusions_by_gender)) if str(g).lower() in GENDERS})
    units = {}
    gender_stats = {}
    warnings = []
    for gender in genders:
        coverage = coverage_by_gender.get(gender)
        exclusion = exclusions_by_gender.get(gender) or {}
        rows = {}
        if exclusion:
            excluded_rows, _ = _validated_rows(exclusion, "excluded", gender, warnings)
            for row in excluded_rows:
                rows[_unit_key(row)] = row
            if not isinstance(exclusion, dict):
                exclusion = {}
        coverage_valid = False
        if coverage is not None:
            # The final coverage decision is authoritative: an early allocation
            # rejection must not relabel a component that has no mesh weights.
            covered_rows, coverage_valid = _validated_rows(coverage, "components", gender, warnings)
            for row in covered_rows:
                rows[_unit_key(row)] = row
            if not isinstance(coverage, dict):
                coverage = {}
            active, total, capacity = (_count(coverage.get(key)) for key in
                                      ("active_components", "total_components", "capacity"))
            if (None in (active, total, capacity) or active > total
                    or total != len(covered_rows)
                    or active != sum(row["status"] == "active" for row in covered_rows)
                    or type(coverage.get("globally_disabled", False)) is not bool):
                coverage_valid = False
                warnings.append(f"{gender}/coverage: invalid or inconsistent counts; coverage unknown")
            if not coverage_valid:
                active = total = capacity = None
        else:
            active, total, capacity = None, _count(exclusion.get("total_units")), None
        gender_stats[gender] = {
            "active": active, "total": total, "capacity": capacity,
            "globally_disabled": bool(coverage_valid and coverage.get("globally_disabled")),
            "complete_coverage": coverage_valid,
            "counts": dict(sorted(Counter(row.get("status", "unknown") for row in rows.values()).items())),
        }
        for key, row in rows.items():
            record = units.setdefault(key, {"unit_key": key, "anchor": row.get("anchor", key),
                                           "source": row.get("source", "unknown"), "genders": {}})
            record["genders"][gender] = row
    counts = Counter()
    safety = set()
    posture = []
    for unit in units.values():
        counts.update({row.get("status", "unknown") for row in unit["genders"].values()})
        affected = []
        measurements = []
        for gender, row in unit["genders"].items():
            if row.get("status") in SAFETY_STATES:
                safety.add(unit["unit_key"])
            if row.get("status") != "gate_transform":
                continue
            reasons = [row.get("reason", "")] + [r.get("reason", "") for r in row.get("placement_checks", [])
                                                   if isinstance(r, dict)]
            match = next((m for reason in reasons if (m := POSTURE_RE.search(str(reason)))), None)
            if match:
                affected.append(gender)
                measurements.append({"gender": gender, **match.groupdict()})
        if affected:
            posture.append({"unit_key": unit["unit_key"], "anchor": unit["anchor"],
                            "genders": sorted(affected), "measurements": measurements})
    return {"format": "uchinoko-reborn-sway-summary-1", "genders": gender_stats,
            "counts": dict(sorted(counts.items())), "source_components_recorded": len(units),
            "safety_excluded_components": len(safety), "posture": posture,
            "components": list(units.values()), "input_warnings": warnings,
            "final_checks": {}, "report_write_errors": []}


def _read_final_checks(converted, genders, warnings):
    result = {}
    for gender in genders:
        checks = {}
        for kind in ("sway_source_gate", "sway_pivot_axiom"):
            path = converted / f"{kind}_{gender}.json"
            check = {"status": "unknown", "path": str(path.resolve())}
            if path.is_file():
                try:
                    data = json.loads(path.read_text(encoding="utf-8-sig"))
                    if (not isinstance(data, dict) or type(data.get("ok")) is not bool
                            or _count(data.get("checked")) is None
                            or not isinstance(data.get("failed"), list)
                            or any(not isinstance(row, dict) for row in data["failed"])
                            or (data["ok"] and data["failed"])
                            or len(data["failed"]) > data["checked"]):
                        raise ValueError("invalid final-check structure")
                    failed = []
                    for index, row in enumerate(data["failed"]):
                        reasons = row.get("reasons", [row.get("reason", "")])
                        if not isinstance(reasons, list) or any(not isinstance(r, str) for r in reasons):
                            raise ValueError("invalid final-check reasons")
                        if index < 3:
                            failed.append({"bone": str(row.get("bone", row.get("pivot", "unknown"))),
                                           "donor": str(row.get("donor", "")),
                                           "reason_count": len(reasons), "reasons": [r[:500] for r in reasons[:3]]})
                    status = ("passed" if data["checked"] > 0 else "unknown") if data["ok"] else "failed"
                    check.update(status=status, checked=data["checked"],
                                 failed_count=len(data["failed"]), examples=failed)
                except (OSError, ValueError) as exc:
                    warnings.append(f"{path.name}: {type(exc).__name__}; final check unknown")
            checks[kind] = check
        statuses = {check["status"] for check in checks.values()}
        result[gender] = {"status": "failed" if "failed" in statuses else
                          "unknown" if "unknown" in statuses else "passed", "checks": checks}
    return result


def _read_adaptation(converted, genders, warnings):
    paths = {g: converted / f"sway_adaptation_{g}.json" for g in genders}
    if not any(path.is_file() for path in paths.values()):
        return {}
    result = {}
    for gender, path in paths.items():
        entry = {"status": "unknown", "components": [], "path": str(path.resolve())}
        result[gender] = entry
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if (not isinstance(data, dict) or data.get("mode") != "physbone-v1"
                    or data.get("gender") != gender or not isinstance(data.get("components"), list)
                    or not isinstance(data.get("node_overrides"), dict)):
                raise ValueError("自动转换记录的结构或性别不正确")
            seen = set()
            for row in data["components"]:
                if (not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k]
                        for k in ("unit_key", "anchor", "target_root"))
                        or row["unit_key"] in seen
                        or any(_count(row.get(k)) is None for k in ("representative_source_joints",
                            "independent_mapped_joints", "unweighted_terminal_bones", "merged_secondary_branches"))
                        or type(row.get("preserved")) is not bool
                        or not isinstance(row.get("warnings"), list)
                        or any(not isinstance(w, str) for w in row["warnings"])):
                    raise ValueError("自动转换部件字段缺失、重复或无效")
                seen.add(row["unit_key"])
                if (row["independent_mapped_joints"] > row["representative_source_joints"]
                        or row["preserved"] != (row["independent_mapped_joints"] == row["representative_source_joints"]
                                                and row["unweighted_terminal_bones"] > 0)):
                    raise ValueError("骨链保留状态与关节数量不一致")
                mode = row.get("parameter_mode")
                node = data["node_overrides"].get(row["target_root"])
                if not isinstance(node, dict):
                    raise ValueError("缺少该部件的最终参数记录")
                if mode == "physbone-v1":
                    from sway_auto import validate_profile
                    validate_profile(node.get("source_profile"))
                elif mode != "manual_override" or not isinstance(node.get("motion"), dict):
                    raise ValueError("参数来源未知，无法确认自动转换是否生效")
                gravity = row.get("gravity_fit")
                if gravity is not None and (not isinstance(gravity, dict)
                        or gravity.get("status") not in ("neutral", "matched_neutral_pose", "fallback")
                        or type(gravity.get("gravity_z")) not in (int, float)
                        or not math.isfinite(gravity["gravity_z"])):
                    raise ValueError("重力拟合记录无效")
                entry["components"].append({k: row.get(k) for k in (
                    "unit_key", "anchor", "target_root", "representative_source_joints", "independent_mapped_joints",
                    "unweighted_terminal_bones", "merged_secondary_branches", "preserved", "parameter_mode",
                    "source_version", "integration_type", "warnings", "gravity_fit")})
            entry["status"] = "recorded"
        except (OSError, ValueError, TypeError, KeyError) as exc:
            # Do not display partial rows as a complete successful conversion.
            entry["components"] = []
            entry["reason"] = ("缺少该性别的自动转换记录" if isinstance(exc, FileNotFoundError)
                               else f"无法读取完整有效的自动转换记录：{type(exc).__name__}：{exc}")
            warnings.append(f"{path.name}: {entry['reason']}；自动参数状态未知")
    return result


def _joint_lines(row, indent="  "):
    source, mapped, terminals = (_count(row.get(k)) for k in (
        "representative_source_joints", "independent_mapped_joints", "unweighted_terminal_bones"))
    if None in (source, mapped, terminals):
        return []
    lines = [f"{indent}代表主链关节：{source}→{mapped} 个独立映射；另 {terminals} 个无权重末端骨。"]
    branches = _count(row.get("merged_secondary_branches"))
    if branches:
        lines.append(f"{indent}其余 {branches} 条分支仍合并到代表主链；不代表每条分支都独立模拟。")
    return lines


def _adaptation_warning(message):
    exact = {
        "source curves were not exported; reconvert from Unity to retain their variation": "缺少 Unity 源曲线，当前仅使用基础数值；请从新版 Unity 导出器重新导出，才能保留沿骨链的变化。",
        "source geometry/SDK depth ratios unavailable; inferred from exported chain topology": "缺少源骨链几何或 SDK 深度比例，目前由骨链拓扑推断；重新从 Unity 导出可提供准确比例。",
        "source world scale unavailable; radius assumes unit source scale": "缺少骨骼世界缩放，碰撞半径暂按缩放 1 换算；请重新从 Unity 导出。",
        "source joints remain merged; per-segment behavior is an approximation": "部分源关节仍被合并，每段独立摆动只能近似。",
        "secondary branches share the representative chain and its parameter samples": "分支共用代表主链及其参数采样，分支不是独立模拟。",
        "source PhysBone colliders are not yet reproduced by the cooked backend": "源 PhysBone 碰撞器尚未移植；保存半径参数不代表已重建身体、衣服的碰撞关系。",
        "response coefficients match at 60 Hz near rest; large rotations and other frame rates differ": "响应系数按 60 Hz、接近静止姿态的小角度匹配；大幅旋转或其他帧率下会有差异。",
        "AllMotion immobility approximates component movement; local animated-pivot suppression differs": "AllMotion 惯性抑制仅近似整体移动，局部动画支点移动时的抑制与 VRChat 不完全相同。",
        "unknown or missing PhysBone version; using the 1.1 response approximation": "缺少或无法识别 PhysBone 版本，暂按 1.1 响应近似；请重新从 Unity 导出。",
        "unknown or missing integration type; using the Simplified response approximation": "缺少或无法识别积分模式，暂按 Simplified 近似；请重新从 Unity 导出。",
        "explicit component tuning takes precedence over automatic adaptation": "该部件的手动参数优先，本部件没有应用自动参数转换。",
        "gravity falloff is frozen at the captured neutral pose; dynamic orientation response is not represented": "重力衰减按导出时的静止姿态计算，姿态变化后的重力响应尚不能复刻。",
        "gravity fits only neutral-pose static balance at 60 Hz; transient and moving-pose behavior differ": "重力仅拟合 60 Hz 下静止姿态的平衡，运动过程及姿态变化时仍有差异。",
        "gravity source version is not known PhysBone 1.1; no equivalent scalar is available": "重力源版本不是已知的 PhysBone 1.1，无法可靠换算；本节点未添加重力。",
        "one node cannot represent these source gravity targets: relative residual exceeds 0.1": "同一节点无法同时满足各段的源重力目标，拟合误差超过阈值；本节点未添加重力。",
        "coincident donor heads share a curve coordinate": "重合的目标骨骼起点共用曲线坐标，无法独立表示该处的参数变化。",
    }
    if message in exact:
        return exact[message]
    if match := re.fullmatch(r"source curve (.+) is unavailable; using its scalar value", message):
        return f"缺少 {match[1]} 源曲线，暂使用该参数的基础数值；重新从 Unity 导出可补齐信息。"
    if match := re.fullmatch(r"Explicit (.+) approximation: directional limits and source colliders are not reproduced", message):
        return f"{match[1]} 方向约束已转换为有限角度近似，原方向限制和碰撞器并未等价复刻。"
    if message.startswith("invalid or missing "):
        return "源参数缺失或无效，使用回退值；建议重新从 Unity 导出。原始原因：" + message
    if "gravity" in message:
        return "重力无法完整拟合或输入无效，请结合该部件的重力状态检查。原始原因：" + message
    return "转换提示：" + message.replace("\n", " ")


def _adaptation_lines(adaptation):
    if not adaptation:
        return []
    lines = ["", "Unity PhysBone 自动参数转换", "参数由 Unity 的 PhysBone 版本、积分模式、曲线和实际骨链换算；以下是转换记录，不是游戏内效果已验证的结论。"]
    for gender, entry in adaptation.items():
        prefix = GENDERS.get(gender, gender)
        if entry["status"] != "recorded":
            lines.append(f"- {prefix}：自动参数状态未知。{entry['reason']}；请重新完整转换并保留日志。")
            continue
        rows = entry["components"]
        automatic = sum(row["parameter_mode"] == "physbone-v1" for row in rows)
        lines.append(f"- {prefix}：记录 {len(rows)} 个最终部件，其中 {automatic} 个使用自动参数，{len(rows)-automatic} 个使用手动参数。")
        for row in rows:
            lines.append(f"  {row['anchor']} [源 ID: {row['unit_key']}]")
            lines.extend(_joint_lines(row, "    "))
            lines.append("    主链保留：" + ("完整保留代表主链关节。" if row["preserved"] else "部分关节合并或无独立末端，不能宣称完整保留。"))
            mode = "Unity 自动换算" if row["parameter_mode"] == "physbone-v1" else "手动参数覆盖"
            lines.append(f"    参数来源：{mode}；PhysBone 版本：{row.get('source_version') or '未记录'}；积分模式：{row.get('integration_type') or '未记录'}。")
            gravity = row.get("gravity_fit")
            if gravity:
                labels = {"neutral": "静止目标不需要额外重力", "matched_neutral_pose": "已拟合静止平衡，运动过程为近似",
                          "fallback": "拟合未通过，使用回退值，不能视为重力已还原"}
                lines.append(f"    重力：{labels[gravity['status']]}；写入 Z 加速度 {gravity['gravity_z']:.6g} cm/s²。")
            elif row["parameter_mode"] == "physbone-v1":
                lines.append("    重力：未记录拟合结果，不能确认已还原。")
            for message in dict.fromkeys(row["warnings"]):
                lines.append("    注意：" + _adaptation_warning(message))
    return lines


def render_chinese(report):
    lines = ["Uchinoko Reborn 动态骨骼诊断报告", "", "按源部件 ID 去重，不把男女各一次当成两个部件；节点分配统计不等于最终安全检查通过。", "", "动态节点分配"]
    for gender, stats in report["genders"].items():
        prefix = GENDERS.get(gender, gender)
        if stats["globally_disabled"]:
            lines.append(f"- {prefix}：全局动态关闭，本次未评估各部件。")
        elif stats["active"] is None:
            lines.append(f"- {prefix}：未记录完整覆盖率，启用数量未知。")
        else:
            capacity = stats["capacity"] if stats["capacity"] is not None else "未知"
            lines.append(f"- {prefix}：已独立分配 {stats['active']}/{stats['total']} 个源动态部件；模板容量 {capacity} 个物理节点。")
            following = stats["counts"].get("nested_follow_parent", 0)
            if following:
                lines.append(f"  另有 {following} 个源部件随父级动态，不独立占用节点；子组件参数不单独生效。")
    lines += _adaptation_lines(report.get("source_adaptation", {}))
    lines += ["", "最终安全检查"]
    final_labels = {"passed": "通过", "failed": "未通过，不能确认动态可正常使用", "unknown": "未知，缺少完整有效的检查结果"}
    for gender, result in report.get("final_checks", {}).items():
        lines.append(f"- {GENDERS.get(gender, gender)}：{final_labels[result['status']]}。")
        for kind, check in result["checks"].items():
            title = "源骨骼变换与权重" if kind == "sway_source_gate" else "支点位置"
            lines.append(f"  {title}：{final_labels[check['status']]}；完整结果：{check['path']}")
            if check["status"] == "failed":
                lines.append(f"  未通过 {check['failed_count']}/{check['checked']} 项；下方只展示前 3 项及每项前 3 条原因。")
                for sample in check["examples"]:
                    lines.append(f"    {sample['bone']} → {sample['donor']}（共 {sample['reason_count']} 条原因）")
                    lines.extend("      " + reason.replace("\n", " ") for reason in sample["reasons"])
    if not report.get("final_checks"):
        lines.append("- 未记录最终检查；不能从节点分配数量推断检查通过。")
    lines += ["", "原因分类（同一部件跨男女去重；男女状态不同的部件可出现在多个分类中）"]
    for status, count in report["counts"].items():
        lines.append(f"- {STATUS_LABELS.get(status, status)}：{count} 个源部件。")
    lines += [f"- 安全检查实际排除：共 {report['safety_excluded_components']} 个源部件。",
              "关闭、无权重及容量限制分别列出，不代表整个模型转换失败。",
              "源部件、骨链与骨骼数量不是同一概念；一个 PhysBone 可能有多个分支。", ""]
    if report["input_warnings"]:
        lines += ["报告输入读取失败；以下信息不完整：", *[f"- {w}" for w in report["input_warnings"]], ""]
    lines += ["部件明细"]
    units = sorted(report["components"], key=lambda unit: (
        not any(row.get("status") in SAFETY_STATES for row in unit["genders"].values()), unit["anchor"], unit["unit_key"]))
    for unit in units:
        lines += ["", f"{unit['anchor']}  [源 ID: {unit['unit_key']}]"]
        for gender, row in unit["genders"].items():
            status = row.get("status", "unknown")
            lines.append(f"  {GENDERS.get(gender, gender)}：{STATUS_LABELS.get(status, status)}")
            reason = str(row.get("reason", ""))
            match = POSTURE_RE.search(reason)
            if match:
                d = match.groupdict()
                lines.append(f"  具体源骨：{d['bone']}；供体骨：{d['donor']}；方向差 {d['angle']}°，安全阈值 {d['threshold']}°。")
            if row.get("limit_type"):
                lines.append(f"  源约束：{row['limit_type']}；转换方式：{row.get('limit_conversion', '未记录')}；转换角度：{row.get('converted_limit_angle', '未记录')}°。")
            lines.extend(_joint_lines(row))
            if "preserve_segments_requested" in row:
                state = ("已请求并生效" if row.get("preserve_segments_effective") is True
                         else "已请求，但未生效" if row.get("preserve_segments_requested") is True
                         else "未请求")
                lines.append(f"  保留分段：{state}；此处确认转换映射，实际摆动仍需在游戏中验证。")
            lines.append("  影响与建议：" + ADVICE.get(status, ADVICE["unassigned"]))
            if row.get("parent_unit_key"):
                parent = next((u for u in report["components"] if u["unit_key"] == row["parent_unit_key"]), None)
                parent_anchor = parent["anchor"] if parent else "未记录锚点"
                lines.append(f"  父组件：{parent_anchor} [源 ID: {row['parent_unit_key']}]；子组件独立参数不单独生效。")
            if reason:
                lines.append("  原始原因：" + reason.replace("\n", " "))
    lines += ["", "如何反馈", "请提供本报告、sway_summary.json、男女 sway_coverage/sway_exclusions JSON 以及转换日志。",
              "需要复现或修复骨骼关系时，还需对应模型的 Unity 导出；报告本身不包含完整模型。", ""]
    return "\n".join(lines)


def write_report(converted, requested_genders):
    converted = Path(converted)
    coverage, exclusions, warnings = {}, {}, []
    found = False
    for gender in sorted({str(g).lower() for g in requested_genders if str(g).lower() in GENDERS}):
        for prefix, target, key in (("sway_coverage", coverage, "components"), ("sway_exclusions", exclusions, "excluded")):
            path = converted / f"{prefix}_{gender}.json"
            if not path.is_file():
                continue
            found = True
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(data, dict) or not isinstance(data.get(key), list):
                    raise ValueError("invalid report structure")
                target[gender] = data
            except (OSError, ValueError) as exc:
                warnings.append(f"{path.name}: {type(exc).__name__}")
    adaptation = _read_adaptation(converted, sorted({str(g).lower() for g in requested_genders
                                  if str(g).lower() in GENDERS}), warnings)
    if not found and not adaptation:
        return None
    report = summarize(coverage, exclusions, requested_genders)
    if adaptation:
        report["source_adaptation"] = adaptation
    report["input_warnings"].extend(warnings)
    for gender in report["genders"]:
        if gender not in coverage and gender not in exclusions:
            report["input_warnings"].append(f"{gender}: no coverage or exclusion report; state unknown")
    report["final_checks"] = _read_final_checks(converted, report["genders"], report["input_warnings"])
    report["report_path"] = str((converted / REPORT_FILENAME).resolve())
    try:
        Path(report["report_path"]).write_text(render_chinese(report), encoding="utf-8")
    except OSError as exc:
        report["report_write_errors"].append(f"{report['report_path']}: {type(exc).__name__}")
        report["report_path"] = None
    try:
        (converted / SUMMARY_FILENAME).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        report["report_write_errors"].append(f"{SUMMARY_FILENAME}: {type(exc).__name__}")
    return report


def marker_payload(report):
    """Single-line protocol for the existing translated completion-note route."""
    keys = ("genders", "counts", "safety_excluded_components", "report_path", "input_warnings", "report_write_errors")
    data = {key: report[key] for key in keys}
    data["final_checks"] = {gender: result["status"] for gender, result in report["final_checks"].items()}
    data["posture"] = report["posture"][:3]
    data["posture_components"] = len(report["posture"])
    return MARKER_PREFIX + json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def failed_report(requested_genders, error):
    """A reporting error must not invalidate an otherwise completed conversion."""
    report = summarize({}, {}, requested_genders)
    report["report_path"] = None
    report["report_write_errors"] = [f"Diagnostic report failed: {type(error).__name__}: {error}"]
    return report
