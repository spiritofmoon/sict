# setup.py
import sys
from setuptools import setup, Extension
import pybind11

# 检查操作系统，此模块仅适用于Windows
if sys.platform != "win32":
    raise RuntimeError("This module is only supported on Windows.")

# 定义C++扩展模块
ext_modules = [
    Extension(
        # 模块名，必须与PYBIND11_MODULE的第一个参数一致
        'input_module_all_inf',
        # 源文件列表
        ['input_module_all_inf.cpp'],
        # 包含目录
        include_dirs=[
            pybind11.get_include(),
        ],
        # 语言
        language='c++',
        # MSVC编译器的额外参数
        extra_compile_args=['/std:c++17', '/EHsc'],
        # 需要链接的Windows库 (setuptools通常会自动处理，但显式指定更可靠)
        libraries=['user32'],
    ),
]

setup(
    name='input_module_all_inf',
    version='1.0',
    author='Your Name',
    description='A high-performance keyboard and mouse listener',
    ext_modules=ext_modules,
)