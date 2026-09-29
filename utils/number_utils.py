"""
数字处理工具模块

提供金额、数量等数字的格式化、计算、验证等功能
"""

import re
from typing import Union, Optional, Tuple, List
from decimal import Decimal, getcontext, ROUND_HALF_UP


class NumberUtils:
    """
    数字处理工具类
    """
    
    # 默认精度
    DEFAULT_PRECISION = 2
    
    # 初始化Decimal上下文
    getcontext().rounding = ROUND_HALF_UP
    getcontext().prec = 28  # 设置足够的精度
    
    @staticmethod
    def to_decimal(value: Union[float, int, str, Decimal]) -> Optional[Decimal]:
        """
        将各种类型转换为Decimal对象
        
        Args:
            value: 要转换的值
            
        Returns:
            Decimal: Decimal对象，转换失败返回None
        """
        if value is None:
            return None
        
        try:
            if isinstance(value, Decimal):
                return value
            elif isinstance(value, (int, float)):
                return Decimal(str(value))
            elif isinstance(value, str):
                # 清理字符串中的非数字字符（保留负号和小数点）
                cleaned = re.sub(r'[^\d.-]', '', value)
                return Decimal(cleaned)
            return None
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def round_number(value: Union[float, int, str, Decimal], 
                    precision: int = DEFAULT_PRECISION) -> float:
        """
        四舍五入数字
        
        Args:
            value: 要四舍五入的值
            precision: 小数位数
            
        Returns:
            float: 四舍五入后的结果
        """
        decimal_value = NumberUtils.to_decimal(value)
        if decimal_value is None:
            return 0.0
        
        # 使用Decimal进行精确的四舍五入
        rounded = decimal_value.quantize(Decimal(f'0.{"0" * precision}'))
        return float(rounded)
    
    @staticmethod
    def format_currency(value: Union[float, int, str, Decimal], 
                       currency_symbol: str = "¥", 
                       precision: int = DEFAULT_PRECISION, 
                       thousands_separator: str = ",",
                       decimal_separator: str = ".") -> str:
        """
        格式化货币
        
        Args:
            value: 金额
            currency_symbol: 货币符号
            precision: 小数位数
            thousands_separator: 千位分隔符
            decimal_separator: 小数分隔符
            
        Returns:
            str: 格式化后的货币字符串
        """
        # 转换为Decimal并四舍五入
        decimal_value = NumberUtils.to_decimal(value)
        if decimal_value is None:
            return f"{currency_symbol}0{decimal_separator}{'0' * precision}"
        
        # 格式化数字部分
        rounded = decimal_value.quantize(Decimal(f'0.{"0" * precision}'))
        parts = str(rounded).split('.')
        
        # 处理整数部分，添加千位分隔符
        integer_part = parts[0]
        # 处理负数
        negative = False
        if integer_part.startswith('-'):
            negative = True
            integer_part = integer_part[1:]
        
        # 从右向左每3位添加分隔符
        formatted_integer = ''
        for i, char in enumerate(reversed(integer_part)):
            if i > 0 and i % 3 == 0:
                formatted_integer = thousands_separator + formatted_integer
            formatted_integer = char + formatted_integer
        
        # 组合结果
        result = currency_symbol
        if negative:
            result += '-'
        result += formatted_integer
        
        # 添加小数部分
        if precision > 0:
            decimal_part = parts[1] if len(parts) > 1 else '0' * precision
            decimal_part = decimal_part.ljust(precision, '0')[:precision]  # 确保小数位数正确
            result += decimal_separator + decimal_part
        
        return result
    
    @staticmethod
    def format_percentage(value: Union[float, int, str, Decimal], 
                         precision: int = DEFAULT_PRECISION, 
                         include_symbol: bool = True) -> str:
        """
        格式化百分比
        
        Args:
            value: 百分比值（如0.1表示10%）
            precision: 小数位数
            include_symbol: 是否包含百分号
            
        Returns:
            str: 格式化后的百分比字符串
        """
        # 转换为Decimal并乘以100
        decimal_value = NumberUtils.to_decimal(value)
        if decimal_value is None:
            return f"0{'.' + '0' * precision if precision > 0 else ''}{'%' if include_symbol else ''}"
        
        # 转换为百分比并四舍五入
        percentage_value = decimal_value * Decimal('100')
        rounded = percentage_value.quantize(Decimal(f'0.{"0" * precision}'))
        
        # 格式化为字符串
        result = f"{float(rounded):.{precision}f}"
        if include_symbol:
            result += '%'
        
        return result
    
    @staticmethod
    def calculate_discount(original_price: Union[float, int, str, Decimal], 
                          discount_value: Union[float, int, str, Decimal], 
                          is_percentage: bool = True) -> Tuple[float, float]:
        """
        计算折扣金额和折后价格
        
        Args:
            original_price: 原价
            discount_value: 折扣值（如果是百分比，则为0-100的数字）
            is_percentage: 是否为百分比折扣
            
        Returns:
            tuple: (折扣金额, 折后价格)
        """
        # 转换为Decimal
        original = NumberUtils.to_decimal(original_price)
        discount = NumberUtils.to_decimal(discount_value)
        
        if original is None or discount is None or original < 0:
            return 0.0, float(original or 0)
        
        # 计算折扣金额
        if is_percentage:
            # 确保折扣百分比在合理范围内
            discount_percent = discount / Decimal('100')
            discount_amount = original * discount_percent
        else:
            # 直接折扣金额，不能超过原价
            discount_amount = min(discount, original)
        
        # 计算折后价格
        discounted_price = original - discount_amount
        
        return float(discount_amount), float(discounted_price)
    
    @staticmethod
    def calculate_tax(amount: Union[float, int, str, Decimal], 
                     tax_rate: Union[float, int, str, Decimal]) -> float:
        """
        计算税额
        
        Args:
            amount: 计税金额
            tax_rate: 税率（百分比，如13表示13%）
            
        Returns:
            float: 税额
        """
        # 转换为Decimal
        base_amount = NumberUtils.to_decimal(amount)
        rate = NumberUtils.to_decimal(tax_rate)
        
        if base_amount is None or rate is None or base_amount < 0:
            return 0.0
        
        # 计算税额
        tax_amount = base_amount * (rate / Decimal('100'))
        
        return float(tax_amount)
    
    @staticmethod
    def calculate_total_with_tax(subtotal: Union[float, int, str, Decimal], 
                                tax_rate: Union[float, int, str, Decimal]) -> Tuple[float, float]:
        """
        计算含税总价和税额
        
        Args:
            subtotal: 不含税金额
            tax_rate: 税率（百分比）
            
        Returns:
            tuple: (税额, 含税总价)
        """
        # 计算税额
        tax_amount = NumberUtils.calculate_tax(subtotal, tax_rate)
        
        # 计算总价
        subtotal_float = float(NumberUtils.to_decimal(subtotal) or 0)
        total = subtotal_float + tax_amount
        
        return tax_amount, total
    
    @staticmethod
    def calculate_average(numbers: List[Union[float, int, str, Decimal]]) -> float:
        """
        计算平均值
        
        Args:
            numbers: 数字列表
            
        Returns:
            float: 平均值
        """
        if not numbers:
            return 0.0
        
        # 转换并过滤有效数字
        valid_numbers = []
        for num in numbers:
            decimal_num = NumberUtils.to_decimal(num)
            if decimal_num is not None:
                valid_numbers.append(decimal_num)
        
        if not valid_numbers:
            return 0.0
        
        # 计算平均值
        total = sum(valid_numbers)
        average = total / Decimal(len(valid_numbers))
        
        return float(average)
    
    @staticmethod
    def is_valid_number(value: str) -> bool:
        """
        检查字符串是否为有效数字
        
        Args:
            value: 要检查的字符串
            
        Returns:
            bool: 是否为有效数字
        """
        if not isinstance(value, str):
            return False
        
        # 匹配整数或小数（包括负数）
        pattern = r'^-?\d+(\.\d+)?$'
        return bool(re.match(pattern, value))
    
    @staticmethod
    def is_valid_positive_number(value: str) -> bool:
        """
        检查字符串是否为有效正数
        
        Args:
            value: 要检查的字符串
            
        Returns:
            bool: 是否为有效正数
        """
        if not isinstance(value, str):
            return False
        
        # 匹配正数（包括小数）
        pattern = r'^\d+(\.\d+)?$'
        if not re.match(pattern, value):
            return False
        
        # 确保不是0
        try:
            num = float(value)
            return num > 0
        except ValueError:
            return False
    
    @staticmethod
    def clamp_number(value: Union[float, int], 
                    min_value: Union[float, int], 
                    max_value: Union[float, int]) -> float:
        """
        将数字限制在指定范围内
        
        Args:
            value: 要限制的数字
            min_value: 最小值
            max_value: 最大值
            
        Returns:
            float: 限制后的数字
        """
        if min_value > max_value:
            min_value, max_value = max_value, min_value
        
        return max(min_value, min(max_value, float(value)))
    
    @staticmethod
    def calculate_percentage_change(old_value: Union[float, int, str, Decimal], 
                                  new_value: Union[float, int, str, Decimal],
                                  precision: int = DEFAULT_PRECISION) -> float:
        """
        计算百分比变化
        
        Args:
            old_value: 旧值
            new_value: 新值
            precision: 小数位数
            
        Returns:
            float: 百分比变化（正值表示增长，负值表示减少）
        """
        # 转换为Decimal
        old = NumberUtils.to_decimal(old_value)
        new = NumberUtils.to_decimal(new_value)
        
        if old is None or new is None:
            return 0.0
        
        # 避免除以零
        if old == 0:
            return float('inf') if new > 0 else 0.0
        
        # 计算变化百分比
        change_percent = ((new - old) / old) * Decimal('100')
        
        # 四舍五入
        rounded = change_percent.quantize(Decimal(f'0.{"0" * precision}'))
        
        return float(rounded)
    
    @staticmethod
    def format_number(value: Union[float, int, str, Decimal], 
                    precision: int = DEFAULT_PRECISION,
                    thousands_separator: str = ",",
                    decimal_separator: str = ".") -> str:
        """
        格式化数字
        
        Args:
            value: 要格式化的数字
            precision: 小数位数
            thousands_separator: 千位分隔符
            decimal_separator: 小数分隔符
            
        Returns:
            str: 格式化后的数字字符串
        """
        # 转换为Decimal并四舍五入
        decimal_value = NumberUtils.to_decimal(value)
        if decimal_value is None:
            return f"0{decimal_separator}{'0' * precision}"
        
        # 格式化数字部分
        rounded = decimal_value.quantize(Decimal(f'0.{"0" * precision}'))
        parts = str(rounded).split('.')
        
        # 处理整数部分，添加千位分隔符
        integer_part = parts[0]
        # 处理负数
        negative = False
        if integer_part.startswith('-'):
            negative = True
            integer_part = integer_part[1:]
        
        # 从右向左每3位添加分隔符
        formatted_integer = ''
        for i, char in enumerate(reversed(integer_part)):
            if i > 0 and i % 3 == 0:
                formatted_integer = thousands_separator + formatted_integer
            formatted_integer = char + formatted_integer
        
        # 组合结果
        result = ''
        if negative:
            result += '-'
        result += formatted_integer
        
        # 添加小数部分
        if precision > 0:
            decimal_part = parts[1] if len(parts) > 1 else '0' * precision
            decimal_part = decimal_part.ljust(precision, '0')[:precision]  # 确保小数位数正确
            result += decimal_separator + decimal_part
        
        return result


