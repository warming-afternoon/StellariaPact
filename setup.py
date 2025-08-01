# -*- coding: utf-8 -*-
import os
import subprocess
import sys
from typing import List, Union

# --- 配置 ---
VENV_DIR = ".venv"  # 虚拟环境目录名


# --- 辅助函数 ---
def print_step(message: str):
    """打印格式化的步骤信息。"""
    print(f"\n--- {message} ---")


def run_command(
    command: List[str], check: bool = True, capture_output: bool = False
) -> Union[subprocess.CompletedProcess, None]:
    """
    运行一个命令。
    - capture_output=False: 输出会直接流式传输到终端。
    - capture_output=True: 捕获输出，不显示。
    """
    print(f"执行: {' '.join(command)}")
    try:
        if capture_output:
            return subprocess.run(command, check=check, capture_output=True, encoding="utf-8")
        else:
            return subprocess.run(command, check=check)
    except subprocess.CalledProcessError as e:
        print(f"错误: 命令 '{' '.join(command)}' 执行失败，退出码 {e.returncode}")
        if capture_output and e.stdout:
            print(f"标准输出:\n{e.stdout}")
        if capture_output and e.stderr:
            print(f"标准错误:\n{e.stderr}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"错误: 命令未找到。请确认 '{command[0]}' 是否在您的系统 PATH 中。")
        sys.exit(1)
    return None


def ensure_uv_installed():
    """检查 uv 是否已安装，如果未安装则进行安装。"""
    try:
        run_command(["uv", "--version"], capture_output=True)
        print("uv 已安装。")
    except (FileNotFoundError, SystemExit):
        print_step("未找到 uv，现在通过 pip 进行安装...")
        run_command([sys.executable, "-m", "pip", "install", "uv"])


def create_virtual_environment():
    """如果虚拟环境不存在，则创建它。"""
    if not os.path.exists(VENV_DIR):
        print_step(f"正在创建虚拟环境: '{VENV_DIR}'...")
        # 始终使用全局 uv
        run_command(["uv", "venv", VENV_DIR])
    else:
        print("虚拟环境已存在。")


def install_dependencies(is_dev: bool = False):
    """使用 uv 安装项目依赖。"""
    # 关键修正：始终使用全局 uv，它会自动检测并作用于 .venv
    if is_dev:
        print_step("正在安装开发依赖...")
        run_command(["uv", "pip", "install", "-e", ".[dev]"])
    else:
        print_step("正在安装用户依赖...")
        run_command(["uv", "pip", "install", "."])


def setup_pre_commit():
    """安装 pre-commit 钩子。"""
    print_step("正在安装 pre-commit 钩子...")
    # pre-commit 必须在虚拟环境中运行，所以我们用 `uv run`
    run_command(["uv", "run", "--", "pre-commit", "install"])


def main():
    """主设置脚本。"""
    print("开始项目设置...")

    is_dev = "dev" in sys.argv

    ensure_uv_installed()
    create_virtual_environment()
    install_dependencies(is_dev)

    if is_dev:
        setup_pre_commit()

    print("\n-----------------------------------------")
    print("✅ 设置完成！")
    print("-----------------------------------------\n")
    print("环境已配置完毕。您无需手动激活虚拟环境。")
    print("\n要运行机器人，请使用以下命令:")
    print("uv run stellaria-pact\n")

    try:
        answer = input("是否立即启动机器人? (y/n): ").lower()
        if answer == "y":
            print_step("正在启动机器人... (按 Ctrl+C 停止)")
            run_command(["uv", "run", "stellaria-pact"], check=False)
    except (KeyboardInterrupt, EOFError):
        print("\n操作已取消。")


if __name__ == "__main__":
    main()
