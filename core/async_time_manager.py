"""
Step Time Manager Module

Responsible for controlling the simulation of real time flows, supporting spontaneous time progression and time consumption based on complexity of decision-making
"""

import time
import threading
from typing import Dict, List, Callable
from queue import PriorityQueue
import uuid
from config.environment_config import EnvironmentConfig


class AsyncTimeManager:
    """
    Step Time Manager to support spontaneous time progression and time consumption based on complexity of decision-making
        """

    WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    def __init__(self):
        """
        Initialise anisotime manager
                """
        self._tick = EnvironmentConfig.START_TICK
        self._day = self._tick // EnvironmentConfig.TICKS_PER_DAY
        self._weekday = self._day % 7  

    def _update_calendar_fields(self):
        self._day = self._tick // EnvironmentConfig.TICKS_PER_DAY
        self._weekday = self._day % 7

    async def run_timer(self, tick_num: int):
        """
        Run timer, advance time
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
        Gets the current week.
                """
        return self._weekday

    def get_weekday_name(self) -> str:
        """
        Fetch the string of the current week
                """
        return self.WEEKDAY_NAMES[self._weekday]

    def set_tick(self, tick: int):
        self._tick = tick
        self._update_calendar_fields()

    def get_datetime(self):
        """
        Get Current Time Information

        Returns:
            tuple:
              Day: Day (int)
              -Weekday: A few strings a week (Mon/Tue/...)
              - time: day time (HH:MM:SS or tick)
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
        Let's see if it's a working day.
                """
        return self._weekday < 5

    def is_work_time(self) -> bool:
        """
        Determine whether the current point of time is working Internal
                """
        current_second_of_day = self._tick % EnvironmentConfig.TICKS_PER_DAY

        work_start = EnvironmentConfig.OnWork_PER_DAY
        work_end = EnvironmentConfig.OffWork_PER_DAY

        return work_start <= current_second_of_day < work_end

    def is_payday(self) -> bool:
        """
        Let's see if it's payday.
                """
        return (self._day + 1) % 30 == 0

    def fast_forward_to_next_workday_start(self) -> int:
        """
        Get into the next business day.
                """
        absolute_now = self._tick
        current_day = self._day

        candidate_day = current_day + 1
        # Slight weekends -- follow-up fine time to consider
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
