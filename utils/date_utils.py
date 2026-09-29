"""
日期时间处理工具模块

提供日期时间的格式化、计算、转换等功能
"""

import time
from datetime import datetime, timedelta, date
from typing import Optional, Union, List


class DateUtils:
    """
    日期时间处理工具类
    """
    
    # 常用日期格式
    DATE_FORMAT = "%Y-%m-%d"
    TIME_FORMAT = "%H:%M:%S"
    DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
    DATE_FORMAT_CN = "%Y年%m月%d日"
    DATETIME_FORMAT_CN = "%Y年%m月%d日 %H:%M:%S"
    
    @staticmethod
    def now() -> datetime:
        """
        获取当前日期时间
        
        Returns:
            datetime: 当前日期时间对象
        """
        return datetime.now()
    
    @staticmethod
    def today() -> date:
        """
        获取今天日期
        
        Returns:
            date: 今天日期对象
        """
        return date.today()
    
    @staticmethod
    def format_datetime(dt: Union[datetime, str, int, float], 
                      fmt: str = DATETIME_FORMAT) -> str:
        """
        格式化日期时间
        
        Args:
            dt: 日期时间对象、字符串、时间戳
            fmt: 格式字符串
            
        Returns:
            str: 格式化后的字符串
        """
        # 转换为datetime对象
        dt_obj = DateUtils.to_datetime(dt)
        if dt_obj:
            return dt_obj.strftime(fmt)
        return ""
    
    @staticmethod
    def format_date(d: Union[date, datetime, str, int, float], 
                   fmt: str = DATE_FORMAT) -> str:
        """
        格式化日期
        
        Args:
            d: 日期对象、字符串、时间戳
            fmt: 格式字符串
            
        Returns:
            str: 格式化后的字符串
        """
        # 转换为date对象
        date_obj = DateUtils.to_date(d)
        if date_obj:
            return date_obj.strftime(fmt)
        return ""
    
    @staticmethod
    def to_datetime(value: Union[datetime, str, int, float]) -> Optional[datetime]:
        """
        将各种类型转换为datetime对象
        
        Args:
            value: 要转换的值
            
        Returns:
            datetime: datetime对象，转换失败返回None
        """
        if isinstance(value, datetime):
            return value
        elif isinstance(value, date) and not isinstance(value, datetime):
            return datetime.combine(value, datetime.min.time())
        elif isinstance(value, (int, float)):
            # 时间戳
            return datetime.fromtimestamp(value)
        elif isinstance(value, str):
            # 尝试多种格式解析
            formats = [
                DateUtils.DATETIME_FORMAT,
                DateUtils.DATE_FORMAT,
                DateUtils.DATETIME_FORMAT_CN,
                DateUtils.DATE_FORMAT_CN,
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d",
                "%m-%d-%Y",
                "%d-%m-%Y",
                "%Y%m%d%H%M%S",
                "%Y%m%d"
            ]
            
            for fmt in formats:
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def to_date(value: Union[date, datetime, str, int, float]) -> Optional[date]:
        """
        将各种类型转换为date对象
        
        Args:
            value: 要转换的值
            
        Returns:
            date: date对象，转换失败返回None
        """
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        elif isinstance(value, datetime):
            return value.date()
        elif isinstance(value, (int, float)):
            # 时间戳
            return datetime.fromtimestamp(value).date()
        elif isinstance(value, str):
            # 尝试多种格式解析
            formats = [
                DateUtils.DATE_FORMAT,
                DateUtils.DATE_FORMAT_CN,
                "%Y/%m/%d",
                "%m-%d-%Y",
                "%d-%m-%Y",
                "%Y%m%d",
                DateUtils.DATETIME_FORMAT,
                DateUtils.DATETIME_FORMAT_CN,
                "%Y/%m/%d %H:%M:%S"
            ]
            
            for fmt in formats:
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def to_timestamp(value: Union[datetime, date, str, int, float]) -> Optional[float]:
        """
        将各种类型转换为时间戳
        
        Args:
            value: 要转换的值
            
        Returns:
            float: 时间戳，转换失败返回None
        """
        if isinstance(value, (int, float)):
            return float(value)
        elif isinstance(value, datetime):
            return value.timestamp()
        elif isinstance(value, date) and not isinstance(value, datetime):
            return datetime.combine(value, datetime.min.time()).timestamp()
        elif isinstance(value, str):
            dt = DateUtils.to_datetime(value)
            if dt:
                return dt.timestamp()
        
        return None
    
    @staticmethod
    def add_days(dt: Union[datetime, date], days: int) -> Union[datetime, date]:
        """
        增加天数
        
        Args:
            dt: 日期时间对象
            days: 天数
            
        Returns:
            Union[datetime, date]: 增加天数后的对象
        """
        if isinstance(dt, datetime):
            return dt + timedelta(days=days)
        elif isinstance(dt, date):
            return dt + timedelta(days=days)
        return dt
    
    @staticmethod
    def add_hours(dt: datetime, hours: int) -> datetime:
        """
        增加小时数
        
        Args:
            dt: 日期时间对象
            hours: 小时数
            
        Returns:
            datetime: 增加小时数后的对象
        """
        if isinstance(dt, datetime):
            return dt + timedelta(hours=hours)
        return dt
    
    @staticmethod
    def add_minutes(dt: datetime, minutes: int) -> datetime:
        """
        增加分钟数
        
        Args:
            dt: 日期时间对象
            minutes: 分钟数
            
        Returns:
            datetime: 增加分钟数后的对象
        """
        if isinstance(dt, datetime):
            return dt + timedelta(minutes=minutes)
        return dt
    
    @staticmethod
    def days_between(start_date: Union[date, datetime], end_date: Union[date, datetime]) -> int:
        """
        计算两个日期之间的天数差
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            int: 天数差
        """
        # 转换为date对象
        start = DateUtils.to_date(start_date)
        end = DateUtils.to_date(end_date)
        
        if start and end:
            return (end - start).days
        return 0
    
    @staticmethod
    def hours_between(start_dt: Union[datetime, date], end_dt: Union[datetime, date]) -> float:
        """
        计算两个日期时间之间的小时差
        
        Args:
            start_dt: 开始日期时间
            end_dt: 结束日期时间
            
        Returns:
            float: 小时差
        """
        # 转换为datetime对象
        start = DateUtils.to_datetime(start_dt)
        end = DateUtils.to_datetime(end_dt)
        
        if start and end:
            return (end - start).total_seconds() / 3600
        return 0
    
    @staticmethod
    def is_weekend(d: Union[date, datetime]) -> bool:
        """
        检查是否为周末
        
        Args:
            d: 日期对象
            
        Returns:
            bool: 是否为周末
        """
        # 转换为date对象
        date_obj = DateUtils.to_date(d)
        if date_obj:
            # 5是周六，6是周日
            return date_obj.weekday() in [5, 6]
        return False
    
    @staticmethod
    def get_week_start(d: Union[date, datetime]) -> date:
        """
        获取所在周的开始日期（周一）
        
        Args:
            d: 日期对象
            
        Returns:
            date: 周开始日期
        """
        # 转换为date对象
        date_obj = DateUtils.to_date(d)
        if date_obj:
            # 计算到周一的天数
            days_since_monday = date_obj.weekday()
            return date_obj - timedelta(days=days_since_monday)
        return DateUtils.today()
    
    @staticmethod
    def get_week_end(d: Union[date, datetime]) -> date:
        """
        获取所在周的结束日期（周日）
        
        Args:
            d: 日期对象
            
        Returns:
            date: 周结束日期
        """
        # 获取周开始日期
        week_start = DateUtils.get_week_start(d)
        # 加6天得到周日
        return week_start + timedelta(days=6)
    
    @staticmethod
    def get_month_start(d: Union[date, datetime]) -> date:
        """
        获取所在月的开始日期
        
        Args:
            d: 日期对象
            
        Returns:
            date: 月开始日期
        """
        # 转换为date对象
        date_obj = DateUtils.to_date(d)
        if date_obj:
            return date(date_obj.year, date_obj.month, 1)
        return DateUtils.today()
    
    @staticmethod
    def get_month_end(d: Union[date, datetime]) -> date:
        """
        获取所在月的结束日期
        
        Args:
            d: 日期对象
            
        Returns:
            date: 月结束日期
        """
        # 转换为date对象
        date_obj = DateUtils.to_date(d)
        if date_obj:
            # 获取下个月的第一天
            if date_obj.month == 12:
                next_month_first = date(date_obj.year + 1, 1, 1)
            else:
                next_month_first = date(date_obj.year, date_obj.month + 1, 1)
            # 减1天得到本月最后一天
            return next_month_first - timedelta(days=1)
        return DateUtils.today()
    
    @staticmethod
    def is_in_range(date_to_check: Union[date, datetime], 
                   start_date: Union[date, datetime], 
                   end_date: Union[date, datetime]) -> bool:
        """
        检查日期是否在指定范围内
        
        Args:
            date_to_check: 要检查的日期
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            bool: 是否在范围内
        """
        # 转换为相同类型进行比较
        if isinstance(date_to_check, datetime) or isinstance(start_date, datetime) or isinstance(end_date, datetime):
            dt_check = DateUtils.to_datetime(date_to_check)
            dt_start = DateUtils.to_datetime(start_date)
            dt_end = DateUtils.to_datetime(end_date)
            return dt_check is not None and dt_start is not None and dt_end is not None and dt_start <= dt_check <= dt_end
        else:
            d_check = DateUtils.to_date(date_to_check)
            d_start = DateUtils.to_date(start_date)
            d_end = DateUtils.to_date(end_date)
            return d_check is not None and d_start is not None and d_end is not None and d_start <= d_check <= d_end
    
    @staticmethod
    def get_business_days(start_date: Union[date, datetime], 
                         end_date: Union[date, datetime],
                         holidays: List[Union[date, str]] = None) -> int:
        """
        计算两个日期之间的工作日数量
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            holidays: 假期列表
            
        Returns:
            int: 工作日数量
        """
        # 转换为date对象
        start = DateUtils.to_date(start_date)
        end = DateUtils.to_date(end_date)
        
        if not start or not end:
            return 0
        
        # 确保开始日期小于结束日期
        if start > end:
            start, end = end, start
        
        # 转换假期列表为date对象
        holiday_dates = []
        if holidays:
            for h in holidays:
                holiday_date = DateUtils.to_date(h)
                if holiday_date:
                    holiday_dates.append(holiday_date)
        
        # 计算工作日数量
        business_days = 0
        current = start
        
        while current <= end:
            # 检查是否为工作日（周一到周五）且不是假期
            if current.weekday() < 5 and current not in holiday_dates:
                business_days += 1
            current += timedelta(days=1)
        
        return business_days
    
    @staticmethod
    def get_age(birth_date: Union[date, datetime]) -> int:
        """
        根据出生日期计算年龄
        
        Args:
            birth_date: 出生日期
            
        Returns:
            int: 年龄
        """
        # 转换为date对象
        birth = DateUtils.to_date(birth_date)
        if not birth:
            return 0
        
        today = DateUtils.today()
        
        # 计算年龄
        age = today.year - birth.year
        
        # 检查是否已经过了生日
        if today.month < birth.month or (today.month == birth.month and today.day < birth.day):
            age -= 1
        
        return max(0, age)


