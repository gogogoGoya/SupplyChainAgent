"""
字符串处理工具模块

提供字符串的格式化、验证、转换等功能
"""

import re
import string
from typing import Optional, List, Dict, Any
import unicodedata


class StringUtils:
    """
    字符串处理工具类
    """
    
    # 常用正则表达式模式
    PATTERNS = {
        'email': r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
        'phone_cn': r'^1[3-9]\d{9}$',  # 中国大陆手机号
        'id_card_cn': r'^[1-9]\d{5}(18|19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]$',  # 中国身份证号
        'postal_code_cn': r'^\d{6}$',  # 中国邮政编码
        'url': r'^https?://[\w\-]+(\.[\w\-]+)+([\w\-\.,@?^=%&:/~\+#]*[\w\-\@?^=%&/~\+#])?$'
    }
    
    @staticmethod
    def trim(text: Optional[str]) -> str:
        """
        去除字符串首尾空白
        
        Args:
            text: 输入字符串
            
        Returns:
            str: 处理后的字符串
        """
        if text is None:
            return ""
        return str(text).strip()
    
    @staticmethod
    def ltrim(text: Optional[str]) -> str:
        """
        去除字符串左侧空白
        
        Args:
            text: 输入字符串
            
        Returns:
            str: 处理后的字符串
        """
        if text is None:
            return ""
        return str(text).lstrip()
    
    @staticmethod
    def rtrim(text: Optional[str]) -> str:
        """
        去除字符串右侧空白
        
        Args:
            text: 输入字符串
            
        Returns:
            str: 处理后的字符串
        """
        if text is None:
            return ""
        return str(text).rstrip()
    
    @staticmethod
    def is_empty(text: Optional[str]) -> bool:
        """
        判断字符串是否为空（None、空字符串或只包含空白字符）
        
        Args:
            text: 要检查的字符串
            
        Returns:
            bool: 是否为空
        """
        return text is None or str(text).strip() == ""
    
    @staticmethod
    def is_not_empty(text: Optional[str]) -> bool:
        """
        判断字符串是否非空
        
        Args:
            text: 要检查的字符串
            
        Returns:
            bool: 是否非空
        """
        return not StringUtils.is_empty(text)
    
    @staticmethod
    def truncate(text: Optional[str], max_length: int, suffix: str = "...") -> str:
        """
        截断字符串，超过最大长度时添加后缀
        
        Args:
            text: 输入字符串
            max_length: 最大长度
            suffix: 截断后缀
            
        Returns:
            str: 处理后的字符串
        """
        if text is None:
            return ""
        
        text = str(text)
        if len(text) <= max_length:
            return text
        
        # 确保后缀不会导致结果比最大长度短太多
        if max_length <= len(suffix):
            return suffix[:max_length]
        
        return text[:max_length - len(suffix)] + suffix
    
    @staticmethod
    def capitalize(text: Optional[str]) -> str:
        """
        将字符串首字母大写
        
        Args:
            text: 输入字符串
            
        Returns:
            str: 处理后的字符串
        """
        if text is None:
            return ""
        return str(text).capitalize()
    
    @staticmethod
    def title_case(text: Optional[str]) -> str:
        """
        将字符串每个单词首字母大写
        
        Args:
            text: 输入字符串
            
        Returns:
            str: 处理后的字符串
        """
        if text is None:
            return ""
        return str(text).title()
    
    @staticmethod
    def snake_case(text: Optional[str]) -> str:
        """
        将字符串转换为蛇形命名法（下划线分隔）
        
        Args:
            text: 输入字符串（支持驼峰命名）
            
        Returns:
            str: 处理后的字符串
        """
        if text is None:
            return ""
        
        text = str(text)
        # 将驼峰命名转换为蛇形
        # 添加下划线在大写字母前
        result = re.sub(r'(?<=[a-z0-9])([A-Z])', r'_\1', text)
        # 将多个下划线替换为单个
        result = re.sub(r'_+', '_', result)
        # 移除首尾下划线并转为小写
        return result.strip('_').lower()
    
    @staticmethod
    def camel_case(text: Optional[str]) -> str:
        """
        将字符串转换为驼峰命名法
        
        Args:
            text: 输入字符串（支持下划线、连字符等分隔）
            
        Returns:
            str: 处理后的字符串
        """
        if text is None:
            return ""
        
        text = str(text)
        # 将分隔符（下划线、连字符等）后的字母大写
        # 首先将文本转为小写并分割
        parts = re.split(r'[-_\s]+', text.lower())
        # 首字母小写，后续单词首字母大写
        if not parts:
            return ""
        return parts[0] + ''.join(word.capitalize() for word in parts[1:])
    
    @staticmethod
    def pascal_case(text: Optional[str]) -> str:
        """
        将字符串转换为帕斯卡命名法（每个单词首字母大写）
        
        Args:
            text: 输入字符串
            
        Returns:
            str: 处理后的字符串
        """
        if text is None:
            return ""
        
        text = str(text)
        # 将分隔符（下划线、连字符等）后的字母大写
        parts = re.split(r'[-_\s]+', text.lower())
        if not parts:
            return ""
        return ''.join(word.capitalize() for word in parts)
    
    @staticmethod
    def is_valid_email(text: Optional[str]) -> bool:
        """
        验证是否为有效的邮箱地址
        
        Args:
            text: 要检查的字符串
            
        Returns:
            bool: 是否为有效邮箱
        """
        if text is None:
            return False
        return bool(re.match(StringUtils.PATTERNS['email'], str(text)))
    
    @staticmethod
    def is_valid_phone_cn(text: Optional[str]) -> bool:
        """
        验证是否为有效的中国大陆手机号码
        
        Args:
            text: 要检查的字符串
            
        Returns:
            bool: 是否为有效手机号
        """
        if text is None:
            return False
        return bool(re.match(StringUtils.PATTERNS['phone_cn'], str(text)))
    
    @staticmethod
    def is_valid_id_card_cn(text: Optional[str]) -> bool:
        """
        验证是否为有效的中国身份证号码
        
        Args:
            text: 要检查的字符串
            
        Returns:
            bool: 是否为有效身份证号
        """
        if text is None:
            return False
        
        text = str(text)
        # 先进行格式验证
        if not re.match(StringUtils.PATTERNS['id_card_cn'], text):
            return False
        
        # 验证校验码（简化版）
        # 加权因子
        weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
        # 校验码对应值
        check_codes = ['1', '0', 'X', '9', '8', '7', '6', '5', '4', '3', '2']
        
        # 计算校验码
        total = 0
        for i in range(17):
            total += int(text[i]) * weights[i]
        
        # 计算校验码位置
        check_code_pos = total % 11
        
        # 比较校验码
        return check_codes[check_code_pos].upper() == text[17].upper()
    
    @staticmethod
    def is_valid_url(text: Optional[str]) -> bool:
        """
        验证是否为有效的URL
        
        Args:
            text: 要检查的字符串
            
        Returns:
            bool: 是否为有效URL
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
        遮蔽敏感信息
        
        Args:
            text: 原始文本
            start_pos: 遮蔽开始位置
            end_pos: 遮蔽结束位置（None表示到结尾）
            mask_char: 遮蔽字符
            
        Returns:
            str: 遮蔽后的文本
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
        
        # 创建遮蔽部分
        masked_length = end_pos - start_pos
        masked_part = mask_char * masked_length
        
        # 组合结果
        return text[:start_pos] + masked_part + text[end_pos:]
    
    @staticmethod
    def mask_email(email: Optional[str], mask_user: bool = True, mask_domain: bool = False) -> str:
        """
        遮蔽邮箱地址
        
        Args:
            email: 邮箱地址
            mask_user: 是否遮蔽用户名部分
            mask_domain: 是否遮蔽域名部分
            
        Returns:
            str: 遮蔽后的邮箱地址
        """
        if email is None or not StringUtils.is_valid_email(str(email)):
            return str(email or "")
        
        email = str(email)
        username, domain = email.split('@', 1)
        
        # 处理用户名部分
        if mask_user:
            if len(username) <= 3:
                masked_username = username[0] + '*' * (len(username) - 1)
            else:
                # 保留前1位和后1位
                masked_username = username[0] + '*' * (len(username) - 2) + username[-1]
        else:
            masked_username = username
        
        # 处理域名部分
        if mask_domain:
            if '.' in domain:
                parts = domain.split('.')
                if len(parts[0]) <= 2:
                    masked_domain = '*' * len(parts[0]) + '.' + '.'.join(parts[1:])
                else:
                    # 保留前1位和后1位
                    masked_domain = parts[0][0] + '*' * (len(parts[0]) - 2) + parts[0][-1] + '.' + '.'.join(parts[1:])
            else:
                masked_domain = '*' * len(domain)
        else:
            masked_domain = domain
        
        return f"{masked_username}@{masked_domain}"
    
    @staticmethod
    def mask_phone_cn(phone: Optional[str]) -> str:
        """
        遮蔽中国大陆手机号（遮蔽中间4位）
        
        Args:
            phone: 手机号码
            
        Returns:
            str: 遮蔽后的手机号
        """
        if phone is None or not StringUtils.is_valid_phone_cn(str(phone)):
            return str(phone or "")
        
        phone = str(phone)
        # 保留前3位和后4位
        return f"{phone[:3]}****{phone[-4:]}"
    
    @staticmethod
    def normalize_whitespace(text: Optional[str]) -> str:
        """
        标准化空白字符（将多个连续空白替换为单个空格）
        
        Args:
            text: 输入字符串
            
        Returns:
            str: 处理后的字符串
        """
        if text is None:
            return ""
        return re.sub(r'\s+', ' ', str(text)).strip()
    
    @staticmethod
    def remove_punctuation(text: Optional[str], keep: Optional[str] = None) -> str:
        """
        移除标点符号
        
        Args:
            text: 输入字符串
            keep: 要保留的标点符号
            
        Returns:
            str: 处理后的字符串
        """
        if text is None:
            return ""
        
        text = str(text)
        if keep:
            # 创建保留标点符号的转换表
            punct_to_remove = ''.join(p for p in string.punctuation if p not in keep)
            translator = str.maketrans('', '', punct_to_remove)
        else:
            # 移除所有标点符号
            translator = str.maketrans('', '', string.punctuation)
        
        return text.translate(translator)
    
    @staticmethod
    def to_ascii(text: Optional[str], replace_char: str = '?') -> str:
        """
        将非ASCII字符转换为ASCII（或替换）
        
        Args:
            text: 输入字符串
            replace_char: 替换字符
            
        Returns:
            str: 处理后的字符串
        """
        if text is None:
            return ""
        
        # 先尝试将可分解的Unicode字符标准化为ASCII
        normalized = unicodedata.normalize('NFKD', str(text))
        ascii_text = normalized.encode('ascii', 'ignore').decode('ascii')
        
        # 如果需要替换非ASCII字符而不是忽略
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
        计算单词数量
        
        Args:
            text: 输入字符串
            
        Returns:
            int: 单词数量
        """
        if text is None or not str(text).strip():
            return 0
        
        # 使用正则表达式匹配单词
        words = re.findall(r'\b\w+\b', str(text))
        return len(words)
    
    @staticmethod
    def safe_filename(text: Optional[str], max_length: int = 200, replace_char: str = '_') -> str:
        """
        将字符串转换为安全的文件名
        
        Args:
            text: 输入字符串
            max_length: 最大长度
            replace_char: 替换字符
            
        Returns:
            str: 安全的文件名
        """
        if text is None:
            return ""
        
        # 移除或替换不安全字符
        # Windows文件名不能包含: < > : " / \ | ? *
        unsafe_chars = '<>:"/\\|?*' + ''.join(chr(c) for c in range(32))  # 加上控制字符
        
        # 创建替换表
        translator = str.maketrans(unsafe_chars, replace_char * len(unsafe_chars))
        safe = str(text).translate(translator)
        
        # 移除多余的替换字符
        safe = re.sub(rf'{re.escape(replace_char)}+', replace_char, safe).strip(replace_char)
        
        # 截断到最大长度
        return StringUtils.truncate(safe, max_length, "")
    
    @staticmethod
    def format_template(template: Optional[str], **kwargs) -> str:
        """
        格式化模板字符串
        
        Args:
            template: 模板字符串，使用{key}占位符
            **kwargs: 替换的键值对
            
        Returns:
            str: 格式化后的字符串
        """
        if template is None:
            return ""
        
        try:
            return str(template).format(**kwargs)
        except (KeyError, IndexError):
            # 如果替换失败，返回原始模板
            return str(template)


