# 在專案裡建立 AIWF MCP 連線

完成後，你可以在 Codex CLI、GitHub Copilot CLI 或 VS Code 的對話裡查詢這個專案的 AIWF 任務。用戶端會透過標準輸入輸出（stdio）啟動本機的 `aiwf-mcp`，每個伺服器綁定一個專案工作目錄。先以預設的唯讀模式確認連對專案，需要建任務時再開啟寫入。

## 1. 在要管理的專案確認 AIWF Core

以下指令適用於 macOS 或 Linux 的 Bash。先在終端機進入**要管理的專案根目錄**。在同一個終端機執行後續指令，並為這個工作目錄取一個專屬的代號。本文以 `project-a` 為例。

```bash
PROJECT_DIR="$(pwd -P)"
BINDING_ID="project-a"
MCP_VENV="$HOME/.venvs/aiwf-mcp"
export AIWF_PYTHON="$(command -v python3)"
"$AIWF_PYTHON" --version
```

需要 Python 3.10 以上。如果顯示較舊的版本，請把上面的 `python3` 換成本機已安裝的版本，例如 `python3.12`，再確認一次。首次安裝 Core 時，從可信任的 AIWF 來源套件執行 `/path/to/aiwf-package/aiwf install --target "$PROJECT_DIR" --yes`。專案已有 Core 就直接執行下列檢查。[首次安裝](../adoption_guide.md) · [升級既有專案](../upgrading.md)

```bash
./aiwf query context --full-workflow
```

看到 `"execution": "ok"` 再繼續。本文使用 Core `1.7.17.post4` 與 Adapter `0.3.2`。如果 CLI 不認得 `query`，請先升級 Core。若回報 `AIWF-LOCK-UNSUPPORTED`，請檢查專案所在的檔案系統。[支援的本機儲存環境](../cli_reference.md#concurrent-workflow-operations-and-recovery)

## 2. 取得並安裝 Adapter

在專案外建立專用的 Python 虛擬環境。Core 與 Adapter 分開安裝。你可以使用已建好的 Python 安裝檔（wheel），也可以從 AIWF 原始碼自行建置。下面兩條路徑擇一即可。

```bash
"$AIWF_PYTHON" -m venv "$MCP_VENV"
```

**已有 wheel 安裝檔**時，把路徑換成你拿到的檔案，直接進入下方的安裝步驟。

```bash
MCP_WHEEL="/path/to/aiwf_mcp-0.3.2-py3-none-any.whl"
```

**手上是 AIWF 原始碼**時，先用以下指令建立 wheel。`AIWF_SOURCE` 指向含有 `integrations/mcp/pyproject.toml` 的來源目錄。只安裝了 Core 的專案請另外取得含 Adapter 的來源套件或對應版本的 wheel。

```bash
AIWF_SOURCE="/path/to/aiwf-package"
"$MCP_VENV/bin/python" -m pip wheel --no-deps --wheel-dir "$MCP_VENV/wheels" "$AIWF_SOURCE/integrations/mcp"
MCP_WHEEL="$MCP_VENV/wheels/aiwf_mcp-0.3.2-py3-none-any.whl"
```

兩種方式都用同一組指令安裝。`[guidance]` 一併安裝查詢 Guidance 所需的 PyYAML。看到 `--repo-root`、`--binding-id` 和 `--mode` 的說明，表示伺服器執行檔已就緒。

```bash
"$MCP_VENV/bin/python" -m pip install "${MCP_WHEEL}[guidance]"
"$MCP_VENV/bin/aiwf-mcp" --help
```

## 3. 在你使用的用戶端註冊

**Codex CLI** 可直接用同一個終端機註冊。`get` 會顯示剛儲存的執行檔與參數。確認 `--repo-root` 後面是要管理的專案，再從該專案開啟新的 Codex 對話。完整的註冊選項可執行 `codex mcp add --help` 查看。

```bash
codex mcp add "aiwf-$BINDING_ID" -- "$MCP_VENV/bin/aiwf-mcp" --repo-root "$PROJECT_DIR" --binding-id "$BINDING_ID"
codex mcp get "aiwf-$BINDING_ID"
```

**GitHub Copilot CLI** 可用同樣的執行檔和參數註冊，然後在專案內開啟 Copilot 對話。[Copilot CLI MCP 設定](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers)

```bash
copilot mcp add "aiwf-$BINDING_ID" -- "$MCP_VENV/bin/aiwf-mcp" --repo-root "$PROJECT_DIR" --binding-id "$BINDING_ID"
copilot mcp get "aiwf-$BINDING_ID"
```

**VS Code** 可從命令選擇區執行 `MCP: Add Server`，選擇 **Command (stdio)**。把下列範例的兩個路徑換成虛擬環境及專案的實際絕對路徑，輸入完整啟動指令，並為伺服器取名，例如 `aiwf-project-a`。儲存後在該工作區開啟 Copilot 對話。[VS Code 本機 MCP 設定](https://github.com/microsoft/vscode-docs/blob/main/docs/agent-customization/mcp-servers.md)

```text
"/absolute/path/to/aiwf-mcp-venv/bin/aiwf-mcp" --repo-root "/absolute/path/to/project" --binding-id project-a
```

需要手動編輯設定時，三種用戶端的範本位於 `$MCP_VENV/share/aiwf-mcp/examples/`。保留現有伺服器設定，把 AIWF 那一筆加進去。直接在終端機執行 `aiwf-mcp --repo-root …` 會等候用戶端送出請求，日常使用由用戶端啟動它即可。

## 4. 從對話確認真的連到專案

把下面這句貼到你選的用戶端，代號換成自己的。展開實際的工具呼叫，核對回傳值。

> 請用 aiwf-project-a 的 MCP 工具呼叫 `aiwf_context`。確認 `repository.binding_id` 是 `project-a` 後，再用 `aiwf_list_tasks` 列出任務。

| 檢查項目 | 第一次連線應看到的結果 |
| --- | --- |
| `aiwf_context` | `execution` 為 `ok`、`repository.binding_id` 等於自己設定的代號、`interface.mode` 為 `read-only`。若代號不同，先更正用戶端設定。 |
| `aiwf_list_tasks` | `result.tasks` 會列出該專案的任務。專案還沒有任何任務時，會回傳空陣列 `[]`。 |

## 5. 需要寫入時，建立第一筆任務

在允許 Agent 寫入的專案，編輯先前註冊的伺服器。Codex CLI 的使用者設定預設在 `~/.codex/config.toml`，Copilot CLI 預設在 `~/.copilot/mcp-config.json`，VS Code 可從工作區的 MCP 伺服器清單開啟該項設定。

在既有 `args` 陣列的末尾加上 `"--mode", "read-write"`，保留原本的專案路徑和代號，然後重啟該 MCP 伺服器。再次呼叫 `aiwf_context`，核對代號、`interface.mode` 為 `read-write`，並確認 `interface.write_operations` 包含 `aiwf_new_task`。若清單是空的，請檢查第一步的 `result.mutation_root_writable` 以及該伺服器程序對專案根目錄的寫入權限。

下列操作會在綁定的專案裡**實際建立一筆任務**。在對話中送出一次，成功時 `operation_status` 為 `succeeded`，`target` 是含日期與編號的任務目錄。

> 請在 aiwf-project-a 呼叫 `aiwf_new_task`，使用 `{"binding_id":"project-a","name":"verify_mcp_setup"}`，並顯示回傳的 `target`。

若已經建立過，請用 `aiwf_list_tasks` 找回原路徑。後續操作使用完整的 `target`。[任務流程範例](basic_lifecycle.md)