# 示例用法
if __name__ == "__main__":
    # 格式化货币
    price = 12345.6789
    formatted_price = NumberUtils.format_currency(price)
    print(f"格式化货币: {formatted_price}")
    
    # 格式化百分比
    discount_rate = 0.15
    formatted_percent = NumberUtils.format_percentage(discount_rate)
    print(f"格式化百分比: {formatted_percent}")
    
    # 计算折扣
    original_price = 1000
    discount_value = 20
    discount_amount, discounted_price = NumberUtils.calculate_discount(original_price, discount_value, is_percentage=True)
    print(f"原价: {original_price}, 折扣: {discount_value}%, 折扣金额: {discount_amount:.2f}, 折后价: {discounted_price:.2f}")
    
    # 计算税额
    subtotal = 1000
    tax_rate = 13
    tax_amount, total_with_tax = NumberUtils.calculate_total_with_tax(subtotal, tax_rate)
    print(f"不含税金额: {subtotal}, 税率: {tax_rate}%, 税额: {tax_amount:.2f}, 含税总价: {total_with_tax:.2f}")
    
    # 格式化大数字
    large_number = 123456789.123456
    formatted_large = NumberUtils.format_number(large_number, precision=4)
    print(f"格式化大数字: {formatted_large}")
    
    # 计算百分比变化
    old_sales = 10000
    new_sales = 12500
    change_percent = NumberUtils.calculate_percentage_change(old_sales, new_sales)
    print(f"销售额变化: {old_sales} -> {new_sales}, 变化百分比: {change_percent:.2f}%")
    
    # 限制数字范围
    value = 150
    min_val = 0
    max_val = 100
    clamped = NumberUtils.clamp_number(value, min_val, max_val)
    print(f"限制范围 [{min_val}, {max_val}]: {value} -> {clamped}")