# 示例用法
if __name__ == "__main__":
    # 基本操作
    text = "  Hello World  "
    print(f"原始文本: '{text}'")
    print(f"去除空白: '{StringUtils.trim(text)}'")
    print(f"是否为空: {StringUtils.is_empty(text)}")
    
    # 字符串格式化
    long_text = "这是一个非常长的文本，需要被截断以适应显示需求"
    truncated = StringUtils.truncate(long_text, 20)
    print(f"截断文本: '{truncated}'")
    
    # 命名格式转换
    camel_text = "camelCaseExample"
    print(f"驼峰转蛇形: '{StringUtils.snake_case(camel_text)}'")
    
    snake_text = "snake_case_example"
    print(f"蛇形转驼峰: '{StringUtils.camel_case(snake_text)}'")
    print(f"蛇形转帕斯卡: '{StringUtils.pascal_case(snake_text)}'")
    
    # 验证功能
    email = "test@example.com"
    invalid_email = "not-an-email"
    print(f"邮箱验证 '{email}': {StringUtils.is_valid_email(email)}")
    print(f"邮箱验证 '{invalid_email}': {StringUtils.is_valid_email(invalid_email)}")
    
    phone = "13812345678"
    print(f"手机号验证 '{phone}': {StringUtils.is_valid_phone_cn(phone)}")
    
    # 敏感信息遮蔽
    masked_email = StringUtils.mask_email("zhang.san@example.com")
    print(f"遮蔽邮箱: '{masked_email}'")
    
    masked_phone = StringUtils.mask_phone_cn("13812345678")
    print(f"遮蔽手机号: '{masked_phone}'")
    
    # 其他功能
    text_with_punct = "Hello, World! How are you?"
    print(f"移除标点: '{StringUtils.remove_punctuation(text_with_punct)}'")
    print(f"移除标点(保留!): '{StringUtils.remove_punctuation(text_with_punct, keep='!')}'")
    
    # 模板格式化
    template = "欢迎 {name}，您的订单编号是 {order_id}"
    formatted = StringUtils.format_template(template, name="张三", order_id="ORD-2024-12345")
    print(f"模板格式化: '{formatted}'")