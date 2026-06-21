import os
from pydantic import BaseModel, Field

class WireConfig(BaseModel):
    output_dir: str = Field(default="output")
    timeout_ms: int = Field(default=30000)
    user_agent: str = Field(default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
    headless: bool = Field(default=True)
    
_config = None

def get_config() -> WireConfig:
    global _config
    if _config is None:
        _config = WireConfig()
    return _config
