"""
Date time-processing tool module

Provide formatting, computing, conversion, etc. of date time
"""

import time
from datetime import datetime, timedelta, date
from typing import Optional, Union, List


class DateUtils:
    """
    Date-time-processing tool class
        """
    
    # Common Date Formatting
    DATE_FORMAT = "%Y-%m-%d"
    TIME_FORMAT = "%H:%M:%S"
    DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
    DATE_FORMAT_CN = "%Y-%m-%d"
    DATETIME_FORMAT_CN = "%Y-%m-%d %H:%M:%S"
    
    @staticmethod
    def now() -> datetime:
        """
        Fetch current date time
                
        Returns:
            datetime: Current Date Time Object
                """
        return datetime.now()
    
    @staticmethod
    def today() -> date:
        """
        Can not open message
                
        Returns:
            date:
                """
        return date.today()
    
    @staticmethod
    def format_datetime(dt: Union[datetime, str, int, float], 
                      fmt: str = DATETIME_FORMAT) -> str:
        """
        Format Date Time
                
        Args:
            dt: Date time object, string, time stamp
            fmt: Format String
                        
        Returns:
            str: Formatted String
                """
        # Convert to Datatime Object
        dt_obj = DateUtils.to_datetime(dt)
        if dt_obj:
            return dt_obj.strftime(fmt)
        return ""
    
    @staticmethod
    def format_date(d: Union[date, datetime, str, int, float], 
                   fmt: str = DATE_FORMAT) -> str:
        """
        Formatting Date
                
        Args:
            d: Date object, string, time stamp
            fmt: Format String
                        
        Returns:
            str: Formatted String
                """
        # Convert to date object
        date_obj = DateUtils.to_date(d)
        if date_obj:
            return date_obj.strftime(fmt)
        return ""
    
    @staticmethod
    def to_datetime(value: Union[datetime, str, int, float]) -> Optional[datetime]:
        """
        Convert all types to datetime objects
                
        Args:
            value: value to be converted
                        
        Returns:
            Datetime: datetime object, conversion failed to returnNone
                """
        if isinstance(value, datetime):
            return value
        elif isinstance(value, date) and not isinstance(value, datetime):
            return datetime.combine(value, datetime.min.time())
        elif isinstance(value, (int, float)):
            # Timetamp
            return datetime.fromtimestamp(value)
        elif isinstance(value, str):
            # Try multiformat resolution
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
        Convert all types to date objects
                
        Args:
            value: value to be converted
                        
        Returns:
            Date: date object, conversion failed to return Noone
                """
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        elif isinstance(value, datetime):
            return value.date()
        elif isinstance(value, (int, float)):
            # Timetamp
            return datetime.fromtimestamp(value).date()
        elif isinstance(value, str):
            # Try multiformat resolution
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
        Convert types to timetamps
                
        Args:
            value: value to be converted
                        
        Returns:
            float: Timetamp, conversion failed to returnNone
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
        Number of additional days
                
        Args:
            dt: Date time objects
            days: days
                        
        Returns:
            Union [datetime, date]:
                """
        if isinstance(dt, datetime):
            return dt + timedelta(days=days)
        elif isinstance(dt, date):
            return dt + timedelta(days=days)
        return dt
    
    @staticmethod
    def add_hours(dt: datetime, hours: int) -> datetime:
        """
        Additional hours
                
        Args:
            dt: Date time objects
            hours: hours
                        
        Returns:
            datetime: object after additional hours
                """
        if isinstance(dt, datetime):
            return dt + timedelta(hours=hours)
        return dt
    
    @staticmethod
    def add_minutes(dt: datetime, minutes: int) -> datetime:
        """
        Increase in minutes
                
        Args:
            dt: Date time objects
            minutes:
                        
        Returns:
            datetime: object after minutes
                """
        if isinstance(dt, datetime):
            return dt + timedelta(minutes=minutes)
        return dt
    
    @staticmethod
    def days_between(start_date: Union[date, datetime], end_date: Union[date, datetime]) -> int:
        """
        Calculate the number of days between two dates Bad
                
        Args:
            parameter: Start date
            end_date: End date
                        
        Returns:
            Int: Day difference
                """
        # Convert to date object
        start = DateUtils.to_date(start_date)
        end = DateUtils.to_date(end_date)
        
        if start and end:
            return (end - start).days
        return 0
    
    @staticmethod
    def hours_between(start_dt: Union[datetime, date], end_dt: Union[datetime, date]) -> float:
        """
        Calculate the hour difference between the two dates
                
        Args:
            parameter: Start date
            parameter: End date
                        
        Returns:
            float: hour difference
                """
        # Convert to Datatime Object
        start = DateUtils.to_datetime(start_dt)
        end = DateUtils.to_datetime(end_dt)
        
        if start and end:
            return (end - start).total_seconds() / 3600
        return 0
    
    @staticmethod
    def is_weekend(d: Union[date, datetime]) -> bool:
        """
        Check for weekends
                
        Args:
            d: Date Object
                        
        Returns:
            Bool: Is it a weekend?
                """
        # Convert to date object
        date_obj = DateUtils.to_date(d)
        if date_obj:
            # Five is Saturday. Six is Sunday.
            return date_obj.weekday() in [5, 6]
        return False
    
    @staticmethod
    def get_week_start(d: Union[date, datetime]) -> date:
        """
        Fetch the start date of the week (Mon)
                
        Args:
            d: Date Object
                        
        Returns:
            date: Start of week
                """
        # Convert to date object
        date_obj = DateUtils.to_date(d)
        if date_obj:
            # Count to Monday
            days_since_monday = date_obj.weekday()
            return date_obj - timedelta(days=days_since_monday)
        return DateUtils.today()
    
    @staticmethod
    def get_week_end(d: Union[date, datetime]) -> date:
        """
        Fetch the end date of the week (Sunday)
                
        Args:
            d: Date Object
                        
        Returns:
            date: end of week
                """
        # Fetch week start date
        week_start = DateUtils.get_week_start(d)
        # Plus six days to get Sunday.
        return week_start + timedelta(days=6)
    
    @staticmethod
    def get_month_start(d: Union[date, datetime]) -> date:
        """
        Fetch the start date of the month
                
        Args:
            d: Date Object
                        
        Returns:
            Date: Start date
                """
        # Convert to date object
        date_obj = DateUtils.to_date(d)
        if date_obj:
            return date(date_obj.year, date_obj.month, 1)
        return DateUtils.today()
    
    @staticmethod
    def get_month_end(d: Union[date, datetime]) -> date:
        """
        Fetch end date of month
                
        Args:
            d: Date Object
                        
        Returns:
            date: end of month
                """
        # Convert to date object
        date_obj = DateUtils.to_date(d)
        if date_obj:
            # Get first day of next month
            if date_obj.month == 12:
                next_month_first = date(date_obj.year + 1, 1, 1)
            else:
                next_month_first = date(date_obj.year, date_obj.month + 1, 1)
            # Less one day to last day of the month.
            return next_month_first - timedelta(days=1)
        return DateUtils.today()
    
    @staticmethod
    def is_in_range(date_to_check: Union[date, datetime], 
                   start_date: Union[date, datetime], 
                   end_date: Union[date, datetime]) -> bool:
        """
        Check whether the date is in the specified range Internal
                
        Args:
            parameter : Date to check
            parameter: Start date
            end_date: End date
                        
        Returns:
            Bool: Is it in range? Internal
                """
        # Convert to the same type for comparison
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
        Calculate the number of working days between two dates
                
        Args:
            parameter: Start date
            end_date: End date
            Holiday list
                        
        Returns:
            Int: Number of working days
                """
        # Convert to date object
        start = DateUtils.to_date(start_date)
        end = DateUtils.to_date(end_date)
        
        if not start or not end:
            return 0
        
        # Ensure that the start date is less than the end date
        if start > end:
            start, end = end, start
        
        # Convert vacation list to date object
        holiday_dates = []
        if holidays:
            for h in holidays:
                holiday_date = DateUtils.to_date(h)
                if holiday_date:
                    holiday_dates.append(holiday_date)
        
        # Calculate the number of working days
        business_days = 0
        current = start
        
        while current <= end:
            # Check if it's a working day (Monday to Friday) and not a holiday
            if current.weekday() < 5 and current not in holiday_dates:
                business_days += 1
            current += timedelta(days=1)
        
        return business_days
    
    @staticmethod
    def get_age(birth_date: Union[date, datetime]) -> int:
        """
        Age by date of birth
                
        Args:
            parameter: Date of birth
                        
        Returns:
            Int: Age
                """
        # Convert to date object
        birth = DateUtils.to_date(birth_date)
        if not birth:
            return 0
        
        today = DateUtils.today()
        
        # Calculate age
        age = today.year - birth.year
        
        # Check your birthday.
        if today.month < birth.month or (today.month == birth.month and today.day < birth.day):
            age -= 1
        
        return max(0, age)


# Example Usage
if __name__ == "__main__":
    # Get Current Time
    now = DateUtils.now()
    print(f"Current time: {DateUtils.format_datetime(now)}")
    print(f"Current date: {DateUtils.format_date(now)}")
    print(f"Current timestamp: {DateUtils.to_timestamp(now)}")
    
    # Date Count
    tomorrow = DateUtils.add_days(now, 1)
    next_week = DateUtils.add_days(now, 7)
    print(f"Tomorrow: {DateUtils.format_date(tomorrow)}")
    print(f"This day next week: {DateUtils.format_date(next_week)}")
    
    # Calculating day differential
    days_diff = DateUtils.days_between(now, next_week)
    print(f"Day difference: {days_diff}")
    
    # Can not open message
    week_start = DateUtils.get_week_start(now)
    week_end = DateUtils.get_week_end(now)
    print(f"Start of this week: {DateUtils.format_date(week_start)}")
    print(f"End of this week: {DateUtils.format_date(week_end)}")
    
    # Month Information
    month_start = DateUtils.get_month_start(now)
    month_end = DateUtils.get_month_end(now)
    print(f"Start of this month: {DateUtils.format_date(month_start)}")
    print(f"End of this month: {DateUtils.format_date(month_end)}")
    
    # Check if it's in range.
    test_date = DateUtils.add_days(now, 3)
    in_range = DateUtils.is_in_range(test_date, week_start, week_end)
    print(f"Is {DateUtils.format_date(test_date)} within this week: {in_range}")
    
    # Calculating working days
    holidays = ["2024-01-01"]  # New Year's Eve.
    business_days = DateUtils.get_business_days("2024-01-01", "2024-01-10", holidays)
    print(f"Business days between 2024-01-01 and 2024-01-10: {business_days}")
