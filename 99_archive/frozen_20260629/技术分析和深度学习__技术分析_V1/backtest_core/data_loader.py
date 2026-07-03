"""
数据加载和预处理模块
"""

import pandas as pd
import numpy as np
from typing import Union, Optional
import copy
import logging

logger = logging.getLogger(__name__)


class DataLoader:
    """Handles loading and preprocessing of screen and returns data."""
    
    def __init__(self):
        """Initialize the DataLoader."""
        self.screen: Optional[pd.DataFrame] = None
        self.returns: Optional[pd.DataFrame] = None
        
    def load_screen(self, source: Union[str, pd.DataFrame]) -> pd.DataFrame:
        """
        从pickle文件或DataFrame加载screen数据
        
        参数:
        -----------
        source : str or DataFrame
            路径 to pickle 文件 or DataFrame object
            
        收益率:
        --------
        DataFrame
            Loaded screen 数据
    """
        if isinstance(source, str):
            logger.info(f"Loading screen data from {source}")
            self.screen = pd.read_pickle(source)
        elif isinstance(source, pd.DataFrame):
            logger.info("Using provided screen DataFrame")
            self.screen = copy.deepcopy(source)
        else:
            raise TypeError("screen must be str (path) or DataFrame")
        
        logger.info(f"Screen data loaded: {self.screen.shape}")
        return self.screen
    
    def load_returns(self, source: Union[str, pd.DataFrame]) -> pd.DataFrame:
        """
        从pickle文件或DataFrame加载收益率数据
        
        参数:
        -----------
        source : str or DataFrame
            路径 to pickle 文件 or DataFrame object
            
        收益率:
        --------
        DataFrame
            Loaded 收益率 数据
        """
        if isinstance(source, str):
            logger.info(f"Loading returns data from {source}")
            self.returns = pd.read_pickle(source)
        elif isinstance(source, pd.DataFrame):
            logger.info("Using provided returns DataFrame")
            self.returns = copy.deepcopy(source)
        else:
            raise TypeError("returns must be str (path) or DataFrame")
        
        logger.info(f"Returns data loaded: {self.returns.shape}")
        return self.returns
    
    @staticmethod
    def validate_screen_data(screen: pd.DataFrame) -> bool:
        """
        验证screen数据结构
        
        参数:
        -----------
        screen : DataFrame
            Screen 数据 to 验证
            
        收益率:
        --------
        bool
            True if valid, raises error otherwise
        """
        required_cols = ['Date', 'ISIN']
        
        for col in required_cols:
            if col not in screen.columns and screen.index.name != col:
                raise ValueError(f"Required column '{col}' not found in screen data")
        
        return True
    
    @staticmethod
    def validate_returns_data(returns: pd.DataFrame) -> bool:
        """
        验证收益率数据结构
        
        参数:
        -----------
        收益率 : DataFrame
            收益率 数据 to 验证
            
        收益率:
        --------
        bool
            True if valid, raises error otherwise
        """
        if not isinstance(returns.index, pd.DatetimeIndex):
            raise ValueError("Returns index must be DatetimeIndex")
        
        return True
    
    def get_date_range(self) -> dict:
        """
        获取已加载数据的日期范围信息
        
        收益率:
        --------
        字典
            Dictionary with 日期 range info
        """
        info = {}
        
        if self.screen is not None:
            info['screen_start'] = self.screen['Date'].min()
            info['screen_end'] = self.screen['Date'].max()
            info['screen_periods'] = self.screen['Date'].nunique()
        
        if self.returns is not None:
            info['returns_start'] = self.returns.index.min()
            info['returns_end'] = self.returns.index.max()
            info['returns_days'] = len(self.returns)
        
        return info

