#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AGENTS.md 编写规范检查器（规范正文见同目录上级 SKILL.md）。

为什么要有它：AGENTS.md 每次会话全文注入，是团队共享的「工作区法律」；
机器环境（绝对路径、工具链版本）写进来会让别的成员拿到错误事实，
体量失控会吃掉所有人的上下文。纸面规矩拦不住，下沉为机械检查。

规则（数据驱动，加规则往 RULES 里添一条即可）：
  R1 绝对机器路径（/Users/<人>/、/home/<人>/、C:\\Users\\）—— 工作区级错误
  R2 机器相关系统前缀（/usr/local/、/opt/homebrew/）—— 工作区级警告（brew 前缀因机而异）
  R3 疑似密钥（sk-… / ghp_… / AKIA… 等）—— 警告（私有仓库口径见根 AGENTS.md）
  R4 体量预算：工作区级 >25KB 警告、>40KB 错误（注入成本）
  R5 引用的 .pi/skills/<名>/ 不存在 —— 警告（悬空指针）

分级：用户级（~/.pi/agent/AGENTS.md）允许写机器环境，跳过 R1/R2/R4。
豁免：某行末尾写 HTML 注释 <!-- agents-md-ok: R1 --> 可豁免该行指定规则。

用法：
  python3 check_agents_md.py <文件…>     显式路径
  python3 check_agents_md.py --staged    只查暂存区里的 AGENTS.md（pre-commit 用）
  python3 check_agents_md.py --all       全仓已跟踪的 AGENTS.md（存量体检）
