# cchat

Browse and search Claude Code conversation history from the terminal.

`cchat` reads the JSONL conversation logs that Claude Code stores in `~/.claude/projects/` and presents them as readable conversation turns. It handles compaction stitching, branch detection, and the full UUID tree structure so you don't have to parse raw JSONL yourself.

## Install

### pip / pipx

```bash
pip install cchat
# or
pipx install cchat
```

### curl (no pip needed)

```bash
curl -fsSL https://raw.githubusercontent.com/asparagusbeef/cchat/main/cchat.py \
  -o ~/.local/bin/cchat && chmod +x ~/.local/bin/cchat
```

### wget

```bash
wget -qO ~/.local/bin/cchat \
  https://raw.githubusercontent.com/asparagusbeef/cchat/main/cchat.py && chmod +x ~/.local/bin/cchat
```

### PowerShell (Windows without WSL)

```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/asparagusbeef/cchat/main/cchat.py" `
  -OutFile "$env:LOCALAPPDATA\cchat\cchat.py"
```

> **Note:** cchat reads `~/.claude/projects/` which is a Linux/macOS path. On native Windows (not WSL), Claude Code may store data differently.

## Quick start

```bash
# List recent sessions in the current project
cchat list

# View the last 5 turns of the latest session
cchat view

# View a specific session (by index from list)
cchat view 2

# Search across all sessions
cchat search "error handling"
```

## Commands

| Command | Alias | Description |
|---------|-------|-------------|
| `cchat list [N]` | `ls` | List recent sessions (default: 10) |
| `cchat view [SESSION]` | `v` | View conversation turns |
| `cchat copy [SESSION]` | `cp` | Copy messages to clipboard (WSL) |
| `cchat search PATTERN` | `s` | Search across sessions |
| `cchat tree [SESSION]` | | Show conversation tree structure |
| `cchat export [SESSION]` | | Export full session (markdown or JSON) |
| `cchat projects` | | List all projects |

### View options

| Flag | Description |
|------|-------------|
| `-n N` | Show last N turns |
| `-r RANGE` | Show specific turns: `5`, `3-7`, `-1`, `-3--1` |
| `--all` | Show all turns |
| `--tools` | Show tool call summaries |
| `--raw` | Show everything (tool I/O, thinking, system) |
| `--json` | Output as JSON |
| `--no-stitch` | Don't bridge compaction boundaries |
| `--timestamps` | Show timestamps |
| `--compact-summaries` | Include compaction summary messages |
| `--truncate LEN` | Truncate length for raw content (default: 500) |
| `-p PATH` | Use a different project directory |

### Session selection

Sessions can be specified by:
- **Index**: `cchat view 2` (2nd most recent from `cchat list`)
- **UUID prefix**: `cchat view a1b2c3` (matches session ID)
- **Omitted**: uses the most recent session

## How it works

Claude Code stores each conversation as a JSONL file in `~/.claude/projects/<project-key>/`. Each line is a JSON entry with a type (`user`, `assistant`, `system`, etc.) and a UUID-based parent-child tree.

cchat:
1. **Resolves the active path** by walking the UUID tree from the last entry backward
2. **Stitches across compaction boundaries** using `logicalParentUuid` links (or positional fallback)
3. **Groups entries into turns** (one user message + full assistant response)
4. **Detects branch points** by filtering out mechanical fan-out (tool_use forks, progress entries)

## Requirements

- Python 3.8+
- No dependencies (stdlib only)
- Clipboard copy uses `clip.exe` (WSL) — other platforms not yet supported

## License

MIT
