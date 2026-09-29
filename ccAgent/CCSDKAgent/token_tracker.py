"""
Token使用量跟踪器
统计各部门(role)和轮次(round)的Token消耗数据
"""

import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Any, Optional


class TokenTracker:
    """Token使用量统计类"""

    def __init__(self, workspace_dir: Path):
        """
        初始化TokenTracker

        Args:
            workspace_dir: workspace目录路径
        """
        self.workspace_dir = Path(workspace_dir)
        self.usage_dir = self.workspace_dir / "token_usage"
        self.usage_dir.mkdir(parents=True, exist_ok=True)

        # 数据结构: {round_id: {role: [{usage_data}, ...]}}
        self.data: Dict[int, Dict[str, List[Dict[str, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )

    def record(self, round_id: int, role: str, result_message) -> None:
        """
        记录单次query的token使用数据

        Args:
            round_id: 工作轮次ID
            role: 部门角色名（Analyst/HR/Sales/Production/Inventory/Procurement）
            result_message: Claude Agent SDK的ResultMessage对象
        """
        # 从ResultMessage中提取使用数据（容错处理）
        usage = getattr(result_message, "usage", {}) or {}

        entry = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            "total_cost_usd": getattr(result_message, "total_cost_usd", 0) or 0,
            "num_turns": getattr(result_message, "num_turns", 0) or 0,
            "duration_ms": getattr(result_message, "duration_ms", 0) or 0,
            "session_id": getattr(result_message, "session_id", "") or "",
        }

        self.data[round_id][role].append(entry)

    def build_report(self) -> Dict[str, Any]:
        """
        构建汇总报告

        Returns:
            包含总计和分轮次统计的报告字典
        """
        report = {
            "generated_at": datetime.now().isoformat(),
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cache_read_input_tokens": 0,
            "total_cache_creation_input_tokens": 0,
            "total_cost_usd": 0.0,
            "total_duration_ms": 0,
            "rounds": {}
        }

        # 逐轮统计
        for round_id in sorted(self.data.keys()):
            round_data = self.data[round_id]
            round_stats = {
                "round_input_tokens": 0,
                "round_output_tokens": 0,
                "round_cache_read_input_tokens": 0,
                "round_cache_creation_input_tokens": 0,
                "round_cost_usd": 0.0,
                "round_duration_ms": 0,
                "roles": {}
            }

            # 逐角色统计
            for role in sorted(round_data.keys()):
                attempts = round_data[role]
                role_stats = {
                    "attempts": len(attempts),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "total_cost_usd": 0.0,
                    "total_duration_ms": 0,
                }

                # 累加该角色的所有尝试
                for attempt in attempts:
                    role_stats["input_tokens"] += attempt.get("input_tokens", 0)
                    role_stats["output_tokens"] += attempt.get("output_tokens", 0)
                    role_stats["cache_read_input_tokens"] += attempt.get("cache_read_input_tokens", 0)
                    role_stats["cache_creation_input_tokens"] += attempt.get("cache_creation_input_tokens", 0)
                    role_stats["total_cost_usd"] += attempt.get("total_cost_usd", 0)
                    role_stats["total_duration_ms"] += attempt.get("duration_ms", 0)

                # 四舍五入成本
                role_stats["total_cost_usd"] = round(role_stats["total_cost_usd"], 6)

                round_stats["roles"][role] = role_stats

                # 累加到轮次总计
                round_stats["round_input_tokens"] += role_stats["input_tokens"]
                round_stats["round_output_tokens"] += role_stats["output_tokens"]
                round_stats["round_cache_read_input_tokens"] += role_stats["cache_read_input_tokens"]
                round_stats["round_cache_creation_input_tokens"] += role_stats["cache_creation_input_tokens"]
                round_stats["round_cost_usd"] += role_stats["total_cost_usd"]
                round_stats["round_duration_ms"] += role_stats["total_duration_ms"]

            # 四舍五入轮次成本
            round_stats["round_cost_usd"] = round(round_stats["round_cost_usd"], 6)

            report["rounds"][str(round_id)] = round_stats

            # 累加到总计
            report["total_input_tokens"] += round_stats["round_input_tokens"]
            report["total_output_tokens"] += round_stats["round_output_tokens"]
            report["total_cache_read_input_tokens"] += round_stats["round_cache_read_input_tokens"]
            report["total_cache_creation_input_tokens"] += round_stats["round_cache_creation_input_tokens"]
            report["total_cost_usd"] += round_stats["round_cost_usd"]
            report["total_duration_ms"] += round_stats["round_duration_ms"]

        report["total_cost_usd"] = round(report["total_cost_usd"], 6)

        return report

    def save_report(self) -> Path:
        """
        保存报告到JSON文件

        Returns:
            报告文件路径
        """
        report = self.build_report()
        report_path = self.usage_dir / "usage_report.json"

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"\nToken usage report saved to: {report_path}")
        return report_path

    def print_summary(self) -> None:
        """在控制台打印汇总表格"""
        report = self.build_report()

        print("\n" + "=" * 100)
        print("TOKEN USAGE SUMMARY")
        print("=" * 100)
        print(
            f"{'Round':<8} {'Role':<20} {'Attempts':<12} "
            f"{'Input':<12} {'Output':<12} {'Cost($)':<12} {'Time(s)':<12}"
        )
        print("-" * 100)

        for round_id in sorted(report["rounds"].keys()):
            round_data = report["rounds"][round_id]
            for role in sorted(round_data["roles"].keys()):
                role_stats = round_data["roles"][role]
                duration_sec = role_stats["total_duration_ms"] / 1000.0
                print(
                    f"{round_id:<8} {role:<20} {role_stats['attempts']:<12} "
                    f"{role_stats['input_tokens']:<12} {role_stats['output_tokens']:<12} "
                    f"{role_stats['total_cost_usd']:<12.6f} {duration_sec:<12.1f}"
                )

        print("-" * 100)
        duration_sec = report["total_duration_ms"] / 1000.0
        print(
            f"{'TOTAL':<8} {'':<20} {'':<12} "
            f"{report['total_input_tokens']:<12} {report['total_output_tokens']:<12} "
            f"{report['total_cost_usd']:<12.6f} {duration_sec:<12.1f}"
        )
        print("=" * 100 + "\n")
