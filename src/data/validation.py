import pandas as pd
from loguru import logger
from typing import List

def validate(df: pd.DataFrame, feature_cols: List[str]) -> bool:
    """Validate that the dataframe has the required columns and is not empty."""
    if df.empty:
        logger.error("Validation failed: DataFrame is empty.")
        return False
        
    missing_cols = [col for col in feature_cols if col not in df.columns]
    if missing_cols:
        logger.error(f"Validation failed: Missing columns: {missing_cols}")
        return False
        
    logger.info("Data validation passed.")
    return True