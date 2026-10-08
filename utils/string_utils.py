"""
String Processing Tool Module

Provides string formatting, authentication, conversion, etc.
"""

import re
import string
from typing import Optional, List, Dict, Any
import unicodedata


class StringUtils:
    """
    String Processing Tool Class
        """
    
    # Common regular expression mode
    PATTERNS = {
        'email': r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
        'phone_cn': r'^1[3-9]\d{9}$',  # Chinese mainland cell phone number
        'id_card_cn': r'^[1-9]\d{5}(18|19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]$',  # Chinese ID number
        'postal_code_cn': r'^\d{6}$',  # Chinese Postal Code
        'url': r'^https?://[\w\-]+(\.[\w\-]+)+([\w\-\.,@?^=%&:/~\+#]*[\w\-\@?^=%&/~\+#])?$'
    }
    
    @staticmethod
    def trim(text: Optional[str]) -> str:
        """
        Remove string end blank
                
        Args:
            text: Enter string
                        
        Returns:
            str: Processed String
                """
        if text is None:
            return ""
        return str(text).strip()
    
    @staticmethod
    def ltrim(text: Optional[str]) -> str:
        """
        Remove left blank of string
                
        Args:
            text: Enter string
                        
        Returns:
            str: Processed String
                """
        if text is None:
            return ""
        return str(text).lstrip()
    
    @staticmethod
    def rtrim(text: Optional[str]) -> str:
        """
        Remove Right Space of String
                
        Args:
            text: Enter string
                        
        Returns:
            str: Processed String
                """
        if text is None:
            return ""
        return str(text).rstrip()
    
    @staticmethod
    def is_empty(text: Optional[str]) -> bool:
        """
        Determines whether the string is empty (None, empty string or only contains blank characters)
                
        Args:
            text: String to check
                        
        Returns:
            Bool: Is it empty
                """
        return text is None or str(text).strip() == ""
    
    @staticmethod
    def is_not_empty(text: Optional[str]) -> bool:
        """
        Determines whether the string is empty
                
        Args:
            text: String to check
                        
        Returns:
            Bool: Is it empty
                """
        return not StringUtils.is_empty(text)
    
    @staticmethod
    def truncate(text: Optional[str], max_length: int, suffix: str = "...") -> str:
        """
        Break string, after maximum length added
                
        Args:
            text: Enter string
            parameter: Maximum length
            suffix: Break Postfix
                        
        Returns:
            str: Processed String
                """
        if text is None:
            return ""
        
        text = str(text)
        if len(text) <= max_length:
            return text
        
        # Make sure the suffix doesn't result in much shorter than the maximum length.
        if max_length <= len(suffix):
            return suffix[:max_length]
        
        return text[:max_length - len(suffix)] + suffix
    
    @staticmethod
    def capitalize(text: Optional[str]) -> str:
        """
        Capitalise the first letter of the string
                
        Args:
            text: Enter string
                        
        Returns:
            str: Processed String
                """
        if text is None:
            return ""
        return str(text).capitalize()
    
    @staticmethod
    def title_case(text: Optional[str]) -> str:
        """
        Capitalise the first letter of each string
                
        Args:
            text: Enter string
                        
        Returns:
            str: Processed String
                """
        if text is None:
            return ""
        return str(text).title()
    
    @staticmethod
    def snake_case(text: Optional[str]) -> str:
        """
        Convert string to snake-shaped naming (separated by underlined)
                
        Args:
            text: Enter a string (support for camel naming)
                        
        Returns:
            str: Processed String
                """
        if text is None:
            return ""
        
        text = str(text)
        # Converting the name of the camel to a snake
        # Add underline before uppercase
        result = re.sub(r'(?<=[a-z0-9])([A-Z])', r'_\1', text)
        # Replace multiple underlineds with individual
        result = re.sub(r'_+', '_', result)
        # Remove tail underlined and turn to lowercase
        return result.strip('_').lower()
    
    @staticmethod
    def camel_case(text: Optional[str]) -> str:
        """
        Convert string to camel naming
                
        Args:
            text: Enter a string (supported by a line, hyphen etc.)
                        
        Returns:
            str: Processed String
                """
        if text is None:
            return ""
        
        text = str(text)
        # Capitalise letters after separator (underline, hyphen etc.)
        # First turn text into lowercase and split
        parts = re.split(r'[-_\s]+', text.lower())
        # First letter lower, next word uppercase
        if not parts:
            return ""
        return parts[0] + ''.join(word.capitalize() for word in parts[1:])
    
    @staticmethod
    def pascal_case(text: Optional[str]) -> str:
        """
        Convert string to Pascal Naming
                
        Args:
            text: Enter string
                        
        Returns:
            str: Processed String
                """
        if text is None:
            return ""
        
        text = str(text)
        # Capitalise letters after separator (underline, hyphen etc.)
        parts = re.split(r'[-_\s]+', text.lower())
        if not parts:
            return ""
        return ''.join(word.capitalize() for word in parts)
    
    @staticmethod
    def is_valid_email(text: Optional[str]) -> bool:
        """
        Could not close temporary folder: %s
                
        Args:
            text: String to check
                        
        Returns:
            Bool: Is it a valid mailbox
                """
        if text is None:
            return False
        return bool(re.match(StringUtils.PATTERNS['email'], str(text)))
    
    @staticmethod
    def is_valid_phone_cn(text: Optional[str]) -> bool:
        """
        Check if it's a valid mainland Chinese cell phone number
                
        Args:
            text: String to check
                        
        Returns:
            Bool: valid cell number
                """
        if text is None:
            return False
        return bool(re.match(StringUtils.PATTERNS['phone_cn'], str(text)))
    
    @staticmethod
    def is_valid_id_card_cn(text: Optional[str]) -> bool:
        """
        Validation of Chinese ID number Code
                
        Args:
            text: String to check
                        
        Returns:
            Bool: valid ID number
                """
        if text is None:
            return False
        
        text = str(text)
        # Format validation first
        if not re.match(StringUtils.PATTERNS['id_card_cn'], text):
            return False
        
        # Validate checksum (simplified version)
        # Weighted factor
        weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
        # Validation Correlation
        check_codes = ['1', '0', 'X', '9', '8', '7', '6', '5', '4', '3', '2']
        
        # Calculating Validation
        total = 0
        for i in range(17):
            total += int(text[i]) * weights[i]
        
        # Calculating verification position
        check_code_pos = total % 11
        
        # Compare calibration
        return check_codes[check_code_pos].upper() == text[17].upper()
    
    @staticmethod
    def is_valid_url(text: Optional[str]) -> bool:
        """
        Could not close temporary folder: %s
                
        Args:
            text: String to check
                        
        Returns:
            Bool: Is it a valid URL
                """
        if text is None:
            return False
        return bool(re.match(StringUtils.PATTERNS['url'], str(text)))
    
    @staticmethod
    def mask_sensitive_info(text: Optional[str], 
                          start_pos: int = 0, 
                          end_pos: Optional[int] = None, 
                          mask_char: str = '*') -> str:
        """
        Hide Sensitive Information
                
        Args:
            text: original text
            parameter: Shade Start Location
            end_pos: Shade End Location (None indicates End)
            parameter:shading Symbol
                        
        Returns:
            st: behind the masked text
                """
        if text is None:
            return ""
        
        text = str(text)
        if start_pos < 0:
            start_pos = 0
        
        if end_pos is None or end_pos > len(text):
            end_pos = len(text)
        
        if start_pos >= end_pos:
            return text
        
        # Create Shade
        masked_length = end_pos - start_pos
        masked_part = mask_char * masked_length
        
        # Group results
        return text[:start_pos] + masked_part + text[end_pos:]
    
    @staticmethod
    def mask_email(email: Optional[str], mask_user: bool = True, mask_domain: bool = False) -> str:
        """
        Cover Mailbox Address
                
        Args:
            email: Mailbox address
            parameter : Whether the user name is hidden
            parameter : Whether the domain name is protected
                        
        Returns:
            st: The address of the masked mailbox
                """
        if email is None or not StringUtils.is_valid_email(str(email)):
            return str(email or "")
        
        email = str(email)
        username, domain = email.split('@', 1)
        
        # Process user name component
        if mask_user:
            if len(username) <= 3:
                masked_username = username[0] + '*' * (len(username) - 1)
            else:
                # Retain first and second places
                masked_username = username[0] + '*' * (len(username) - 2) + username[-1]
        else:
            masked_username = username
        
        # Process domain name component
        if mask_domain:
            if '.' in domain:
                parts = domain.split('.')
                if len(parts[0]) <= 2:
                    masked_domain = '*' * len(parts[0]) + '.' + '.'.join(parts[1:])
                else:
                    # Retain first and second places
                    masked_domain = parts[0][0] + '*' * (len(parts[0]) - 2) + parts[0][-1] + '.' + '.'.join(parts[1:])
            else:
                masked_domain = '*' * len(domain)
        else:
            masked_domain = domain
        
        return f"{masked_username}@{masked_domain}"
    
    @staticmethod
    def mask_phone_cn(phone: Optional[str]) -> str:
        """
        Covering the mainland Chinese cell phone number.
                
        Args:
            Phone number Code
                        
        Returns:
            st: The cell phone number behind the mask
                """
        if phone is None or not StringUtils.is_valid_phone_cn(str(phone)):
            return str(phone or "")
        
        phone = str(phone)
        # Retain first three and fourth.
        return f"{phone[:3]}****{phone[-4:]}"
    
    @staticmethod
    def normalize_whitespace(text: Optional[str]) -> str:
        """
        Standardised whitespace characters (replace multiple consecutive blanks to single spaces)
                
        Args:
            text: Enter string
                        
        Returns:
            str: Processed String
                """
        if text is None:
            return ""
        return re.sub(r'\s+', ' ', str(text)).strip()
    
    @staticmethod
    def remove_punctuation(text: Optional[str], keep: Optional[str] = None) -> str:
        """
        Remove Punctuation
                
        Args:
            text: Enter string
            keepep: Punctuation to keep
                        
        Returns:
            str: Processed String
                """
        if text is None:
            return ""
        
        text = str(text)
        if keep:
            # Create a conversion table to keep noms
            punct_to_remove = ''.join(p for p in string.punctuation if p not in keep)
            translator = str.maketrans('', '', punct_to_remove)
        else:
            # Remove All Punctuations
            translator = str.maketrans('', '', string.punctuation)
        
        return text.translate(translator)
    
    @staticmethod
    def to_ascii(text: Optional[str], replace_char: str = '?') -> str:
        """
        Convert non-ASCII characters to ASCII (or replace)
                
        Args:
            text: Enter string
            parameter: Replace word Symbol
                        
        Returns:
            str: Processed String
                """
        if text is None:
            return ""
        
        # First try to standardize decomposable Unicode characters to ASCII
        normalized = unicodedata.normalize('NFKD', str(text))
        ascii_text = normalized.encode('ascii', 'ignore').decode('ascii')
        
        # If non-ASCII characters need to be replaced rather than ignored
        if replace_char != '':
            result = ''
            for char in str(text):
                if ord(char) < 128:
                    result += char
                else:
                    result += replace_char
            return result
        
        return ascii_text
    
    @staticmethod
    def count_words(text: Optional[str]) -> int:
        """
        Calculate the number of words
                
        Args:
            text: Enter string
                        
        Returns:
            Int: Number of Words
                """
        if text is None or not str(text).strip():
            return 0
        
        # Match words with regular expression
        words = re.findall(r'\b\w+\b', str(text))
        return len(words)
    
    @staticmethod
    def safe_filename(text: Optional[str], max_length: int = 200, replace_char: str = '_') -> str:
        """
        Convert text to a safe file name.
                
        Args:
            text: Enter string
            max_length: Maximum output length.
            replace_char: Replacement character for unsafe symbols.
                        
        Returns:
            str: Safe file name.
                """
        if text is None:
            return ""
        
        # Remove or replace unsafe characters
        # Windows filenames cannot contain: < > : " / \ *
        unsafe_chars = '<>:"/\\|?*' + ''.join(chr(c) for c in range(32))  # Add Control Character
        
        # Create replacement table
        translator = str.maketrans(unsafe_chars, replace_char * len(unsafe_chars))
        safe = str(text).translate(translator)
        
        # Remove Additional Replace Characters
        safe = re.sub(rf'{re.escape(replace_char)}+', replace_char, safe).strip(replace_char)
        
        # Break to maximum length
        return StringUtils.truncate(safe, max_length, "")
    
    @staticmethod
    def format_template(template: Optional[str], **kwargs) -> str:
        """
        Formatting Template String
                
        Args:
            template: Template string, position with {key} Symbol
            **kwargs: Replace key pairs
                        
        Returns:
            str: Formatted String
                """
        if template is None:
            return ""
        
        try:
            return str(template).format(**kwargs)
        except (KeyError, IndexError):
            # Return original template if replacement failed
            return str(template)


