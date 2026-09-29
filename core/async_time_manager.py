"""
异步时间管理器模块

负责控制仿真的时间流动，支持自发时间推进和基于决策复杂度的时间消耗
"""

import time
import threading
from typing import Dict, List, Callable
from queue import PriorityQueue
import uuid
from config.environment_config import EnvironmentConfig


class AsyncTimeManager:
    """
    异步时间管理器，支持自发时间推进和基于决策复杂度的时间消耗
    """

    WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    def __init__(self):
        """
        初始化异步时间管理器
        """
        self._tick = EnvironmentConfig.START_TICK
        self._day = self._tick // EnvironmentConfig.TICKS_PER_DAY
        self._weekday = self._day % 7  

    # ===== 内部统一更新时间字段的方法 =====
    def _update_calendar_fields(self):
        self._day = self._tick // EnvironmentConfig.TICKS_PER_DAY
        self._weekday = self._day % 7

    async def run_timer(self, tick_num: int):
        """
        运行定时器，推进时间
        """
        assert tick_num > 0, "tick_num must be positive"
        self._tick += tick_num
        self._update_calendar_fields()

    def get_tick(self) -> int:
        return self._tick

    def get_day(self) -> int:
        return self._day

    def get_weekday(self) -> int:
        """
        获取当前是周几（0=周一 ... 6=周日）
        """
        return self._weekday

    def get_weekday_name(self) -> str:
        """
        获取当前周几的字符串表示
        """
        return self.WEEKDAY_NAMES[self._weekday]

    def set_tick(self, tick: int):
        self._tick = tick
        self._update_calendar_fields()

    def get_datetime(self):
        """
        获取当前时间信息

        Returns:
            tuple:
              - day: 第几天（int）
              - weekday: 周几字符串（Mon/Tue/...）
              - time: 当天时间（HH:MM:SS 或 tick）
        """
        tick = self._tick
        day = self._day
        weekday_str = self.get_weekday_name()

        time_of_day = tick % EnvironmentConfig.TICKS_PER_DAY

        if EnvironmentConfig.TICKS_PER_DAY == 24 * 60 * 60:
            hours = time_of_day // 3600
            minutes = (time_of_day % 3600) // 60
            seconds = time_of_day % 60
            formatted_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            return (day, weekday_str, formatted_time)
        else:
            return (day, weekday_str, time_of_day)

    def is_weekday(self) -> bool:
        """
        判断当前是否是工作日
        """
        return self._weekday < 5

    def is_work_time(self) -> bool:
        """
        判断当前时间点是否在工作时间内
        """
        current_second_of_day = self._tick % EnvironmentConfig.TICKS_PER_DAY

        work_start = EnvironmentConfig.OnWork_PER_DAY
        work_end = EnvironmentConfig.OffWork_PER_DAY

        return work_start <= current_second_of_day < work_end

    def is_payday(self) -> bool:
        """
        判断当前day是否是发薪日
        """
        return (self._day + 1) % 30 == 0

    def fast_forward_to_next_workday_start(self) -> int:
        """
        快进到下一个工作日的上班时间
        """
        absolute_now = self._tick
        current_day = self._day

        candidate_day = current_day + 1
        # 略过周末--后续精细时间应用再考虑
        # while (candidate_day % 7) in (5, 6):
        #     candidate_day += 1

        target_absolute = (
            candidate_day * EnvironmentConfig.TICKS_PER_DAY
            + EnvironmentConfig.OnWork_PER_DAY
        )

        delta = target_absolute - absolute_now
        if delta <= 0:
            return 0

        self._tick += delta
        self._update_calendar_fields()
        return delta
