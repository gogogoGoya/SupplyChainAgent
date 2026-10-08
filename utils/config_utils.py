"""
Configure Management Tool Module

Provides configuration file loading, resolution and access
"""

import os
import json
import configparser
from typing import Any, Dict, Optional, Union, List, Tuple
import logging

# Try importing the Yaml module and adding error processing
try:
    import yaml
    yaml_available = True
except ImportError:
    yaml_available = False
    # logging.warning ("PyYAML module not found, YAML profile format not supported")

# Define the profile type supported
SUPPORTED_FORMATS_BASE = {
    '.json': 'json',
    '.ini': 'ini',
    '.conf': 'ini'
}

# Add yaml support if yaml is available
if yaml_available:
    SUPPORTED_FORMATS_BASE.update({
        '.yaml': 'yaml',
        '.yml': 'yaml'
    })


class ConfigUtils:
    """
    Configure Management Tool Class
        """
    
    # Supported profile type (based on Yaml availability dynamics)
    SUPPORTED_FORMATS = SUPPORTED_FORMATS_BASE.copy()
    
    @staticmethod
    def load_config(config_path: str) -> Optional[Dict[str, Any]]:
        """
        Load profile
                
        Args:
            parameter: Profile path
                        
        Returns:
            dict: Configure data, return None if loading failed
                """
        # Check if the file exists
        if not os.path.exists(config_path):
            logging.error(f"Configuration file does not exist: {config_path}")
            return None
        
        # Fetch File Extension
        _, ext = os.path.splitext(config_path)
        ext = ext.lower()
        
        # Check for supported file type
        if ext not in ConfigUtils.SUPPORTED_FORMATS:
            logging.error(f"Unsupported configuration format: {ext}")
            return None
        
        config_format = ConfigUtils.SUPPORTED_FORMATS[ext]
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                if config_format == 'json':
                    return json.load(f)
                elif config_format == 'yaml' and yaml_available:
                    return yaml.safe_load(f)
                elif config_format == 'yaml' and not yaml_available:
                    logging.error("YAML is unavailable because PyYAML is not installed")
                    return None
                elif config_format == 'ini':
                    config = configparser.ConfigParser()
                    config.read_file(f)
                    # Convert to Dictionary
                    return ConfigUtils._ini_to_dict(config)
                
        except json.JSONDecodeError as e:
            logging.error(f"JSON configuration parse error: {e}")
        except Exception as e:
            if yaml_available and isinstance(e, yaml.YAMLError):
                logging.error(f"YAML configuration parse error: {e}")
        except configparser.Error as e:
            logging.error(f"INI configuration parse error: {e}")
        except Exception as e:
            logging.error(f"Failed to load configuration: {e}")
        
        return None
    
    @staticmethod
    def _ini_to_dict(config: configparser.ConfigParser) -> Dict[str, Any]:
        """
        Convert ConfigParser object to dictionary
                
        Args:
            Config: ConfigParser Object
                        
        Returns:
            dict: Converted Dictionary
                """
        result = {}
        
        # Convert sections
        for section in config.sections():
            section_dict = {}
            
            # Convert Options in Section
            for key, value in config[section].items():
                # Type of tried conversion value
                converted_value = ConfigUtils._convert_value(value)
                section_dict[key] = converted_value
            
            result[section] = section_dict
        
        # Convert Default Section
        if config.defaults():
            default_dict = {}
            for key, value in config.defaults().items():
                default_dict[key] = ConfigUtils._convert_value(value)
            result['DEFAULT'] = default_dict
        
        return result
    
    @staticmethod
    def _convert_value(value: str) -> Any:
        """
        Try converting string values to the appropriate type
                
        Args:
            value: string value
                        
        Returns:
            Value after conversion
                """
        # Try to convert to a boolean
        if value.lower() in ('true', 'yes', '1'):
            return True
        if value.lower() in ('false', 'no', '0'):
            return False
        
        # Try to convert to integer
        try:
            return int(value)
        except ValueError:
            pass
        
        # Try to convert to floating point number
        try:
            return float(value)
        except ValueError:
            pass
        
        # Try to convert to empty
        if value.lower() in ('none', 'null', ''):
            return None
        
        # Try to convert to a list (simply comma-separated format)
        if ',' in value:
            items = [item.strip() for item in value.split(',')]
            # Check if all items can be converted to numbers
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
        
        # Return original string
        return value
    
    @staticmethod
    def save_config(config_data: Dict[str, Any], 
                   config_path: str,
                   format_type: Optional[str] = None) -> bool:
        """
        Save Configuration to File
                
        Args:
            parameter: Configure data
            parameter: Profile path
            format_type: File format type, if None based on extension
                        
        Returns:
            Bool: Save successfully
                """
        # Determine File Format
        if format_type is None:
            _, ext = os.path.splitext(config_path)
            ext = ext.lower()
            if ext in ConfigUtils.SUPPORTED_FORMATS:
                format_type = ConfigUtils.SUPPORTED_FORMATS[ext]
            else:
                # Default JSON format
                format_type = 'json'
        else:
            format_type = format_type.lower()
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(os.path.abspath(config_path)), exist_ok=True)
        
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                if format_type == 'json':
                    json.dump(config_data, f, ensure_ascii=False, indent=2)
                elif format_type == 'yaml' and yaml_available:
                    yaml.dump(config_data, f, allow_unicode=True, default_flow_style=False)
                elif format_type == 'yaml' and not yaml_available:
                    logging.error("YAML is unavailable because PyYAML is not installed")
                    return False
                elif format_type == 'ini':
                    config = configparser.ConfigParser()
                    # Convert the dictionary to ConfigParser
                    for section, values in config_data.items():
                        if isinstance(values, dict):
                            config[section] = values
                        else:
                            # Process non-dictionaries values
                            config[section] = {'value': values}
                    config.write(f)
                else:
                    logging.error(f"Unsupported configuration format: {format_type}")
                    return False
            
            return True
            
        except Exception as e:
            logging.error(f"Failed to save configuration: {e}")
            return False
    
    @staticmethod
    def get_config_value(config: Dict[str, Any], 
                        key_path: Union[str, List[str]], 
                        default: Any = None) -> Any:
        """
        Fetch Configuration Value
                
        Args:
            config: Configure Dictionary
            parameter: Key path, support point-separated string or list
            default: default
                        
        Returns:
            Configure values or defaults
                """
        # Convert key path to list
        if isinstance(key_path, str):
            keys = key_path.split('.')
        else:
            keys = list(key_path)
        
        # Cross-key Path Fetch Value
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
        Set Configuration Values
                
        Args:
            config: Configure Dictionary
            parameter: Key path, support point-separated string or list
            value: value to set
                        
        Returns:
            dict: updated configuration dictionary
                """
        # Convert key path to list
        if isinstance(key_path, str):
            keys = key_path.split('.')
        else:
            keys = list(key_path)
        
        # Create or update configuration
        current = config
        for i, key in enumerate(keys[:-1]):
            if key not in current or not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]
        
        # Set final value
        current[keys[-1]] = value
        
        return config
    
    @staticmethod
    def merge_configs(base_config: Dict[str, Any], 
                     override_config: Dict[str, Any],
                     deep: bool = True) -> Dict[str, Any]:
        """
        Merge Configuration
                
        Args:
            parameter: Basic configuration
            parameter: Overwrite Configuration
            Deep Merge
                        
        Returns:
            dict: Merged Configuration
                """
        # Copy Basic Configuration
        merged = base_config.copy()
        
        if not deep:
            # Light Merge
            merged.update(override_config)
            return merged
        
        # Depth Merge
        for key, value in override_config.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                # Recursive Merge Dictionary
                merged[key] = ConfigUtils.merge_configs(merged[key], value, deep=True)
            else:
                # Direct Replace
                merged[key] = value
        
        return merged
    
    @staticmethod
    def get_env(key: str, 
               default: Any = None, 
               convert_type: bool = True) -> Any:
        """
        Get Environmental Variables
                
        Args:
            key: Environment variable name.
            default: default
            convert_type: Whether to infer and convert the value type.
                        
        Returns:
            Environment variable or default
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
        Verify if the configuration contains the required key
                
        Args:
            config: Configure Dictionary
            required_keys: List of required keys, support point separators or lists
                        
        Returns:
            tuple: (valid, missing list)
                """
        missing_keys = []
        
        for key_path in required_keys:
            # Try to fetch key values
            value = ConfigUtils.get_config_value(config, key_path, default=ConfigUtils)
            # Use a special value as a tag
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
        Load all profiles from directory
                
        Args:
            Directory path
            recursive: Whether to reload
            List of files format to load
                        
        Returns:
            dict: Profile Path - > Configure Data Map
                """
        configs = {}
        
        # If format is specified, only these formats are processed
        if formats:
            valid_exts = [ext for ext, fmt in ConfigUtils.SUPPORTED_FORMATS.items() if fmt in formats]
        else:
            valid_exts = list(ConfigUtils.SUPPORTED_FORMATS.keys())
        
        if recursive:
            # Recursive history directory
            for root, _, files in os.walk(directory):
                for file in files:
                    _, ext = os.path.splitext(file)
                    if ext in valid_exts:
                        file_path = os.path.join(root, file)
                        config_data = ConfigUtils.load_config(file_path)
                        if config_data is not None:
                            configs[file_path] = config_data
        else:
            # Only go through the current directory
            if not os.path.exists(directory):
                logging.error(f"Directory does not exist: {directory}")
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
        Create Default Profile
                
        Args:
            parameter: Profile path
            parameter: Default Configuration Data
            Overwrite: Overwrite Existing Files
                        
        Returns:
            Bool: Created successfully
                """
        # Check that the file exists
        if os.path.exists(config_path) and not overwrite:
            logging.info(f"Configuration file already exists; skipping creation: {config_path}")
            return False
        
        return ConfigUtils.save_config(default_config, config_path)


# Example Usage
if __name__ == "__main__":
    # Set Log Level
    logging.basicConfig(level=logging.INFO)
    
    # Create example profile data
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
    
    # Save Configuration to JSON File
    json_path = 'config.json'
    save_result = ConfigUtils.save_config(sample_config, json_path)
    print(f"Save JSON configuration: {'success' if save_result else 'failed'}")
    
    # Load profile
    loaded_config = ConfigUtils.load_config(json_path)
    if loaded_config:
        print("Loaded configuration:")
        print(json.dumps(loaded_config, ensure_ascii=False, indent=2))
    
    # Fetch Configuration Value
    app_name = ConfigUtils.get_config_value(loaded_config, 'app.name', 'DefaultApp')
    debug_mode = ConfigUtils.get_config_value(loaded_config, 'app.debug', False)
    db_host = ConfigUtils.get_config_value(loaded_config, 'database.host')
    
    print(f"Application name: {app_name}")
    print(f"Debug mode: {debug_mode}")
    print(f"Database host: {db_host}")
    
    # Set Configuration Values
    updated_config = ConfigUtils.set_config_value(loaded_config, 'api.timeout', 60)
    updated_config = ConfigUtils.set_config_value(updated_config, ['api', 'max_connections'], 100)
    
    print("Updated configuration values:")
    print(f"API timeout: {ConfigUtils.get_config_value(updated_config, 'api.timeout')}")
    print(f"Maximum connections: {ConfigUtils.get_config_value(updated_config, 'api.max_connections')}")
    
    # Merge Configuration
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
    print("Merged configuration:")
    print(json.dumps(merged_config, ensure_ascii=False, indent=2))
    
    # Authentication Configuration
    required_keys = ['app.name', 'database.host', 'database.port']
    is_valid, missing = ConfigUtils.validate_config(sample_config, required_keys)
    
    print(f"Configuration validation: {'valid' if is_valid else 'invalid'}")
    if not is_valid:
        print(f"Missing keys: {missing}")
    
    # Clear Test File
    if os.path.exists(json_path):
        os.remove(json_path)
        print(f"Removed test file: {json_path}")
