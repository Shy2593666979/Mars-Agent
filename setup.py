#!/usr/bin/env python3
"""
Mars Agent Setup Script
-----------------------
备用安装脚本，兼容旧版本的pip和构建工具
"""

from setuptools import setup, find_packages
import os


def read_file(filename):
    """读取文件内容"""
    with open(os.path.join(os.path.dirname(__file__), filename), encoding='utf-8') as f:
        return f.read()


def read_requirements():
    """读取依赖列表"""
    # 直接使用硬编码的依赖列表，避免编码问题
    requirements = [
        "mcp>=1.6.0",
        "openai>=1.12.0", 
        "langgraph>=0.3.0",
    ]
    return requirements


setup(
    name="mars-agent",
    version="0.1.0",
    author="MingGuang Tian",
    author_email="2593666979@qq.com",
    description="Mars Agent - 基于主副代理架构的AI代理系统，支持MCP协议和流式处理",
    long_description=read_file("README.md"),
    long_description_content_type="text/markdown",
    url="https://github.com/Shy2593666979/Mars-Agent",
    project_urls={
        "Homepage": "https://github.com/Shy2593666979/Mars-Agent",
        "Bug Tracker": "https://github.com/Shy2593666979/Mars-Agent/issues",
        "Repository": "https://github.com/Shy2593666979/Mars-Agent",
    },
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
    python_requires=">=3.11",
    install_requires=read_requirements(),
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-asyncio>=0.21.0",
            "black>=23.0",
            "flake8>=6.0",
            "mypy>=1.0",
        ],
    },
    keywords="ai agent mcp streaming llm chatbot",
    include_package_data=True,
    zip_safe=False,
) 