# Example Usage
if __name__ == "__main__":
    # Basic Operations
    text = "  Hello World  "
    print(f"Original text: '{text}'")
    print(f"Trimmed text: '{StringUtils.trim(text)}'")
    print(f"Is empty: {StringUtils.is_empty(text)}")
    
    # String Formatting
    long_text = "This long text must be truncated to fit the display."
    truncated = StringUtils.truncate(long_text, 20)
    print(f"Truncated text: '{truncated}'")
    
    # Name Format Conversion
    camel_text = "camelCaseExample"
    print(f"Camel case to snake case: '{StringUtils.snake_case(camel_text)}'")
    
    snake_text = "snake_case_example"
    print(f"Snake case to camel case: '{StringUtils.camel_case(snake_text)}'")
    print(f"Snake case to Pascal case: '{StringUtils.pascal_case(snake_text)}'")
    
    # Authentication function
    email = "test@example.com"
    invalid_email = "not-an-email"
    print(f"Email validation '{email}': {StringUtils.is_valid_email(email)}")
    print(f"Email validation '{invalid_email}': {StringUtils.is_valid_email(invalid_email)}")
    
    phone = "13812345678"
    print(f"Phone validation '{phone}': {StringUtils.is_valid_phone_cn(phone)}")
    
    # Sensitive information mask
    masked_email = StringUtils.mask_email("zhang.san@example.com")
    print(f"Masked email: '{masked_email}'")
    
    masked_phone = StringUtils.mask_phone_cn("13812345678")
    print(f"Masked phone: '{masked_phone}'")
    
    # Other functions
    text_with_punct = "Hello, World! How are you?"
    print(f"Remove punctuation: '{StringUtils.remove_punctuation(text_with_punct)}'")
    print(f"Remove punctuation (keep !): '{StringUtils.remove_punctuation(text_with_punct, keep='!')}'")
    
    # Template Formatting
    template = "Welcome {name}; your order number is {order_id}."
    formatted = StringUtils.format_template(template, name="Example User", order_id="ORD-2024-12345")
    print(f"Formatted template: '{formatted}'")
