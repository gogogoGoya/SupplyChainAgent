"""
Digital Processing Tool Module

Provide functions such as formatting, computing, certification of amounts, quantities, etc.
"""

import re
from typing import Union, Optional, Tuple, List
from decimal import Decimal, getcontext, ROUND_HALF_UP


class NumberUtils:
    """
    Digital Processing Tool Category
        """
    
    # Default Precision
    DEFAULT_PRECISION = 2
    
    # Initialize Decimal Context
    getcontext().rounding = ROUND_HALF_UP
    getcontext().prec = 28  # Set enough precision
    
    @staticmethod
    def to_decimal(value: Union[float, int, str, Decimal]) -> Optional[Decimal]:
        """
        Convert types to Decimal objects
                
        Args:
            value: value to be converted
                        
        Returns:
            Decimal: Decimal Object, None returns with conversion failure
                """
        if value is None:
            return None
        
        try:
            if isinstance(value, Decimal):
                return value
            elif isinstance(value, (int, float)):
                return Decimal(str(value))
            elif isinstance(value, str):
                # Clears non-numeric characters in a string (reserve negative numbers and decimal points)
                cleaned = re.sub(r'[^\d.-]', '', value)
                return Decimal(cleaned)
            return None
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def round_number(value: Union[float, int, str, Decimal], 
                    precision: int = DEFAULT_PRECISION) -> float:
        """
        Rounded
                
        Args:
            value: value to be rounded
            Number of decimal places
                        
        Returns:
            Float: result rounded
                """
        decimal_value = NumberUtils.to_decimal(value)
        if decimal_value is None:
            return 0.0
        
        # Use Decimal for precise rounding
        rounded = decimal_value.quantize(Decimal(f'0.{"0" * precision}'))
        return float(rounded)
    
    @staticmethod
    def format_currency(value: Union[float, int, str, Decimal], 
                       currency_symbol: str = "¥", 
                       precision: int = DEFAULT_PRECISION, 
                       thousands_separator: str = ",",
                       decimal_separator: str = ".") -> str:
        """
        Formatting Currency
                
        Args:
            Value: Amount
            parameter: Currency symbol
            Number of decimal places
            parameter: thousands separator
            decimal_separator: Decimal Separator
                        
        Returns:
            str: Formatted Currency String
                """
        # Convert to Decimal and rounded
        decimal_value = NumberUtils.to_decimal(value)
        if decimal_value is None:
            return f"{currency_symbol}0{decimal_separator}{'0' * precision}"
        
        # Formatting numbers section
        rounded = decimal_value.quantize(Decimal(f'0.{"0" * precision}'))
        parts = str(rounded).split('.')
        
        # Handle integer part, add thousands partition Symbol
        integer_part = parts[0]
        # Deal with negative numbers
        negative = False
        if integer_part.startswith('-'):
            negative = True
            integer_part = integer_part[1:]
        
        # Add Separator every 3 places from right to left
        formatted_integer = ''
        for i, char in enumerate(reversed(integer_part)):
            if i > 0 and i % 3 == 0:
                formatted_integer = thousands_separator + formatted_integer
            formatted_integer = char + formatted_integer
        
        # Group results
        result = currency_symbol
        if negative:
            result += '-'
        result += formatted_integer
        
        # Add decimal part
        if precision > 0:
            decimal_part = parts[1] if len(parts) > 1 else '0' * precision
            decimal_part = decimal_part.ljust(precision, '0')[:precision]  # Make sure the decimal is correct.
            result += decimal_separator + decimal_part
        
        return result
    
    @staticmethod
    def format_percentage(value: Union[float, int, str, Decimal], 
                         precision: int = DEFAULT_PRECISION, 
                         include_symbol: bool = True) -> str:
        """
        Formatting Percentage
                
        Args:
            Value: Percentage value (e.g. 0.1 means 10%)
            Number of decimal places
            parameter: Does it contain a percentage number?
                        
        Returns:
            str: Percentage string after formatting
                """
        # Convert to Decimal and multiply by 100
        decimal_value = NumberUtils.to_decimal(value)
        if decimal_value is None:
            return f"0{'.' + '0' * precision if precision > 0 else ''}{'%' if include_symbol else ''}"
        
        # Convert to percentage and rounded
        percentage_value = decimal_value * Decimal('100')
        rounded = percentage_value.quantize(Decimal(f'0.{"0" * precision}'))
        
        # Format into string
        result = f"{float(rounded):.{precision}f}"
        if include_symbol:
            result += '%'
        
        return result
    
    @staticmethod
    def calculate_discount(original_price: Union[float, int, str, Decimal], 
                          discount_value: Union[float, int, str, Decimal], 
                          is_percentage: bool = True) -> Tuple[float, float]:
        """
        Calculation of discount amount and discount price
                
        Args:
            parameter: Original price
            discount_value: Debit value (0-100 in percentage)
            parameter : Whether it is a percentage discount
                        
        Returns:
            tuple: (discount amount, discount price)
                """
        # Convert to Decimal
        original = NumberUtils.to_decimal(original_price)
        discount = NumberUtils.to_decimal(discount_value)
        
        if original is None or discount is None or original < 0:
            return 0.0, float(original or 0)
        
        # Calculation of discount amount
        if is_percentage:
            # Ensure that the percentage discount is within reasonable range Internal
            discount_percent = discount / Decimal('100')
            discount_amount = original * discount_percent
        else:
            # Direct discount amount, not above original price
            discount_amount = min(discount, original)
        
        # Calculating post-mortem prices
        discounted_price = original - discount_amount
        
        return float(discount_amount), float(discounted_price)
    
    @staticmethod
    def calculate_tax(amount: Union[float, int, str, Decimal], 
                     tax_rate: Union[float, int, str, Decimal]) -> float:
        """
        Calculation of taxes
                
        Args:
            amount: tax amount
            tax_rate: Tax rate (percentage, i.e. 13%)
                        
        Returns:
            Taxes
                """
        # Convert to Decimal
        base_amount = NumberUtils.to_decimal(amount)
        rate = NumberUtils.to_decimal(tax_rate)
        
        if base_amount is None or rate is None or base_amount < 0:
            return 0.0
        
        # Calculation of taxes
        tax_amount = base_amount * (rate / Decimal('100'))
        
        return float(tax_amount)
    
    @staticmethod
    def calculate_total_with_tax(subtotal: Union[float, int, str, Decimal], 
                                tax_rate: Union[float, int, str, Decimal]) -> Tuple[float, float]:
        """
        Computation of gross and tax values
                
        Args:
            Subtotal: No tax amounts
            tax_rate: Tax rate (percentage)
                        
        Returns:
            Tuple: (tax, including total tax)
                """
        # Calculation of taxes
        tax_amount = NumberUtils.calculate_tax(subtotal, tax_rate)
        
        # Calculate total price
        subtotal_float = float(NumberUtils.to_decimal(subtotal) or 0)
        total = subtotal_float + tax_amount
        
        return tax_amount, total
    
    @staticmethod
    def calculate_average(numbers: List[Union[float, int, str, Decimal]]) -> float:
        """
        Calculated average
                
        Args:
            Numbers: Number List
                        
        Returns:
            float: average
                """
        if not numbers:
            return 0.0
        
        # Convert and filter valid numbers
        valid_numbers = []
        for num in numbers:
            decimal_num = NumberUtils.to_decimal(num)
            if decimal_num is not None:
                valid_numbers.append(decimal_num)
        
        if not valid_numbers:
            return 0.0
        
        # Calculated average
        total = sum(valid_numbers)
        average = total / Decimal(len(valid_numbers))
        
        return float(average)
    
    @staticmethod
    def is_valid_number(value: str) -> bool:
        """
        Checks if the string is a valid number
                
        Args:
            value: String to check
                        
        Returns:
            Bool: Is it a valid number
                """
        if not isinstance(value, str):
            return False
        
        # Match integer or decimal (including negative)
        pattern = r'^-?\d+(\.\d+)?$'
        return bool(re.match(pattern, value))
    
    @staticmethod
    def is_valid_positive_number(value: str) -> bool:
        """
        Check if the string is active positive
                
        Args:
            value: String to check
                        
        Returns:
            Bool: Is it a valid positive number
                """
        if not isinstance(value, str):
            return False
        
        # Match positive numbers (including decimals)
        pattern = r'^\d+(\.\d+)?$'
        if not re.match(pattern, value):
            return False
        
        # Make sure it's not zero.
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
        Limiting numbers to specified ranges
                
        Args:
            Value: Numbers to limit
            parameter: Minimal value
            parameter: Maximum value
                        
        Returns:
            float: Limited Numbers
                """
        if min_value > max_value:
            min_value, max_value = max_value, min_value
        
        return max(min_value, min(max_value, float(value)))
    
    @staticmethod
    def calculate_percentage_change(old_value: Union[float, int, str, Decimal], 
                                  new_value: Union[float, int, str, Decimal],
                                  precision: int = DEFAULT_PRECISION) -> float:
        """
        Calculated percentage change
                
        Args:
            parameter: Old value
            new_value: New value
            Number of decimal places
                        
        Returns:
            float: percentage change (positive for growth, negative for decrease)
                """
        # Convert to Decimal
        old = NumberUtils.to_decimal(old_value)
        new = NumberUtils.to_decimal(new_value)
        
        if old is None or new is None:
            return 0.0
        
        # Avoid dividing by zero
        if old == 0:
            return float('inf') if new > 0 else 0.0
        
        # Calculated percentage change
        change_percent = ((new - old) / old) * Decimal('100')
        
        # Rounded
        rounded = change_percent.quantize(Decimal(f'0.{"0" * precision}'))
        
        return float(rounded)
    
    @staticmethod
    def format_number(value: Union[float, int, str, Decimal], 
                    precision: int = DEFAULT_PRECISION,
                    thousands_separator: str = ",",
                    decimal_separator: str = ".") -> str:
        """
        Format Numbers
                
        Args:
            value: numbers to format
            Number of decimal places
            parameter: thousands separator
            decimal_separator: Decimal Separator
                        
        Returns:
            str: Formatted Digital String
                """
        # Convert to Decimal and rounded
        decimal_value = NumberUtils.to_decimal(value)
        if decimal_value is None:
            return f"0{decimal_separator}{'0' * precision}"
        
        # Formatting numbers section
        rounded = decimal_value.quantize(Decimal(f'0.{"0" * precision}'))
        parts = str(rounded).split('.')
        
        # Handle integer part, add thousands partition Symbol
        integer_part = parts[0]
        # Deal with negative numbers
        negative = False
        if integer_part.startswith('-'):
            negative = True
            integer_part = integer_part[1:]
        
        # Add Separator every 3 places from right to left
        formatted_integer = ''
        for i, char in enumerate(reversed(integer_part)):
            if i > 0 and i % 3 == 0:
                formatted_integer = thousands_separator + formatted_integer
            formatted_integer = char + formatted_integer
        
        # Group results
        result = ''
        if negative:
            result += '-'
        result += formatted_integer
        
        # Add decimal part
        if precision > 0:
            decimal_part = parts[1] if len(parts) > 1 else '0' * precision
            decimal_part = decimal_part.ljust(precision, '0')[:precision]  # Make sure the decimal is correct.
            result += decimal_separator + decimal_part
        
        return result


# Example Usage
if __name__ == "__main__":
    # Formatting Currency
    price = 12345.6789
    formatted_price = NumberUtils.format_currency(price)
    print(f"Formatted currency: {formatted_price}")
    
    # Formatting Percentage
    discount_rate = 0.15
    formatted_percent = NumberUtils.format_percentage(discount_rate)
    print(f"Formatted percentage: {formatted_percent}")
    
    # Calculate discount
    original_price = 1000
    discount_value = 20
    discount_amount, discounted_price = NumberUtils.calculate_discount(original_price, discount_value, is_percentage=True)
    print(f"Original price: {original_price}, discount: {discount_value}%, discount amount: {discount_amount:.2f}, discounted price: {discounted_price:.2f}")
    
    # Calculation of taxes
    subtotal = 1000
    tax_rate = 13
    tax_amount, total_with_tax = NumberUtils.calculate_total_with_tax(subtotal, tax_rate)
    print(f"Subtotal: {subtotal}, tax rate: {tax_rate}%, tax: {tax_amount:.2f}, total with tax: {total_with_tax:.2f}")
    
    # Format Big Numbers
    large_number = 123456789.123456
    formatted_large = NumberUtils.format_number(large_number, precision=4)
    print(f"Formatted large number: {formatted_large}")
    
    # Calculated percentage change
    old_sales = 10000
    new_sales = 12500
    change_percent = NumberUtils.calculate_percentage_change(old_sales, new_sales)
    print(f"Sales change: {old_sales} -> {new_sales}, percentage change: {change_percent:.2f}%")
    
    # Limit number ranges
    value = 150
    min_val = 0
    max_val = 100
    clamped = NumberUtils.clamp_number(value, min_val, max_val)
    print(f"Clamp to [{min_val}, {max_val}]: {value} -> {clamped}")
