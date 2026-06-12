"""数据根目录解析 —— 全项目唯一实现。

之前 main.py / storage.py / customization.py 各写了一份"读 FRESH_APP_ROOT
环境变量，否则取 exe/脚本目录下 FRESH_Data"的逻辑，三处靠 main 写
os.environ 隐式同步，导入顺序一变就会解析出不同的根目录。
"""
import os
import sys
from pathlib import Path

DATA_ROOT_ENV = 'FRESH_APP_ROOT'


def portable_data_root() -> Path:
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parent
    return base_dir / 'FRESH_Data'


def resolve_data_root() -> Path:
    configured = os.getenv(DATA_ROOT_ENV)
    if configured:
        return Path(configured)
    return portable_data_root()


def set_data_root(root) -> None:
    """显式设定当前数据根（其余模块经 resolve_data_root 读取）。"""
    os.environ[DATA_ROOT_ENV] = str(root)
