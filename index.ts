/**
 * AGENTS.md 编写规范守卫（pi-agents-md-guard，npm 包形态）
 *
 * 为什么：AGENTS.md 每次会话全文注入、团队共享；机器环境（绝对路径）与体量失控
 * 会污染所有成员的会话。用户 2026-11-24 拍板：要有规范 + 插件动态检查，
 * 「当他要写 agents.md 的时候要检查」，且插件一律走 npm + GitHub Actions 发布。
 *
 * 三个入口（同一份规则）：
 * 1. 动态检查：write / edit 落盘任何 AGENTS.md 后，自动跑检查器，把发现追加进工具结果，
 *    模型当轮就能看到并修正（不拦写盘 —— 检查是反馈，不是门禁；门禁在 pre-commit）。
 * 2. 工具 `agents_md_check`：模型可主动检查任意 AGENTS.md（写前自查）。
 * 3. 命令 `/agents-md [路径…]`：人工体检，缺省查工作区根 AGENTS.md。
 *
 * 检查器解析顺序：工作区 .pi/skills/agents-md/scripts/check_agents_md.py 优先
 * （仓库自带 SSOT，与 pre-commit 闸门同一份）→ 包内 scripts/check_agents_md.py 兜底
 * （其它工作区没有该 skill 也能用）。两份脚本内容需保持同步（见 README）。
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { Type } from "typebox";

/** 工作区检查器相对仓库根的路径（仓库自带时的规则唯一事实） */
const CHECKER_REL = ".pi/skills/agents-md/scripts/check_agents_md.py";
/** 包内自带的检查器副本（其它工作区兜底） */
const BUNDLED_CHECKER = fileURLToPath(new URL("./scripts/check_agents_md.py", import.meta.url));
/** 单次检查超时：检查器只读文件 + 正则，正常 <200ms */
const TIMEOUT_MS = 10_000;

type CheckResult = { ok: boolean; output: string };

/** 解析检查器：工作区 SSOT 优先，包内副本兜底；都没有返回 null */
function resolveChecker(cwd: string): string | null {
  const workspace = path.join(cwd, CHECKER_REL);
  if (fs.existsSync(workspace)) return workspace;
  if (fs.existsSync(BUNDLED_CHECKER)) return BUNDLED_CHECKER;
  return null;
}

/** 跑检查器；脚本 / python 缺失时返回 ok=true 并注明跳过（守卫不能把宿主搞挂） */
function runChecker(cwd: string, targets: string[]): Promise<CheckResult> {
  const script = resolveChecker(cwd);
  if (!script) {
    return Promise.resolve({ ok: true, output: "（agents-md-guard：未找到检查器脚本，跳过检查）" });
  }
  return new Promise((resolve) => {
    const child = spawn("python3", [script, ...targets], { cwd });
    let out = "";
    const timer = setTimeout(() => child.kill("SIGKILL"), TIMEOUT_MS);
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (out += d));
    child.on("error", (e) => {
      clearTimeout(timer);
      resolve({ ok: true, output: `（agents-md-guard：python3 不可用，跳过检查：${e.message}）` });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ ok: code === 0, output: out.trim() });
    });
  });
}

/** 从 write / edit 的入参里取目标路径，只认 basename 为 AGENTS.md 的 */
function agentsTarget(toolName: string, input: unknown, cwd: string): string | null {
  if (toolName !== "write" && toolName !== "edit") return null;
  const p = (input as { path?: unknown })?.path;
  if (typeof p !== "string" || path.basename(p) !== "AGENTS.md") return null;
  return path.resolve(cwd, p);
}

export default function (pi: ExtensionAPI) {
  // 入口 1：写后动态检查 —— 把发现追加进工具结果，模型当轮可见
  pi.on("tool_result", async (event, ctx) => {
    const target = agentsTarget(event.toolName, event.input, ctx.cwd);
    if (!target || event.isError) return;
    const { ok, output } = await runChecker(ctx.cwd, [target]);
    if (ok && !output.includes("⚠️")) return; // 全绿不打扰
    const note = ok
      ? `\n\n【agents-md-guard】写入后检查有警告，请评估是否修正：\n${output}`
      : `\n\n【agents-md-guard】❌ 违反 AGENTS.md 编写规范，必须修正后重新写入（规范见工作区 Skill agents-md，没有则见包 README）：\n${output}`;
    return { content: [...event.content, { type: "text" as const, text: note }] };
  });

  // 入口 2：模型主动检查工具
  pi.registerTool({
    name: "agents_md_check",
    label: "AGENTS.md 规范检查",
    description:
      "按编写规范检查 AGENTS.md（绝对机器路径 / 密钥 / 体量 / 悬空技能引用）。写或改任何 AGENTS.md 前先调它自查；缺省查工作区根 AGENTS.md。规范正文：工作区 .pi/skills/agents-md/SKILL.md（没有则见包 README）",
    parameters: Type.Object({
      paths: Type.Optional(Type.Array(Type.String(), { description: "要检查的文件路径；留空查工作区根 AGENTS.md" })),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      const targets = params.paths?.length ? params.paths.map((p) => path.resolve(ctx.cwd, p)) : [path.join(ctx.cwd, "AGENTS.md")];
      const { ok, output } = await runChecker(ctx.cwd, targets);
      return {
        content: [{ type: "text", text: output || (ok ? "✅ 0 问题" : "检查失败") }],
        details: { ok },
      };
    },
  });

  // 入口 3：人工命令
  pi.registerCommand("agents-md", {
    description: "检查 AGENTS.md 编写规范（缺省查工作区根；可传路径）",
    handler: async (args, ctx) => {
      const targets = args.trim() ? args.trim().split(/\s+/) : ["AGENTS.md"];
      const { output } = await runChecker(ctx.cwd, targets);
      ctx.ui.notify(output || "✅ 0 问题", "info");
    },
  });
}