"""
配置管理工具模块

提供配置文件加载、解析和访问功能
"""

import os
import json
import configparser
from typing import Any, Dict, Optional, Union, List, Tuple
import logging

# 尝试导入yaml模块，添加错误处理
try:
    import yaml
    yaml_available = True
except ImportError:
    yaml_available = False
    # logging.warning("PyYAML模块未找到，将不支持YAML配置文件格式")

# 定义支持的配置文件类型
SUPPORTED_FORMATS_BASE = {
    '.json': 'json',
    '.ini': 'ini',
    '.conf': 'ini'
}

# 如果yaml可用，添加yaml支持
if yaml_available:
    SUPPORTED_FORMATS_BASE.update({
        '.yaml': 'yaml',
        '.yml': 'yaml'
    })


class ConfigUtils:
    """
    配置管理工具类
    """
    
    # 支持的配置文件类型（根据yaml可用性动态设置）
    SUPPORTED_FORMATS = SUPPORTED_FORMATS_BASE.copy()
    
    @staticmethod
    def load_config(config_path: str) -> Optional[Dict[str, Any]]:
        """
        加载配置文件
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            dict: 配置数据，如果加载失败返回None
        """
        # 检查文件是否存在
        if not os.path.exists(config_path):
            logging.error(f"配置文件不存在: {config_path}")
            return None
        
        # 获取文件扩展名
        _, ext = os.path.splitext(config_path)
        ext = ext.lower()
        
        # 检查是否支持的文件类型
        if ext not in ConfigUtils.SUPPORTED_FORMATS:
            logging.error(f"不支持的配置文件格式: {ext}")
            return None
        
        config_format = ConfigUtils.SUPPORTED_FORMATS[ext]
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                if config_format == 'json':
                    return json.load(f)
                elif config_format == 'yaml' and yaml_available:
                    return yaml.safe_load(f)
                elif config_format == 'yaml' and not yaml_available:
                    logging.error("YAML配置文件格式不被支持，因为PyYAML模块未安装")
                    return None
                elif config_format == 'ini':
                    config = configparser.ConfigParser()
                    config.read_file(f)
                    # 转换为字典
                    return ConfigUtils._ini_to_dict(config)
                
        except json.JSONDecodeError as e:
            logging.error(f"JSON配置解析错误: {e}")
        except Exception as e:
            if yaml_available and isinstance(e, yaml.YAMLError):
                logging.error(f"YAML配置解析错误: {e}")
        except configparser.Error as e:
            logging.error(f"INI配置解析错误: {e}")
        except Exception as e:
            logging.error(f"配置文件加载失败: {e}")
        
        return None
    
    @staticmethod
    def _ini_to_dict(config: configparser.ConfigParser) -> Dict[str, Any]:
        """
        将ConfigParser对象转换为字典
        
        Args:
            config: ConfigParser对象
            
        Returns:
            dict: 转换后的字典
        """
        result = {}
        
        # 转换sections
        for section in config.sections():
            section_dict = {}
            
            # 转换section中的选项
            for key, value in config[section].items():
                # 尝试转换值的类型
                converted_value = ConfigUtils._convert_value(value)
                section_dict[key] = converted_value
            
            result[section] = section_dict
        
        # 转换默认section
        if config.defaults():
            default_dict = {}
            for key, value in config.defaults().items():
                default_dict[key] = ConfigUtils._convert_value(value)
            result['DEFAULT'] = default_dict
        
        return result
    
    @staticmethod
    def _convert_value(value: str) -> Any:
        """
        尝试将字符串值转换为适当的类型
        
        Args:
            value: 字符串值
            
        Returns:
            转换后的值
        """
        # 尝试转换为布尔值
        if value.lower() in ('true', 'yes', '1'):
            return True
        if value.lower() in ('false', 'no', '0'):
            return False
        
        # 尝试转换为整数
        try:
            return int(value)
        except ValueError:
            pass
        
        # 尝试转换为浮点数
        try:
            return float(value)
        except ValueError:
            pass
        
        # 尝试转换为空值
        if value.lower() in ('none', 'null', ''):
            return None
        
        # 尝试转换为列表（简单的逗号分隔格式）
        if ',' in value:
            items = [item.strip() for item in value.split(',')]
            # 检查是否所有项都能转换为数字
            all_numeric = True
            numeric_items = []
            for item in items:
                try:
                    if '.' in item:
                        numeric_items.append(float(item))
                    else:
                        numeric_items.append(int(item))
                except ValueError:
                    all_numeric = False
                    break
            
            if all_numeric:
                return numeric_items
            return items
        
        # 返回原始字符串
        return value
    
    @staticmethod
    def save_config(config_data: Dict[str, Any], 
                   config_path: str,
                   format_type: Optional[str] = None) -> bool:
        """
        保存配置到文件
        
        Args:
            config_data: 配置数据
            config_path: 配置文件路径
            format_type: 文件格式类型，如果为None则根据扩展名判断
            
        Returns:
            bool: 是否保存成功
        """
        # 确定文件格式
        if format_type is None:
            _, ext = os.path.splitext(config_path)
            ext = ext.lower()
            if ext in ConfigUtils.SUPPORTED_FORMATS:
                format_type = ConfigUtils.SUPPORTED_FORMATS[ext]
            else:
                # 默认使用JSON格式
                format_type = 'json'
        else:
            format_type = format_type.lower()
        
        # 确保目录存在
        os.makedirs(os.path.dirname(os.path.abspath(config_path)), exist_ok=True)
        
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                if format_type == 'json':
                    json.dump(config_data, f, ensure_ascii=False, indent=2)
                elif format_type == 'yaml' and yaml_available:
                    yaml.dump(config_data, f, allow_unicode=True, default_flow_style=False)
                elif format_type == 'yaml' and not yaml_available:
                    logging.error("YAML配置文件格式不被支持，因为PyYAML模块未安装")
                    return False
                elif format_type == 'ini':
                    config = configparser.ConfigParser()
                    # 将字典转换为ConfigParser格式
                    for section, values in config_data.items():
                        if isinstance(values, dict):
                            config[section] = values
                        else:
                            # 处理非字典值
                            config[section] = {'value': values}
                    config.write(f)
                else:
                    logging.error(f"不支持的配置文件格式: {format_type}")
                    return False
            
            return True
            
        except Exception as e:
            logging.error(f"配置保存失败: {e}")
            return False
    
    @staticmethod
    def get_config_value(config: Dict[str, Any], 
                        key_path: Union[str, List[str]], 
                        default: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            config: 配置字典
            key_path: 键路径，支持点分隔字符串或列表
            default: 默认值
            
        Returns:
            配置值或默认值
        """
        # 将键路径转换为列表
        if isinstance(key_path, str):
            keys = key_path.split('.')
        else:
            keys = list(key_path)
        
        # 遍历键路径获取值
        current = config
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        
        return current
    
    @staticmethod
    def set_config_value(config: Dict[str, Any], 
                        key_path: Union[str, List[str]], 
                        value: Any) -> Dict[str, Any]:
        """
        设置配置值
        
        Args:
            config: 配置字典
            key_path: 键路径，支持点分隔字符串或列表
            value: 要设置的值
            
        Returns:
            dict: 更新后的配置字典
        """
        # 将键路径转换为列表
        if isinstance(key_path, str):
            keys = key_path.split('.')
        else:
            keys = list(key_path)
        
        # 创建或更新配置
        current = config
        for i, key in enumerate(keys[:-1]):
            if key not in current or not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]
        
        # 设置最终值
        current[keys[-1]] = value
        
        return config
    
    @staticmethod
    def merge_configs(base_config: Dict[str, Any], 
                     override_config: Dict[str, Any],
                     deep: bool = True) -> Dict[str, Any]:
        """
        合并配置
        
        Args:
            base_config: 基础配置
            override_config: 覆盖配置
            deep: 是否深度合并
            
        Returns:
            dict: 合并后的配置
        """
        # 复制基础配置
        merged = base_config.copy()
        
        if not deep:
            # 浅合并
            merged.update(override_config)
            return merged
        
        # 深度合并
        for key, value in override_config.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                # 递归合并字典
                merged[key] = ConfigUtils.merge_configs(merged[key], value, deep=True)
            else:
                # 直接替换
                merged[key] = value
        
        return merged
    
    @staticmethod
    def get_env(key: str, 
               default: Any = None, 
               convert_type: bool = True) -> Any:
        """
        获取环境变量
        
        Args:
            key: 环境变量名
            default: 默认值
            convert_type: 是否自动转换类型
            
        Returns:
            环境变量值或默认值
        """
        value = os.environ.get(key)
        if value is None:
            return default
        
        if convert_type:
            return ConfigUtils._convert_value(value)
        
        return value
    
    @staticmethod
    def validate_config(config: Dict[str, Any], 
                       required_keys: List[Union[str, List[str]]]) -> Tuple[bool, List[str]]:
        """
        验证配置是否包含必需的键
        
        Args:
            config: 配置字典
            required_keys: 必需的键列表，支持点分隔字符串或列表
            
        Returns:
            tuple: (是否有效, 缺失的键列表)
        """
        missing_keys = []
        
        for key_path in required_keys:
            # 尝试获取键值
            value = ConfigUtils.get_config_value(config, key_path, default=ConfigUtils)
            # 使用一个特殊值作为标记
            if value is ConfigUtils:
                if isinstance(key_path, list):
                    missing_keys.append('.'.join(key_path))
                else:
                    missing_keys.append(key_path)
        
        return len(missing_keys) == 0, missing_keys
    
    @staticmethod
    def load_config_from_directory(directory: str,
                                 recursive: bool = False,
                                 formats: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        """
        从目录加载所有配置文件
        
        Args:
            directory: 目录路径
            recursive: 是否递归加载
            formats: 要加载的文件格式列表
            
        Returns:
            dict: 配置文件路径 -> 配置数据的映射
        """
        configs = {}
        
        # 如果指定了格式，只处理这些格式
        if formats:
            valid_exts = [ext for ext, fmt in ConfigUtils.SUPPORTED_FORMATS.items() if fmt in formats]
        else:
            valid_exts = list(ConfigUtils.SUPPORTED_FORMATS.keys())
        
        if recursive:
            # 递归遍历目录
            for root, _, files in os.walk(directory):
                for file in files:
                    _, ext = os.path.splitext(file)
                    if ext in valid_exts:
                        file_path = os.path.join(root, file)
                        config_data = ConfigUtils.load_config(file_path)
                        if config_data is not None:
                            configs[file_path] = config_data
        else:
            # 只遍历当前目录
            if not os.path.exists(directory):
                logging.error(f"目录不存在: {directory}")
                return configs
            
            for file in os.listdir(directory):
                file_path = os.path.join(directory, file)
                if os.path.isfile(file_path):
                    _, ext = os.path.splitext(file)
                    if ext in valid_exts:
                        config_data = ConfigUtils.load_config(file_path)
                        if config_data is not None:
                            configs[file_path] = config_data
        
        return configs
    
    @staticmethod
    def create_default_config(config_path: str, 
                            default_config: Dict[str, Any],
                            overwrite: bool = False) -> bool:
        """
        创建默认配置文件
        
        Args:
            config_path: 配置文件路径
            default_config: 默认配置数据
            overwrite: 是否覆盖已存在的文件
            
        Returns:
            bool: 是否创建成功
        """
        # 检查文件是否已存在
        if os.path.exists(config_path) and not overwrite:
            logging.info(f"配置文件已存在，跳过创建: {config_path}")
            return False
        
        return ConfigUtils.save_config(default_config, config_path)


# 示例用法
if __name__ == "__main__":
    # 设置日志级别
    logging.basicConfig(level=logging.INFO)
    
    # 创建示例配置数据
    sample_config = {
        'app': {
            'name': 'SupplyChainSystem',
            'version': '1.0.0',
            'debug': True
        },
        'database': {
            'host': 'localhost',
            'port': 5432,
            'username': 'admin',
            'password': '********',
            'database': 'supply_chain'
        },
        'api': {
            'timeout': 30,
            'retry_count': 3,
            'allowed_origins': ['http://localhost:3000', 'http://localhost:8080']
        }
    }
    
    # 保存配置到JSON文件
    json_path = 'config.json'
    save_result = ConfigUtils.save_config(sample_config, json_path)
    print(f"保存JSON配置: {'成功' if save_result else '失败'}")
    
    # 加载配置文件
    loaded_config = ConfigUtils.load_config(json_path)
    if loaded_config:
        print("加载的配置:")
        print(json.dumps(loaded_config, ensure_ascii=False, indent=2))
    
    # 获取配置值
    app_name = ConfigUtils.get_config_value(loaded_config, 'app.name', 'DefaultApp')
    debug_mode = ConfigUtils.get_config_value(loaded_config, 'app.debug', False)
    db_host = ConfigUtils.get_config_value(loaded_config, 'database.host')
    
    print(f"应用名称: {app_name}")
    print(f"调试模式: {debug_mode}")
    print(f"数据库主机: {db_host}")
    
    # 设置配置值
    updated_config = ConfigUtils.set_config_value(loaded_config, 'api.timeout', 60)
    updated_config = ConfigUtils.set_config_value(updated_config, ['api', 'max_connections'], 100)
    
    print("更新后的配置值:")
    print(f"API超时: {ConfigUtils.get_config_value(updated_config, 'api.timeout')}")
    print(f"最大连接数: {ConfigUtils.get_config_value(updated_config, 'api.max_connections')}")
    
    # 合并配置
    override_config = {
        'app': {
            'debug': False
        },
        'database': {
            'port': 3306
        },
        'security': {
            'enabled': True
        }
    }
    
    merged_config = ConfigUtils.merge_configs(sample_config, override_config)
    print("合并后的配置:")
    print(json.dumps(merged_config, ensure_ascii=False, indent=2))
    
    # 验证配置
    required_keys = ['app.name', 'database.host', 'database.port']
    is_valid, missing = ConfigUtils.validate_config(sample_config, required_keys)
    
    print(f"配置验证: {'有效' if is_valid else '无效'}")
    if not is_valid:
        print(f"缺失的键: {missing}")
    
    # 清理测试文件
    if os.path.exists(json_path):
        os.remove(json_path)
        print(f"清理测试文件: {json_path}")