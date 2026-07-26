"""
Logging configuration for the backtest system.
"""

import logging
import sys
from pathlib import Path
from datetime import datetime


def setup_logging(
    log_level: str = 'INFO',
    log_file: str = None,
    log_dir: str = 'logs'
):
    """
    Set up logging configuration for the application.
    
    Parameters:
    -----------
    log_level : str
        Logging level ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
    log_file : str, optional
        Log file name. If None, uses timestamp-based name
    log_dir : str
        Directory for log files
    """
    # Create logs directory if it doesn't exist
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)
    
    # Generate log file name if not provided
    if log_file is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = f'backtest_{timestamp}.log'
    
    log_filepath = log_path / log_file
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filepath, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set specific loggers
    logging.getLogger('matplotlib').setLevel(logging.WARNING)
    logging.getLogger('PIL').setLevel(logging.WARNING)
    
    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized. Log file: {log_filepath}")
    
    return logger


class ContextFilter(logging.Filter):
    """Custom filter to add context to log records."""
    
    def __init__(self, context_dict: dict = None):
        super().__init__()
        self.context = context_dict or {}
    
    def filter(self, record):
        for key, value in self.context.items():
            setattr(record, key, value)
        return True


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the specified name.
    
    Parameters:
    -----------
    name : str
        Logger name (usually __name__)
        
    Returns:
    --------
    Logger
        Configured logger instance
    """
    return logging.getLogger(name)

