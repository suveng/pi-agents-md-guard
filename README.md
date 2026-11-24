# pi-agents-md-guard

AGENTS.md 编写规范守卫（pi 插件）。AGENTS.md 每次会话全文注入、团队共享；机器环境（绝对路径）与体量失控会污染所有成员的会话。本插件把规范下沉为机械检查。

## 安装

```bash
pi install npm:pi-agents-md-guard
```

装好后 `/reload`（或新会话）生效。依赖：本机 `python3`（检查器是跨平台 python 脚本）。

## 三个入口

1. **写后动态检查**：`write` / `edit` 落盘任何 `AGENTS.md` 后自动检查，发现追加进工具结果，模型当轮可见并修正。不拦写盘 —— 检查是反馈；硬门禁建议放 pre-commit（见下）。
2. **工具 `agents_md_check`**：写前主动自查，`paths` 留空查工作区根 `AGENTS.md`。
3. **命令 `/agents-md [路径…]`**：人工体检。

## 规则

| 规则 | 级别 | 内容 |
|---|---|---|
| R1 | 错误 | 绝对机器路径（`/Users/<人>/`、`/home/<人>/`、`C:\Users\`）——工作区是团队共享的，机器环境写用户级 `~/.pi/agent/AGENTS.md` |
| R2 | 警告 | 机器相关系统前缀（`/usr/local/`、`/opt/homebrew/`） |
| R3 | 警告 | 疑似密钥（`sk-…` / `ghp_…` / `AKIA…` 等）——凭据放环境变量或 Keychain |
| R4 | 25KB 警告 / 40KB 错误 | 体量预算（每次会话全文注入的上下文成本） |
| R5 | 警告 | 引用了不存在的 `.pi/skills/<名>/`（悬空指针） |

- **用户级豁免**：`~/.pi/agent/` 下的 AGENTS.md 允许写机器环境，跳过 R1/R2/R4。
- **单行豁免**：行尾写 `<!-- agents-md-ok: R1 -->`（可逗号分隔多个规则 id）。

## 检查器解析顺序

1. 工作区 `.pi/skills/agents-md/scripts/check_agents_md.py`（仓库自带 SSOT，与 pre-commit 闸门同一份）优先；
2. 包内 `scripts/check_agents_md.py` 兜底（其它工作区没有该 skill 也能用）。

⚠️ 两份脚本内容需保持同步：源头在 doger 仓 `.pi/skills/agents-md/scripts/check_agents_md.py`，改规则后把文件复制到本包 `scripts/` 并发新版。

检查器也可独立跑：

```bash
python3 scripts/check_agents_md.py <文件…>   # 显式路径
python3 scripts/check_agents_md.py --staged  # 暂存区（pre-commit 用）
python3 scripts/check_agents_md.py --all     # 全仓存量体检
```

退出码：0 无错误（警告不拦）/ 1 有错误 / 2 用法错。

## 发布

推 `v*` tag 由 GitHub Actions OIDC trusted publishing 自动 `npm publish`（无 NPM_TOKEN）。

## License

MIT