退出码：0 = 无错误（警告不拦）；1 = 有错误；2 = 用法/环境错。
"""
import argparse
import os
import re
import subprocess
import sys

# 体量阈值（字节）：警告线 / 硬上限
SIZE_WARN = 25 * 1024
SIZE_HARD = 40 * 1024

# 规则表：id、级别、正则、说明。callable 规则另行处理（R4/R5）。
REGEX_RULES = [
    ("R1", "error", re.compile(r"(?<![\w~])(?:/Users/[A-Za-z0-9_.-]+/|/home/[A-Za-z0-9_.-]+/|[A-Za-z]:\\Users\\)"),
     "绝对机器路径：工作区是团队共享的，机器环境写用户级 ~/.pi/agent/AGENTS.md；此处改用 ~ 或 <工作区根> 占位"),
    ("R2", "warn", re.compile(r"/usr/local/|/opt/homebrew/"),
     "机器相关系统前缀（brew 前缀因机而异）：建议移到用户级 AGENTS.md"),
    ("R3", "warn", re.compile(r"\b(?:sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})\b"),
     "疑似密钥：AGENTS.md 会注入每个会话，凭据放环境变量或 Keychain，不要写正文"),
]

SKILL_REF = re.compile(r"\.pi/skills/([a-z0-9-]+)/")
OK_MARK = re.compile(r"<!--\s*agents-md-ok:\s*([A-Z0-9,\s]+?)\s*-->")


def is_user_level(path):
    """用户级 = 家目录下 .pi/agent/ 里的 AGENTS.md（机器环境合法落点）。"""
    real = os.path.realpath(path)
    return real.startswith(os.path.join(os.path.realpath(os.path.expanduser("~")), ".pi", "agent") + os.sep)


def file_repo_root(path, fallback):
    """目标文件自身所在仓的根（R5 用它解析技能引用）。

    为什么不用 cwd 的仓根：npm 包形态下检查器可从任意 cwd 查别仓的 AGENTS.md，
    用 cwd 仓根会把目标仓真实存在的技能全判成悬空（2026-11-24 实测 6 个 R5 假警告）。
    """
    d = os.path.dirname(os.path.abspath(path)) or "."
    out = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else fallback


def check_file(path, repo_root):
    """返回 [(级别, 规则id, 行号, 说明)]；文件读不了按错误报。"""
    findings = []
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        return [("error", "R0", 0, f"读不了文件：{e}")]
    user_level = is_user_level(path)
    lines = text.split("\n")
    for no, line in enumerate(lines, 1):
        ok = OK_MARK.search(line)
        allowed = {x.strip() for x in ok.group(1).split(",")} if ok else set()
        for rid, level, pat, msg in REGEX_RULES:
            if user_level and rid in ("R1", "R2"):
                continue
            if rid in allowed:
                continue
            m = pat.search(line)
            if m:
                findings.append((level, rid, no, f"{msg}（命中：{m.group(0)[:60]}）"))
    # R4 体量（仅工作区级）
    if not user_level:
        size = len(text.encode("utf-8"))
        if size > SIZE_HARD:
            findings.append(("error", "R4", 0, f"体量 {size} 字节 > 硬上限 {SIZE_HARD}：细节下沉 skill/docs，正文只留硬约束 + 指针"))
        elif size > SIZE_WARN:
            findings.append(("warn", "R4", 0, f"体量 {size} 字节 > 建议值 {SIZE_WARN}：每次会话全文注入，考虑瘦身"))
    # R5 悬空 skill 引用（相对目标文件自身所在仓的根解析，跨仓检查不误报）
    seen = set()
    ref_root = file_repo_root(path, repo_root)
    for name in SKILL_REF.findall(text):
        if name in seen:
            continue
        seen.add(name)
        if not os.path.isdir(os.path.join(ref_root, ".pi", "skills", name)):
            findings.append(("warn", "R5", 0, f"引用了不存在的技能目录 .pi/skills/{name}/（悬空指针）"))
    return findings


def git_files(args, repo_root):
    # core.quotepath=false：中文路径（如 知识库/**/AGENTS.md）默认会被 git 转义成
    # "\347\237\245…" 带引号字串，直接拼路径会全部读不到文件（2026-11-24 --all 实测 81 个 R0）。
    out = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=repo_root, capture_output=True, text=True)
    if out.returncode != 0:
        print(f"git 调用失败：{out.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return [l for l in out.stdout.split("\n") if l.strip()]


def collect_targets(opts, repo_root):
    if opts.staged:
        names = git_files(["diff", "--cached", "--name-only", "--diff-filter=ACM"], repo_root)
        return [os.path.join(repo_root, n) for n in names if os.path.basename(n) == "AGENTS.md"]
    if opts.all:
        names = git_files(["ls-files", "*AGENTS.md"], repo_root)
        return [os.path.join(repo_root, n) for n in names]
    return opts.paths


def main():
    ap = argparse.ArgumentParser(description="AGENTS.md 编写规范检查")
    ap.add_argument("paths", nargs="*", help="要检查的文件")
    ap.add_argument("--staged", action="store_true", help="只查暂存区里的 AGENTS.md")
    ap.add_argument("--all", action="store_true", help="全仓已跟踪的 AGENTS.md")
    ap.add_argument("--quiet", action="store_true", help="通过时不输出")
    opts = ap.parse_args()
    if not opts.paths and not opts.staged and not opts.all:
        ap.print_usage()
        return 2
    repo_root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip() or os.getcwd()
    targets = collect_targets(opts, repo_root)
    if not targets:
        if not opts.quiet:
            print("没有要检查的 AGENTS.md")
        return 0
    errors = warns = 0
    for path in targets:
        findings = check_file(path, repo_root)
        rel = os.path.relpath(path, repo_root)
        for level, rid, no, msg in findings:
            mark = "❌" if level == "error" else "⚠️"
            loc = f"{rel}:{no}" if no else rel
            print(f"{mark} {rid} {loc} {msg}")
            errors += level == "error"
            warns += level == "warn"
    if errors == 0 and warns == 0:
        if not opts.quiet:
            print(f"✅ 检查 {len(targets)} 个 AGENTS.md，0 问题")
        return 0
    print(f"共 {errors} 错误 / {warns} 警告（规范见 .pi/skills/agents-md/SKILL.md；行尾 <!-- agents-md-ok: R1 --> 可豁免单行）")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())