# 示例用法
if __name__ == "__main__":
    # 获取当前时间
    now = DateUtils.now()
    print(f"当前时间: {DateUtils.format_datetime(now)}")
    print(f"当前日期: {DateUtils.format_date(now)}")
    print(f"当前时间戳: {DateUtils.to_timestamp(now)}")
    
    # 日期计算
    tomorrow = DateUtils.add_days(now, 1)
    next_week = DateUtils.add_days(now, 7)
    print(f"明天: {DateUtils.format_date(tomorrow)}")
    print(f"下周今天: {DateUtils.format_date(next_week)}")
    
    # 计算天数差
    days_diff = DateUtils.days_between(now, next_week)
    print(f"相差天数: {days_diff}")
    
    # 周信息
    week_start = DateUtils.get_week_start(now)
    week_end = DateUtils.get_week_end(now)
    print(f"本周开始: {DateUtils.format_date(week_start)}")
    print(f"本周结束: {DateUtils.format_date(week_end)}")
    
    # 月信息
    month_start = DateUtils.get_month_start(now)
    month_end = DateUtils.get_month_end(now)
    print(f"本月开始: {DateUtils.format_date(month_start)}")
    print(f"本月结束: {DateUtils.format_date(month_end)}")
    
    # 检查是否在范围内
    test_date = DateUtils.add_days(now, 3)
    in_range = DateUtils.is_in_range(test_date, week_start, week_end)
    print(f"{DateUtils.format_date(test_date)} 是否在本周内: {in_range}")
    
    # 计算工作日
    holidays = ["2024-01-01"]  # 元旦假期
    business_days = DateUtils.get_business_days("2024-01-01", "2024-01-10", holidays)
    print(f"2024-01-01到2024-01-10之间的工作日数量: {business_days}")