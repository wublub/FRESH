# FRESH

> 苹果风格的 Windows 本地便签 / 截图 / 附件追踪工具。基于 PySide6 构建，单文件可携，数据加密，离线可用。

![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Framework](https://img.shields.io/badge/UI-PySide6-green)
![Encryption](https://img.shields.io/badge/data-Fernet%20encrypted-orange)

FRESH 是一个 Windows 桌面便签工具，集**文字便签 + 截图/文件归档 + 附件追踪**于一体。所有数据加密存储于本地，支持多账户与密码保护，并对外部附件的移动、改名做了深度追踪，让"被你扔到某个角落的那份文件"也能继续被打开。

---

## ✨ 主要功能

- **文字便签** — 创建、编辑、富文本、置顶、分类归档、全文搜索。
- **全截图工作区** — 框选截图、拖入图片、粘贴剪贴板图片；选中某张截图后，可在这张截图下面添加文件或文件夹附件。
- **归档分类** — 给截图、截图下的附件和备忘录添加分类，在归档列表和时间线中筛选查看。
- **附件栏** — 拖入文件或文件夹作为附件，双击打开，右键显示位置或重新定位。
- **最近删除** — 删除的备忘录、附件、截图先进入回收站，可恢复，可彻底删除。
- **外部附件追踪** — 文件被移动、改名后自动找回（ADS + File ID + Everything + hash 兜底）。
- **数据导入导出** — 导出 zip，包含数据、复制型附件、外部引用内容、源码和 exe。
- **系统托盘** — 最小化到托盘，快速新建文字、框选截图、保存剪贴板图片。
- **多账户 + 密码加密** — 每个账户独立目录，密码派生密钥，多账户互不可见。
- **机器密钥模式** — 不设密码时按机器 ID + 用户名 + 本地 salt 派生密钥（更方便，但只在本机解密）。
- **开机启动** — 更多菜单一键开/关。
- **Everything 加速** — 检测到 Everything 时通过 IPC 或 `es.exe` 加速文件定位。
- **快捷键自定义** — 所有快捷键都可改，存于 `QSettings('FRESH','FRESH')`。

---

## 🔐 数据安全

FRESH 的所有本地数据（包括 `data.json` 和 `attachments/` 中的文件）**默认加密**：

| 模式 | 密钥来源 | 适用场景 |
| --- | --- | --- |
| 机器密钥 | 机器 GUID + 用户名 + 本地 salt（`.fkey`） | 单用户、单机使用，开箱即用 |
| 密码密钥 | PBKDF2-HMAC-SHA256（600,000 轮）+ 用户密码 | 多账户、防泄漏、跨机迁移 |

- 加密算法：Fernet（AES-128-CBC + HMAC-SHA256）。
- 已加密文件统一前缀 `FENC1\n`，明文文件首次启动会自动迁移。
- 附件通过 `path_for(att)` 返回会话级临时解密缓存路径（`tempfile.mkdtemp` + `atexit` 清理），原始 attachments 目录始终保持加密。

> ⚠️ 密码模式下忘记密码 = 永久无法解密。FRESH 不保留任何明文备份。

---

## 🚀 快速开始

### 运行环境

- Windows 10 / 11
- Python 3.11+
- PySide6
- cryptography
- PyInstaller（仅打包 exe 时需要）
- Everything（可选，用于加速附件恢复）

### 安装依赖

```powershell
pip install PySide6 cryptography pyinstaller
```

### 源码运行

```powershell
python main.py
```

或双击：

```text
启动.bat        # 无控制台启动
调试启动.bat    # 带控制台输出
```

### 打包 exe

```powershell
python -m PyInstaller --noconfirm FRESH.spec
```

构建结果输出到 `dist\FRESH\FRESH.exe`。这是 onedir 包，分发时需要保留
整个 `dist\FRESH` 文件夹；建议压缩为 zip 后上传到 GitHub Releases。

---

## 📁 数据位置

FRESH 的数据默认保存在软件旁边的 `FRESH_Data` 文件夹；也可以通过 **更多 → 选择数据文件夹...** 改到任意位置。首次使用新版时，如果软件旁边还没有数据，会从旧的 `%APPDATA%\FRESH` 复制一份到默认位置。

```text
FRESH_Data\
├── accounts.json           # 账户索引
├── accounts\<id>\          # 单个账户目录
│   ├── data.json           # 加密：便签、截图、附件元数据
│   ├── attachments\        # 加密：复制进来的附件和截图
│   ├── trash\              # 加密：最近删除区
│   ├── scan_settings.json  # Everything 路径、扫描范围
│   └── .fkey               # 隐藏：机器密钥模式的 salt
├── ui_text.json            # 界面文案覆盖
└── custom.qss              # 界面样式覆盖
```

---

## 🎨 自定义文字和样式

首次启动后，FRESH 会自动在当前数据文件夹生成两个可编辑文件：`ui_text.json` 和 `custom.qss`。

也可以在软件里直接编辑：**更多 → 外观与文字配置...**

**文字覆盖**示例：

```json
{
  "texts": {
    "＋  新建": "新便签",
    "搜索文字和文件": "搜索内容",
    "时间线": "完成记录"
  }
}
```

包含 `{count}`、`{name}`、`{path}` 等占位符的文案，右侧 value 里必须保留对应占位符。

**样式覆盖**示例（追加在内置样式之后）：

```css
#new_button {
    background: #0F766E;
    border-radius: 6px;
}

#title_input {
    font-size: 24px;
}
```

修改后点击「保存并应用」立即生效；也可以**更多 → 重新加载外观与文字**或重启软件。

---

## ⌨️ 常用快捷键

| 快捷键 | 功能 |
| --- | --- |
| `Ctrl+N` | 新建文字备忘录 |
| `Ctrl+Shift+N` | 框选截图 |
| `Ctrl+Alt+N` | 从图片文件添加截图 |
| `Ctrl+F` | 聚焦搜索 |
| `Ctrl+L` | 打开时间线 |
| `Ctrl+Shift+Delete` | 打开最近删除 |
| `Ctrl+E` | 归档/取消归档当前项目 |
| `Ctrl+T` | 置顶/取消置顶当前文字备忘录 |
| `Alt+↑` / `Alt+↓` | 在可见列表中切到上一条/下一条 |
| `Ctrl+Enter` | 在搜索/列表/标题/正文之间快速推进 |
| `Delete` | 列表聚焦时将当前项目移到最近删除 |

> 所有快捷键都可在 **更多 → 快捷键设置...** 中重新绑定。

---

## 🔎 搜索和编辑

文字工作区的搜索同时匹配：标题、正文、分类、归档信息、附件名称、附件备注、附件路径。

- 搜索框按 `Enter` 或 `↓` 直接进入结果列表；`Esc` 清空搜索或回到编辑区。
- 标题下方可直接选择或输入分类。
- 正文上方提供：加粗、斜体、下划线、项目符号、清除格式。
- 置顶备忘录固定在普通备忘录之前，并显示「置顶」标记。

全截图工作区的「＋ 添加」会弹出菜单，可框选截图、选择截图图片，也可给当前选中的截图添加文件或文件夹。也可以直接点某张截图右上角的 `+`，或把文件/文件夹拖到那张截图卡片上。添加的文件/文件夹只显示在对应截图卡片下方，不会共享到其他截图，也不会作为新的截图出现在左侧列表。

右键托盘图标可直接执行：**快速新建文字** / **快速框选截图** / **保存剪贴板图片**。

---

## 🗑️ 最近删除

备忘录、普通附件、截图删除后**不会立即从磁盘移除**，而是进入：

**更多 → 最近删除**

- 普通删除直接移入最近删除，不再二次弹窗。
- 在最近删除里可以恢复，或在确认后彻底删除。
- 彻底删除复制型附件和截图时，才会真正抹掉 `attachments` 中的文件。

---

## 📎 附件类型

FRESH 区分两类附件：

| 类型 | 行为 | 适用 |
| --- | --- | --- |
| **复制型** | 复制到当前数据文件夹 `accounts\<id>\attachments`（加密） | 截图、剪贴板图片、小文件归档 |
| **引用型** | 保留原路径，建立追踪信息（不复制本体） | 大文件、外部工作目录中的文档 |

引用型附件如果文件移动或改名，FRESH 会自动尝试恢复它的新位置。

---

## 🛰️ 文件追踪机制

外部附件加入时，FRESH 会记录多种信息：

1. **NTFS ADS 标记** — 写入 `fresh_id` alternate data stream。
2. **NTFS File ID** — 记录卷序列号和文件 ID，用于同盘移动/改名的快速恢复。
3. **原始文件名和大小** — 用于候选搜索和排序。
4. **内容 hash** — ≤ 64 MB 时计算完整 SHA-256，大文件计算前 64 MB。

恢复顺序：

1. 校验原路径是否仍是原附件，避免误打开同名新文件。
2. 使用 NTFS File ID 快速定位。
3. 使用 Everything 按文件名找候选，再用 ADS 标记验证。
4. 按 ADS 标记扫描（自定义范围优先，但会自动纳入当前所有本地盘和移动盘）。
5. 按文件名查找候选，用内容 hash 验证。
6. 按内容 hash 扫描兜底。

自动恢复只在 hash 唯一命中时自动采纳；多个相同副本时留给手动选择。找回新位置后会重新写入 ADS 标记并更新 File ID。

---

## 🔌 Everything 集成

支持两种加速方式：

- **IPC** — Everything 主程序运行时直接通过 `WM_COPYDATA` 查询。
- **es.exe** — 找不到 IPC 时回退到 Everything CLI。

入口：**更多 → 文件查找设置...**

可配置：是否启用 Everything、手动指定 `es.exe` 路径、自定义慢速扫描根目录。

---

## 🗂️ 项目结构

```text
main.py            主窗口、界面、交互、附件恢复任务、导入导出
storage.py         本地 JSON 数据存储、附件元数据、路径解析
accounts.py        多账户管理、密码加密、账户切换
crypter.py         数据加密：Fernet + PBKDF2 / 机器密钥派生
customization.py   外部文字和样式覆盖
ftrack.py          文件追踪：ADS、File ID、Everything、hash、扫描
everything_ipc.py  Everything IPC 查询实现
shell_notify.py    Shell 变更通知（监听文件复制/剪切）
styles.py          Qt 样式
FRESH.spec         PyInstaller 打包配置
启动.bat           无控制台启动
调试启动.bat       调试启动
dist\FRESH\        打包后的完整程序目录
```

---

## ⚠️ 已知限制

- 最强追踪能力依赖 **Windows + NTFS**。
- 文件夹没有内容 hash，主要依赖 ADS 和 File ID。
- 文件内容被修改后，旧 hash 不能再证明它是同一个文件。
- 大文件只 hash 前 64 MB + 文件大小，速度更快但理论上不如完整 hash 严格。
- 如果文件被复制到不保留 ADS 的位置、又修改内容、还改名，程序无法 100% 自动证明它还是原文件。
- 密码模式下忘记密码无法找回数据。
- Everything 非必需，但安装并保持运行会显著提升恢复速度。

---

## 🛠️ 开发备注

语法检查：

```powershell
python -m py_compile main.py storage.py accounts.py crypter.py ftrack.py everything_ipc.py customization.py
```

重新打包：

```powershell
python -m PyInstaller --noconfirm FRESH.spec
```

---

## 🙏 致谢

感谢以下社区与公益项目，让 FRESH 的开发过程更加顺利：

### 💚 Linux.do 社区赞助

感谢 [**Linux.do**](https://linux.do) 社区在开发过程中提供的赞助、技术讨论与反馈。Linux.do 是一个聚集了大量 Geek、开发者和爱好者的开放社区，本项目的不少功能灵感和调试线索都来自社区伙伴们的讨论。

### 🌏 AnyRouter 公益

感谢 [**AnyRouter**](https://anyrouter.top) 提供的公益 AI 服务支持。AnyRouter 通过公益的方式让更多开发者可以低门槛使用大模型能力，对个人开发者和开源项目极为友好。FRESH 在开发与代码维护中受益于此。

> **真诚**、**友善**、**团结**、**专业**

---

## 📜 License

本项目目前以源码形式分享给社区，欢迎学习、改进与反馈。如需用于商业用途，请先开 issue 联系。

---

## 💬 反馈与贡献

- **Issue** — 欢迎提交 bug 报告、功能建议、使用问题。
- **Pull Request** — 欢迎修复 bug、补充文档、新增小功能。提交前请先 `python -m py_compile` 确认语法没问题。
- **讨论** — 也可以到 [Linux.do](https://linux.do) 社区交流。
