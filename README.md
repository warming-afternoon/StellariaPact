# StellariaPact

A Discord bot for StellariaPact.

## ⚡ 快速开始 (Quick Start)

**要求**: [Python 3.8+](https://www.python.org/downloads/)

1.  **下载项目代码**
    ```bash
    git clone https://github.com/your-username/StellariaPact.git
    cd StellariaPact
    ```

2.  **创建并配置 `config.json`**
    复制 `config.json.example` 并重命名为 `config.json`，然后填入你的 Discord Bot Token 等必要信息。

3.  **运行安装脚本**
    这将是您需要运行的**唯一**的安装命令。它会自动安装所有需要的工具和依赖。

    *   **作为普通用户**:
        ```bash
        python setup.py
        ```
    *   **作为开发者**:
        ```bash
        python setup.py dev
        ```
    脚本会自动处理好一切，并在结束后询问你是否立即启动机器人。

4.  **日常运行**
    安装完成后，你可以随时使用以下命令来启动机器人：
    ```bash
    uv run stellaria-pact
    ```

---

## 👨‍💻 开发指南 (For Developers)

`python setup.py dev` 命令会自动为你安装所有开发工具（如 `ruff`, `pre-commit`）并设置好 Git 钩子。

### 日常开发命令

所有命令都通过 `uv run` 执行，**无需手动激活虚拟环境**。

*   **运行机器人**:
    ```bash
    uv run stellaria-pact
    ```

*   **代码格式化**:
    ```bash
    uv run ruff format .
    ```

*   **代码检查**:
    ```bash
    uv run ruff check .
    ```

### 依赖管理

*   **添加新依赖**:
    1.  手动将包名添加到 `pyproject.toml` 的 `dependencies` 或 `dev` 列表中。
    2.  运行 `uv pip install -e .[dev]` 或 `uv pip install .` 来更新环境。

*   **更新锁文件**:
    当你手动修改 `pyproject.toml` 后，运行以下命令来更新 `uv.lock` 文件，以保证所有协作者的环境一致性：
    ```bash
    uv pip compile pyproject.toml -o uv.lock