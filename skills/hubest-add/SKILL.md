# /hubest-add — Register current project with Hubest

Register the current working directory as a project in Hubest (Claude Code Multi-Session Manager).

## Usage

```
/hubest-add [path] [--global]
```

- No arguments: registers the current working directory
- `path`: registers the specified directory instead
- `--global`: inject hooks into `~/.claude/settings.json` instead of the project's `.claude/settings.json`

## Instructions

Run the following command:

```bash
python3 ~/.hubest/hubest_cli.py register $ARGUMENTS
```

Report the output to the user. If the command exits with a non-zero status, report the error.
